"""
Worker Autoscaler for Studio54

Manages dynamic scaling of Celery worker containers based on load.
Uses Redis for configuration storage and Docker SDK for container management.

Scale-up: When ALL workers are at max capacity (8 tasks) for 5+ minutes,
          spawn one additional worker. Repeat every 5 minutes up to max_workers.
Scale-down: When any worker has 0 active tasks for 10+ minutes and count > 1,
            remove one idle worker.
"""

import json
import logging
import time
from dataclasses import dataclass
from typing import Optional

import docker
import redis

from app.config import settings

logger = logging.getLogger(__name__)

# Redis key prefix
PREFIX = "worker_autoscale"

# Autoscale thresholds
SCALE_UP_DELAY = 300    # 5 minutes at capacity before scaling up
SCALE_DOWN_DELAY = 600  # 10 minutes idle before scaling down
MAX_TASKS_PER_WORKER = 8  # Matches --autoscale max

# Reference container label for cloning
WORKER_SERVICE_LABEL = "com.docker.compose.service"
WORKER_SERVICE_NAME = "studio54-worker"


def _get_docker_client() -> docker.DockerClient:
    """Get Docker client via socket."""
    return docker.from_env()


@dataclass
class WorkerInfo:
    """Info about a single worker from celery inspect."""
    name: str
    active_tasks: int
    container_id: Optional[str] = None


@dataclass
class AutoscaleConfig:
    """Autoscale configuration stored in Redis."""
    enabled: bool = False
    max_workers: int = 1


@dataclass
class AutoscaleStatus:
    """Current autoscale status for API responses."""
    enabled: bool
    max_workers: int
    current_workers: int
    total_active_tasks: int
    workers: list  # List of WorkerInfo dicts
    at_capacity_since: Optional[float] = None
    idle_since: Optional[float] = None


def _get_redis() -> redis.Redis:
    """Get Redis client."""
    return redis.from_url(settings.redis_url)


def get_config() -> AutoscaleConfig:
    """Read autoscale config from Redis."""
    r = _get_redis()
    enabled = r.get(f"{PREFIX}:enabled")
    max_workers = r.get(f"{PREFIX}:max_workers")
    return AutoscaleConfig(
        enabled=enabled == b"true" if enabled else False,
        max_workers=int(max_workers) if max_workers else 1,
    )


def set_config(enabled: Optional[bool] = None, max_workers: Optional[int] = None) -> AutoscaleConfig:
    """Update autoscale config in Redis."""
    r = _get_redis()
    if enabled is not None:
        r.set(f"{PREFIX}:enabled", "true" if enabled else "false")
    if max_workers is not None:
        max_workers = max(1, min(10, max_workers))
        r.set(f"{PREFIX}:max_workers", str(max_workers))
    return get_config()


def get_worker_info() -> list[WorkerInfo]:
    """Get active task counts per worker via celery inspect."""
    try:
        from app.tasks.celery_app import celery_app
        inspector = celery_app.control.inspect()
        active = inspector.active() or {}

        workers = []
        for worker_name, tasks in active.items():
            workers.append(WorkerInfo(
                name=worker_name,
                active_tasks=len(tasks),
            ))
        return workers
    except Exception as e:
        logger.error(f"Failed to inspect workers: {e}")
        return []


def _get_worker_containers() -> list:
    """Get running studio54-worker containers via Docker SDK."""
    try:
        client = _get_docker_client()
        containers = client.containers.list(
            filters={
                "label": f"{WORKER_SERVICE_LABEL}={WORKER_SERVICE_NAME}",
                "status": "running",
            }
        )
        return containers
    except Exception as e:
        logger.error(f"Failed to list worker containers: {e}")
        return []


def get_worker_container_count() -> int:
    """Count running studio54-worker containers via Docker SDK."""
    return len(_get_worker_containers())


def _get_reference_container():
    """Get the first running worker container to clone config from."""
    containers = _get_worker_containers()
    return containers[0] if containers else None


def scale_workers(target_count: int) -> bool:
    """Scale workers up by cloning the reference worker container."""
    try:
        current = get_worker_container_count()
        if target_count <= current:
            return True

        ref = _get_reference_container()
        if not ref:
            logger.error("No reference worker container found to clone")
            return False

        client = _get_docker_client()

        # Extract config from reference container
        ref_details = ref.attrs
        ref_config = ref_details.get("Config", {})
        ref_host_config = ref_details.get("HostConfig", {})
        ref_network_settings = ref_details.get("NetworkSettings", {})

        # Get the image
        image = ref_config.get("Image", ref_details.get("Image"))

        # Get environment
        env = ref_config.get("Env", [])

        # Get command
        cmd = ref_config.get("Cmd")

        # Get network(s)
        networks = list(ref_network_settings.get("Networks", {}).keys())

        # Get volumes/binds
        binds = ref_host_config.get("Binds", [])

        # Get restart policy
        restart_policy = ref_host_config.get("RestartPolicy", {"Name": "unless-stopped"})

        for i in range(current, target_count):
            container_name = f"studio54-worker-scaled-{i + 1}"

            # Check if container already exists
            try:
                existing = client.containers.get(container_name)
                if existing.status == "running":
                    logger.info(f"Container {container_name} already running")
                    continue
                existing.remove(force=True)
            except docker.errors.NotFound:
                pass

            container = client.containers.run(
                image=image,
                command=cmd,
                environment=env,
                volumes=[b for b in binds] if binds else None,
                network=networks[0] if networks else None,
                name=container_name,
                restart_policy=restart_policy,
                detach=True,
                labels={
                    WORKER_SERVICE_LABEL: WORKER_SERVICE_NAME,
                    "studio54.scaled": "true",
                },
            )

            # Connect to additional networks
            for net in networks[1:]:
                try:
                    network_obj = client.networks.get(net)
                    network_obj.connect(container)
                except Exception as e:
                    logger.warning(f"Failed to connect {container_name} to network {net}: {e}")

            logger.info(f"Created scaled worker container: {container_name} (id={container.short_id})")

        return True
    except Exception as e:
        logger.error(f"Failed to scale workers: {e}")
        return False


