# CLAUDE.md — Storyloom

> AI context file. Loaded automatically by Claude Code on entering the project.

## Project

Storyloom is an AI-powered interactive text fiction game engine. The LLM is the narrative brain; the program is the flow manager + context steward + dual-end interface. Currently in design/specification phase — no production code yet.

**Current direction (2026-07-04):** Moving from custom `--- block ---` delimiters to **XML output format** (3/3 correctness in first test vs ~20-74% for text-based format). Planning **conversation-based architecture** with sliding window + Round 1 anchoring to replace stateless per-round prompts. See memory: [[xml-format-decision]] [[conversation-architecture]].

## Core Design Concepts

These are the foundational ideas. The authoritative spec is `docs/spec/exec-flow.md`.

### Bridge Mechanism
Each story segment contains a `--- bridge ---` marker. When the program reaches it during parsing, it immediately submits the next round's prompt to the LLM — while continuing to display the tail text after the bridge. The player perceives continuous narration with no segment boundary pauses.

### Two-Layer Branching
- **Intra-segment branching** (`@branch`): Narrative variants within one segment. Player choices route to different `--- narrative:branch_name ---` blocks. Does NOT affect the outline.
- **Outline branching** (`if → route`): Story-direction forks at checkpoint nodes. The program evaluates conditions against local state and routes to different outline nodes. Irreversible.

### Local Source of Truth
All game data lives in a local `GameState` object. The LLM can only *suggest* changes via `--- state ---` blocks. The program validates each suggestion — type checks, range checks, variable existence — before applying. Rejected changes are fed back to the LLM in the next round.

### Block Separators (current: `--- block ---`, target: XML)
LLM output uses structured markers: `--- narrative ---`, `--- options ---`, `--- state ---`, `--- checkpoint ---`, `--- bridge ---`. The program parses these with regex (`^--- (\w+)(?::(\w+))? ---$`). Full spec: `docs/spec/block-spec.md`.

**⚠️ In transition:** Testing shows XML format (`<seg>`, `<choice>`, `<bridge/>`, `<branch>`) achieves 100% correctness vs ~20-74% for text blocks. Key advantages: node IDs as attributes prevent suffix appending; `<branch>` as container prevents missing post-choice narratives; `<bridge/>` as unique tag prevents double-bridge misuse. See `tests/data/prompts/frame-v1.txt` and `tests/analyze_frame.py`.

### Minimal Context Strategy (current)
Each round's prompt carries only 5 information categories (no accumulated chat history):
1. Outline tree + node progress — "where the story is going"
2. State snapshot — "the result of what happened"
3. Checkpoint summaries — "key events so far"
4. Bridge text — "what's happening right now"
5. Rejected change feedback — "what state changes were invalid last round"

**⚠️ Planned change:** Conversation-based architecture with sliding window (see [[conversation-architecture]]):
- Round 1 output preserved as permanent format anchor (self-bootstrapping few-shot)
- Last 3-5 rounds as full dialogue history for narrative coherence
- Earlier rounds compressed into checkpoint summaries
- Target ~50K token context ceiling

## Document Map

| Document | Role | Authority |
|----------|------|-----------|
| `docs/design.md` | Vision, architecture, phased roadmap | Advisory |
| `docs/spec/exec-flow.md` | Phase 1 execution pipeline | **Authoritative** |
| `docs/spec/block-spec.md` | Block separator syntax, numbering, branching, state validation | **Authoritative** |
| `docs/spec/prompt-design.md` | All Prompt templates, constraints, and examples | **Authoritative** |
| `docs/spec/data-model.md` | State, save system, constants | **Authoritative** |
| `docs/spec/walkthrough.md` | 4-round narrative loop example | Reference |
| `docs/README.md` | Documentation index | — |
| `tests/data/prompts/frame-v1.txt` | XML-format prompt (new direction) | Test |
| `tests/analyze_frame.py` | XML output correctness analyzer | Test |
| `tests/run_prompt_test.py` | LLM API test harness | Test |
| `tests/analyze_results.py` | Text-format output analyzer | Test |

**Authority rule:** `docs/spec/exec-flow.md` wins over `docs/design.md` on any conflict.

## Tech Stack

- **Language:** Python 3 (standard library preferred)
- **Interface:** Terminal CLI (Phase 1), FastAPI + SSE (Phase 2+)
- **LLM:** OpenAI-compatible API (abstracted behind common interface)
- **Storage:** Local JSON files in `saves/` directory

## Conventions

