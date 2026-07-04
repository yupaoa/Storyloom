# 区块分隔符与 Prompt 格式规范

> **定位**：LLM 输出的结构化区块定义——语法、路由机制、状态校验规则。  
> **配套文档**：
> - [`exec-flow.md`](./exec-flow.md) — 程序执行管线（如何组装 Prompt、解析响应、展示内容）
> - [`data-model.md`](./data-model.md) — 数据模型、存档、常量
>
>

---

## §1 区块分隔符速查

LLM 输出采用结构化标记，程序按正则 `^--- (\w+)(?::(\w+))? ---$` 提取区块类型和分支名。全部使用英文命名。

部分区块支持**分支名**：`--- block:branch ---`（缺省 branch 即为 `main`），用于段内路由。

| 区块标记 | 必需 | 支持分支名 | 说明 |
|----------|------|----------|------|
| `--- narrative ---` | ✅ 必选 | ✅ | 故事叙述正文 |
| `--- options ---` | 可选 | ✅ | 选项列表。第一行 `choice: 选择名` |
| `--- state ---` | 可选 | ✅ | 数据变更 + 段内路由 |
| `--- checkpoint ---` | 可选 | ❌ 固定 main | 大纲路由。`node <id>` 或 `end` |
| `--- bridge ---` | 通常必选 | ❌ 固定 main | 下一轮衔接标记。结局轮同样必选（程序在 bridge 处检测 ending_flag 并提交独立冒险日志调用） |
| `=== story_config ===` | 共创必选 | — | 故事设定（共创阶段） |
| `=== outline ===` | 共创必选 | — | 大纲树（共创阶段） |
| `=== variables ===` | 共创必选 | — | 变量定义（共创阶段 Step 3.5） |

> **共创 vs 叙事**：共创用 `=== xxx ===`，叙事用 `--- xxx ---`。两者不会同时出现。

---

## §2 内容编号规范

> **目的**：让 LLM 在生成过程中自我计量，替代字数估算。编号类似文本编辑器中的行号——LLM 生成每个叙事段时标注编号，程序解析后剥离编号展示。

### 2.1 编号规则

| 内容类型 | 编号方式 | 示例 | 说明 |
|----------|---------|------|------|
| `narrative:*` 内每个展示段 | 数字，全局递增 | `1.` `2.` `3.` ... | 所有 narrative 块共享同一序列，按生成物理顺序 |
| `options` 内选项行 | 字母 | `A.` `B.` `C.` | 不占用数字序列 |
| `choice:` 声明行 | ❌ 无编号 | `choice: approach` | 元数据，不展示 |
| `state` 内各行 | ❌ 无编号 | `@var 体力 -10` | 数据指令 |
| `checkpoint` | ❌ 无编号 | `node ch2_xxx` | 路由标记 |
| `bridge` | ❌ 无编号 | `--- bridge ---` | 分隔符 |

### 2.2 完整示例

```
--- narrative:main ---
1. 雨水敲击着头顶的金属雨棚，霓虹灯在积水里折射出破碎的光。
2. "林焰，"他用沙哑的嗓音说，"坐。"
3. 耗子把一杯泛着蓝色荧光的液体推到你面前。

--- options:main ---
choice: approach
A. 直视对方，直截了当："芯片在哪儿？" -> direct
B. 先环顾四周，压低声音说话 -> cautious

--- state:main ---
if approach == A -> @var 信任度 +5

--- checkpoint ---
node ch2_confrontation
summary: 在霓虹深渊与耗子接头，选择了接触方式。

--- bridge ---

--- narrative:direct ---
4. 你直视耗子的义眼，那一点红光在昏暗中微微闪烁。
5. "芯片在哪儿？我没时间绕弯子。"
6. 耗子的嘴角抽搐了一下，手缓缓伸进风衣内袋。

--- narrative:cautious ---
7. 你的目光扫过昏暗的酒吧。角落里几个穿皮夹克的人正盯着你们。
8. "先说清楚，这地方有多少人在盯着你。"
```

### 2.3 Prompt 编号指令

> 以下为注入 System Prompt 格式约束部分的编号指令。程序按 `SEGMENTS_PER_ROUND_MIN`/`MAX` 替换目标范围。

```
编号规则（重要）：

1. 每个叙事段（narrative 内的展示单位）前加数字编号，从 1 开始顺序递增。
   所有 narrative 块（包括不同 branch 的）共享同一条编号序列。

2. 本次生成 {MIN}-{MAX} 个叙事段。bridge 插入在第 ~{RATIO} 位置
   （约第 {BRIDGE_AT} 段之后）。编写到接近该段数时放置 bridge。

3. 选项行用字母编号（A/B/C），不占用数字序列。

4. 每段为一句对话或一句描写。一段不宜包含超过一个角色的发言。
   段与段之间空行分隔。
```

