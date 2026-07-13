#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  bootstrap_workspace.sh [--force] [workspace]

Install the bundled CICIEC project tools and initialize non-secret project
memory/CI data templates. Existing files are preserved unless --force is used.

Workspace selection order:
  1. positional workspace argument
  2. CICIEC_WORKSPACE environment variable
USAGE
}

force=0
if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi
if [[ "${1:-}" == "--force" ]]; then
  force=1
  shift
fi

workspace="${1:-${CICIEC_WORKSPACE:-}}"
if [[ -z "$workspace" ]]; then
  echo "error: pass a workspace path or set CICIEC_WORKSPACE" >&2
  exit 2
fi

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
skill_dir="$(cd "$script_dir/.." && pwd)"
tool_source="$script_dir/project-tools"
template_source="$skill_dir/templates"

mkdir -p "$workspace/tools" "$workspace/ci_data"

install_file() {
  local source="$1"
  local target="$2"
  if [[ -e "$target" && "$force" -ne 1 ]]; then
    echo "preserved: $target"
    return
  fi
  cp "$source" "$target"
  echo "installed: $target"
}

for source in "$tool_source"/*; do
  target="$workspace/tools/$(basename "$source")"
  install_file "$source" "$target"
  chmod +x "$target"
done

install_file "$template_source/CICIEC_STAGE3_PROJECT_MEMORY.md" \
  "$workspace/CICIEC_STAGE3_PROJECT_MEMORY.md"
install_file "$template_source/CICIEC_STAGE3_CI_DATA_PIPELINE.md" \
  "$workspace/CICIEC_STAGE3_CI_DATA_PIPELINE.md"
install_file "$template_source/CICIEC_STAGE3_CI_RESULTS.md" \
  "$workspace/CICIEC_STAGE3_CI_RESULTS.md"
install_file "$template_source/ciciec.env.example" \
  "$workspace/ciciec.env.example"
install_file "$template_source/ciciec.env.example.ps1" \
  "$workspace/ciciec.env.example.ps1"
install_file "$template_source/ci_data/ciciec_stage3_score_winner_tree.json" \
  "$workspace/ci_data/ciciec_stage3_score_winner_tree.json"
install_file "$template_source/ci_data/ciciec_stage3_score_winner_tree.md" \
  "$workspace/ci_data/ciciec_stage3_score_winner_tree.md"
install_file "$template_source/ci_data/ciciec_stage3_ci_latest.md" \
  "$workspace/ci_data/ciciec_stage3_ci_latest.md"

for data_file in \
  ciciec_stage3_ci_runs.jsonl \
  ciciec_stage3_eval_results.jsonl \
  ciciec_stage3_strategy_summaries.jsonl; do
  target="$workspace/ci_data/$data_file"
  if [[ ! -e "$target" ]]; then
    : > "$target"
    echo "created: $target"
  else
    echo "preserved: $target"
  fi
done

echo
echo "Workspace initialized: $workspace"
echo "Next: review ciciec.env.example (Bash) or ciciec.env.example.ps1 (PowerShell)."
echo "Export the required values in the current shell before using live services."
echo "Then run: $workspace/tools/ciciec_iterate.sh status"
