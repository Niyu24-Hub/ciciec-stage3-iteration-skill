# CICIEC Stage 3 Iteration Skill

A Codex skill for running a repeatable CICIEC Stage 3 SoC iteration workflow:
inspect project memory, collect GitLab CI evidence, submit artifacts to an online
judge, record scores, and maintain a generated winner tree.

The repository contains the orchestration skill only. The target project must
provide the companion scripts and data files described in
[`references/workflow.md`](ciciec-stage3-iteration/references/workflow.md).

## Install

```sh
git clone https://github.com/Niyu24-Hub/ciciec-stage3-iteration-skill.git
cp -R ciciec-stage3-iteration-skill/ciciec-stage3-iteration \
  "${CODEX_HOME:-$HOME/.codex}/skills/"
```

Then invoke it in Codex with `$ciciec-stage3-iteration`.

## Configure

Point the skill at a compatible project workspace:

```sh
export CICIEC_WORKSPACE=/path/to/ciciec_workspace
export CICIEC_SUBMISSION_REPO=regional-submission
export CICIEC_SUBMISSION_REF=submit/codex
```

CI and judge credentials must be supplied through environment variables. Never
commit tokens, passwords, cookies, generated evidence, or submission code to
this repository.

## What is intentionally excluded

- Personal filesystem paths and repository identifiers
- Access tokens and online-judge credentials
- Historical CI jobs, submissions, scores, and CRC values
- Competition submission source code and generated evidence

## License

MIT
