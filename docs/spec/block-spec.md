# XML 元素规范

> **定位**：LLM 输出的 XML 元素定义——语法、路由机制、状态校验规则。  
> **配套文档**：
> - [`exec-flow.md`](./exec-flow.md) — 程序执行管线（如何组装 Prompt、解析响应、展示内容）
> - [`data-model.md`](./data-model.md) — 数据模型、存档、常量
> - [`prompt-design.md`](./prompt-design.md) — Round 1 Prompt 模板中的 XML 格式定义

---

## §1 XML 元素速查

LLM 输出使用 XML 格式，根元素为 `<story>`。程序通过 `StreamingXmlParser` 逐行流式解析（利用 `NNN| ` 行号前缀，每行自包含）。

### 1.1 根元素

| 元素 | 说明 |
|------|------|
| `<story>` | 根元素，包裹全部输出。所有其他元素均为其子元素 |

### 1.2 子元素一览

| 元素 | 标签 | 位置限制 | 出现次数 | 说明 |
|------|------|---------|---------|------|
| 叙事段 | `<seg>` | 任意 | 0-N | 每个叙事段。text node 为内容。行号通过 `NNN\| ` 行前缀标注（非 XML 属性） |
| 分支容器 | `<branch>` | 任意 | 0-N | 分支叙事容器。name 属性标识分支名。内含 `<seg>` 子元素 |
| 选项 | `<choice>` | 仅 bridge 前 | 0-1 | 玩家选项列表。id 属性为变量名。内含 `<opt>` 子元素 |
| 选项项 | `<opt>` | 含在 `<choice>` 内 | 2-5 | 单个选项。key 为数字键（1/2/3/4），branch 为分支名 |
| 状态变更 | `<set>` | 仅 bridge 前 | 0-N | 状态变量变更。var/op/val 属性为必填，if 属性可选 |
| 检查点 | `<checkpoint>` | 仅 bridge 前 | 0-1 | 大纲路由。node/summary 属性。内含 `<route>` 子元素 |
| 路由 | `<route>` | 含在 `<checkpoint>` 内 | 0-N | 分支路由。if 属性可选，target 指定目标节点 |
| **桥接** | **`<bridge/>`** | — | **恰好 1 次** | 自闭合。标记交互区与叙事区的分界 |

> **关键顺序约束**：`<choice>`、`<set>`、`<checkpoint>` 必须出现在 `<bridge/>` 之前。
> `<bridge/>` 之后仅允许 `<seg>` 和 `<branch>`，严格禁止其他元素。

### 1.3 完整结构示例

> 行号前缀（`NNN| `）由 LLM 在每行输出，程序解析前剥离。行号不是 XML 的一部分。

```xml
001| <story>
002| <seg>雨水敲击着头顶的金属雨棚，霓虹灯在积水里折射出破碎的光。</seg>
003| <seg>耗子抬起眼，义眼红光在昏暗中微微闪烁。</seg>
004| <seg>耗子: 林焰，坐。</seg>
005| <choice id="approach">
006|   <opt key="1" branch="direct">直视对方，直截了当</opt>
007|   <opt key="2" branch="cautious">先环顾四周，压低声音</opt>
008| </choice>
009| <set var="信任度" op="+" val="5" if="approach==1"/>
010| <checkpoint node="ch2_confrontation" summary="在霓虹深渊与耗子接头，选择了接触方式。"/>
011| <bridge/>
012| <branch name="direct">
013| <seg>你直视耗子的义眼，那一点红光在昏暗中微微闪烁。</seg>
014| <seg>林焰: 芯片在哪儿？我没时间绕弯子。</seg>
015| </branch>
016| <branch name="cautious">
017| <seg>你的目光扫过昏暗的酒吧，角落里几个穿皮夹克的人正盯着你们。</seg>
018| </branch>
019| </story>
```

---

## §2 行号与编号规范

