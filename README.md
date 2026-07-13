# CICIEC Stage 3 迭代 Skill

这是一个面向 Codex 的 CICIEC Stage 3 SoC 项目迭代 Skill。它将项目记忆、
GitLab CI、构建产物、在线评测、成绩记录和最优版本维护连接成一套可重复执行的
工作流，帮助不同 Codex 会话在已有证据基础上继续开发，而不是每次重新理解项目。

> 本 Skill 是 Codex 的项目操作规程和流程编排层，不是独立运行的常驻机器人。
> 仓库已包含 CI 收集、在线评测、winner tree 更新、完整链路包装器和工作区初始化
> 模板；用户只需提供自己的项目代码、服务地址、项目 ID 和访问凭据。

## 运行效果

下面是通过完整迭代流程获得的前端测评结果。任务 `5267` 对应版本
`1f9cb365`，测评状态为 `Finished`，得分为 `100.00`，并已标记为最终提交版本。

![前端测评效果：最终提交版本获得 100 分](docs/images/frontend-evaluation.png)

## Skill 的作用

普通开发会话结束后，关键状态往往散落在聊天记录、Git 提交、CI 页面和评测页面
中。下一个会话需要重新查找这些信息，容易重复尝试、遗漏最佳版本或误用旧数据。

本 Skill 主要解决以下问题：

| 问题 | Skill 提供的作用 |
| --- | --- |
| 新会话不了解项目现状 | 优先读取项目记忆、最新 CI 摘要和 winner tree |
| CI 结果只存在网页中 | 将 pipeline、job、commit 和 artifact 信息沉淀为本地数据 |
| 构建成功后需要手工提交评测 | 统一产物选择、在线提交、等待结果和成绩记录流程 |
| 多个版本难以判断最佳结果 | 根据评测数据生成并维护 score winner tree |
| 失败和低分实验被重复执行 | 保留历史证据，让后续决策建立在已有结果之上 |
| 推送、评测等操作风险较高 | 区分只读、干运行和真实提交命令，并设置分支与凭据边界 |

## 核心能力

- **项目上下文恢复**：读取项目记忆、CI 数据管线说明、当前 winner tree 和仓库状态。
- **CI 证据沉淀**：收集 GitLab pipeline、job、commit、状态和 artifact 信息。
- **在线评测自动化**：选择成功构建产物，提交在线评测并等待最终结果。
- **成绩持续记录**：将任务、版本、得分和运行结果追加到结构化数据中。
- **最优版本维护**：从历史成绩中生成 winner tree，识别当前最佳版本。
- **完整迭代闭环**：串联代码修改、检查、推送、CI、评测和下一轮决策。
- **跨会话协作**：让新的 Codex 会话基于持久化证据继续工作。
- **操作安全约束**：保护凭据，避免误推主分支、覆盖用户修改或误触实时评测。

## 完整工作流程

```mermaid
flowchart TD
    A[用户提出开发或评测目标] --> B[Codex 加载 Skill]
    B --> C[读取项目记忆、CI 摘要、winner tree 和 Git 状态]
    C --> D{是否需要修改代码}
    D -- 否 --> E[查看现有 CI 与评测证据]
    D -- 是 --> F[进行小范围代码修改]
    F --> G[执行本地检查]
    G --> H[推送配置的提交分支]
    H --> I[等待并收集 GitLab CI]
    E --> J{是否已有可用构建产物}
    I --> K{CI 是否成功}
    K -- 否 --> L[记录失败证据并分析原因]
    L --> C
    K -- 是 --> J
    J -- 否 --> C
    J -- 是 --> M[选择对应 commit 的 artifact]
    M --> N[提交在线评测并等待结果]
    N --> O[记录任务、版本、得分和运行数据]
    O --> P[更新 score winner tree]
    P --> Q{结果是否改变后续方向}
    Q -- 是 --> R[更新项目记忆或决策记录]
    Q -- 否 --> S[保留生成数据，不重复记录]
    R --> T[进入下一轮迭代]
    S --> T
```

### 各阶段说明

| 阶段 | Codex 的动作 | 主要产物 |
| --- | --- | --- |
| 1. 状态恢复 | 读取项目记忆、CI 摘要、winner tree、Git 状态 | 当前已知状态和最佳版本 |
| 2. 开发修改 | 根据目标进行小范围修改，保留用户已有改动 | 待验证的代码版本 |
| 3. 本地验证 | 执行与修改范围匹配的检查 | 本地检查结果 |
| 4. CI 构建 | 推送指定分支，等待 GitLab pipeline 和 job | CI 状态与构建 artifact |
| 5. 在线评测 | 选择正确 commit 的成功产物并提交 | 评测任务和最终得分 |
| 6. 数据沉淀 | 写入 CI、评测结果和 winner tree | JSONL、JSON、Markdown 摘要 |
| 7. 决策更新 | 只在结果改变后续方向时更新项目记忆 | 下一轮可复用的策略上下文 |

