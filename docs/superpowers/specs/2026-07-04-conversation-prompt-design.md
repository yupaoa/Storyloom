# 对话式 Prompt 架构设计

> 状态：已确认 | 日期：2026-07-04 | 作者：Slev + Claude Code

## 背景

当前架构每轮发送独立 System Prompt（~3000 tokens），LLM 每轮重新学习格式规则。对话式架构改用 messages 数组，Round 1 永久锚定 + 滑动窗口，消除格式规则重复。

## 设计目标

1. **消除格式重复** — 格式规范只在 Round 1 教一次，后续靠对话历史维持
2. **叙事连贯性** — 最近 N 轮完整对话保留，LLM 有上下文记忆
3. **上下文可控** — 滑动窗口 + 压缩机制，目标 ≤50K tokens
4. **格式漂移防护** — Round 1 输出作为永久 few-shot 范例；出错时追加单条纠正提示

## 核心概念

### 消息数组结构

```
messages = [
  {role: "user",      content: Round1_完整Prompt},      // 永久锚定
  {role: "assistant", content: Round1_XML输出},          // 永久锚定（故事开局）

  // 滑出窗口的轮次 → 压缩为摘要
  {role: "user",      content: "已完成的章节摘要：..."},   // 压缩
  {role: "assistant", content: "（以上为已发生事件的摘要。当前故事继续推进。）"},

  // 窗口内轮次 → 完整保留
  {role: "user",      content: Round_N-3_上下文},
  {role: "assistant", content: Round_N-3_XML输出},
  {role: "user",      content: Round_N-2_上下文},
  {role: "assistant", content: Round_N-2_XML输出},
  {role: "user",      content: Round_N-1_上下文},
  {role: "assistant", content: Round_N-1_XML输出},

  // 当前轮
  {role: "user",      content: Round_N_上下文},
]
```

### Round 1 Prompt

永久保留在 messages[0]。内容：

- 角色定义（2-3 句）
- XML 输出格式规范（结构总览 + 元素说明）
- 一个非本主题的完整 XML 格式范例（展示所有元素类型）
- 核心规则（段格式、序号、段数与 bridge、choice/branch 对应、set 语法、checkpoint 约束、XML 规范、禁止项）
- 质量要求
- 故事上下文（背景、主角、风格、冲突、角色、大纲、当前状态）
- "请开始故事。"

> 格式范例永久保留在 Round 1 消息中，LLM 自然将注意力转移到最近的正确输出，无需程序主动移除。

### Round N 上下文（N ≥ 2）

自然追加在对话末尾的 user 消息，不含角色定义、格式规范、故事上下文（已在 Round 1）。内容：

- 进度：当前节点、目标、已完成节点
- 重要事件：滑出窗口轮次的压缩 checkpoint 摘要
- 当前状态：所有 state_vars 值
- 错误反馈：上一轮被拒变更（仅当非空）
- 当前节点目标
- 上一轮结尾（bridge_text，从上一轮 assistant XML 输出中提取 `<bridge/>` 之后的纯文本）

格式为自然文本，不套模板——作为对话窗口中的一条消息。

### 压缩策略

| 参数 | 值 |
|------|-----|
| 窗口大小 | 3 轮完整历史 |
| 首次压缩 | Round 5 |
| 压缩单位 | 滑出窗口的轮次合并为一个 user/assistant 消息对 |

**压缩格式**：

```
user: 以下是之前发生的主要事件：

- ch1_bar：在霓虹深渊酒吧与耗子接头，选择了直截了当的接触方式
- ch2_confrontation：与耗子完成芯片交易，耗子透露芯片来自荒坂R&D
- ...

assistant: （以上为已发生事件的摘要。当前故事继续推进。）
```

摘要来源：滑出窗口内每轮的 `<checkpoint summary="...">` 属性值，拼合为列表。如有关键 state 变更可附带（"体力降至 30"）。

**压缩触发示例**：

```
Round 1:  无压缩（仅锚定 + 输出）
Round 2:  无压缩（窗口内）
Round 3:  无压缩（窗口内）
Round 4:  无压缩（窗口内）
Round 5:  压缩 Round 2 → 窗口 = [1] [压缩2] [3] [4] [5当前]
Round 6:  压缩 Round 2-3 → 窗口 = [1] [压缩2-3] [4] [5] [6当前]
Round N:  压缩 Round 2~N-4 → 窗口 = [1] [压缩2~N-4] [N-3] [N-2] [N-1] [N当前]
```

### 格式范例生命周期

格式范例永久保存在 Round 1 消息中（messages[0]），不编辑不删除。理由：

- 范例 ~500 tokens，在 50K 上下文目标下占比很小
- LLM 自然将注意力从远距离范例转移到最近的正确输出
- 避免代码复杂度

### 格式错误纠正

仅当上一轮解析出现格式错误时，在当前 Round N 消息末尾追加纠正提示。单条，简短，指出具体错误（如 "上一轮 checkpoint 的 node 值与大纲不匹配"）。正确时不追加。

## 上下文预估

以 medium 故事（~20 轮）为例：

- Round 1 Prompt：~2500 tokens
- Round 1 输出：~1500 tokens
- 3 轮完整窗口（含 user 上下文 + assistant 输出）：~6000 tokens × 3 = 18000 tokens
- 压缩消息对：~500 tokens
- 当前轮消息：~500 tokens
- **总计：~23000 tokens**，远在 50K 目标之下

## 与现有 Prompt 的关系

此为全新设计，不复用当前 `docs/spec/prompt-design.md` 中的 Prompt 模板。核心变化：

| 维度 | 旧（v4/v5） | 新（对话式） |
|------|------------|------------|
| 消息结构 | 每轮独立 system + user | messages 数组，持续对话 |
| 格式规则 | 每轮重复 ~3000 tokens | Round 1 教一次 |
| Round 1 输出 | 不保留 | 永久保留作为格式范例 |
| bridge_text | user message 的一部分 | 从 assistant 输出提取，追加在当前消息 |
| 对话历史 | 无 | 最近 3 轮完整保留 |
| 压缩 | 无 | checkpoint 摘要合并 |
| XML 格式 | 同 | 同（frame-v1） |

## 待定项

- Round 1 Prompt 中叙事段建议值（60-120）后续可进一步确认
- 格式范例可根据测试结果扩充完善
- 上下文上限的硬截断策略（超 50K 时如何处理）
