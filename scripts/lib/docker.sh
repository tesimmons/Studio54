#!/usr/bin/env bash
# scripts/lib/docker.sh — Docker utility functions for Studio54 scripts

# Requires logging.sh to be sourced first

COMPOSE_FILE="${STUDIO54_COMPOSE_FILE:-$(dirname "$(dirname "$(dirname "${BASH_SOURCE[0]}")")")/docker-compose.yml}"
ENV_FILE="${STUDIO54_ENV_FILE:-$(dirname "$(dirname "$(dirname "${BASH_SOURCE[0]}")")")/.env}"

# Run docker compose with the correct file/env
dc() {
    docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" "$@"
}

# Check if Docker is available
docker_available() {
    command -v docker &>/dev/null && docker info &>/dev/null 2>&1
}

# Check if Docker Compose is available
compose_available() {
    docker compose version &>/dev/null 2>&1
}

# Check if a container is running
container_running() {
    local name="$1"
    docker ps --format '{{.Names}}' | grep -q "^${name}$"
}

# Check if a container exists (running or stopped)
container_exists() {
    local name="$1"
    docker ps -a --format '{{.Names}}' | grep -q "^${name}$"
}

# Wait for a container to become healthy
wait_healthy() {
    local name="$1"
    local timeout="${2:-120}"
    local elapsed=0
    local interval=5

    log_info "Waiting for ${name} to become healthy..."
    while [[ $elapsed -lt $timeout ]]; do
        local health
        health=$(docker inspect --format='{{.State.Health.Status}}' "$name" 2>/dev/null || echo "missing")
        case "$health" in
            healthy) log_success "${name} is healthy"; return 0 ;;
            unhealthy) log_error "${name} is unhealthy"; return 1 ;;
        esac
        sleep $interval
        elapsed=$((elapsed + interval))
        echo -n "."
    done
    echo ""
    log_warn "${name} health check timed out after ${timeout}s"
    return 1
}

# Stop and remove a container
container_remove() {
    local name="$1"
    if container_running "$name"; then
        log_info "Stopping ${name}..."
        docker stop "$name" 2>/dev/null || true
    fi
    if container_exists "$name"; then
        log_info "Removing ${name}..."
        docker rm "$name" 2>/dev/null || true
    fi
}

# Pull an image with retries
pull_image() {
    local image="$1"
    local max_retries="${2:-3}"
    local attempt=1
    while [[ $attempt -le $max_retries ]]; do
        log_info "Pulling ${image} (attempt ${attempt}/${max_retries})..."
        if docker pull "$image"; then
            return 0
        fi
        attempt=$((attempt + 1))
        [[ $attempt -le $max_retries ]] && sleep 5
    done
    log_error "Failed to pull ${image} after ${max_retries} attempts"
    return 1
}

# Build a service with --no-cache
build_no_cache() {
    local service="$1"
    log_step "Building ${service} (no cache)..."
    dc build --no-cache "$service"
}

# Prune dangling images
prune_images() {
    log_info "Pruning dangling images..."
    docker image prune -f
    docker builder prune -f
}

# Verify a file exists inside a running container (hash comparison)
verify_deployment() {
    local container="$1"
    local host_file="$2"
    local container_file="$3"

    if ! container_running "$container"; then
        log_warn "Container ${container} is not running — skipping verification"
        return 0
    fi

    local host_hash container_hash
    host_hash=$(md5sum "$host_file" 2>/dev/null | cut -d' ' -f1)
    container_hash=$(docker exec "$container" md5sum "$container_file" 2>/dev/null | cut -d' ' -f1)

    if [[ "$host_hash" == "$container_hash" && -n "$host_hash" ]]; then
        log_success "Deployment verified: ${container_file}"
        return 0
    else
        log_warn "Hash mismatch — deployment may not be current"
        log_debug "Host: ${host_hash}  Container: ${container_hash}"
        return 1
    fi
}

# Show resource usage for studio54 containers
show_container_stats() {
    docker stats --no-stream --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.NetIO}}" \
        $(docker ps --filter "name=studio54" --format "{{.Names}}" | tr '\n' ' ') 2>/dev/null || true
}
