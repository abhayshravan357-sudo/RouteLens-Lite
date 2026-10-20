#!/usr/bin/env bash
# RouteLens Quality Check Runner
# Safe automated quality checks for the RouteLens project
# 
# This script performs safe, read-only quality checks:
# - Git repository validation
# - Backend Python tests
# - Frontend TypeScript type checking
# - Frontend production build
# - Git diff whitespace check
# 
# It never modifies source files, stages changes, or alters Git history.

set -uo pipefail

# Configuration
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPORT_DIR="${REPO_ROOT}/.routelens/reports"
TIMESTAMP="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
REPORT_FILE="${REPORT_DIR}/check-$(date -u +"%Y%m%d-%H%M%S").json"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Results tracking
declare -A CHECK_RESULTS
declare -A CHECK_COMMANDS
declare -A CHECK_OUTPUTS
declare -A CHECK_DURATIONS
OVERALL_SUCCESS=true

# Ensure report directory exists
mkdir -p "${REPORT_DIR}"

# Helper functions
log_info() { echo -e "${BLUE}[INFO]${NC} $*"; }
log_success() { echo -e "${GREEN}[PASS]${NC} $*"; }
log_warning() { echo -e "${YELLOW}[WARN]${NC} $*"; }
log_error() { echo -e "${RED}[FAIL]${NC} $*"; }

run_check() {
    local check_name="$1"
    local cmd="$2"
    local required="${3:-true}"
    
    log_info "Running check: ${check_name}"
    CHECK_COMMANDS["${check_name}"]="${cmd}"
    
    local start_time
    start_time=$(date +%s.%N)
    
    local output
    local exit_code=0
    output=$(eval "${cmd}" 2>&1) || exit_code=$?
    
    local end_time
    end_time=$(date +%s.%N)
    local duration
    duration=$(echo "${end_time} - ${start_time}" | bc -l)
    
    CHECK_RESULTS["${check_name}"]=${exit_code}
    CHECK_OUTPUTS["${check_name}"]="${output}"
    CHECK_DURATIONS["${check_name}"]="${duration}"
    
    if [[ ${exit_code} -eq 0 ]]; then
        log_success "${check_name} (${duration}s)"
        CHECK_RESULTS["${check_name}_status"]="pass"
    else
        if [[ "${required}" == "true" ]]; then
            log_error "${check_name} failed (${duration}s)"
            OVERALL_SUCCESS=false
            CHECK_RESULTS["${check_name}_status"]="fail"
        else
            log_warning "${check_name} failed (non-blocking)"
            CHECK_RESULTS["${check_name}_status"]="fail_nonblocking"
        fi
        CHECK_OUTPUTS["${check_name}"]="${output}"
    fi
    
    CHECK_DURATIONS["${check_name}"]="${duration}"
}

# JSON escaping function
json_escape() {
    local input="$1"
    input="${input//\\/\\\\}"
    input="${input//\"/\\\"}"
    input="${input//$'\n'/\\n}"
    input="${input//$'\t'/\\t}"
    input="${input//$'\r'/\\r}"
    echo "${input}"
}

