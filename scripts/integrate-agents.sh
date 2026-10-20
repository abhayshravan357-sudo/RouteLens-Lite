#!/usr/bin/env bash
# RouteLens Agent Integration
#
# Merges agent branches one at a time into the integration branch,
# running the relevant checks after each merge so a broken merge is
# caught at the step that caused it.
#
# The script never resets, cleans, or discards anything. If a merge
# conflicts it stops and says so, leaving the conflict in place for a
# human to resolve.

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT" || exit 1

INTEGRATION_BRANCH="${INTEGRATION_BRANCH:-integration/baseline-2026-10-20}"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info()  { echo -e "${BLUE}[INFO]${NC} $*"; }
log_ok()    { echo -e "${GREEN}[OK]${NC}   $*"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
log_error() { echo -e "${RED}[FAIL]${NC} $*"; }

run_checks() {
    log_info "Running backend tests..."
    ( cd backend && source .venv/bin/activate && python -m pytest -q ) 2>&1 | tail -5
    local backend_status=${PIPESTATUS[0]}

    log_info "Running frontend build..."
    ( cd frontend && npx tsc --noEmit && npm run build ) 2>&1 | tail -3
    local frontend_status=${PIPESTATUS[0]}

    if [[ ${backend_status} -ne 0 ]]; then
        log_error "Backend tests failed after the merge."
        return 1
    fi
    if [[ ${frontend_status} -ne 0 ]]; then
        log_error "Frontend build failed after the merge."
        return 1
    fi
    return 0
}

integrate_branch() {
    local branch="$1"
    local label="$2"

    log_info "--- Integrating ${label} (${branch}) ---"

    # Never integrate a branch with nothing in it.
    local ahead
    ahead=$(git rev-list --count "${INTEGRATION_BRANCH}..${branch}" 2>/dev/null || echo 0)
    if [[ "${ahead}" == "0" ]]; then
        log_warn "${label} has no commits beyond the integration branch; skipping."
        return 0
    fi

    # Show what is coming.
    log_info "Commits to integrate:"
    git log --oneline "${INTEGRATION_BRANCH}..${branch}" | sed 's/^/    /'

    log_info "Files changed:"
    git diff --stat "${INTEGRATION_BRANCH}..${branch}" | sed 's/^/    /'

    # Refuse to merge with a dirty tree.
    if [[ -n "$(git status --short)" ]]; then
        log_error "The working tree is not clean. Commit or stash before integrating."
        git status --short | sed 's/^/    /'
        return 1
    fi

    if ! git merge --no-ff -m "Merge ${label}: ${branch}" "${branch}"; then
        log_error "Merge conflicted. Resolve it and run 'git merge --continue'."
        git status --short | sed 's/^/    /'
        return 1
    fi

    log_ok "${label} merged."

    if ! run_checks; then
        log_error "Checks failed after merging ${label}. The merge is in place for review."
        return 1
    fi

    log_ok "Checks pass after ${label}."
    return 0
}

# Branches in integration order. Each is merged and verified before the
# next one, so a fault is found at the change that caused it.
BRANCHES=(
    "feature/routing-table-api|routing table API (RouteCore)"
    "feature/lab-verification|packet lab verification (PacketLab)"
    "feature/pcap-backend|PCAP importer backend (Autonomous Engineering)"
    "feature/pcap-ui|PCAP importer UI and topology map (JourneyUI)"
    "feature/browser-e2e-expansion|browser test expansion (TestPilot)"
)

main() {
    log_info "RouteLens integration into ${INTEGRATION_BRANCH}"
    log_info "Repository: ${REPO_ROOT}"
    echo ""

    local current
    current=$(git branch --show-current)
    if [[ "${current}" != "${INTEGRATION_BRANCH}" ]]; then
        log_error "Expected to be on ${INTEGRATION_BRANCH} but am on ${current}."
        exit 1
    fi

    local entry branch label
    for entry in "${BRANCHES[@]}"; do
        branch="${entry%%|*}"
        label="${entry##*|}"

        if ! git rev-parse --verify "${branch}" >/dev/null 2>&1; then
            log_warn "Branch ${branch} does not exist; skipping."
            continue
        fi

        if ! integrate_branch "${branch}" "${label}"; then
            log_error "Stopping at ${label}. Nothing further was merged."
            exit 1
        fi
        echo ""
    done

    log_ok "All branches integrated and verified."
    log_info "Final state:"
    git log --oneline -1 | sed 's/^/    /'
    git status --short | sed 's/^/    /'
}

main "$@"
