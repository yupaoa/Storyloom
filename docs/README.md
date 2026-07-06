# Storyloom 文档索引

## 文档地图

| 文档 | 内容 | 受众 | 权威性 |
|------|------|------|--------|
| [`spec/exec-flow.md`](./spec/exec-flow.md) | Phase 1 程序执行管线（启动→结局） | 开发者、AI 工具 | **权威** |
| [`spec/block-spec.md`](./spec/block-spec.md) | XML 元素语法、编号规范、分支路由、状态校验 | 开发者 | **权威** |
| [`spec/data-model.md`](./spec/data-model.md) | GameState、存档系统、常量、约定 | 开发者 | **权威** |
| [`spec/prompt-design.md`](./spec/prompt-design.md) | 全阶段 Prompt 模板、对话式消息数组架构 | 开发者、调试者 | **权威** |
| [`superpowers/specs/`](./superpowers/specs/) | 功能设计规格（按日期归档） | 设计者、审查者 | 参考 |
| [`superpowers/plans/`](./superpowers/plans/) | 实现计划（按日期归档） | 实现者 | 参考 |

## 推荐阅读顺序

### 首次了解项目
1. [`spec/exec-flow.md`](./spec/exec-flow.md) — 理解程序执行管线
2. [`spec/block-spec.md`](./spec/block-spec.md) — 理解 XML 输出格式
3. [`spec/prompt-design.md`](./spec/prompt-design.md) — 理解 Prompt 模板和对话架构

### 开始实现
1. [`spec/exec-flow.md`](./spec/exec-flow.md) — 执行管线（主文档）
2. [`spec/block-spec.md`](./spec/block-spec.md) — XML 格式（实现解析器时参考）
3. [`spec/prompt-design.md`](./spec/prompt-design.md) — Prompt 模板（实现 prompt_builder 时参考）
4. [`spec/data-model.md`](./spec/data-model.md) — 数据结构（实现 GameState 和存档时参考）

### 审查设计
1. [`spec/exec-flow.md`](./spec/exec-flow.md) + 配套 spec — 完整规范
2. [`superpowers/specs/`](./superpowers/specs/) — 历史设计决策和演变过程

## 权威层级

```
spec/exec-flow.md     ──── 最高权威（执行流程）
spec/block-spec.md    ──── 同等权威（XML 元素规范）
spec/prompt-design.md ──── 同等权威（Prompt 模板）
spec/data-model.md    ──── 同等权威（数据模型）
```

**冲突解决**：spec 文档之间应保持一致。Prompt 格式以 `tests/data/prompts/round1-linenum.txt` 为最终标准。

## 扩展路线

### Phase 1 — CLI 纯文本 MVP（当前）
终端 CLI、LLM 自定义变量、共创阶段变量定义、固定选项、自动存档。验证核心游戏循环。

### Phase 2 — Web + 动态系统
- **变量系统增强**：可用变量数扩展至 10+，支持更复杂的数值约束
- **Web 界面**：FastAPI + SSE 流式渲染，选项按钮、状态面板、移动端适配
- **向量记忆**：角色/地点/事件 embed 存储，每轮检索注入 Prompt
- **多模型**：叙事用主力模型，审查/追问用便宜模型
- **自定义输入**：玩家可自由输入行动，合理性检查模型把关
- **一致性审查**：独立模型检查剧情与大纲、状态变更的合理性

### Phase 3 — 完整体验
- **图像生成** — 关键场景异步生成插画
- **云同步** — 存档加密上传，跨设备同步
- **TTS** — 可选角色语音朗读
- **剧本导出** — 冒险历史格式化为 Markdown/PDF
- **多人模式** — 不同玩家扮演不同角色，AI 居中叙述协调
