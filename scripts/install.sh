#!/usr/bin/env bash
# scripts/install.sh — Full automated install for Studio54
#
# This script installs all prerequisites and sets up Studio54 from scratch.
# It is safe to run multiple times (idempotent).
#
# Usage: bash <(curl -fsSL https://raw.githubusercontent.com/tesimmons/Studio54/main/scripts/install.sh)
#   -or- ./scripts/install.sh  (if the repo is already cloned)

set -Eeuo pipefail

REPO_URL="https://github.com/tesimmons/Studio54.git"
INSTALL_DIR="${STUDIO54_INSTALL_DIR:-/opt/studio54}"
DATA_DIR="${STUDIO54_DATA_DIR:-/docker/studio54}"
SYSTEMD_UNIT="/etc/systemd/system/studio54.service"

# Minimal logging before lib is available
_info()  { echo -e "\033[0;34m[INFO]\033[0m  $*"; }
_ok()    { echo -e "\033[0;32m[OK]\033[0m    $*"; }
_warn()  { echo -e "\033[1;33m[WARN]\033[0m  $*"; }
_error() { echo -e "\033[0;31m[ERROR]\033[0m $*" >&2; }

banner() {
    echo -e "\033[0;35m\033[1m"
    echo "  ╔═══════════════════════════════════╗"
    echo "  ║          Studio54 Installer        ║"
    echo "  ║    Music & Audiobook Management    ║"
    echo "  ╚═══════════════════════════════════╝"
    echo -e "\033[0m"
}

###############################################################################
# Step 1 — OS detection
###############################################################################
detect_os() {
    if [[ -f /etc/os-release ]]; then
        # shellcheck disable=SC1091
        source /etc/os-release
        OS_ID="${ID:-unknown}"
        OS_VERSION="${VERSION_ID:-unknown}"
    else
        OS_ID="unknown"
        OS_VERSION="unknown"
    fi
    _info "Detected OS: ${OS_ID} ${OS_VERSION}"

    case "$OS_ID" in
        ubuntu|debian) PKG_MGR="apt-get" ;;
        fedora|rhel|centos) PKG_MGR="dnf" ;;
        *)
            _warn "Unsupported OS: ${OS_ID}. Proceeding anyway..."
            PKG_MGR="apt-get"
            ;;
    esac
}

###############################################################################
# Step 2 — Install Docker and Docker Compose
###############################################################################
install_docker() {
    if command -v docker &>/dev/null && docker compose version &>/dev/null 2>&1; then
        _ok "Docker already installed ($(docker --version | awk '{print $3}' | tr -d ','))"
        return 0
    fi

    _info "Installing Docker..."
    case "$PKG_MGR" in
        apt-get)
            sudo apt-get update -qq
            sudo apt-get install -y ca-certificates curl gnupg lsb-release
            sudo install -m 0755 -d /etc/apt/keyrings
            curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
                | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
            sudo chmod a+r /etc/apt/keyrings/docker.gpg
            echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
                https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" \
                | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
            sudo apt-get update -qq
            sudo apt-get install -y docker-ce docker-ce-cli containerd.io \
                docker-buildx-plugin docker-compose-plugin
            ;;
        dnf)
            sudo dnf install -y docker docker-compose-plugin
            ;;
    esac

    sudo systemctl enable --now docker
    sudo usermod -aG docker "$USER" || true
    _ok "Docker installed"
}

###############################################################################
# Step 3 — Clone or update the repository
###############################################################################
setup_repo() {
    if [[ -d "$INSTALL_DIR/.git" ]]; then
        _info "Repository exists at ${INSTALL_DIR} — pulling latest..."
        git -C "$INSTALL_DIR" pull --ff-only
    else
        _info "Cloning Studio54 to ${INSTALL_DIR}..."
        sudo git clone "$REPO_URL" "$INSTALL_DIR"
        sudo chown -R "$USER:$USER" "$INSTALL_DIR"
    fi
    _ok "Repository ready at ${INSTALL_DIR}"
}