generate_report() {
    local overall_status="pass"
    if [[ "${OVERALL_SUCCESS}" != "true" ]]; then
        overall_status="fail"
    fi
    
    # Build JSON report using printf to avoid heredoc issues
    local json_report
    json_report=$(
        cat <<'EOF'
{
  "repository": "REPO_ROOT_PLACEHOLDER",
  "timestamp": "TIMESTAMP_PLACEHOLDER",
  "branch": "BRANCH_PLACEHOLDER",
  "commit": "COMMIT_PLACEHOLDER",
  "overall_status": "OVERALL_STATUS_PLACEHOLDER",
  "checks": {
EOF
)
    
    local first=true
    for check_name in "${!CHECK_RESULTS[@]}"; do
        [[ "${check_name}" == *"_status" ]] && continue
        [[ "${check_name}" == *"_duration" ]] && continue
        
        if [[ "${first}" != "true" ]]; then
            json_report+=","
        fi
        first=false
        
        local status="${CHECK_RESULTS[${check_name}_status]:-unknown}"
        local exit_code="${CHECK_RESULTS[${check_name}]:-1}"
        local duration="${CHECK_DURATIONS[${check_name}]:-0}"
        local cmd="${CHECK_COMMANDS[${check_name}]:-}"
        local output="$(json_escape "${CHECK_OUTPUTS[${check_name}]:-}")"
        
        json_report+=$(cat <<EOF
    "$(json_escape "${check_name}")": {
      "status": "$(json_escape "${status}")",
      "exit_code": ${exit_code},
      "duration_seconds": ${duration},
      "command": "$(json_escape "${cmd}")",
      "output": "$(json_escape "${output}")"
    }
EOF
)
    done
    
    json_report+=$(cat <<'EOF'
  },
  "git_status": {
    "branch": "BRANCH_PLACEHOLDER",
    "short_status": "SHORT_STATUS_PLACEHOLDER",
    "diff_stat": "DIFF_STAT_PLACEHOLDER"
  }
}
EOF
)
    
    # Replace placeholders
    local branch_name
    branch_name=$(git -C "${REPO_ROOT}" branch --show-current 2>/dev/null || echo 'unknown')
    local commit_hash
    commit_hash=$(git -C "${REPO_ROOT}" rev-parse HEAD 2>/dev/null || echo 'unknown')
    local short_status
    short_status=$(git -C "${REPO_ROOT}" status --short 2>/dev/null | head -50)
    local diff_stat
    diff_stat=$(git -C "${REPO_ROOT}" diff --stat 2>/dev/null || echo '')
    
    json_report="${json_report//REPO_ROOT_PLACEHOLDER/$(json_escape "${REPO_ROOT}")}"
    json_report="${json_report//TIMESTAMP_PLACEHOLDER/$(json_escape "${TIMESTAMP}")}"
    json_report="${json_report//BRANCH_PLACEHOLDER/$(json_escape "${branch_name}")}"
    json_report="${json_report//COMMIT_PLACEHOLDER/$(json_escape "${commit_hash}")}"
    json_report="${json_report//OVERALL_STATUS_PLACEHOLDER/$(json_escape "${overall_status}")}"
    json_report="${json_report//BRANCH_PLACEHOLDER/$(json_escape "${branch_name}")}"
    json_report="${json_report//COMMIT_PLACEHOLDER/$(json_escape "${commit_hash}")}"
    json_report="${json_report//OVERALL_STATUS_PLACEHOLDER/$(json_escape "${overall_status}")}"
    json_report="${json_report//BRANCH_PLACEHOLDER/$(json_escape "${branch_name}")}"
    json_report="${json_report//SHORT_STATUS_PLACEHOLDER/$(json_escape "${short_status}")}"
    json_report="${json_report//DIFF_STAT_PLACEHOLDER/$(json_escape "${diff_stat}")}"
    
    echo "${json_report}" > "${REPORT_FILE}"
    
    # Also create a markdown report
    local md_report="${REPORT_FILE%.json}.md"
    cat > "${md_report}" <<EOF
# RouteLens Quality Check Report

**Repository:** ${REPO_ROOT}  
**Timestamp:** ${TIMESTAMP}  
**Branch:** $(git -C "${REPO_ROOT}" branch --show-current 2>/dev/null || echo 'unknown')  
**Commit:** $(git -C "${REPO_ROOT}" rev-parse HEAD 2>/dev/null || echo 'unknown')  
**Overall Status:** ${overall_status}

## Checks

| Check | Status | Duration | Command |
|-------|--------|----------|---------|
EOF
    
    for check_name in "${!CHECK_RESULTS[@]}"; do
        [[ "${check_name}" == *"_status" ]] && continue
        [[ "${check_name}" == *"_duration" ]] && continue
        
        local status="${CHECK_RESULTS[${check_name}_status]:-unknown}"
        local exit_code="${CHECK_RESULTS[${check_name}]:-1}"
        local duration="${CHECK_DURATIONS[${check_name}]:-0}"
        local cmd="${CHECK_COMMANDS[${check_name}]:-}"
        
        local status_icon="❌"
        [[ "${status}" == "pass" ]] && status_icon="✅"
        [[ "${status}" == "fail_nonblocking" ]] && status_icon="⚠️"
        
        echo "| ${check_name} | ${status_icon} ${status} | ${duration}s | \`${cmd}\` |" >> "${md_report}"
    done
    
    cat >> "${md_report}" <<EOF

## Git Status

\`\`\`
$(git -C "${REPO_ROOT}" status --short 2>/dev/null || echo 'Failed to get git status')
\`\`\`

## Diff Stat

\`\`\`
$(git -C "${REPO_ROOT}" diff --stat 2>/dev/null || echo 'Failed to get diff stat')
\`\`\`

---
*Report generated at ${TIMESTAMP} by RouteLens Orchestrator*
EOF
    
    log_info "Reports generated: ${REPORT_FILE} and ${md_report}"
}

# Main execution
main() {
    log_info "RouteLens Quality Check Starting..."
    log_info "Repository: ${REPO_ROOT}"
    
    # Verify we're in the correct repository
    if [[ ! -d "${REPO_ROOT}/.git" ]]; then
        log_error "Not a Git repository: ${REPO_ROOT}"
        exit 1
    fi
    
    # Verify required directories
    if [[ ! -d "${REPO_ROOT}/backend" ]] || [[ ! -d "${REPO_ROOT}/frontend" ]]; then
        log_error "Missing backend/ or frontend/ directory"
        exit 1
    fi
    
    # Verify required commands
    local missing_cmds=()
    command -v git >/dev/null 2>&1 || missing_cmds+=("git")
    command -v python3 >/dev/null 2>&1 || missing_cmds+=("python3")
    command -v npm >/dev/null 2>&1 || missing_cmds+=("npm")
    command -v bc >/dev/null 2>&1 || missing_cmds+=("bc")
    
    if [[ ${#missing_cmds[@]} -gt 0 ]]; then
        log_error "Missing required commands: ${missing_cmds[*]}"
        exit 1
    fi
    
    # Record initial Git status
    local initial_status
    initial_status=$(git -C "${REPO_ROOT}" status --short 2>/dev/null || echo "Failed to get git status")
    
    # Run checks
    log_info "Running quality checks..."
    
    # 1. Git diff check (whitespace)
    run_check "git-diff-check" "git -C \"${REPO_ROOT}\" diff --check"
    
    # 2. Backend tests
    if [[ -d "${REPO_ROOT}/backend/.venv" ]]; then
        run_check "backend-tests" "cd \"${REPO_ROOT}/backend\" && source .venv/bin/activate && python -m pytest -q"
    else
        log_warning "Backend virtual environment not found, skipping backend tests"
        CHECK_RESULTS["backend-tests"]="1"
        CHECK_RESULTS["backend-tests_status"]="skip"
        CHECK_OUTPUTS["backend-tests"]="Virtual environment not found"
        CHECK_DURATIONS["backend-tests"]="0"
    fi
    
    # 3. Frontend TypeScript check
    if [[ -f "${REPO_ROOT}/frontend/package.json" ]]; then
        run_check "typescript-check" "cd \"${REPO_ROOT}/frontend\" && npx tsc --noEmit"
    else
        log_warning "Frontend package.json not found, skipping TypeScript check"
        CHECK_RESULTS["typescript-check"]="1"
        CHECK_RESULTS["typescript-check_status"]="skip"
        CHECK_OUTPUTS["typescript-check"]="package.json not found"
        CHECK_DURATIONS["typescript-check"]="0"
    fi
    
    # 4. Frontend production build
    if [[ -f "${REPO_ROOT}/frontend/package.json" ]]; then
        run_check "frontend-build" "cd \"${REPO_ROOT}/frontend\" && npm run build"
    else
        log_warning "Frontend package.json not found, skipping build"
        CHECK_RESULTS["frontend-build"]="1"
        CHECK_RESULTS["frontend-build_status"]="skip"
        CHECK_OUTPUTS["frontend-build"]="package.json not found"
        CHECK_DURATIONS["frontend-build"]="0"
    fi
    
    # Generate reports
    generate_report
    
    # Final Git status check
    local final_status
    final_status=$(git -C "${REPO_ROOT}" status --short 2>/dev/null || echo "Failed to get git status")
    
    if [[ "${OVERALL_SUCCESS}" == "true" ]]; then
        log_success "All required checks passed!"
        exit 0
    else
        log_error "Some required checks failed"
        exit 1
    fi
}

main "$@"