## 输入与输出

### 输入

Skill 运行时通常需要以下信息：

- 用户提出的开发、验证、CI 收集或在线评测目标
- 兼容的 CICIEC 项目工作区
- 提交仓库目录和允许推送的工作分支
- 项目记忆、CI 数据和已有评测记录
- 通过环境变量提供的 GitLab 与在线评测凭据

### 输出

配套工具链通常维护以下数据：

| 文件 | 内容 |
| --- | --- |
| `ci_data/ciciec_stage3_ci_runs.jsonl` | 历次 CI pipeline 和 job 的结构化记录 |
| `ci_data/ciciec_stage3_ci_latest.md` | 最新 CI 状态的人类可读摘要 |
| `ci_data/ciciec_stage3_eval_results.jsonl` | 历次在线评测任务与成绩记录 |
| `ci_data/ciciec_stage3_score_winner_tree.json` | 机器可读的最优版本关系 |
| `ci_data/ciciec_stage3_score_winner_tree.md` | 当前最佳成绩和版本的可读展示 |
| 项目记忆或结果台账 | 对未来设计决策有持续价值的结论 |

## 适用场景

以下请求适合触发 `$ciciec-stage3-iteration`：

- “先读取项目沉淀，告诉我当前最佳版本和下一步建议。”
- “收集最近的 GitLab CI 结果，但不要推送或提交在线评测。”
- “检查当前提交是否已有成功产物，先做一次评测 dry-run。”
- “把当前版本走完 push、CI、在线评测和成绩记录全链路。”
- “刷新评测结果和 winner tree，判断是否出现新的最佳版本。”
- “接手上一轮 Codex 的工作，基于现有证据继续优化。”

## 安装

```sh
git clone https://github.com/Niyu24-Hub/ciciec-stage3-iteration-skill.git
cp -R ciciec-stage3-iteration-skill/ciciec-stage3-iteration \
  "${CODEX_HOME:-$HOME/.codex}/skills/"
```

安装后，在 Codex 中通过 `$ciciec-stage3-iteration` 显式调用。符合 Skill 描述的
CICIEC Stage 3 请求也可以触发自动加载。

### 初始化项目工作区

公开仓库已经内置完整配套工具和非敏感模板。将它们安装到目标工作区：

```sh
export CICIEC_WORKSPACE=/path/to/ciciec_workspace
bash "${CODEX_HOME:-$HOME/.codex}/skills/ciciec-stage3-iteration/scripts/bootstrap_workspace.sh" \
  "$CICIEC_WORKSPACE"
```

初始化脚本会：

- 安装 5 个 CI、评测和成绩维护工具到 `$CICIEC_WORKSPACE/tools/`
- 创建项目记忆、CI 管线说明和结果台账模板
- 创建 `ci_data/` 目录、空 JSONL 数据文件和初始 winner tree
- 生成不含真实凭据的 `ciciec.env.example`
- 默认保留工作区中已经存在的同名文件

只有明确需要覆盖已有工具或模板时才使用 `--force`。

## 环境配置

设置兼容的项目工作区、提交仓库目录和工作分支：

```sh
export CICIEC_WORKSPACE=/path/to/ciciec_workspace
export CICIEC_SUBMISSION_REPO=regional-submission
export CICIEC_SUBMISSION_REF=submit/codex
```

配置用户自己的 GitLab、在线评测服务和项目标识：

```sh
export CICIEC_GITLAB_API_URL=https://gitlab.example.com/api/v4
export CICIEC_GITLAB_PROJECT_ID=123
export CICIEC_JUDGE_BASE_URL=https://judge.example.com
export CICIEC_STAGE3_LAB_ID='optional-if-auto-discovery-works'
```

执行 CI 收集和在线评测时，通过当前 Shell 设置凭据：

```sh
export GITLAB_TOKEN='...'
export CICIEC_JUDGE_USER='...'
export CICIEC_JUDGE_PASSWORD='...'
```

初始化脚本会从 Skill 中安装以下配套工具：

- `tools/ciciec_iterate.sh`
- `tools/ciciec_ci_push_collect.sh`
- `tools/collect_ciciec_ci.py`
- `tools/ciciec_judge.py`
- `tools/update_ciciec_eval_winners.py`

## 命令与风险级别