> **目的**：让 LLM 在生成过程中自我计量，替代字数估算。每行以 `NNN| ` 前缀开头（零填充 3 位），程序解析前剥离。行号类似文本编辑器中的行号——LLM 每行标注，程序剥离后展示。

### 2.1 行号规则

| 元素 | 编号方式 | 示例 |
|------|---------|------|
| 每行输出 | `NNN\| ` 前缀，零填充 3 位，全局连续递增 | `001\| ` `002\| ` ... `150\| ` |
| `<opt>` 选项项 | key 属性，数字 | `key="1"` `key="2"` |
| 其他元素 | ❌ 无编号 | 元数据/分隔符 |

> `<seg>` 元素不再使用 `n` 属性——行号由 `NNN| ` 前缀提供。解析器兼容旧格式（`n` 缺失时默认 0），但当前 Prompt 不产生 `n` 属性。

### 2.2 Prompt 行号指令

> 以下为注入 Round 1 Prompt 格式规范部分的行号约束。

```
- 每行以 NNN| 前缀开头（零填充 3 位），从 001 开始，全局连续递增，不重复不跳号
- {MIN}-{MAX} 行。bridge 放在交互与叙事分界处，约总行数 75%
- 对话段：`角色名: 内容`（英文半角冒号，冒号后空一格，对话不加引号）
- 旁白段：15-40 字，一段只说一件事
```

### 2.3 程序解析规则

程序使用 `StreamingXmlParser` 逐行流式解析（详见 [`exec-flow.md` §4.4](./exec-flow.md)）。核心要点：
- 剥离 `NNN| ` 行号前缀——不是 XML 的一部分
- 每行是自包含的 XML 片段，逐行正则匹配，不等完整文档
- 解析过程中同步累积结构化数据到 `ParsedOutput`

**对话段识别**（可复用旧逻辑，XML 文本节点保持相同格式）：

```python
def classify_segment(text: str) -> tuple[str, str | None, str]:
    """Return (type, speaker_name | None, content).
    
    Dialogue format: 角色名: 对话内容
    - English colon ':' (U+003A), one space after colon, no quotes.
    - Program accepts both '：' (U+FF1A) and ':' (U+003A) as delimiter.
    """
    m = re.match(r'^([一-鿿\w\[\]·.]{1,12})[：:]\s?(.*)', text)
    if m:
        return ("dialogue", m.group(1), m.group(2))
    return ("narration", None, text)
```

### 2.4 行号校验

| 检查 | 处理 |
|------|------|
| 起始行号 ≠ 001 | 记入 numbering_issues，接受 |
| 行号重复/不连续 | 记入 numbering_issues，接受 |
| 总行数 < MIN 或 > MAX | 接受，记入 rejected_changes，下轮反馈 |
| bridge 位置偏离过大 | 接受，记入 rejected_changes，下轮反馈 |

> **宽容原则**：内容质量优先于行号准确性。行号是 LLM 的辅助工具，不是硬性约束。

---

## §3 分支路由机制

程序每轮维护两个临时变量（轮次结束时清空）：

| 变量 | 初始值 | 说明 |
|------|--------|------|
| `current_branch` | `"main"` | 当前执行的分支名 |
| `choice_dict` | `{}` | 选项选择值 |

**路由规则**：

```
程序从头到尾顺序扫描 <story> 的子元素：
  元素在 bridge 之前？
  ├── 是 → 检查标签类型
  │   ├── <seg> → 如果不在 <branch> 内或 current_branch == main → 展示
  │   ├── <branch> → 如果 name == current_branch → 展示其内部 <seg>
  │   ├── <choice> → 缓存到展示队列
  │   ├── <set> → 立即执行
  │   └── <checkpoint> → 立即执行
  └── 否（bridge 之后）
      ├── <seg> → 如果不在 <branch> 内 → 展示（作为 bridge_text）
      ├── <branch name="X"> → 如果 X == current_branch → 展示其内部 <seg>
      └── 其他元素 → 错误 / 拒绝
```

**`current_branch` 修改来源**：

