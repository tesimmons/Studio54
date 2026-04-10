"""
Docker Compose Volume Mount Manager for Studio54

Manages dynamic volume mounts in docker-compose.yml:
- Validates host paths via busybox container probe
- Backs up and atomically writes compose file changes
- Spawns detached restart-agent container to recreate services
- Supports rollback from backup
"""

import logging
import os
import shutil
import tempfile
from datetime import datetime, timezone
from typing import Optional

import docker
import redis
from ruamel.yaml import YAML
from sqlalchemy.orm import Session

from app.config import settings
from app.models.storage_mount import StorageMount, MountStatus

logger = logging.getLogger(__name__)

# Path to compose file inside the container
COMPOSE_FILE_PATH = "/app/compose/docker-compose.yml"
COMPOSE_BACKUP_PATH = "/app/compose/docker-compose.yml.bak"

# Services that receive user-managed volume mounts
MANAGED_SERVICES = ["studio54-service", "studio54-worker", "studio54-beat"]

# System mount container paths that cannot be used by user mounts
PROTECTED_CONTAINER_PATHS = {
    "/var/run/docker.sock",
    "/app/compose/docker-compose.yml",
    "/app/compose/.env",
    "/app/logs",
    "/app", "/etc", "/var", "/proc", "/sys", "/dev", "/bin", "/sbin",
    "/usr", "/lib", "/lib64", "/root", "/tmp",
}

# System mount markers - these mounts are never modified by apply_mounts
SYSTEM_HOST_PATHS = {
    "/var/run/docker.sock",
    "./docker-compose.yml",
    "../.env",
}

# Redis lock key for concurrent apply prevention
APPLY_LOCK_KEY = "storage_mounts:apply_lock"
APPLY_LOCK_TTL = 300  # 5 minutes


def _get_docker_client() -> docker.DockerClient:
    """Get Docker client via socket."""
    return docker.from_env()


def _get_redis_client() -> redis.Redis:
    """Get Redis client."""
    return redis.from_url(settings.redis_url)


def validate_host_path(host_path: str) -> dict:
    """
    Validate that a host path exists by running a temporary busybox container.

    Returns:
        dict with keys: valid (bool), error (str|None), free_space_gb (float|None)
    """
    if not host_path or not host_path.startswith("/"):
        return {"valid": False, "error": "Host path must be an absolute path", "free_space_gb": None}

    try:
        client = _get_docker_client()

        # Run a busybox container that checks if the path exists and gets disk space
        result = client.containers.run(
            "busybox:latest",
            command=f'sh -c "test -d /probe && df -P /probe | tail -1 | awk \'{{print $4}}\'"',
            volumes={host_path: {"bind": "/probe", "mode": "ro"}},
            remove=True,
            network_mode="none",
            mem_limit="32m",
            name=f"studio54-path-probe-{os.getpid()}",
            detach=False,
        )

        output = result.decode("utf-8").strip() if isinstance(result, bytes) else str(result).strip()
        free_space_gb = None
        if output.isdigit():
            # df reports in 1K blocks
            free_space_gb = round(int(output) / (1024 * 1024), 2)

        return {"valid": True, "error": None, "free_space_gb": free_space_gb}

    except docker.errors.ContainerError as e:
        logger.warning(f"Path validation failed for {host_path}: {e}")
        return {"valid": False, "error": f"Path does not exist or is not accessible: {host_path}", "free_space_gb": None}
    except docker.errors.ImageNotFound:
        return {"valid": False, "error": "busybox image not found. Pull it with: docker pull busybox:latest", "free_space_gb": None}
    except docker.errors.APIError as e:
        logger.error(f"Docker API error during path validation: {e}")
        return {"valid": False, "error": f"Docker error: {str(e)}", "free_space_gb": None}
    except Exception as e:
        logger.error(f"Unexpected error during path validation: {e}")
        return {"valid": False, "error": f"Validation error: {str(e)}", "free_space_gb": None}


