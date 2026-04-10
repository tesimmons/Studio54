#!/usr/bin/env bash
# scripts/deploy.sh — Deploy a Studio54 service with cache-busting and verification
#
# Usage: ./scripts/deploy.sh <service> [--skip-verify]
#
# Handles the shared-image services:
#   studio54-service -> also restarts studio54-worker + studio54-beat
#   studio54-web     -> rebuilds and restarts web frontend

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

source "$SCRIPT_DIR/lib/logging.sh"
source "$SCRIPT_DIR/lib/docker.sh"
source "$SCRIPT_DIR/lib/validation.sh"

cd "$PROJECT_ROOT"

SERVICE="${1:-}"
SKIP_VERIFY="${2:-}"

if [[ -z "$SERVICE" ]]; then
    log_error "Usage: $0 <service> [--skip-verify]"
    echo ""
    echo "  Services:"
    echo "    studio54-service   (also restarts worker + beat)"
    echo "    studio54-web"
    echo "    studio54-worker"
    echo "    studio54-beat"
    echo "    studio54-db"
    echo "    studio54-redis"
    exit 1
fi

check_docker || exit 1

# Map service to its companions (shared image)
declare -A COMPANIONS=(
    ["studio54-service"]="studio54-worker studio54-beat"
    ["studio54-worker"]=""
    ["studio54-beat"]=""
    ["studio54-web"]=""
    ["studio54-db"]=""
    ["studio54-redis"]=""
)

if [[ ! "${COMPANIONS[$SERVICE]+_}" ]]; then
    log_error "Unknown service: ${SERVICE}"
    exit 1
fi

log_header "Deploying ${SERVICE}"

# --- Step 1: Build (only for services with a Dockerfile) ---
BUILDABLE_SERVICES=("studio54-service" "studio54-web")
if printf '%s\n' "${BUILDABLE_SERVICES[@]}" | grep -q "^${SERVICE}$"; then
    log_step "Building ${SERVICE} (--no-cache)..."
    dc build --no-cache "$SERVICE"
    log_success "Build complete"
fi

# --- Step 2: Stop and remove primary container ---
log_step "Stopping and removing ${SERVICE}..."
container_remove "$SERVICE"

# --- Step 3: Stop companions (share same image) ---
if [[ -n "${COMPANIONS[$SERVICE]}" ]]; then
    for companion in ${COMPANIONS[$SERVICE]}; do
        log_info "Stopping companion: ${companion}"
        container_remove "$companion"
    done
fi

# --- Step 4: Recreate containers ---
log_step "Starting ${SERVICE}..."
dc up -d --no-deps "$SERVICE"

if [[ -n "${COMPANIONS[$SERVICE]}" ]]; then
    for companion in ${COMPANIONS[$SERVICE]}; do
        log_info "Starting companion: ${companion}"
        dc up -d --no-deps "$companion"
    done
fi

# --- Step 5: Verify (optional, only for service) ---
if [[ "$SKIP_VERIFY" != "--skip-verify" && "$SERVICE" == "studio54-service" ]]; then
    log_step "Verifying deployment..."
    sleep 5  # give container a moment to start
    verify_deployment "studio54-service" \
        "$PROJECT_ROOT/studio54-service/app/main.py" \
        "/app/app/main.py" || log_warn "Verification inconclusive — check manually"
fi

# --- Step 6: Cleanup ---
log_step "Cleaning up dangling images..."
prune_images

# --- Summary ---
echo ""
log_success "Deployment complete: ${SERVICE}"
docker ps --filter "name=studio54" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
