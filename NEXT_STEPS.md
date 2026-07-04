# Storyloom — 下一阶段开发启动

你是 Claude Code，接入 Storyloom 项目的 AI 开发助手。

## 项目概要

Storyloom 是一个 AI 驱动的交互式文字小说游戏引擎。LLM 是叙事大脑，程序是流程管理器 + 上下文管家。项目处于设计/规格阶段，Python 3 实现，终端 CLI 界面。

核心文档：
- `docs/spec/exec-flow.md` — 执行管线（权威）
- `docs/spec/block-spec.md` — 区块分隔符、分支路由、状态校验
- `docs/spec/prompt-design.md` — Prompt 模板与设计原则
- `docs/spec/data-model.md` — GameState、存档、常量
- `docs/design.md` — 愿景与阶段规划（参考）

## 本会话的起点

我们刚刚完成了两个重要决策：

### 1. LLM 输出格式：从自定义 `--- block ---` 迁移到 XML

**测试结果**：Frame v1 (XML) 首次测试达到 **3/3 (100%) 正确率**，而当前文本格式为 ~20-74%。

关键改进：
- `node="ch2_confrontation"` 作为 XML 属性值，消除了 node ID 后缀问题（26% 错误率 → 0%）
- `<branch name="x">...</branch>` 容器语义让分支结构更可靠
- `<bridge/>` 作为唯一自闭合标签，避免了"双 bridge"误用
- 分析器 `tests/analyze_frame.py` 已验证

当前 prompt 文件：`tests/data/prompts/frame-v1.txt`
需要修正的点（已更新到 prompt）：
- bridge 之前允许 `<branch>`（局部小分支/段内分支）
- bridge 之后允许裸 `<seg>`（单分支/无选项轮次）
- bridge 之后约束：禁止 `<choice>` `<set>` `<checkpoint>`，而非只允许 `<branch>`
- `&` 需要转义为 `&amp;`

### 2. 对话式架构：从无状态 Prompt 迁移到滑动窗口

**核心设计**（未实现）：
- Round 1 完整输出永久保留，作为格式范例锚定（self-bootstrapping few-shot）
- 最近 3-5 轮保留完整对话历史，维持剧情连贯性
- 更早轮次压缩为 checkpoint 摘要
- 状态 snapshot 每轮刷新（防止 LLM 信任自己的叙事胜过程序数据）
- 目标上下文上限 ~50K tokens

## 下一步任务

按优先级排序：

### Phase A: 完善 XML 格式
1. 在 frame-v1.txt 基础上，设计 **对话式架构的 Round 1 Prompt**（包含完整格式规范 + 示例）
2. 设计 **Round N (N≥2) 的轻量 Prompt**（仅含：进度、状态、上一轮错误反馈 + 对话历史）
3. 运行多轮测试（3-5 轮），验证格式一致性是否保持
4. 对比不同题材（mystery/romance/wuxia）下的正确率

### Phase B: 实现滑动窗口
5. 设计上下文管理策略：何时压缩、压缩格式、锚定机制
6. 实现 `ContextManager` 模块：组装每轮 messages、管理窗口滑动
7. 测试长篇场景（20+ 轮），验证 token 使用和叙事质量

### Phase C: 程序实现
8. 基于 XML 格式重写 `prompt_builder` 模块
9. 重写响应解析器（从 regex → XML parser）
10. 实现 GameState、存档系统、叙事循环
11. 构建终端 CLI 界面

## 关键约束

- **Prompt 语言**：中文
- **代码注释和 git 提交**：英文
- **变量名**：中文（state variables, choice names）
- **XML 标签/属性名**：英文
- **对话格式**：`角色名: 内容`（英文冒号，不引用号）
- **每段只做一件事**：旁白 15-40 字，对话 ≤50 字
- **Python 3**：标准库优先
- **LLM API**：OpenAI 兼容接口（当前测试用 DeepSeek）

## 测试工具

```bash
# 运行 XML 格式测试
python3 tests/run_prompt_test.py --prompt tests/data/prompts/frame-v1.txt --runs 3

# 分析结果
python3 tests/analyze_frame.py --prompt tests/data/prompts/frame-v1.txt \
    --output-dir tests/data/output/frame-v1/

# 运行文本格式测试（对比用）
python3 tests/run_prompt_test.py --prompt tests/data/prompts/v5.txt --runs 3
python3 tests/analyze_results.py --prompt tests/data/prompts/v5.txt \
    --output-dir tests/data/output/v5/
```

## 记忆文件

项目记忆位于 `.claude/projects/-home-slev-workspace-projects-Storyloom/memory/`：
- `xml-format-decision.md` — XML 格式决策和测试结果
- `conversation-architecture.md` — 对话式架构设计
- `MEMORY.md` — 所有记忆索引

---

请先阅读上述关键文档和记忆文件，完全理解项目后，从 Phase A 第 1 步开始。