def validate_container_path(container_path: str) -> Optional[str]:
    """
    Validate that a container path doesn't conflict with system paths.

    Returns:
        Error message string if invalid, None if valid.
    """
    if not container_path or not container_path.startswith("/"):
        return "Container path must be an absolute path"

    # Check exact matches and prefix matches against protected paths
    for protected in PROTECTED_CONTAINER_PATHS:
        if container_path == protected or container_path.startswith(protected + "/"):
            return f"Container path conflicts with system path: {protected}"

    return None


def _load_compose() -> tuple:
    """Load docker-compose.yml with ruamel.yaml (preserves comments)."""
    yaml = YAML()
    yaml.preserve_quotes = True
    with open(COMPOSE_FILE_PATH, "r") as f:
        data = yaml.load(f)
    return yaml, data


def _backup_compose():
    """Create a backup of the current compose file."""
    shutil.copy2(COMPOSE_FILE_PATH, COMPOSE_BACKUP_PATH)
    logger.info(f"Backed up compose file to {COMPOSE_BACKUP_PATH}")


def _atomic_write_compose(yaml, data):
    """Write compose file. Uses direct write since the file is bind-mounted
    from the host and os.rename() fails with EBUSY on bind mounts."""
    compose_dir = os.path.dirname(COMPOSE_FILE_PATH)
    fd, tmp_path = tempfile.mkstemp(dir=compose_dir, suffix=".yml.tmp")
    try:
        with os.fdopen(fd, "w") as f:
            yaml.dump(data, f)
        # Copy content instead of rename — bind-mounted files can't be renamed
        shutil.copy2(tmp_path, COMPOSE_FILE_PATH)
        logger.info("Compose file written successfully")
    except Exception:
        raise
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


def _is_system_mount(volume_str: str) -> bool:
    """Check if a volume string represents a system mount."""
    # Parse the host path from the volume string (host:container[:mode])
    parts = volume_str.split(":")
    if len(parts) < 2:
        return False
    host_path = parts[0]

    # Check against known system paths
    for sys_path in SYSTEM_HOST_PATHS:
        if host_path == sys_path:
            return True

    # Check for log mounts and download mounts (contain env vars)
    if "${STUDIO54_DATA_DIR" in host_path and "/logs" in host_path:
        return True
    if "${SABNZBD_DOWNLOAD_DIR" in host_path:
        return True

    return False


def _is_managed_mount(volume_str: str) -> bool:
    """Check if a volume string has a managed mount comment marker."""
    # Managed mounts are identified by inline comment or by not being system mounts
    return not _is_system_mount(volume_str)


def _mount_to_volume_str(mount: StorageMount) -> str:
    """Convert a StorageMount DB record to a docker-compose volume string."""
    mode = "ro" if mount.read_only else "rw"
    return f"{mount.host_path}:{mount.container_path}:{mode}"


def get_pending_changes(db: Session) -> dict:
    """
    Compare DB mounts vs current compose volumes.

    Returns:
        dict with keys: has_changes (bool), additions (list), removals (list), changes (list)
    """
    # Get all active non-system mounts from DB
    db_mounts = db.query(StorageMount).filter(
        StorageMount.is_active == True,
        StorageMount.is_system == False,
    ).all()

    # Get current compose user mounts
    try:
        _, data = _load_compose()
    except Exception as e:
        logger.error(f"Failed to load compose file: {e}")
        return {"has_changes": False, "error": str(e), "additions": [], "removals": [], "changes": []}

    # Extract current user mounts from the service
    service = data.get("services", {}).get("studio54-service", {})
    current_volumes = service.get("volumes", [])
    current_user_mounts = {}
    for vol in current_volumes:
        vol_str = str(vol)
        if not _is_system_mount(vol_str):
            parts = vol_str.split(":")
            if len(parts) >= 2:
                current_user_mounts[parts[1].rstrip(":")] = vol_str

    # Build desired state from DB
    desired_mounts = {}
    for mount in db_mounts:
        desired_mounts[mount.container_path] = _mount_to_volume_str(mount)

    additions = []
    removals = []
    changes = []

    # Find additions and changes
    for container_path, vol_str in desired_mounts.items():
        if container_path not in current_user_mounts:
            additions.append({"container_path": container_path, "volume": vol_str})
        elif current_user_mounts[container_path] != vol_str:
            changes.append({
                "container_path": container_path,
                "old_volume": current_user_mounts[container_path],
                "new_volume": vol_str,
            })

    # Find removals
    for container_path, vol_str in current_user_mounts.items():
        if container_path not in desired_mounts:
            removals.append({"container_path": container_path, "volume": vol_str})

    has_changes = bool(additions or removals or changes)
    # Also check for any pending status mounts
    pending_count = db.query(StorageMount).filter(
        StorageMount.status == MountStatus.PENDING.value
    ).count()

    return {
        "has_changes": has_changes or pending_count > 0,
        "pending_count": pending_count,
        "additions": additions,
        "removals": removals,
        "changes": changes,
    }


