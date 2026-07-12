# CICIEC Stage 3 迭代 Skill

这是一个面向 Codex 的 CICIEC Stage 3 SoC 项目迭代 Skill，用于复用项目记忆、
沉淀 GitLab CI 证据、提交在线评测、记录成绩，并维护自动生成的最优版本树。

本仓库提供流程编排 Skill。实际使用时，目标项目工作区需要提供配套的自动化脚本
和数据文件，具体要求见
[`references/workflow.md`](ciciec-stage3-iteration/references/workflow.md)。

## 运行效果

下面是通过完整迭代流程获得的前端测评结果。任务 `5267` 对应版本
`1f9cb365`，测评状态为 `Finished`，得分为 `100.00`，并已标记为最终提交版本。

![前端测评效果：最终提交版本获得 100 分](docs/images/frontend-evaluation.png)

## 主要能力

- 读取项目记忆、CI 数据和当前成绩 winner tree
- 收集 GitLab pipeline、job 和 artifact 证据
- 选择构建产物并提交在线评测
- 自动记录评测结果和最优版本
- 执行 push → CI → 在线评测 → 成绩沉淀的完整链路
- 在不同 Codex 会话之间复用项目状态和迭代经验

## 安装

```sh
git clone https://github.com/Niyu24-Hub/ciciec-stage3-iteration-skill.git
cp -R ciciec-stage3-iteration-skill/ciciec-stage3-iteration \
  "${CODEX_HOME:-$HOME/.codex}/skills/"
```

安装后，可以在 Codex 中使用 `$ciciec-stage3-iteration` 调用该 Skill。

## 配置

设置兼容的项目工作区、提交仓库目录和工作分支：

```sh
export CICIEC_WORKSPACE=/path/to/ciciec_workspace
export CICIEC_SUBMISSION_REPO=regional-submission
export CICIEC_SUBMISSION_REF=submit/codex
```

目标项目工作区需要提供以下配套工具：

- `tools/ciciec_iterate.sh`
- `tools/ciciec_ci_push_collect.sh`
- `tools/collect_ciciec_ci.py`
- `tools/ciciec_judge.py`
- `tools/update_ciciec_eval_winners.py`

## 基本用法

查看当前项目、CI 和评测状态：

```sh
tools/ciciec_iterate.sh status
```

收集最新 GitLab CI 证据：

```sh
tools/ciciec_iterate.sh collect-ci
```

执行完整迭代链路：

```sh
tools/ciciec_iterate.sh full-chain
```

`full-chain` 会执行真实的分支推送、CI 等待和在线评测提交。运行前应确认仓库
状态、提交分支和所需凭据均正确。

## 安全说明

GitLab 和在线评测凭据必须通过环境变量提供。请勿向本仓库提交访问令牌、密码、
Cookie、命令历史、比赛提交代码或生成的评测数据。

公开版本不包含：

- 个人文件系统路径和私有仓库标识
- GitLab Token 和在线评测凭据
- 比赛提交源代码及 CI 构建产物
- 自动生成的 CI、评测和 winner tree 数据文件

## 仓库结构

```text
.
├── README.md
├── LICENSE
├── docs/images/
│   └── frontend-evaluation.png
└── ciciec-stage3-iteration/
    ├── SKILL.md
    ├── agents/openai.yaml
    └── references/workflow.md
```

## 许可证

本项目使用 MIT License。