- **Conversation:** Chinese (对话用中文)
- **Code comments & git commits:** English
- **Git commits:** Conventional Commits (feat/fix/docs/refactor)
- **Prompt language:** Chinese (all LLM prompts)
- **Block separator names:** English (`--- narrative ---`, `--- checkpoint ---`, etc.)
- **Variable names in prompts:** Chinese (state variable names, choice names)
- **Config constants:** Defined in `config.py`, referenced by name — no hardcoded values in business logic

<!-- superpowers-zh:begin (do not edit between these markers) -->
# Superpowers-ZH 中文增强版

本项目已安装 superpowers-zh 技能框架（20 个 skills）。

## 核心规则

1. **收到任务时，先检查是否有匹配的 skill** — 哪怕只有 1% 的可能性也要检查
2. **设计先于编码** — 收到功能需求时，先用 brainstorming skill 做需求分析
3. **测试先于实现** — 写代码前先写测试（TDD）
4. **验证先于完成** — 声称完成前必须运行验证命令

## 可用 Skills

Skills 位于 `.claude/skills/` 目录，每个 skill 有独立的 `SKILL.md` 文件。

- **brainstorming**: 在任何创造性工作之前必须使用此技能——创建功能、构建组件、添加功能或修改行为。在实现之前先探索用户意图、需求和设计。
- **chinese-code-review**: 中文 review 沟通参考——话术模板、分级标注（必须修复/建议修改/仅供参考）、国内团队常见反模式应对。仅在用户显式 /chinese-code-review 时调用，不要根据上下文自动触发。
- **chinese-commit-conventions**: 中文 commit 与 changelog 配置参考——Conventional Commits 中文适配、commitlint/husky/commitizen 中文模板、conventional-changelog 中文配置。仅在用户显式 /chinese-commit-conventions 时调用，不要根据上下文自动触发。
- **chinese-documentation**: 中文文档排版参考——中英文空格、全半角标点、术语保留、链接格式、中文文案排版指北约定。仅在用户显式 /chinese-documentation 时调用，不要根据上下文自动触发。
- **chinese-git-workflow**: 国内 Git 平台配置参考——Gitee、Coding.net、极狐 GitLab、CNB 的 SSH/HTTPS/凭据/CI 接入差异与镜像同步配置。仅在用户显式 /chinese-git-workflow 时调用，不要根据上下文自动触发。
- **dispatching-parallel-agents**: 当面对 2 个以上可以独立进行、无共享状态或顺序依赖的任务时使用
- **executing-plans**: 当你有一份书面实现计划需要在单独的会话中执行，并设有审查检查点时使用
- **finishing-a-development-branch**: 当实现完成、所有测试通过、需要决定如何集成工作时使用——通过提供合并、PR 或清理等结构化选项来引导开发工作的收尾
- **mcp-builder**: MCP 服务器构建方法论 — 系统化构建生产级 MCP 工具，让 AI 助手连接外部能力
- **receiving-code-review**: 收到代码审查反馈后、实施建议之前使用，尤其当反馈不明确或技术上有疑问时——需要技术严谨性和验证，而非敷衍附和或盲目执行
- **requesting-code-review**: 完成任务、实现重要功能或合并前使用，用于验证工作成果是否符合要求
- **subagent-driven-development**: 当在当前会话中执行包含独立任务的实现计划时使用
- **systematic-debugging**: 遇到任何 bug、测试失败或异常行为时使用，在提出修复方案之前执行
- **test-driven-development**: 在实现任何功能或修复 bug 时使用，在编写实现代码之前
- **using-git-worktrees**: 当需要开始与当前工作区隔离的功能开发，或在执行实现计划之前使用——通过原生工具或 git worktree 回退机制确保隔离工作区存在
- **using-superpowers**: 在开始任何对话时使用——确立如何查找和使用技能，要求在任何响应（包括澄清性问题）之前调用 Skill 工具
- **verification-before-completion**: 在宣称工作完成、已修复或测试通过之前使用，在提交或创建 PR 之前——必须运行验证命令并确认输出后才能声称成功；始终用证据支撑断言
- **workflow-runner**: 在 Claude Code / OpenClaw / Cursor 中直接运行 agency-orchestrator YAML 工作流——无需 API key，使用当前会话的 LLM 作为执行引擎。当用户提供 .yaml 工作流文件或要求多角色协作完成任务时触发。
- **writing-plans**: 当你有规格说明或需求用于多步骤任务时使用，在动手写代码之前
- **writing-skills**: 当创建新技能、编辑现有技能或在部署前验证技能是否有效时使用

## 如何使用

当任务匹配某个 skill 时，使用 `Skill` 工具加载对应 skill 并严格遵循其流程。绝不要用 Read 工具读取 SKILL.md 文件。

如果你认为哪怕只有 1% 的可能性某个 skill 适用于你正在做的事情，你必须调用该 skill 检查。
<!-- superpowers-zh:end -->
