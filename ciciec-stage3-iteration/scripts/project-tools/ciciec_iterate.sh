#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  tools/ciciec_iterate.sh <command> [args...]

Commands:
  bootstrap       Print the project memory and automation entry points to read first.
  status          Show local CI/winner data, submission git status, and judge status if credentials are set.
  collect-ci      Refresh GitLab CI data using tools/collect_ciciec_ci.py --wait.
  judge-current   Submit/reuse the current submission HEAD's CI artifact in the online judge and wait.
  full-chain      Run push -> CI collection -> online judge -> score recording.
  ci-latest       Print the generated CI summary.
  winner          Print the generated score winner tree summary.

Required environment:
  collect-ci/full-chain: GITLAB_TOKEN
  judge-current/full-chain/status live judge probe: CICIEC_JUDGE_USER and CICIEC_JUDGE_PASSWORD

Optional environment:
  CICIEC_SUBMISSION_REPO    default: ./regional-submission
  CICIEC_CI_REF             default: CICIEC_SUBMISSION_REF or submit/codex
  CICIEC_CI_LIMIT           default: 30
  CICIEC_CI_POLL_SECONDS    default: 30
  CICIEC_CI_TIMEOUT_SECONDS default: 3600
  CICIEC_JUDGE_MARK_FINAL   default: 0; full-chain only
  CICIEC_JUDGE_BACKUP_BEST  default: 0; full-chain only

Examples:
  tools/ciciec_iterate.sh status
  tools/ciciec_iterate.sh collect-ci
  tools/ciciec_iterate.sh judge-current
  tools/ciciec_iterate.sh full-chain
USAGE
}

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
workspace="$(cd "$script_dir/.." && pwd)"
submission_repo="${CICIEC_SUBMISSION_REPO:-$workspace/regional-submission}"
ref="${CICIEC_CI_REF:-${CICIEC_SUBMISSION_REF:-submit/codex}}"
limit="${CICIEC_CI_LIMIT:-30}"
poll_seconds="${CICIEC_CI_POLL_SECONDS:-30}"
timeout_seconds="${CICIEC_CI_TIMEOUT_SECONDS:-3600}"

need_gitlab_token() {
  if [[ -z "${GITLAB_TOKEN:-}" ]]; then
    echo "error: set GITLAB_TOKEN in the shell" >&2
    exit 2
  fi
}

need_judge_credentials() {
  if [[ -z "${CICIEC_JUDGE_USER:-}" || -z "${CICIEC_JUDGE_PASSWORD:-}" ]]; then
    echo "error: set CICIEC_JUDGE_USER and CICIEC_JUDGE_PASSWORD in the shell" >&2
    exit 2
  fi
}

print_heading() {
  printf '\n== %s ==\n' "$1"
}

cmd="${1:-status}"
if [[ "$cmd" == "-h" || "$cmd" == "--help" ]]; then
  usage
  exit 0
fi
shift || true

cd "$workspace"

case "$cmd" in
  bootstrap)
    print_heading "Workspace"
    echo "$workspace"
    print_heading "Read first"
    echo "CICIEC_STAGE3_PROJECT_MEMORY.md"
    echo "CICIEC_STAGE3_CI_DATA_PIPELINE.md"
    echo "ci_data/ciciec_stage3_ci_latest.md"
    echo "ci_data/ciciec_stage3_score_winner_tree.md"
    print_heading "Useful commands"
    usage
    ;;

  status)
    print_heading "Submission repo"
    if [[ -d "$submission_repo/.git" ]]; then
      git -C "$submission_repo" status --short --branch
      git -C "$submission_repo" log --oneline -1
    else
      echo "missing submission repo: $submission_repo"
    fi

    print_heading "CI latest"
    if [[ -f ci_data/ciciec_stage3_ci_latest.md ]]; then
      sed -n '1,16p' ci_data/ciciec_stage3_ci_latest.md
    else
      echo "missing ci_data/ciciec_stage3_ci_latest.md"
    fi

    print_heading "Winner"
    if [[ -f ci_data/ciciec_stage3_score_winner_tree.md ]]; then
      sed -n '1,32p' ci_data/ciciec_stage3_score_winner_tree.md
    else
      echo "missing ci_data/ciciec_stage3_score_winner_tree.md"
    fi

    print_heading "Judge status"
    if [[ -n "${CICIEC_JUDGE_USER:-}" && -n "${CICIEC_JUDGE_PASSWORD:-}" ]]; then
      python3 tools/ciciec_judge.py status --ref "$ref"
    else
      echo "skipped: set CICIEC_JUDGE_USER and CICIEC_JUDGE_PASSWORD for live judge status"
    fi
    ;;

  collect-ci)
    need_gitlab_token
    python3 tools/collect_ciciec_ci.py \
      --ref "$ref" \
      --limit "$limit" \
      --wait \
      --poll-seconds "$poll_seconds" \
      --timeout-seconds "$timeout_seconds" \
      "$@"
    ;;

  judge-current)
    need_judge_credentials
    python3 tools/ciciec_judge.py submit --ref "$ref" --commit current --wait "$@"
    ;;

  full-chain)
    need_gitlab_token
    need_judge_credentials
    CICIEC_JUDGE_AFTER_CI=1 tools/ciciec_ci_push_collect.sh "$@"
    ;;

  ci-latest)
    sed -n '1,120p' ci_data/ciciec_stage3_ci_latest.md
    ;;

  winner)
    sed -n '1,140p' ci_data/ciciec_stage3_score_winner_tree.md
    ;;

  *)
    echo "error: unknown command: $cmd" >&2
    usage >&2
    exit 2
    ;;
esac