###############################################################################
# Step 4 — Create .env from template
###############################################################################
setup_env() {
    local env_file="$INSTALL_DIR/.env"
    local example="$INSTALL_DIR/.env.example"

    if [[ -f "$env_file" ]]; then
        _ok ".env already exists — skipping"
        return 0
    fi

    _info "Creating .env from template..."
    cp "$example" "$env_file"

    # Generate secure random values
    local db_password encryption_key
    db_password=$(openssl rand -hex 32)
    encryption_key=$(python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())" 2>/dev/null \
        || openssl rand -base64 32)

    sed -i "s|STUDIO54_DB_PASSWORD=.*|STUDIO54_DB_PASSWORD=${db_password}|" "$env_file"
    sed -i "s|STUDIO54_ENCRYPTION_KEY=.*|STUDIO54_ENCRYPTION_KEY=${encryption_key}|" "$env_file"

    _ok ".env created with generated secrets"
    _warn "Review ${env_file} to set MUSIC_LIBRARY_PATH, AUDIOBOOKS_PATH, and any API keys"
}

###############################################################################
# Step 5 — Create data directories
###############################################################################
setup_dirs() {
    _info "Creating data directories..."
    local dirs=(
        "$DATA_DIR/postgres"
        "$DATA_DIR/redis"
        "$DATA_DIR/cover-art"
    )
    for dir in "${dirs[@]}"; do
        sudo mkdir -p "$dir"
    done
    sudo chown -R "$USER:$USER" "$DATA_DIR" 2>/dev/null || true
    _ok "Data directories created under ${DATA_DIR}"
}

###############################################################################
# Step 6 — Install systemd service
###############################################################################
install_systemd() {
    if [[ ! -f "$INSTALL_DIR/docs/studio54.service" ]]; then
        _warn "Systemd unit template not found — skipping service install"
        return 0
    fi

    _info "Installing systemd service..."
    sudo cp "$INSTALL_DIR/docs/studio54.service" "$SYSTEMD_UNIT"
    sudo sed -i "s|__INSTALL_DIR__|${INSTALL_DIR}|g" "$SYSTEMD_UNIT"
    sudo sed -i "s|__USER__|${USER}|g" "$SYSTEMD_UNIT"
    sudo systemctl daemon-reload
    sudo systemctl enable studio54
    _ok "Systemd service installed and enabled (auto-starts on boot)"
}

###############################################################################
# Step 7 — Pull Docker images
###############################################################################
pull_images() {
    _info "Pulling base images..."
    cd "$INSTALL_DIR"
    docker compose pull studio54-db studio54-redis studio54-dozzle 2>/dev/null || true
    _ok "Base images pulled"
}

###############################################################################
# Step 8 — Build application images
###############################################################################
build_images() {
    _info "Building Studio54 application images..."
    cd "$INSTALL_DIR"
    docker compose build --no-cache studio54-service studio54-web
    _ok "Application images built"
}

###############################################################################
# Step 9 — Start services
###############################################################################
start_services() {
    _info "Starting Studio54..."
    cd "$INSTALL_DIR"
    docker compose up -d
    _ok "Studio54 started"
}

###############################################################################
# Main
###############################################################################
main() {
    banner

    # Must run as non-root (with sudo available)
    if [[ $EUID -eq 0 ]]; then
        _error "Do not run as root. Run as a regular user with sudo privileges."
        exit 1
    fi

    detect_os

    _info "Install directory : ${INSTALL_DIR}"
    _info "Data directory    : ${DATA_DIR}"
    echo ""

    install_docker
    setup_repo
    setup_env
    setup_dirs
    install_systemd
    pull_images
    build_images
    start_services

    echo ""
    echo -e "\033[0;32m\033[1m✓ Studio54 installation complete!\033[0m"
    echo ""
    echo "  Web UI :  http://localhost:${STUDIO54_WEB_PORT:-8009}"
    echo "  API    :  http://localhost:${STUDIO54_SERVICE_PORT:-8010}"
    echo "  Dozzle :  http://localhost:${STUDIO54_DOZZLE_PORT:-9998}"
    echo ""
    echo "  Manage :  ${INSTALL_DIR}/studio54 <command>"
    echo "  Config :  ${INSTALL_DIR}/.env"
    echo ""
    _warn "If Docker group was just added for your user, log out and back in, then run:"
    _info "  cd ${INSTALL_DIR} && ./studio54 start"
}

main "$@"