| 命令 | 作用 | 风险级别 |
| --- | --- | --- |
| `tools/ciciec_iterate.sh status` | 查看本地数据、CI 和评测状态 | 只读 |
| `python3 tools/ciciec_judge.py list-submissions --limit 10` | 查询近期评测任务 | 只读 |
| `tools/ciciec_iterate.sh collect-ci` | 拉取并更新本地 CI 证据 | 远端只读、本地写入 |
| `python3 tools/ciciec_judge.py submit --latest-success --dry-run --no-record` | 验证产物选择，不实际提交 | 干运行 |
| `tools/ciciec_iterate.sh judge-current` | 提交当前 commit 的 CI 产物 | 实时评测 |
| `tools/ciciec_iterate.sh full-chain` | 推送分支、等待 CI、提交评测并记录成绩 | 完整实时操作 |

建议先执行 `status`，再执行 dry-run，确认仓库、分支、commit 和 artifact 对应关系后，
才运行 `judge-current` 或 `full-chain`。

## 在 Codex 中使用

### 只查看状态

```text
使用 $ciciec-stage3-iteration 读取项目记忆、最新 CI 和 winner tree，
只报告当前状态，不推送代码，也不提交在线评测。
```

### 收集 CI 证据

```text
使用 $ciciec-stage3-iteration 收集最近 30 条 GitLab CI 记录，
刷新本地摘要并说明当前最新成功构建对应的 commit。
```

### 在线评测前检查

```text
使用 $ciciec-stage3-iteration 检查当前提交的仓库状态和 CI artifact，
先执行 dry-run，确认不会选错版本。
```

### 执行完整迭代

```text
使用 $ciciec-stage3-iteration 完成当前版本的本地检查、分支推送、
GitLab CI 等待、在线评测和 winner tree 更新，并汇报最终结果。
```

## 安全边界

- 仅通过环境变量传递 Token、用户名和密码。
- 不把访问令牌、密码、Cookie 或命令历史写入项目文件。
- 默认不修改 `.gitlab-ci.yml`，除非用户明确要求。
- 不推送 `main` 或 `master`，只使用配置的提交分支。
- 不回退或覆盖用户已有修改；仓库不干净时先理解变更来源。
- 运行实时命令前确认目标仓库、分支、commit 和 artifact。
- 只有新结果影响未来设计方向时，才更新人工维护的项目记忆或结果台账。

## 公开版本边界

本仓库现在包含完整的 Skill 定义、初始化工具、5 个项目工具脚本、数据模板和中文
说明。出于安全及版权边界，以下用户私有内容不会随仓库发布：

- 个人文件系统路径和私有仓库标识
- GitLab Token、在线评测账号和密码
- 比赛提交源代码、私有 GitLab 配置及 CI 构建产物
- 自动生成的 CI、评测和 winner tree 数据文件
- 真实 GitLab/在线评测服务地址、项目 ID、实验 ID 及其他私有配置

因此，克隆仓库后已经可以完成 Skill 安装和工作区工具初始化；要连接真实 CI 和
在线评测服务，用户仍需提供自己的项目仓库、服务配置和合法访问权限。

## 仓库结构

```text
.
├── README.md
├── LICENSE
├── docs/images/
│   └── frontend-evaluation.png
└── ciciec-stage3-iteration/
    ├── SKILL.md
    ├── agents/
    │   └── openai.yaml
    ├── scripts/
    │   ├── bootstrap_workspace.sh
    │   └── project-tools/
    │       ├── ciciec_iterate.sh
    │       ├── ciciec_ci_push_collect.sh
    │       ├── collect_ciciec_ci.py
    │       ├── ciciec_judge.py
    │       └── update_ciciec_eval_winners.py
    ├── references/
    │   └── workflow.md
    └── templates/
        ├── ciciec.env.example
        ├── CICIEC_STAGE3_PROJECT_MEMORY.md
        ├── CICIEC_STAGE3_CI_DATA_PIPELINE.md
        ├── CICIEC_STAGE3_CI_RESULTS.md
        └── ci_data/
```

- `SKILL.md`：Skill 的触发描述、核心工作方式和安全规则。
- `agents/openai.yaml`：Codex 界面展示名称、简介和默认调用提示。
- `scripts/bootstrap_workspace.sh`：将内置工具和模板安全安装到目标工作区。
- `scripts/project-tools/`：CI 收集、在线评测、完整链路和 winner tree 工具。
- `references/workflow.md`：CI、评测、数据沉淀与完整链路的详细命令。
- `templates/`：不含凭据的项目记忆、环境变量和数据初始化模板。
- `docs/images/frontend-evaluation.png`：公开 README 使用的效果截图。

## 许可证

本项目使用 [MIT License](LICENSE)。
