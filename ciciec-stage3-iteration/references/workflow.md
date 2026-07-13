# CICIEC Stage 3 Workflow Reference

## Scope and Configuration

Initialize a new or incomplete workspace from the installed Skill directory:

```sh
export CICIEC_WORKSPACE=/path/to/ciciec_workspace
bash <skill-directory>/scripts/bootstrap_workspace.sh "$CICIEC_WORKSPACE"
```

The bootstrap command installs the five bundled tools and creates non-secret
project-memory and `ci_data` templates. It preserves existing files unless
`--force` is explicitly passed.

Set the workspace, submission repository, and submission ref before using live
commands:

```sh
export CICIEC_WORKSPACE=/path/to/ciciec_workspace
export CICIEC_SUBMISSION_REPO=regional-submission
export CICIEC_SUBMISSION_REF=submit/codex
cd "$CICIEC_WORKSPACE"
```

Configure service endpoints and identifiers. The public Skill intentionally
contains no private server address or project/lab ID:

```sh
export CICIEC_GITLAB_API_URL=https://gitlab.example.com/api/v4
export CICIEC_GITLAB_PROJECT_ID=123
export CICIEC_JUDGE_BASE_URL=https://judge.example.com
export CICIEC_STAGE3_LAB_ID='optional-if-auto-discovery-works'
```

The bootstrap command installs these bundled commands into the workspace:

- `tools/ciciec_iterate.sh`
- `tools/ciciec_ci_push_collect.sh`
- `tools/collect_ciciec_ci.py`
- `tools/ciciec_judge.py`
- `tools/update_ciciec_eval_winners.py`

## Secret Handling

Set credentials only in the shell:

```sh
export GITLAB_TOKEN='...'
export CICIEC_JUDGE_USER='...'
export CICIEC_JUDGE_PASSWORD='...'
```

If supported by the project toolchain, update the judge-side GitLab token with:

```sh
export CICIEC_JUDGE_GITLAB_TOKEN='...'
python3 tools/ciciec_judge.py set-token
```

Never write credential values into project files.

## Read-Only Status

Use this before making decisions:

```sh
tools/ciciec_iterate.sh status
```

If judge credentials are absent, the wrapper should still print local CI and
winner data and skip live judge status.

Direct read-only commands:

```sh
python3 tools/collect_ciciec_ci.py --limit 30
python3 tools/ciciec_judge.py status
python3 tools/ciciec_judge.py list-ci --show-projects --show-refs --limit 5
python3 tools/ciciec_judge.py list-submissions --limit 10
```

`tools/collect_ciciec_ci.py` requires `GITLAB_TOKEN`. Judge commands require
`CICIEC_JUDGE_USER` and `CICIEC_JUDGE_PASSWORD`.

## Data Sedimentation

Refresh GitLab CI evidence without pushing:

```sh
tools/ciciec_iterate.sh collect-ci
```

Equivalent direct command:

```sh
python3 tools/collect_ciciec_ci.py --limit 30 --wait --poll-seconds 30
```

Expected generated outputs:

- `ci_data/ciciec_stage3_ci_runs.jsonl`
- `ci_data/ciciec_stage3_ci_latest.md`

Record or refresh evaluator winner data:

```sh
python3 tools/update_ciciec_eval_winners.py
```

Expected generated outputs:

- `ci_data/ciciec_stage3_eval_results.jsonl`
- `ci_data/ciciec_stage3_score_winner_tree.json`
- `ci_data/ciciec_stage3_score_winner_tree.md`

## Online Judge

Dry-run latest successful artifact selection without submitting:

```sh
python3 tools/ciciec_judge.py submit --latest-success --dry-run --no-record
```

Submit the current repository HEAD artifact and wait for the board result:

```sh
tools/ciciec_iterate.sh judge-current
```

Equivalent direct command:

```sh
python3 tools/ciciec_judge.py submit --commit current --wait
```

Submit a known CI job:

```sh
python3 tools/ciciec_judge.py submit --job-id <job_id> --wait
```

This performs a live online-judge operation unless the tool finds an existing
submission for the job. It should update evaluator JSONL and the winner tree by
default.

## Full Chain

Run push, GitLab CI collection, online judge, and score recording:

```sh
tools/ciciec_iterate.sh full-chain
```

Required environment:

```sh
export GITLAB_TOKEN='...'
export CICIEC_JUDGE_USER='...'
export CICIEC_JUDGE_PASSWORD='...'
```

Equivalent direct command:

```sh
CICIEC_JUDGE_AFTER_CI=1 tools/ciciec_ci_push_collect.sh
```

Optional toolchain flags:

```sh
CICIEC_JUDGE_MARK_FINAL=1 CICIEC_JUDGE_AFTER_CI=1 tools/ciciec_ci_push_collect.sh
CICIEC_JUDGE_BACKUP_BEST=1 CICIEC_JUDGE_AFTER_CI=1 tools/ciciec_ci_push_collect.sh
```

`full-chain` performs live operations: it pushes the configured submission ref,
waits for CI, and submits a judge task when CI artifacts are available. Confirm
repository status and the selected ref before running it.

## Evidence to Read After a Run

```sh
sed -n '1,80p' ci_data/ciciec_stage3_ci_latest.md
sed -n '1,100p' ci_data/ciciec_stage3_score_winner_tree.md
tail -n 8 ci_data/ciciec_stage3_eval_results.jsonl
```

Use project memory for strategy context:

```sh
rg -n "Latest score winner|Online Judge Automation|Current Known Good State|CI Data Pipeline" CICIEC_STAGE3_PROJECT_MEMORY.md
```

Always re-read generated files before relying on recorded evidence.
