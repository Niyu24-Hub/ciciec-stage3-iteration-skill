---
name: ciciec-stage3-iteration
description: CICIEC Stage 3 project iteration workflow for Codex CLI sessions. Use when working on a CICIEC Stage 3 SoC submission, especially for project-memory reuse, CI evidence collection, GitLab pipeline or artifact inspection, online-judge submission, score recording, winner-tree maintenance, or handing iterative development to another session.
---

# CICIEC Stage 3 Iteration

## Operating Model

Treat this as a project skill plus toolchain, not a separate long-running
agent. The Codex session remains the agent; use this skill to reuse project
memory, generated evidence, and automation scripts.

Set `CICIEC_WORKSPACE` to the compatible project workspace and work from it:

```sh
cd "$CICIEC_WORKSPACE"
```

If the variable is unset or the path does not exist, ask the user for the
workspace path. Allow the submission repository and working ref to be selected
with `CICIEC_SUBMISSION_REPO` and `CICIEC_SUBMISSION_REF`.

## Workspace Bootstrap

If the workspace does not contain the required `tools/`, memory files, or
`ci_data/` structure, install the bundled public toolchain before continuing:

```sh
bash <skill-directory>/scripts/bootstrap_workspace.sh "$CICIEC_WORKSPACE"
```

Preserve existing workspace files by default. Use `--force` only when the user
explicitly wants the bundled templates or tools to replace existing files.
Review `ciciec.env.example` and export the required service configuration in
the current shell; never source placeholder credential values unchanged.

## First Load

Inspect current state before acting:

```sh
pwd
sed -n '1,180p' CICIEC_STAGE3_PROJECT_MEMORY.md
sed -n '1,220p' CICIEC_STAGE3_CI_DATA_PIPELINE.md
sed -n '1,120p' ci_data/ciciec_stage3_score_winner_tree.md
git -C "$CICIEC_SUBMISSION_REPO" status --short --branch
```

Read `references/workflow.md` before running CI, judge, score-recording, or
full-chain commands.

## Core Capabilities

- **Data sedimentation**: use `tools/collect_ciciec_ci.py`, generated CI JSONL
  and Markdown summaries, evaluator JSONL, and the generated winner tree.
- **Full chain**: use `tools/ciciec_ci_push_collect.sh` with
  `tools/ciciec_judge.py`, or the convenience wrapper
  `tools/ciciec_iterate.sh`.
- **Winner policy**: trust the generated winner tree for score status, and
  update curated ledgers only when a result changes design direction.
- **Bundled setup**: use `scripts/bootstrap_workspace.sh`, bundled project
  tools, and templates to initialize a compatible workspace without private
  project files.

## Safety Rules

- Keep all tokens and judge credentials in environment variables only.
- Do not write access tokens, passwords, cookies, or command histories into
  project files.
- Do not modify `.gitlab-ci.yml` unless the user explicitly requests it.
- Do not push `main` or `master`; use the configured submission ref.
- Do not revert user changes. If the submission repository is dirty,
  understand whether those changes are relevant before running a full chain.

## Normal Loop

1. Inspect project memory, generated CI data, the winner tree, and repository
   status.
2. Make narrowly scoped code changes only when requested or clearly needed.
3. Run local checks appropriate to the change.
4. Use the wrapper for evidence collection:
   - `tools/ciciec_iterate.sh status`
   - `tools/ciciec_iterate.sh full-chain` when ready to push and measure
5. Read generated data, then record concise interpretation in project memory
   or a curated results ledger only when it changes future decisions.

## Detailed Commands

See `references/workflow.md` for exact command forms, required environment
variables, and which commands are read-only versus live-submitting.