| 来源 | 机制 | 示例 |
|------|------|------|
| 玩家选择 | 选中的 `<opt>` 的 `branch` 属性 | 选 `key="1"` 且 `branch="direct"` → `current_branch = "direct"` |

**`choice_dict` 修改来源**：`<choice>` 的 `id` 属性声明 choice 名，玩家选择后 `choice_dict[id] = 选项字母序号`。

> **条件变量解析优先级**（适用于所有条件求值场景）：`choice_dict > state_vars`。

---

## §4 各元素语法

### `<seg>`

纯叙事文本。行号由 `NNN| ` 前缀标注（非 XML 属性），text node 为叙事内容：

```xml
001| <seg>你推开厚重的橡木门，冷风裹挟着雪花卷入室内。</seg>
002| <seg>耗子: 芯片在哪儿？我没时间绕弯子。</seg>
```

约束：
- 行号从 001 开始，全局递增（每行 `NNN| ` 前缀）
- 旁白（15-40 字）或对话（`角色名: 内容`，≤50字）
- 一段只做一件事，禁止混合旁白和对话

### `<branch>`

分支叙事容器。`name` 属性标识分支名，内含 `<seg>` 子元素：

```xml
<branch name="direct">
  <seg>你直视耗子的义眼。</seg>
  <seg>林焰: 芯片在哪儿？</seg>
</branch>
```

约束：
- bridge 之前的 `<branch>` 用于预路由（多选项的局部小叙事）
- bridge 之后的 `<branch>` 用于选项后果分支
- `name` 必须与 `<opt>` 的 `branch` 属性精确对应
- `<branch>` 内只能有 `<seg>`，不能嵌套其他元素

### `<choice>`

选项列表。`id` 属性为变量名（中文，2-5 字）。内含 2-5 个 `<opt>` 子元素：

```xml
<choice id="chip_choice">
  <opt key="1" branch="took_chip">接过芯片</opt>
  <opt key="2" branch="left" if="理智值 >= 30">暂时离开</opt>
</choice>
```

#### `<opt>` 属性

| 属性 | 必填 | 说明 |
|------|------|------|
| `key` | 是 | 数字键 `1`/`2`/`3`/`4`。对应选项序号 |
| `branch` | 否 | 选中后设置的 `current_branch`，必须对应 bridge 之后同名的 `<branch name>`。省略时 `current_branch` 不变 |
| `if` | 否 | 条件表达式，满足才可选。格式 `变量名 运算符 值` |

处理逻辑：展示选项 → 玩家选择 → `choice_dict["chip_choice"] = N` → 设置 `current_branch = opt.branch`。

> **约束**：同一个 `<story>` 内最多一个 `<choice>`。

### `<set>`

状态变更。自闭合元素，通过属性定义操作：

```xml
<set var="体力" op="-" val="10"/>
<set var="信任度" op="+" val="5" if="approach==1"/>
<set var="线索" op="+" val="神秘芯片"/>
<set var="所属势力" op="=" val="叛军"/>
<set var="背包" op="-" val="旧钥匙"/>
```

**属性**：

| 属性 | 必填 | 说明 |
|------|------|------|
| `var` | 是 | 变量名（中文） |
| `op` | 是 | 操作符：`+`（number 加减 / list 追加），`-`（number 减 / list 移除），`=`（赋值） |
| `val` | 是 | 操作值 |
| `if` | 否 | 条件表达式。满足才执行。格式 `变量名 运算符 值`，用 `and`/`or` 组合（最多一个） |

**类型对应**：

| 类型 | 支持操作 | 示例 |
|------|---------|------|
| number | `+N`、`-N`、`=N` | `op="-" val="10"`（减10） |
| string | `=值` | `op="=" val="叛军"` |
| list | `+元素`、`-元素` | `op="+" val="神秘芯片"` |

> **条件语法规则**：
> - 变量名引用顺序：`choice_dict`（当前轮选项结果）> `state_vars`
> - 运算符：`==` `!=` `>=` `<=` `>` `<`
> - 组合：最多一次 `and` 或一次 `or`，不允许混合