def _find_idle_worker_container() -> Optional[str]:
    """Find a scaled worker container with 0 active tasks to remove during scale-down."""
    workers = get_worker_info()
    idle_worker_names = {w.name for w in workers if w.active_tasks == 0}
    if not idle_worker_names:
        return None

    # Prefer removing scaled containers (ones we created) over the original
    containers = _get_worker_containers()
    scaled = [c for c in containers if c.labels.get("studio54.scaled") == "true"]

    if scaled:
        return scaled[-1].id

    # Fallback: remove last container if more than 1
    if len(containers) > 1:
        return containers[-1].id

    return None


def scale_down_one() -> bool:
    """Remove one idle worker container."""
    current_count = get_worker_container_count()
    if current_count <= 1:
        return False

    container_id = _find_idle_worker_container()
    if not container_id:
        logger.info("No idle worker container found for scale-down")
        return False

    try:
        client = _get_docker_client()
        container = client.containers.get(container_id)
        container.stop(timeout=30)
        container.remove()
        logger.info(f"Scaled down: removed worker container {container_id[:12]}")
        return True
    except Exception as e:
        logger.error(f"Failed to scale down: {e}")
        return False


def check_and_scale():
    """
    Main autoscale check — called every 60s by beat.

    Logic:
    1. If ALL workers are at max tasks for 5+ min → scale up by 1
    2. If any worker has 0 tasks for 10+ min AND count > 1 → scale down by 1
    3. Clear tracking timestamps when conditions change
    """
    config = get_config()
    if not config.enabled:
        return {"action": "disabled"}

    r = _get_redis()
    workers = get_worker_info()
    current_count = get_worker_container_count()
    now = time.time()

    if not workers:
        logger.debug("No workers found for autoscale check")
        return {"action": "no_workers"}

    total_active = sum(w.active_tasks for w in workers)
    all_at_capacity = all(w.active_tasks >= MAX_TASKS_PER_WORKER for w in workers)
    any_idle = any(w.active_tasks == 0 for w in workers)

    result = {
        "workers": len(workers),
        "containers": current_count,
        "total_active": total_active,
        "all_at_capacity": all_at_capacity,
        "any_idle": any_idle,
    }

    # --- Scale UP logic ---
    if all_at_capacity and current_count < config.max_workers:
        at_capacity_since_raw = r.get(f"{PREFIX}:at_capacity_since")
        if at_capacity_since_raw:
            at_capacity_since = float(at_capacity_since_raw)
            duration = now - at_capacity_since
            if duration >= SCALE_UP_DELAY:
                target = current_count + 1
                logger.info(
                    f"Autoscale UP: all {len(workers)} workers at capacity for "
                    f"{duration:.0f}s, scaling to {target}/{config.max_workers}"
                )
                if scale_workers(target):
                    r.delete(f"{PREFIX}:at_capacity_since")
                    result["action"] = "scaled_up"
                    result["new_count"] = target
                else:
                    result["action"] = "scale_up_failed"
            else:
                result["action"] = f"at_capacity_{duration:.0f}s"
        else:
            r.set(f"{PREFIX}:at_capacity_since", str(now))
            result["action"] = "capacity_tracking_started"
    else:
        # Not at capacity — clear the tracking timestamp
        r.delete(f"{PREFIX}:at_capacity_since")

    # --- Scale DOWN logic ---
    if any_idle and current_count > 1 and not all_at_capacity:
        idle_since_raw = r.get(f"{PREFIX}:idle_since")
        if idle_since_raw:
            idle_since = float(idle_since_raw)
            duration = now - idle_since
            if duration >= SCALE_DOWN_DELAY:
                logger.info(
                    f"Autoscale DOWN: idle worker detected for {duration:.0f}s, "
                    f"scaling down from {current_count}"
                )
                if scale_down_one():
                    r.delete(f"{PREFIX}:idle_since")
                    result["action"] = "scaled_down"
                    result["new_count"] = current_count - 1
                else:
                    result["action"] = "scale_down_failed"
            else:
                if "action" not in result or result["action"] == "capacity_tracking_started":
                    result["action"] = f"idle_{duration:.0f}s"
        else:
            r.set(f"{PREFIX}:idle_since", str(now))
            if "action" not in result:
                result["action"] = "idle_tracking_started"
    else:
        # No idle workers — clear the tracking timestamp
        r.delete(f"{PREFIX}:idle_since")

    if "action" not in result:
        result["action"] = "no_change"

    return result


def get_status() -> AutoscaleStatus:
    """Get full autoscale status for the API."""
    config = get_config()
    workers = get_worker_info()
    current_count = get_worker_container_count()
    r = _get_redis()

    at_capacity_since_raw = r.get(f"{PREFIX}:at_capacity_since")
    idle_since_raw = r.get(f"{PREFIX}:idle_since")

    return AutoscaleStatus(
        enabled=config.enabled,
        max_workers=config.max_workers,
        current_workers=current_count,
        total_active_tasks=sum(w.active_tasks for w in workers),
        workers=[{"name": w.name, "active_tasks": w.active_tasks} for w in workers],
        at_capacity_since=float(at_capacity_since_raw) if at_capacity_since_raw else None,
        idle_since=float(idle_since_raw) if idle_since_raw else None,
    )