def apply_mounts(db: Session) -> dict:
    """
    Apply all active StorageMounts from DB to docker-compose.yml and restart containers.

    Steps:
    1. Read all active StorageMounts from DB
    2. Back up current compose file
    3. Parse compose YAML
    4. Update volumes for managed services
    5. Atomic write
    6. Spawn restart-agent container
    7. Update mount statuses in DB

    Returns:
        dict with keys: success (bool), message (str)
    """
    # Acquire Redis lock to prevent concurrent applies
    r = _get_redis_client()
    lock_acquired = r.set(APPLY_LOCK_KEY, "1", nx=True, ex=APPLY_LOCK_TTL)
    if not lock_acquired:
        return {"success": False, "message": "Another apply operation is in progress. Please wait."}

    try:
        # Get all active mounts from DB
        all_mounts = db.query(StorageMount).filter(
            StorageMount.is_active == True,
        ).all()

        # Separate system and user mounts
        user_mounts = [m for m in all_mounts if not m.is_system]

        # Backup
        _backup_compose()

        # Load and parse compose
        yaml, data = _load_compose()
        services = data.get("services", {})

        # Update volumes for each managed service
        for service_name in MANAGED_SERVICES:
            service = services.get(service_name)
            if not service:
                logger.warning(f"Service {service_name} not found in compose file")
                continue

            current_volumes = service.get("volumes", [])

            # Keep system mounts, replace user mounts
            new_volumes = []
            for vol in current_volumes:
                vol_str = str(vol)
                if _is_system_mount(vol_str):
                    new_volumes.append(vol)

            # Add user mounts
            for mount in user_mounts:
                vol_str = _mount_to_volume_str(mount)
                new_volumes.append(vol_str)

            service["volumes"] = new_volumes

        # Atomic write
        _atomic_write_compose(yaml, data)

        # Update mount statuses
        now = datetime.now(timezone.utc)
        for mount in all_mounts:
            mount.status = MountStatus.APPLIED.value
            mount.last_applied_at = now
            mount.error_message = None
        db.commit()

        # Spawn restart agent
        _spawn_restart_agent()

        return {
            "success": True,
            "message": f"Applied {len(user_mounts)} user mount(s). Containers are restarting (~30s).",
        }

    except Exception as e:
        logger.error(f"Failed to apply mounts: {e}", exc_info=True)
        # Mark pending mounts as failed
        pending_mounts = db.query(StorageMount).filter(
            StorageMount.status == MountStatus.PENDING.value
        ).all()
        for mount in pending_mounts:
            mount.status = MountStatus.FAILED.value
            mount.error_message = str(e)
        db.commit()
        return {"success": False, "message": f"Failed to apply mounts: {str(e)}"}

    finally:
        r.delete(APPLY_LOCK_KEY)


