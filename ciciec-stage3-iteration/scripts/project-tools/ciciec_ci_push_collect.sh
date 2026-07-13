#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  tools/ciciec_ci_push_collect.sh [--dry-run] [--] [git-push-args...]

Reliable local entry point for CICIEC Stage 3 iteration:
  1. run git push for the submission repository;
  2. after a successful push, wait for GitLab CI and update local CI data files.

Environment:
  GITLAB_TOKEN              required; used only by tools/collect_ciciec_ci.py
  CICIEC_SUBMISSION_REPO    default: ./regional-submission
  CICIEC_CI_REF             default: CICIEC_SUBMISSION_REF or submit/codex
  CICIEC_CI_REMOTE          default: origin
  CICIEC_CI_LIMIT           default: 30
  CICIEC_CI_POLL_SECONDS    default: 30
  CICIEC_CI_TIMEOUT_SECONDS default: 3600
  CICIEC_JUDGE_AFTER_CI     default: 0; set to 1 to submit the CI artifact to the judge
  CICIEC_JUDGE_USER         required when CICIEC_JUDGE_AFTER_CI=1
  CICIEC_JUDGE_PASSWORD     required when CICIEC_JUDGE_AFTER_CI=1
  CICIEC_JUDGE_COMMIT       default: pushed repo HEAD
  CICIEC_JUDGE_MARK_FINAL   default: 0; set to 1 to mark finished judge result as final
  CICIEC_JUDGE_BACKUP_BEST  default: 0; set to 1 to refresh best-code backup

Examples:
  export GITLAB_TOKEN='...'
  tools/ciciec_ci_push_collect.sh
  tools/ciciec_ci_push_collect.sh -- origin submit/codex
  CICIEC_JUDGE_AFTER_CI=1 tools/ciciec_ci_push_collect.sh
USAGE
}

dry_run=0
if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi
if [[ "${1:-}" == "--dry-run" ]]; then
  dry_run=1
  shift
fi
if [[ "${1:-}" == "--" ]]; then
  shift
fi

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
workspace="$(cd "$script_dir/.." && pwd)"
submission_repo="${CICIEC_SUBMISSION_REPO:-$workspace/regional-submission}"
ref="${CICIEC_CI_REF:-${CICIEC_SUBMISSION_REF:-submit/codex}}"
remote="${CICIEC_CI_REMOTE:-origin}"
limit="${CICIEC_CI_LIMIT:-30}"
poll_seconds="${CICIEC_CI_POLL_SECONDS:-30}"
timeout_seconds="${CICIEC_CI_TIMEOUT_SECONDS:-3600}"

if [[ -z "${GITLAB_TOKEN:-}" ]]; then
  echo "error: set GITLAB_TOKEN before pushing so CI data can be collected automatically" >&2
  exit 2
fi
if [[ ! -d "$submission_repo/.git" ]]; then
  echo "error: submission repo not found: $submission_repo" >&2
  exit 2
fi

push_args=("$@")
if [[ ${#push_args[@]} -eq 0 ]]; then
  push_args=("$remote" "$ref")
fi

echo "submission repo: $submission_repo"
echo "git push args: ${push_args[*]}"
echo "collector ref: $ref"

if [[ "$dry_run" -eq 1 ]]; then
  echo "dry run: would execute git push, then collect CI data"
  exit 0
fi

git -C "$submission_repo" push "${push_args[@]}"

cd "$workspace"
python3 tools/collect_ciciec_ci.py \
  --ref "$ref" \
  --limit "$limit" \
  --wait \
  --poll-seconds "$poll_seconds" \
  --timeout-seconds "$timeout_seconds"

if [[ "${CICIEC_JUDGE_AFTER_CI:-0}" == "1" ]]; then
  if [[ -z "${CICIEC_JUDGE_USER:-}" || -z "${CICIEC_JUDGE_PASSWORD:-}" ]]; then
    echo "error: set CICIEC_JUDGE_USER and CICIEC_JUDGE_PASSWORD when CICIEC_JUDGE_AFTER_CI=1" >&2
    exit 2
  fi
  judge_commit="${CICIEC_JUDGE_COMMIT:-$(git -C "$submission_repo" rev-parse HEAD)}"
  judge_args=(submit --ref "$ref" --commit "$judge_commit" --wait)
  if [[ "${CICIEC_JUDGE_MARK_FINAL:-0}" == "1" ]]; then
    judge_args+=(--mark-final)
  fi
  if [[ "${CICIEC_JUDGE_BACKUP_BEST:-0}" == "1" ]]; then
    judge_args+=(--backup-best)
  fi
  python3 tools/ciciec_judge.py "${judge_args[@]}"
fi
