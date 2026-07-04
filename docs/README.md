# Storyloom 文档索引

## 文档地图

| 文档 | 内容 | 受众 | 权威性 |
|------|------|------|--------|
| [`design.md`](./design.md) | 设计理念、架构愿景、阶段规划 | 设计者、新贡献者 | 参考 |
| [`spec/exec-flow.md`](./spec/exec-flow.md) | Phase 1 程序执行管线（启动→结局） | 开发者、AI 工具 | **权威** |
| [`spec/block-spec.md`](./spec/block-spec.md) | 区块分隔符语法、分支路由、状态校验 | 开发者 | **权威** |
| [`spec/data-model.md`](./spec/data-model.md) | GameState、存档系统、常量、约定 | 开发者 | **权威** |
| [`spec/walkthrough.md`](./spec/walkthrough.md) | 4 轮叙事循环完整走查样例 | 开发者、审查者 | 参考 |
| [`spec/tests/`](./spec/tests/) | LLM 输出样本（解析器测试 fixture） | 实现者 | 参考 |

## 推荐阅读顺序

### 首次了解项目
1. [`design.md`](./design.md) — 理解设计理念和整体架构
2. [`spec/exec-flow.md`](./spec/exec-flow.md) — 理解程序具体做什么
3. [`spec/walkthrough.md`](./spec/walkthrough.md) — 看一个具体例子

### 开始实现
1. [`spec/exec-flow.md`](./spec/exec-flow.md) — 执行管线（主文档）
2. [`spec/block-spec.md`](./spec/block-spec.md) — 区块格式（实现解析器时参考）
3. [`spec/data-model.md`](./spec/data-model.md) — 数据结构（实现 GameState 和存档时参考）

### 审查设计
1. [`spec/exec-flow.md`](./spec/exec-flow.md) + 配套 spec — 完整规范
2. [`spec/walkthrough.md`](./spec/walkthrough.md) — 用样例验证规范一致性
3. [`design.md`](./design.md) — 确认实现不偏离设计理念

## 权威层级

```
spec/exec-flow.md  ──── 最高权威（执行流程）
spec/block-spec.md ──── 同等权威（区块格式）
spec/data-model.md ──── 同等权威（数据模型）
design.md          ──── 参考（设计理念）
```

**冲突解决**：spec 文档之间应保持一致。spec 与 design.md 冲突时，以 spec 为准。design.md 的讨论结论应回溯修正 spec。