### 2.4 程序解析规则

```python
segments = []
last_num = 0

for narrative_block in matching_blocks(current_branch):
    for line in narrative_block.content.strip().split('\n'):
        line = line.strip()
        if not line:
            continue
        match = re.match(r'^(\d+)\.\s+(.*)', line)
        if match:
            num = int(match.group(1))
            text = match.group(2)
            segments.append((num, text))
            last_num = num
        else:
            # 无编号行 → 视为上一段的延续（LLM 可能忘了编号）
            if segments:
                segments[-1] = (segments[-1][0], segments[-1][1] + '\n' + line)
```

### 2.5 编号校验

| 检查 | 处理 |
|------|------|
| 起始编号 ≠ 1 | 记警告，接受 |
| 编号重复 | 静默接受，记警告 |
| 编号跳号（如 3→5） | 静默接受，记警告 |
| 总段数 < MIN 或 > MAX | 接受，记入 rejected_changes，下轮反馈 |
| bridge 位置偏离 >20% | 接受，记入 rejected_changes，下轮反馈 |

> **宽容原则**：内容质量优先于编号准确性。编号是 LLM 的辅助工具，不是硬性约束。所有编号相关偏差均为"接受但反馈"，不触发重试。

---

## §3 分支路由机制

程序每轮维护两个临时变量（轮次结束时清空）：

| 变量 | 初始值 | 说明 |
|------|--------|------|
| `current_branch` | `"main"` | 当前执行的分支名 |
| `choice_dict` | `{}` | 选项选择值 |

**路由规则**：

```
程序从头到尾顺序扫描区块标记行：
  区块 branch == current_branch 或 branch == "main"？
  ├── 是 → 执行该区块内容
  └── 否 → 跳过，继续
```

**`current_branch` 修改来源**：

| 来源 | 语法 | 示例 |
|------|------|------|
| options 选项行 | `-> branch` | `1. 接过芯片 -> took_chip` |
| state 无条件 | `@branch 值` | `@branch desperate` |
| state 条件结果 | `if ... -> @branch 值` | `if 体力 < 20 -> @branch desperate` |

**`choice_dict` 修改来源**：options 第一行声明 choice，玩家选择后 `choice_dict["选择名"] = 选择编号`。

> checkpoint、bridge 固定为 `main`，不参与段内路由。
>
> **条件变量解析优先级**（适用于所有条件求值场景：options `@if`、state `if`、checkpoint `if → route`）：`choice_dict > state_vars`。程序先在 choice_dict 中查找变量名，未命中则查找 state_vars。

---

## §4 各区块语法

### `--- narrative ---`

纯叙事文本，支持分支名实现段内分支：
```
--- narrative:main ---
（主分支叙事……）

--- narrative:took_chip ---
（仅 current_branch=="took_chip" 时展示……）
```

### `--- options ---`

第一行必须声明 `choice`。选项行可附带 `@if:条件` 和 `-> branch`：
```
--- options:main ---
choice: chip_choice
1. 接过芯片 -> took_chip
2. 暂时离开 @if: 理智值 >= 30 -> left
```
处理：展示选项 → 玩家选择 → `choice_dict["chip_choice"] = N`（N 为选项编号 1/2/3...）→ 若选项有 `-> branch`，设置 `current_branch = branch`。

> **约束**：同一剧情段内所有 `--- options ---` 的 choice 必须唯一。

### `--- state ---`

无条件变更直接执行；条件变更每行独立评估，命中即执行：
```
--- state:main ---
@var 理智值 -10
if chip_choice == 1 -> @var 线索 +神秘芯片, @branch took_chip
if 信任度 >= 50 and 好感度 >= 30 -> @var 关系阶段 =朋友
```

**条件语法规则**：

| 元素 | 说明 |
|------|------|
| 变量名 | 中文，必须引用 state_vars 中存在的变量或同段 options 的 `choice:` 声明值。程序按优先级解析（choice_dict > state_vars） |
| 运算符 | `==` `>=` `<=` `>` `<` `has` |
| 组合 | `and` / `or`。每条条件最多使用一次 and 或一次 or，不允许混合 |
| 动作 | `@var 变量 操作 值` / `@branch 值` / `route node_id`（仅 checkpoint） |
| 关键字 | `if` `->` `@var` `@branch` 固定英文 |

**`@var` 操作符**：

