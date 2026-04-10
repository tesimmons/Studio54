#!/usr/bin/env bash
# scripts/lib/logging.sh — Color-coded logging utilities for Studio54 scripts

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
MAGENTA='\033[0;35m'
WHITE='\033[1;37m'
GRAY='\033[0;37m'
BOLD='\033[1m'
NC='\033[0m' # No Color

# Studio54 brand color (hot pink)
PINK='\033[0;35m'

log_info()    { echo -e "${BLUE}[INFO]${NC}  $*"; }
log_success() { echo -e "${GREEN}[OK]${NC}    $*"; }
log_warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
log_error()   { echo -e "${RED}[ERROR]${NC} $*" >&2; }
log_debug()   { [[ "${DEBUG:-}" == "1" ]] && echo -e "${GRAY}[DEBUG]${NC} $*"; }
log_step()    { echo -e "${MAGENTA}[STEP]${NC}  ${BOLD}$*${NC}"; }
log_header()  { echo -e "\n${CYAN}${BOLD}=== $* ===${NC}\n"; }

# Progress spinner
spinner_pid=""
spinner_start() {
    local msg="${1:-Working...}"
    echo -ne "${BLUE}${msg}${NC} "
    (while true; do
        for c in '⠋' '⠙' '⠹' '⠸' '⠼' '⠴' '⠦' '⠧' '⠇' '⠏'; do
            echo -ne "\r${BLUE}${msg}${NC} ${c}"
            sleep 0.1
        done
    done) &
    spinner_pid=$!
}

spinner_stop() {
    if [[ -n "$spinner_pid" ]]; then
        kill "$spinner_pid" 2>/dev/null
        wait "$spinner_pid" 2>/dev/null
        spinner_pid=""
        echo -e "\r${GREEN}✓${NC}                          "
    fi
}

# Banner
print_banner() {
    echo -e "${PINK}${BOLD}"
    echo "  ╔═══════════════════════════════════╗"
    echo "  ║     ░░░░░░░░░░░░░░░░░░░░░░░░░     ║"
    echo "  ║     ░  ░░  ░░░  ░░░  ░░  ░░  ░    ║"
    echo "  ║     ░  ░░  ░░░  ░░░  ░░  ░░  ░    ║"
    echo "  ║     ░░░░░░░░░░░░░░░░░░░░░░░░░░    ║"
    echo "  ║          Studio54 Manager          ║"
    echo "  ║    Music & Audiobook Management    ║"
    echo "  ╚═══════════════════════════════════╝"
    echo -e "${NC}"
}
