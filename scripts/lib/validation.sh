#!/usr/bin/env bash
# scripts/lib/validation.sh — Prerequisite and environment validation for Studio54

# Requires logging.sh to be sourced first

# Check that a command exists
require_command() {
    local cmd="$1"
    local install_hint="${2:-}"
    if ! command -v "$cmd" &>/dev/null; then
        log_error "Required command not found: ${cmd}"
        [[ -n "$install_hint" ]] && log_info "Install with: ${install_hint}"
        return 1
    fi
    return 0
}

# Verify Docker is installed and the daemon is running
check_docker() {
    if ! command -v docker &>/dev/null; then
        log_error "Docker is not installed"
        log_info "Run: ./studio54 install  (or scripts/install.sh)"
        return 1
    fi
    if ! docker info &>/dev/null 2>&1; then
        log_error "Docker daemon is not running"
        log_info "Start it with: sudo systemctl start docker"
        return 1
    fi
    if ! docker compose version &>/dev/null 2>&1; then
        log_error "Docker Compose plugin is not installed"
        log_info "Run: sudo apt-get install docker-compose-plugin"
        return 1
    fi
    log_success "Docker $(docker --version | awk '{print $3}' | tr -d ',')" \
        "— Compose $(docker compose version --short)"
    return 0
}

# Check that .env exists and has required variables
check_env() {
    local env_file="${1:-.env}"
    if [[ ! -f "$env_file" ]]; then
        log_error ".env file not found at ${env_file}"
        log_info "Copy the template: cp .env.example .env  then edit it"
        return 1
    fi

    local missing=()
    local required_vars=(
        STUDIO54_DB_PASSWORD
        STUDIO54_ENCRYPTION_KEY
    )
    # shellcheck disable=SC1090
    source "$env_file" 2>/dev/null || true
    for var in "${required_vars[@]}"; do
        [[ -z "${!var:-}" ]] && missing+=("$var")
    done

    if [[ ${#missing[@]} -gt 0 ]]; then
        log_error "Missing required .env variables: ${missing[*]}"
        return 1
    fi
    log_success ".env validated"
    return 0
}

# Check disk space (in GB)
check_disk_space() {
    local path="${1:-/}"
    local required_gb="${2:-10}"
    local available_gb
    available_gb=$(df -BG "$path" | awk 'NR==2 {gsub("G",""); print $4}')
    if [[ "$available_gb" -lt "$required_gb" ]]; then
        log_warn "Low disk space: ${available_gb}GB available (${required_gb}GB recommended)"
        return 1
    fi
    log_success "Disk space: ${available_gb}GB available"
    return 0
}

# Check that required directories exist or can be created
check_data_dirs() {
    local env_file="${1:-.env}"
    # shellcheck disable=SC1090
    [[ -f "$env_file" ]] && source "$env_file" 2>/dev/null || true

    local data_dir="${STUDIO54_DATA_DIR:-/docker/studio54}"
    local music_path="${MUSIC_LIBRARY_PATH:-/music}"
    local audiobooks_path="${AUDIOBOOKS_PATH:-/audiobooks}"

    local all_ok=0
    for dir in "$data_dir/postgres" "$data_dir/redis" "$data_dir/cover-art"; do
        if [[ ! -d "$dir" ]]; then
            log_warn "Data directory missing: ${dir}"
            all_ok=1
        fi
    done
    for dir in "$music_path" "$audiobooks_path"; do
        if [[ ! -d "$dir" ]]; then
            log_warn "Media directory missing: ${dir}  (create it or update .env)"
            all_ok=1
        fi
    done
    return $all_ok
}

# Full prerequisite check (used by 'studio54 check')
check_prerequisites() {
    local all_ok=0
    check_docker || all_ok=1

    # Optional: NVIDIA GPU
    if command -v nvidia-smi &>/dev/null; then
        log_success "NVIDIA GPU detected"
    else
        log_info "No NVIDIA GPU detected (not required for Studio54)"
    fi

    check_disk_space / 10 || all_ok=1
    return $all_ok
}