| 操作 | 语法 | 示例 | 适用类型 |
|------|------|------|----------|
| 加减 | `@var 变量 +N` / `@var 变量 -N` | `@var 体力 -10` | number |
| 赋值 | `@var 变量 =值` | `@var 所属势力 =叛军` | number / string |
| 追加 | `@var 变量 +元素` | `@var 线索 +神秘芯片` | list |
| 移除 | `@var 变量 -元素` | `@var 背包 -旧钥匙` | list |

> **类型说明**：变量仅三种类型——`number`（范围 [0, 100]）、`string`（自由文本，替代枚举）、`list`（元素为 string）。不设枚举类型。

> **choice 条件规范**：`if 芯片选择 == 1` 中的 `芯片选择` 必须与同段 `--- options ---` 的 `choice:` 声明值完全一致。禁止使用 `选择1`、`选项1` 等占位词——程序校验时引用不存在的变量名将被拒绝。

### `--- checkpoint ---`

仅做大纲路由，**不修改 state_vars**。如需数据变更，先执行 `--- state ---`：
```
--- checkpoint ---
node ch2_discovery
if 信任度 >= 50 -> route ch3_ally
if 信任度 < 50 -> route ch3_betrayal
summary: 在酒吧获得加密芯片……
```
结局节点：
```
--- checkpoint ---
end
summary: 所有线索汇集……
```
- `node <id>` 或 `end`：标记到达的节点
- `if 条件 -> route <next_node_id>`：分支路由，取首个命中。无条件命中 → 取第一个分支的 next_node
- `summary:`：checkpoint 摘要（必填）

### `--- bridge ---`

标记下一轮 Prompt 组装的触发点。LLM 应先完整生成所有内容块，再选择合适位置插入 bridge。bridge 之后至段末为 bridge_text。

**bridge 之后的区块限制**：

| 区块 | 允许 | 说明 |
|------|------|------|
| `--- state ---` | ❌ | 底层数据变更必须在 bridge 之前 |
| `--- checkpoint ---` | ❌ | 大纲路由必须在 bridge 之前 |
| `--- options ---` | ❌ | 选项交互必须在 bridge 之前 |
| `--- narrative:any_branch ---` | ✅ | 作为不同路径的过渡/悬念文本变体 |

**bridge_text 提取流程**：

```
程序解析到 --- bridge --- 后：
  1. 记录 bridge 之后至段末的全部内容
  2. 扫描其中的 --- narrative:xxx --- 区块
  3. 取 branch == current_branch 或 branch == "main" 的那一条（取第一个匹配）
  4. 剥离该区块的分隔符标记行，保留纯正文
  5. 组装下轮 User Message：
       "--- narrative:main ---\n（提取的正文）"
  6. 其余命名 narrative 跳过（不展示、不注入下轮 Prompt）
```

> **效果**：玩家看到其选择路径对应的过渡文本；下一轮 LLM 收到的 User Message 是干净的 `--- narrative:main ---`，不含其他分支残留。

**多分支场景**：若本段 checkpoint 为多分支节点（在 bridge 之前已处理），bridge 之后可包含多个命名 `--- narrative ---`，分别对应各分支的承接文本。提取机制保证只有当前路径的那一条被注入下一轮。

**结局轮的 bridge 位置**：当 checkpoint 为 `end` 时，bridge **必选**，插入在 `end` 之后、尾部缓冲 narrative 之前：

```
--- checkpoint ---
end
summary: ...
--- bridge ---               ← 必选
--- narrative:main ---       ← 缓冲叙事（用户无感知）
（缓冲正文……）
```

程序在 bridge 处检测到 `ending_flag` → **不组装正常下一轮 Prompt**，改为提交冒险日志 Prompt（独立 LLM 调用，见 `exec-flow.md` §5.4）。尾部 narrative 作为缓冲确保冒险日志有充裕响应时间。展示完 bridge_text 和 adventure_log 后，返回主菜单。

> **设计考量**：bridge 位置不宜太靠后，确保 bridge_text 有足够长度供 LLM 响应；位置由 `BRIDGE_SEGMENT_RATIO` 常量控制（见 data-model.md §A.4）。

---

## §5 状态变更校验

处理 `--- state ---` 中每条变更，逐条独立执行（一条失败不影响其他）。

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
for each line in state_block:
    parse: @var var_name operator value

    var_def = find_var_in_story_config(var_name)
    if not var_def:
        rejected_changes.append({line, reason: "变量不存在"})
        continue

    valid = validate(var_def.type, operator, value)

    if not valid:
        rejected_changes.append({line, reason: valid.error})
        continue

    result = apply(state_vars[var_name], operator, value)
    if var_def.type == "number":
        result = clamp(result, 0, 100)
```

> **静默处理**：list 增删重复/不存在的元素、number 越界取上下限——不中断流程，不展示给用户，但记入 rejected_changes，在下一轮 Prompt 中告知 LLM。