def _spawn_restart_agent():
    """
    Spawn a detached container that runs docker compose up to recreate services.

    Uses the docker:cli image which includes docker compose.
    The agent self-removes after completion (--rm).
    """
    client = _get_docker_client()

    # Remove any leftover restart agent container
    try:
        old = client.containers.get("studio54-restart-agent")
        old.remove(force=True)
    except docker.errors.NotFound:
        pass

    compose_dir = os.path.dirname(COMPOSE_FILE_PATH)

    # We need the host path of the compose directory.
    # Since COMPOSE_FILE_PATH is /app/compose/docker-compose.yml inside the container,
    # and it's bind-mounted from the host, we need to find the host path.
    # We can inspect our own container's mounts to find it.
    host_compose_dir = None
    try:
        # Find our own container
        hostname = os.environ.get("HOSTNAME", "")
        if hostname:
            container = client.containers.get(hostname)
            for mount in container.attrs.get("Mounts", []):
                if mount.get("Destination") == COMPOSE_FILE_PATH:
                    host_compose_dir = os.path.dirname(mount["Source"])
                    break
    except Exception as e:
        logger.warning(f"Could not determine host compose dir from container mounts: {e}")

    if not host_compose_dir:
        # Fallback: try looking up studio54-service container by name
        try:
            svc = client.containers.get("studio54-service")
            for mount in svc.attrs.get("Mounts", []):
                if mount.get("Destination") == COMPOSE_FILE_PATH:
                    host_compose_dir = os.path.dirname(mount["Source"])
                    break
        except Exception as e:
            logger.error(f"Could not determine host compose dir: {e}")
            raise RuntimeError("Cannot determine host path of docker-compose.yml for restart agent")

    host_compose_file = os.path.join(host_compose_dir, "docker-compose.yml")

    # Also need the .env file path (one directory up from compose dir)
    host_env_dir = os.path.dirname(host_compose_dir)

    logger.info(f"Spawning restart agent with compose file at host path: {host_compose_file}")

    services_str = " ".join(MANAGED_SERVICES)
    command = (
        f"sleep 3 && "
        f"docker compose -f /config/docker-compose.yml "
        f"--env-file /config-parent/.env "
        f"up -d --force-recreate {services_str}"
    )

    client.containers.run(
        "docker:cli",
        command=f"sh -c '{command}'",
        volumes={
            "/var/run/docker.sock": {"bind": "/var/run/docker.sock", "mode": "rw"},
            host_compose_dir: {"bind": "/config", "mode": "ro"},
            host_env_dir: {"bind": "/config-parent", "mode": "ro"},
        },
        detach=True,
        remove=True,
        name="studio54-restart-agent",
        network_mode="none",
    )

    logger.info("Restart agent container spawned successfully")


def rollback(db: Session) -> dict:
    """
    Restore docker-compose.yml from backup and restart containers.

    Returns:
        dict with keys: success (bool), message (str)
    """
    if not os.path.exists(COMPOSE_BACKUP_PATH):
        return {"success": False, "message": "No backup file found. Cannot rollback."}

    # Acquire Redis lock
    r = _get_redis_client()
    lock_acquired = r.set(APPLY_LOCK_KEY, "1", nx=True, ex=APPLY_LOCK_TTL)
    if not lock_acquired:
        return {"success": False, "message": "Another operation is in progress. Please wait."}

    try:
        # Restore backup
        shutil.copy2(COMPOSE_BACKUP_PATH, COMPOSE_FILE_PATH)
        logger.info("Restored compose file from backup")

        # Reset any pending/failed mounts
        mounts_to_reset = db.query(StorageMount).filter(
            StorageMount.status.in_([MountStatus.PENDING.value, MountStatus.FAILED.value])
        ).all()
        for mount in mounts_to_reset:
            if mount.last_applied_at:
                mount.status = MountStatus.APPLIED.value
            else:
                # Never applied - deactivate
                mount.is_active = False
                mount.status = MountStatus.FAILED.value
                mount.error_message = "Rolled back before first apply"
        db.commit()

        # Spawn restart agent
        _spawn_restart_agent()

        return {
            "success": True,
            "message": "Rolled back to previous configuration. Containers are restarting (~30s).",
        }

    except Exception as e:
        logger.error(f"Rollback failed: {e}", exc_info=True)
        return {"success": False, "message": f"Rollback failed: {str(e)}"}

    finally:
        r.delete(APPLY_LOCK_KEY)