### `<checkpoint>`

大纲路由节点。自闭合元素，纯路由不修改 state_vars。可选内含 0-N 个 `<route>` 子元素：

```xml
<checkpoint node="ch2_discovery" summary="在酒吧获得加密芯片，决定下一步行动。">
  <route if="信任度 >= 50" target="ch3_ally"/>
  <route if="信任度 < 50" target="ch3_betrayal"/>
</checkpoint>
```

结局节点（无 `<route>` 子元素）：

```xml
<checkpoint node="end" summary="所有线索在此交汇，故事走向终点。"/>
```

**属性**：

| 属性 | 必填 | 说明 |
|------|------|------|
| `node` | 是 | 节点 ID（`end` 为结局）或 `end`。必须原样复制大纲 ID，禁止拼接后缀 |
| `summary` | 是 | 1-2 句中文摘要 |

**`<route>` 属性**：

| 属性 | 必填 | 说明 |
|------|------|------|
| `if` | 否 | 条件表达式。无条件的第一个 route 为默认分支 |
| `target` | 是 | 目标节点 ID，必须存在于大纲中 |

路由评估：顺序评估，第一个命中条件执行。无条件命中的 `<route>` 取第一个。

### `<bridge/>`

自闭合元素，恰好出现一次。标记交互区与叙事区的硬分界：

```xml
<bridge/>
```

**分界规则**：

| 区域 | 允许元素 | 禁止元素 |
|------|---------|---------|
| bridge 之前（交互区） | `<seg>`, `<branch>`, `<choice>`, `<set>`, `<checkpoint>` | — |
| bridge 之后（叙事区） | `<seg>`, `<branch>` | `<choice>`, `<set>`, `<checkpoint>` |

**bridge_text 提取**：

```
程序处理到 <bridge/> 后：
  1. 记录 bridge 之后至 </story> 的全部内容
  2. 提取其中 <seg> 和 <branch> 内的 <seg> 的文本节点
  3. 合并为纯文本（去除 XML 标签）
  4. 作为下一轮 Round N 消息的 bridge_text 字段
```

**多分支场景**：bridge 之后多个 `<branch>` 分别对应各选项后果叙事。`current_branch` 决定展示哪个分支的内容。未选中的分支不展示、不注入下一轮。

**结局轮**：当 `checkpoint node="end"` 时，`<bridge/>` 仍是必选项。程序在 bridge 处检测到 `ending_flag`，提交冒险日志 Prompt（独立 LLM 调用）。

---

## §5 状态变更校验

处理 `<set>` 元素，逐条独立执行（一条失败不影响其他）。

**校验规则**：

| 校验 | 失败处理 |
|------|---------|
| 变量名不存在于 story_config.variables | 静默忽略，记入 rejected_changes |
| number 操作结果越界 | clamp 到 `[0, 100]`，静默处理 |
| list `+` 元素已存在 | 静默忽略 |
| list `-` 元素不存在 | 静默忽略 |
| 操作符与类型不匹配 | 拒绝，记入 rejected_changes |

**伪代码**：

```
for each <set> element:
    var = set.get("var")
    op = set.get("op")
    val = set.get("val")
    condition = set.get("if")

    if condition and not evaluate(condition):
        continue    # 条件不满足，跳过

    var_def = find_var_in_story_config(var)
    if not var_def:
        rejected_changes.append({set_element, reason: "变量不存在"})
        continue

    valid = validate(var_def.type, op, val)
    if not valid:
        rejected_changes.append({set_element, reason: valid.error})
        continue

    result = apply(state_vars[var], op, val)
    if var_def.type == "number":
        result = clamp(result, 0, 100)
```

> **静默处理**：list 增删重复/不存在的元素、number 越界取上下限——不中断流程，不展示给用户，但记入 rejected_changes，在下一轮 Prompt 中告知 LLM。
