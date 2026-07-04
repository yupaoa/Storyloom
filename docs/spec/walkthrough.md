# Phase 1 §4 叙事循环 — 综合样例

> **目的**：基于 [`exec-flow.md`](./exec-flow.md) §4 和 [`block-spec.md`](./block-spec.md) 的定义，设计一个覆盖 4 轮完整剧情段的样例，验证文档表达是否清晰、是否有遗漏的边界条件。
>
> **阅读方式**：每轮按 "回合前状态 → Prompt 组装 → LLM 输出 → 程序执行过程 → 回合后状态 → 用户界面" 的顺序展开。关键执行步骤标注了对应的文档条款。

---

## 0. 样例前置设定

### 0.1 故事背景（story_config）

| 字段 | 值 |
|------|-----|
| genre | adventure |
| label | 霓虹深渊 |
| setting | 2087 年，新东京地下城。巨型企业控制着数据流，芯片即权力。 |
| protagonist | 林焰，前企业安全顾问，现自由佣兵，体内植入了过载的神经接口 |
| tone | 黑暗、紧张、道德灰色地带 |

### 0.2 大纲（outline）

```
ch1_bar (start, 初始)
  └→ ch2_confrontation

ch2_confrontation (交易)
  ├→ ch3_underground    [if 信任度 >= 10]
  └→ ch3_surface        [if 信任度 < 10]

ch3_underground (地下网络)
  └→ ch4_safehouse

ch3_surface (街头追逐)
  └→ ch4_safehouse

ch4_safehouse (安全屋)
  └→ (end)
```

### 0.3 状态模板与初始变量

**模板**: `adventure`

| 变量名 | 类型 | 范围/值 | 初始值 |
|--------|------|---------|--------|
| 体力 | number | 0–100 | 50 |
| 理智值 | number | 0–100 | 60 |
| 信任度 | number | 0–100 | 5 |
| 线索 | list | string[] | [] |
| 芯片状态 | enum | "未获得" / "已获得" / "已破解" | "未获得" |

> 初始值在共创阶段确定，这里直接使用已初始化的 GameState。

### 0.4 本样例的玩家选择路径

```
R1: 选项 1（直接询问芯片下落）
R2: 选项 1（接过芯片）→ 段内路由 took_chip → 大纲路由 ch3_underground
R3: 选项 1（走下水道）→ 体力过低触发 exhausted 分支
R4: 结局
```

### 0.5 阅读约定

- `▸` 程序执行的动作
- `current_name` / `key_dict` 变化以 **粗体** 标注
- 跳过的区块以 `✗ 跳过` 标注
- 条件评估以 `✓ 命中` / `✗ 未命中` 标注
- `[§4.2.x]` 引用文档对应条款

---

## 1. Round 1 — 初入"霓虹深渊"（首轮）

> **覆盖要点**：首轮空 bridge_text、初始 state 声明、基础区块解析、checkpoint 推进、bridge_text 捕获。

### 1.1 回合前 GameState

```
state_vars:
  体力: 50
  理智值: 60
  信任度: 5
  线索: []
  芯片状态: "未获得"

progress:
  current_node: "ch1_bar"
  round_count: 0
  checkpoint_history: []
  checkpoint_summaries: []

bridge_text: ""    ← 首轮为空
rejected_changes: []   ← 首轮为空
```

### 1.2 组装 Prompt

```
═══════════ SYSTEM PROMPT ═══════════
[固定] 你是故事叙述引擎。按指定格式输出……

[故事背景]
setting: 2087 年，新东京地下城……
protagonist: 林焰，前企业安全顾问……
tone: 黑暗、紧张、道德灰色地带

[大纲]
ch1_bar [active] — 霓虹深渊：在酒吧获取情报 → ch2_confrontation
ch2_confrontation [pending] — 地下交易：与神秘线人会面
  ├→ ch3_underground [pending]
  └→ ch3_surface [pending]
ch3_underground [pending] — 地下网络：通过地下渠道逃离
ch3_surface [pending] — 街头追逐：在地面摆脱追兵
ch4_safehouse [pending] — 安全屋：揭开芯片秘密

[进度]
当前节点: ch1_bar
目标: 在酒吧获取情报
已完成节点: （无）

[重要事件]
（首轮为空）

[当前状态]
体力: 50 / 100
理智值: 60 / 100
信任度: 5 / 100
线索: （无）
芯片状态: 未获得

[拒绝反馈]
（首轮为空）
══════════════════════════════════════

═══════════ USER MESSAGE ═══════════
（首轮为空）
══════════════════════════════════════
```

> **对照 §4.3**：System Prompt 七部分齐全（固定规则 + 故事背景 + 大纲 + 进度 + 重要事件 + 当前状态 + 拒绝反馈）。User Message 仅 bridge_text（首轮空）。

### 1.3 LLM 完整输出

```
--- narrative:main ---
雨水敲击着头顶的金属雨棚，霓虹灯在积水里折射出破碎的光。你推开"霓虹深渊"
的铁门，一股混合着合成酒精和汗水的热浪扑面而来。

酒吧深处，一个裹着破旧风衣的身影抬起了头——线人"耗子"。他的义眼在昏暗
中泛着微弱的红光，朝你歪了歪头。

"林焰，"他用沙哑的嗓音说，"坐。"

你在对面的椅子上坐下。耗子把一杯泛着蓝色荧光的液体推到你面前。

"东西到了。但在给你之前——"他的手指在桌面上敲了两下，"我得知道你不是
在耍我。"

--- options:main ---
key: approach
1. 直视对方，单刀直入："芯片在哪儿？我没时间绕弯子。"
2. 环顾四周，压低声音："先说清楚，这地方有多少人在盯着你。"
3. 把酒杯推回去，微微一笑："先谈报酬，再谈芯片。"

--- state:main ---
@var 体力 50
@var 理智值 60
@var 信任度 5
@var 芯片状态 "未获得"

--- checkpoint ---
node ch2_confrontation
summary: 在霓虹深渊酒吧与线人耗子接头，选择了接触方式。

--- bridge ---
耗子的嘴角抽搐了一下。他的手缓缓伸进风衣内袋——
你不知道他掏出来的会是芯片，还是武器。
```

### 1.4 程序执行过程

> 解析正则：`^--- (\w+)(?::(\w+))? ---$` [§4.2.1]

```
═══════════ 第 1 步：解析区块标记 ═══════════
  区块 1: narrative:main       (line 1)
  区块 2: options:main         (line 11)
  区块 3: state:main           (line 16)
  区块 4: checkpoint (main)    (line 22)
  区块 5: bridge (main)        (line 25)

═══════════ 第 2 步：顺序扫描执行 ═══════════
初始: current_name = "main", key_dict = {}

▸ 区块 1: --- narrative:main ---
  路由判定: name="main" == current_name="main" → ✓ 执行  [§4.2.2 路由规则]
  动作: 将叙事文本加入展示缓冲区

▸ 区块 2: --- options:main ---
  路由判定: name="main" == current_name="main" → ✓ 执行
  解析: key = "approach", 选项 1..3 均无 @if 条件
  动作: 展示选项，等待玩家输入
  >>> 玩家选择 [1]
  动作: key_dict = {"approach": 1}                        [§4.2.2 key_dict 修改]
  选项 1 无 "-> name" → current_name 保持 "main"

▸ 区块 3: --- state:main ---
  路由判定: name="main" == current_name="main" → ✓ 执行
  逐行解析:
    行1: @var 体力 50       → 无条件，校验 (0 ≤ 50 ≤ 100) ✓ → 体力 = 50  [§1.3 本地为真相源]
    行2: @var 理智值 60     → 无条件，校验 (0 ≤ 60 ≤ 100) ✓ → 理智值 = 60
    行3: @var 信任度 5      → 无条件，校验 (0 ≤ 5 ≤ 100) ✓   → 信任度 = 5
    行4: @var 芯片状态 "未获得" → 无条件，校验 (枚举值存在) ✓ → 芯片状态 = "未获得"
  无 @name 指令 → current_name 保持 "main"

▸ 区块 4: --- checkpoint ---
  固定 main，始终执行  [§4.2.4: checkpoint 固定 main]
  解析: node = "ch2_confrontation"
  校验: node_id 在 outline 中存在 ✓
  动作:
    - progress.current_node = "ch2_confrontation"
    - checkpoint_history += ["ch1_bar→ch2_confrontation"]
    - checkpoint_summaries += ["在霓虹深渊酒吧与线人耗子接头……"]
    - checkpoint_snapshots["ch1_bar"] = 当前 state_vars 快照    [§1.9 仅存储]
    - 触发自动存档                                            [§6.2 待编写]
    - round_count = 1

▸ 区块 5: --- bridge ---
  固定 main，始终执行
  动作:
    - 触发下一轮 Prompt 后台组装（异步）                        [§1.3 无缝衔接]
    - 捕获 bridge_text = "耗子的嘴角抽搐了一下……还是武器。"
    - bridge 之后无 state/checkpoint → 合规 ✓                 [§4.2.4]

═══════════ 第 3 步：清理临时变量 ═══════════
  current_name = "main" (重置)
  key_dict = {} (清空)                                        [§4.2.2 轮次结束时清空]
```

### 1.5 回合后 GameState

```
state_vars:
  体力: 50
  理智值: 60
  信任度: 5
  线索: []
  芯片状态: "未获得"

progress:
  current_node: "ch2_confrontation"
  round_count: 1
  checkpoint_history: ["ch1_bar→ch2_confrontation"]
  checkpoint_summaries:
    - "在霓虹深渊酒吧与线人耗子接头，选择了接触方式。"
  checkpoint_snapshots:
    ch1_bar: {体力:50, 理智值:60, 信任度:5, 线索:[], 芯片状态:"未获得"}

bridge_text: "耗子的嘴角抽搐了一下。他的手缓缓伸进风衣内袋——\n你不知道他掏出来的会是芯片，还是武器。"
```

### 1.6 用户界面展示

```
──────────────────────────────────────────
  雨水敲击着头顶的金属雨棚，霓虹灯在积水里折射出破碎的光。
  你推开"霓虹深渊"的铁门，一股混合着合成酒精和汗水的热浪
  扑面而来。

  酒吧深处，一个裹着破旧风衣的身影抬起了头——线人"耗子"。
  他的义眼在昏暗中泛着微弱的红光，朝你歪了歪头。

  "林焰，"他用沙哑的嗓音说，"坐。"

  你在对面的椅子上坐下。耗子把一杯泛着蓝色荧光的液体推到
  你面前。

  "东西到了。但在给你之前——"他的手指在桌面上敲了两下，
  "我得知道你不是在耍我。"

  ┌──────────────────────────────────────┐
  │ 1. 直视对方，单刀直入："芯片在哪儿？     │
  │    我没时间绕弯子。"                    │
  │ 2. 环顾四周，压低声音："先说清楚，这     │
  │    地方有多少人在盯着你。"              │
  │ 3. 把酒杯推回去，微微一笑："先谈报酬，   │
  │    再谈芯片。"                          │
  └──────────────────────────────────────┘
  >>> 1

  耗子的嘴角抽搐了一下。他的手缓缓伸进风衣内袋——
  你不知道他掏出来的会是芯片，还是武器。
──────────────────────────────────────────
  [后台: 下一轮 Prompt 组装中……]
```

> **对照 §1.3 无缝衔接原则**：bridge 触发后台请求，用户阅读 bridge_text 时下一轮已在生成。

---

## 2. Round 2 — 地下交易（段内分支 + 大纲分支）

> **覆盖要点**：options `-> name` 路由、命名 narrative/state 的执行与跳过、段内分支不影响大纲、checkpoint 条件路由（大纲分支）、state 校验拒绝反馈。

### 2.1 回合前 GameState

```
state_vars: 同 R1 结束后 (体力:50, 理智值:60, 信任度:5, 线索:[], 芯片状态:"未获得")
current_node: "ch2_confrontation"
round_count: 1

bridge_text: "耗子的嘴角抽搐了一下。他的手缓缓伸进风衣内袋——\n你不知道他掏出来的会是芯片，还是武器。"
rejected_changes: []
```

### 2.2 组装 Prompt

```
═══════════ SYSTEM PROMPT ═══════════
[固定] 你是故事叙述引擎……

[故事背景] （同 R1）

[大纲]
ch1_bar [completed] — 霓虹深渊 → ch2_confrontation
ch2_confrontation [active] — 地下交易：与神秘线人会面
  ├→ ch3_underground [pending]
  └→ ch3_surface [pending]
……

[进度]
当前节点: ch2_confrontation
目标: 与神秘线人会面
已完成节点: ch1_bar

[重要事件]
- R1: 在霓虹深渊酒吧与线人耗子接头，选择了接触方式。

[当前状态]
体力: 50 / 100
理智值: 60 / 100
信任度: 5 / 100
线索: （无）
芯片状态: 未获得

[拒绝反馈]
（空）
══════════════════════════════════════

═══════════ USER MESSAGE ═══════════
耗子的嘴角抽搐了一下。他的手缓缓伸进风衣内袋——
你不知道他掏出来的会是芯片，还是武器。
══════════════════════════════════════
```

> **注意**：大纲中 ch1_bar 已标 `[completed]`，ch2_confrontation 标 `[active]`。checkpoint_summaries 已有一项。

### 2.3 LLM 完整输出

```
--- narrative:main ---
耗子掏出来的不是武器。是一个巴掌大的铁盒，表面布满了细微的刮痕，像是被
粗暴地撬开过很多次。

"别碰——"你刚伸手，他就把盒子往后一缩，"先听我说完。"

他的声音压得更低了。"这芯片是从荒坂集团的 R&D 部门流出来的。他们在上面
跑了一种新型 AI——自主意识级别的东西。芯片本身不值钱，值钱的是里面关着
的东西。"

耗子把铁盒推到桌子中央。盒盖微微张开一条缝，你看到里面有蓝光在脉动。

"现在的问题是，"耗子的义眼聚焦在你身上，"你要不要接这个烫手山芋。"

--- options:main ---
key: chip_choice
1. 伸手接过铁盒，扣在掌心里 -> took_chip
2. 把铁盒推回去，站起身："这不是我要的东西。" -> refused

--- narrative:took_chip ---
你一把扣住铁盒，金属的凉意顺着指尖爬上来。几乎同时，你感到后颈的神经
接口传来一阵刺痒——那是你体内的植入体对芯片产生的反应，就像是它在
*认出*盒子里的东西。

耗子的脸上闪过一丝如释重负的表情。"聪明。"

--- state:took_chip ---
@var 线索 +神秘芯片
@var 信任度 +15
@var 芯片状态 "已获得"
@var 未知变量 +10

--- narrative:refused ---
你把铁盒推回去，金属在桌面上刮出一声刺耳的响。

耗子的表情凝固了。他的手还悬在半空中，义眼的红光闪了两下——那是他愤怒时
的生理反应。"你知道有多少人为了这东西丢了命吗？"

他猛地站起来，椅子在地板上刮出一声尖叫。周围几桌的人转头看了过来。

--- state:refused ---
@var 信任度 -20

--- checkpoint ---
node ch2_confrontation
if 信任度 >= 10 -> route ch3_underground
if 信任度 < 10 -> route ch3_surface
summary: 与耗子完成了芯片交易。选择了是否接收神秘芯片。

--- bridge ---
你把芯片塞进夹克内袋，从后门溜出酒吧。雨还在下。

身后的霓虹灯在积水里拉成模糊的光带，但你已经没心思看风景了——街对面的
阴影里，两个穿黑色合成皮夹克的人同时站直了身子。
```

### 2.4 程序执行过程

```
═══════════ 第 1 步：解析区块标记 ═══════════
  区块 1: narrative:main
  区块 2: options:main
  区块 3: narrative:took_chip
  区块 4: state:took_chip
  区块 5: narrative:refused
  区块 6: state:refused
  区块 7: checkpoint (main)
  区块 8: bridge (main)

═══════════ 第 2 步：顺序扫描执行 ═══════════
初始: current_name = "main", key_dict = {}

▸ 区块 1: --- narrative:main ---
  name="main" == current_name="main" → ✓ 执行
  动作: 展示缓冲 += 耗子掏出铁盒的叙事

▸ 区块 2: --- options:main ---
  name="main" == current_name="main" → ✓ 执行
  解析:
    key = "chip_choice"
    选项 1: "伸手接过铁盒……" -> took_chip   （无 @if，始终可选项）
    选项 2: "把铁盒推回去……" -> refused      （无 @if，始终可选项）
  动作: 展示选项，等待玩家输入
  >>> 玩家选择 [1]
  动作:
    key_dict = {"chip_choice": 1}
    选项 1 有 "-> took_chip" → current_name = "took_chip"  ← 关键！

▸ 区块 3: --- narrative:took_chip ---
  路由判定: name="took_chip" == current_name="took_chip" → ✓ 执行
  动作: 展示缓冲 += 接过芯片的叙事

▸ 区块 4: --- state:took_chip ---
  路由判定: name="took_chip" == current_name="took_chip" → ✓ 执行
  逐行解析:
    行1: @var 线索 +神秘芯片
         → 校验 (线索 是 list, "神秘芯片" 是合法值) ✓
         → 线索 = ["神秘芯片"]

    行2: @var 信任度 +15
         → 校验 (5 + 15 = 20, 0 ≤ 20 ≤ 100) ✓
         → 信任度 = 20

    行3: @var 芯片状态 "已获得"
         → 校验 (枚举值 "已获得" 存在) ✓
         → 芯片状态 = "已获得"

    行4: @var 未知变量 +10                          ← 问题行！
         → 校验 (变量名 "未知变量" 不在模板中) ✗    [§1.3 本地为真相源]
         → 拒绝！加入 rejected_changes
         → rejected_changes = [{
              line: "@var 未知变量 +10",
              reason: "变量 '未知变量' 不在 adventure 模板中"
           }]
  无 @name 指令 → current_name 保持 "took_chip"

▸ 区块 5: --- narrative:refused ---
  路由判定: name="refused" != current_name="took_chip" → ✗ 跳过  [§4.2.2]
  动作: 此分支内容不展示

▸ 区块 6: --- state:refused ---
  路由判定: name="refused" != current_name="took_chip" → ✗ 跳过
  动作: 信任度不会 -20

▸ 区块 7: --- checkpoint ---
  固定 main，始终执行
  解析:
    node = "ch2_confrontation" → 校验存在 ✓
    条件 1: if 信任度 >= 10 → 信任度=20 ≥ 10 → ✓ 命中
            → route = "ch3_underground" → 校验 (在 outline 中) ✓
            → next_node = "ch3_underground"
    条件 2: if 信任度 < 10 → ✗ 未命中（条件 1 已命中，取首个）
  动作:
    - current_node = "ch3_underground"                   ← 大纲分支！
    - checkpoint_history += ["ch2_confrontation→ch3_underground"]
    - checkpoint_summaries += [summary]
    - checkpoint_snapshots["ch2_confrontation"] = 当前快照
    - 自动存档

▸ 区块 8: --- bridge ---
  固定 main，始终执行
  bridge_text = "你把芯片塞进夹克内袋……两个穿黑色合成皮夹克的人同时站直了身子。"
  bridge 之后无 state/checkpoint → 合规 ✓

═══════════ 第 3 步：清理 ═══════════
  current_name = "main" (重置), key_dict = {} (清空)
```

### 2.5 回合后 GameState

```
state_vars:
  体力: 50
  理智值: 60
  信任度: 20          ← +15 (来自 took_chip)
  线索: ["神秘芯片"]   ← 新增
  芯片状态: "已获得"   ← 变更

progress:
  current_node: "ch3_underground"   ← 大纲分支结果
  round_count: 2
  checkpoint_history: ["ch1_bar→ch2_confrontation", "ch2_confrontation→ch3_underground"]
  checkpoint_summaries:
    - "在霓虹深渊酒吧与线人耗子接头，选择了接触方式。"
    - "与耗子完成了芯片交易。选择了是否接收神秘芯片。"
  checkpoint_snapshots:
    ch1_bar: {体力:50, 理智值:60, 信任度:5, 线索:[], 芯片状态:"未获得"}
    ch2_confrontation: {体力:50, 理智值:60, 信任度:20, 线索:["神秘芯片"], 芯片状态:"已获得"}

bridge_text: "你把芯片塞进夹克内袋，从后门溜出酒吧。雨还在下。……"
rejected_changes: [
  { line: "@var 未知变量 +10", reason: "变量 '未知变量' 不在 adventure 模板中" }
]
```

### 2.6 用户界面展示

```
──────────────────────────────────────────
  耗子掏出来的不是武器。是一个巴掌大的铁盒，表面布满了
  细微的刮痕……

  （中间叙事略）

  耗子把铁盒推到桌子中央。盒盖微微张开一条缝，你看到
  里面有蓝光在脉动。

  "现在的问题是，"耗子的义眼聚焦在你身上，"你要不要
  接这个烫手山芋。"

  ┌──────────────────────────────────────┐
  │ 1. 伸手接过铁盒，扣在掌心里            │
  │ 2. 把铁盒推回去，站起身："这不是我要    │
  │    的东西。"                           │
  └──────────────────────────────────────┘
  >>> 1

  你一把扣住铁盒，金属的凉意顺着指尖爬上来。几乎同时，
  你感到后颈的神经接口传来一阵刺痒——那是你体内的
  植入体对芯片产生的反应，就像是它在*认出*盒子里的
  东西。

  耗子的脸上闪过一丝如释重负的表情。"聪明。"

  ───── 桥接 ─────
  你把芯片塞进夹克内袋，从后门溜出酒吧。雨还在下。

  身后的霓虹灯在积水里拉成模糊的光带，但你已经没心思
  看风景了——街对面的阴影里，两个穿黑色合成皮夹克的
  人同时站直了身子。
──────────────────────────────────────────
  [后台: 下一轮 Prompt 组装中……]
```

> **关键验证**：选项 2 的 `narrative:refused` 和 `state:refused` 被跳过——玩家只看到选择的分支。这就是**段内分支**：同一个剧情段内，不同选择导向不同叙事和状态，但不跨越 checkpoint。

---

## 3. Round 3 — 地下逃生（条件路由 + bridge 后路径感知提取）

> **覆盖要点**：options `@if` 条件筛选、state 条件引用 key_dict（优先匹配）、bridge 之后多个命名 narrative、程序按 `current_name` 提取匹配路径的正文、剥离分隔符包装为 `narrative:main`。

### 3.1 回合前 GameState

```
state_vars:
  体力: 50
  理智值: 60
  信任度: 20
  线索: ["神秘芯片"]
  芯片状态: "已获得"

current_node: "ch3_underground"
round_count: 2

bridge_text: "你把芯片塞进夹克内袋……两个穿黑色合成皮夹克的人同时站直了身子。"
rejected_changes: [
  { line: "@var 未知变量 +10", reason: "变量 '未知变量' 不在 adventure 模板中" }
]
```

### 3.2 组装 Prompt

```
═══════════ SYSTEM PROMPT ═══════════
[固定] 你是故事叙述引擎……

[大纲]
ch1_bar [completed]
ch2_confrontation [completed]
ch3_underground [active] — 地下网络：通过地下渠道逃离 → ch4_safehouse
ch3_surface [pending]（未选择的分支）
ch4_safehouse [pending]

[进度]
当前节点: ch3_underground
目标: 通过地下渠道逃离
已完成节点: ch1_bar, ch2_confrontation

[重要事件]
- R1: 在霓虹深渊酒吧与线人耗子接头，选择了接触方式。
- R2: 与耗子完成了芯片交易。选择了接收神秘芯片。

[当前状态]
体力: 50 / 100
理智值: 60 / 100
信任度: 20 / 100
线索: 神秘芯片
芯片状态: 已获得

[拒绝反馈]
⚠ 上轮以下变更被拒绝，请避免再次使用：
  - "@var 未知变量 +10" — 变量 '未知变量' 不在 adventure 模板中
══════════════════════════════════════

═══════════ USER MESSAGE ═══════════
你把芯片塞进夹克内袋，从后门溜出酒吧。雨还在下。

身后的霓虹灯在积水里拉成模糊的光带，但你已经没心思
看风景了——街对面的阴影里，两个穿黑色合成皮夹克的人
同时站直了身子。
══════════════════════════════════════
```

> **对照 §4.3**：拒绝反馈仅在非空时注入 System Prompt。

### 3.3 LLM 完整输出

```
--- narrative:main ---
你没有回头。脚步声在身后响起——至少三个人，穿着硬底靴，步伐整齐。不是街头
混混，是公司安保。

前方是一个废弃的地铁入口，铁栅栏被人撬开了一半。你知道下面是旧城区的地下
通道网络，二战时期修建的防空洞加上后来的走私隧道，像蚁穴一样错综复杂。

你侧身钻进栅栏的缺口，沿着生锈的铁梯向下爬。头顶传来一声吼叫——他们看见
你了。

隧道里漆黑一片，只有远处几盏应急灯发出昏黄的光。你面前有三条路。

--- options:main ---
key: escape_method
1. 潜入下水道——水会掩盖气味，但水流湍急 -> sewer
2. 跳上废弃的维护地铁——更快，但轨道区有高压电 -> metro
3. 寻找地下抵抗组织的暗门 @if: 信任度 >= 15 -> resistance

--- state:main ---
if escape_method == 1 -> @var 体力 -25
if escape_method == 2 -> @var 体力 -10, @var 理智值 -5
if escape_method == 3 -> @var 体力 -5, @var 信任度 +10, @var 线索 +地下网络

--- narrative:sewer ---
下水道的污水没过了你的膝盖，冰冷刺骨。跑出几百米后，你的腿开始发抖——
神经接口过载的副作用来得比预想的快。视线边缘出现了雪花状的噪点，每一次
呼吸都像在吸碎玻璃。

你踉跄了一下，手撑在湿滑的墙壁上。不能停。绝对不能停。

--- state:sewer ---
if 体力 < 30 -> @var 理智值 -10

--- narrative:metro ---
你跳上废弃的维护地铁，抓住冰冷的金属扶手。列车在黑暗的隧道中无声滑行，
只有偶尔擦出的火花照亮两侧斑驳的广告牌。高压电缆在头顶嗡嗡作响。

--- narrative:resistance ---
你在墙壁上找到了抵抗组织的暗记——三横一竖。按照耗子之前提过的暗号，你
在标记下方敲了三下。墙壁悄无声息地滑开了一道缝，一只手伸出来把你拉了进去。

--- checkpoint ---
node ch4_safehouse
summary: 通过地下网络逃离追捕，体力严重透支，但暂时甩掉了追兵。

--- bridge ---
你从一个检修口爬出地面，发现自己在一个废弃的工业区里。身后隧道的回声
渐渐消散——他们没跟上来。

雨水冲刷着你脸上的污泥。远处，一座亮着灯的旧仓库在雨幕中若隐若现。

--- narrative:sewer ---
你浑身湿透，污水从裤脚滴落。体力已经见底，但芯片还在——这是唯一让你
继续向前的理由。仓库的灯光在雨幕中摇曳，像是在招手。

--- narrative:metro ---
地铁隧道的嗡鸣还在耳边回响。你拍了拍身上的灰尘，检查口袋——芯片
安然无恙。远处的仓库亮着灯，不知道里面等着你的是敌是友。

--- narrative:resistance ---
抵抗组织的暗门在你身后关闭。接应人递给你一条干毛巾，指向那座亮着灯的
仓库。"去吧，"他说，"他们在等你。"
```

### 3.4 程序执行过程

```
═══════════ 第 1 步：解析区块标记 ═══════════
  区块 1: narrative:main           (隧道逃生)
  区块 2: options:main             (选择逃生路线)
  区块 3: state:main               (体力消耗，条件引用 key_dict)
  区块 4: narrative:sewer           (下水道路径叙事)
  区块 5: state:sewer               (下水道路径状态)
  区块 6: narrative:metro           (地铁路径叙事 — 未选中则跳过)
  区块 7: narrative:resistance      (抵抗组织路径叙事 — 未选中则跳过)
  区块 8: checkpoint (main)        (到达安全屋)
  区块 9: bridge (main)            (触发下一轮)
  区块 10: narrative:sewer          ← bridge 之后！sewer 路径过渡
  区块 11: narrative:metro          ← bridge 之后！metro 路径过渡
  区块 12: narrative:resistance     ← bridge 之后！resistance 路径过渡

═══════════ 第 2 步：顺序扫描执行 ═══════════
初始: current_name = "main", key_dict = {}

▸ 区块 1: --- narrative:main ---
  name="main" → ✓ 执行 → 展示缓冲 += 隧道逃生叙事

▸ 区块 2: --- options:main ---
  name="main" → ✓ 执行
  解析:
    key = "escape_method"
    选项 3 的 @if: 信任度 >= 15 → key_dict 无"信任度" → 查 state_vars → 20 ≥ 15 ✓ 可显示
  动作: 展示 3 个选项，等待玩家输入
  >>> 玩家选择 [1]
  → key_dict = {"escape_method": 1}
  → 选项 1 有 "-> sewer" → current_name = "sewer"

▸ 区块 3: --- state:main ---
  name="main" → 始终执行
  行1: if escape_method == 1 → key_dict["escape_method"]=1 → ✓ 命中
       → @var 体力 -25 → 校验 0≤25≤100 ✓ → 体力 = 25
  行2: if escape_method == 2 → ✗ 未命中
  行3: if escape_method == 3 → ✗ 未命中

▸ 区块 4: --- narrative:sewer ---
  路由: name="sewer" == current_name="sewer" → ✓ 执行
  动作: 展示缓冲 += 下水道体力透支叙事

▸ 区块 5: --- state:sewer ---
  路由: name="sewer" == current_name="sewer" → ✓ 执行
  行1: if 体力 < 30 → 体力=25 < 30 → ✓ 命中
       → @var 理智值 -10 → 校验 0≤50≤100 ✓ → 理智值 = 50

▸ 区块 6: --- narrative:metro ---
  路由: name="metro" != current_name="sewer" → ✗ 跳过         [§4.2.2]
  （此分支的叙事和状态均不执行）

▸ 区块 7: --- narrative:resistance ---
  路由: name="resistance" != current_name="sewer" → ✗ 跳过
  （注意 resistance 没有对应的 state 块——state 不是必选的）

▸ 区块 8: --- checkpoint ---
  固定 main，始终执行
  node = "ch4_safehouse" → 校验 ✓ → current_node 更新, 存档

▸ 区块 9: --- bridge ---
  固定 main，始终执行
  ▸ 触发下一轮 Prompt 后台组装

═══════════ bridge 之后：路径感知提取 ═══════════

  约束检查: bridge 之后无 state / checkpoint / options → 合规 ✓    [§4.2.3]

▸ 扫描 bridge 之后的 narrative 区块（current_name = "sewer"）:

  区块 10: --- narrative:sewer ---
    路由: name="sewer" == current_name="sewer" → ✓ 匹配！         [§4.2.3 bridge_text 提取]
    动作: 展示缓冲 += "你浑身湿透……"
    ▸ 提取此区块正文（不含 `--- narrative:sewer ---` 标记行），
      作为 bridge_text 的候选内容

  区块 11: --- narrative:metro ---
    路由: name="metro" != current_name="sewer" → ✗ 跳过
    （此文本既不展示，也不进入 bridge_text）

  区块 12: --- narrative:resistance ---
    路由: name="resistance" != current_name="sewer" → ✗ 跳过

  ▸ bridge_text 提取结果:
    纯文本 = "你浑身湿透，污水从裤脚滴落。体力已经见底，但芯片还在——
             这是唯一让你继续向前的理由。仓库的灯光在雨幕中摇曳，像是在招手。"

  ▸ 组装下一轮 User Message:
    在纯文本开头插入 `--- narrative:main ---` →
    User Message = "--- narrative:main ---\n你浑身湿透，污水从裤脚滴落……"

═══════════ 第 3 步：清理 ═══════════
  current_name = "main" (重置), key_dict = {} (清空)
```

### 3.5 回合后 GameState

```
state_vars:
  体力: 25              ← 50 - 25 (下水道消耗)
  理智值: 50            ← 60 - 10 (sewer 路径低体力惩罚)
  信任度: 20
  线索: ["神秘芯片"]
  芯片状态: "已获得"

progress:
  current_node: "ch4_safehouse"
  round_count: 3
  checkpoint_history: [……, "ch3_underground→ch4_safehouse"]
  checkpoint_summaries: [……, "通过地下网络逃离追捕，体力严重透支……"]

bridge_text: 仅包含匹配 current_name="sewer" 的 narrative:sewer 正文
  （narrative:metro 和 narrative:resistance 的内容已被跳过，
   分隔符 `--- narrative:sewer ---` 在组装时由程序剥离，
   下一轮 User Message 开头插入 `--- narrative:main ---`）
```

### 3.6 用户界面展示

```
──────────────────────────────────────────
  你没有回头。脚步声在身后响起——至少三个人……

  （隧道逃生叙事……）

  隧道里漆黑一片，只有远处几盏应急灯发出昏黄的光。你面前
  有三条路。

  ┌──────────────────────────────────────┐
  │ 1. 潜入下水道——水会掩盖气味，但水流湍急 │
  │ 2. 跳上废弃的维护地铁——更快，但轨道区   │
  │    有高压电                            │
  │ 3. 寻找地下抵抗组织的暗门               │
  └──────────────────────────────────────┘
  >>> 1

  下水道的污水没过了你的膝盖，冰冷刺骨。跑出几百米后，
  你的腿开始发抖——神经接口过载的副作用来得比预想的快。
  视线边缘出现了雪花状的噪点，每一次呼吸都像在吸碎玻璃。

  你踉跄了一下，手撑在湿滑的墙壁上。不能停。绝对不能停。

  ───── 桥接 ─────
  你从一个检修口爬出地面，发现自己在一个废弃的工业区里。
  身后隧道的回声渐渐消散——他们没跟上来。

  雨水冲刷着你脸上的污泥。远处，一座亮着灯的旧仓库在雨幕
  中若隐若现。

  你浑身湿透，污水从裤脚滴落。体力已经见底，但芯片还在——
  这是唯一让你继续向前的理由。仓库的灯光在雨幕中摇曳，
  像是在招手。
──────────────────────────────────────────
  [后台: 下一轮 Prompt 组装中……]
  [组装逻辑: 提取匹配 current_name="sewer" 的 narrative 正文，
   剥离分隔符，包装为 --- narrative:main ---]
```

> **对照 §4.2.3**：bridge 之后的三个命名 narrative 中，只有匹配 `current_name="sewer"` 的被展示和提取。metro 和 resistance 的过渡文本既不显示也不进入 bridge_text——用户只能看到自己选择路径的内容。

---

## 4. Round 4 — 安全屋（结局轮）

> **覆盖要点**：checkpoint `end` 结局处理、adventure_log 生成、bridge 可选省略。

### 4.1 回合前 GameState

```
state_vars:
  体力: 25
  理智值: 50
  信任度: 20
  线索: ["神秘芯片"]
  芯片状态: "已获得"

current_node: "ch4_safehouse"
round_count: 3

bridge_text: "你从一个检修口爬出地面……这一切还远没有结束。"
rejected_changes: []  ← 上轮无拒绝
```

### 4.2 组装 Prompt

```
═══════════ SYSTEM PROMPT ═══════════
……（同前几轮的结构）

[大纲]
ch1_bar [completed]
ch2_confrontation [completed]
ch3_underground [completed]
ch4_safehouse [active] — 安全屋：揭开芯片秘密 → (end)

[重要事件]
- R1: 在霓虹深渊酒吧与线人耗子接头……
- R2: 与耗子完成了芯片交易……
- R3: 通过地下网络逃离追捕，体力严重透支……

[当前状态]
体力: 25 / 100
理智值: 50 / 100
信任度: 20 / 100
线索: 神秘芯片
芯片状态: 已获得
══════════════════════════════════════

═══════════ USER MESSAGE ═══════════
你从一个检修口爬出地面……这一切还远没有结束。
══════════════════════════════════════
```

### 4.3 LLM 完整输出

```
--- narrative:main ---
仓库里等待着你的是一个你没想到的人——耗子。

"你比我想象的快，"他坐在一张堆满显示器的桌前，手里转着一支数据线，
"而且活着。这已经超过我的预期了。"

你靠在门框上，把铁盒从口袋里掏出来扔给他。耗子接住盒子，但没有打开。

"不用看了，"他说，"芯片已经激活了。你的神经接口刚才应该感觉到了——
它在和你体内的植入体配对。"

你皱起眉头。"我没授权任何配对。"

耗子耸了耸肩。"芯片不是用来卖的。它是用来找人的——找像你这样的人。
前荒坂员工、神经接口植入者、还没有被公司回收的……幸存者。"

他把显示器转过来对着你。屏幕上是一个庞大的网络拓扑图，上面有上百个
节点在跳动——每一个都代表一个像你一样的人。

"欢迎加入抵抗组织，林焰。"

--- checkpoint ---
end
summary: 在废弃仓库与耗子重逢，得知芯片的真正用途——它是地下抵抗组织的
联络密钥，正在寻找所有前荒坂神经接口植入者。林焰的命运与这个组织绑在了一起。

--- adventure_log ---
## 冒险回顾：霓虹深渊

### 第一章：接头
在霓虹深渊酒吧遇到了线人耗子。选择了直接询问芯片下落，展现了你作为
前安全顾问的专业素养——不绕弯子，直击要害。

### 第二章：交易
接过了神秘芯片。这个选择让你获得了耗子的信任，也让你成为了荒坂集团
追捕的目标。芯片在你体内的植入体上激活了某种未知的配对协议。

### 第三章：逃生
通过下水道逃离追捕，体力几近透支。神经接口的过载让你在隧道中经历了
一次濒临崩溃的时刻——但你挺过来了。

### 结局：真相
芯片不是武器，不是数据，而是一个信标——它在寻找所有被荒坂抛弃的
神经接口植入者。你不是唯一的幸存者，而你刚刚加入了他们的行列。

### 最终状态
- 体力: 25 / 100（需要休息）
- 理智值: 50 / 100（承受了巨大压力但未崩溃）
- 信任度: 20 / 100（与耗子建立了初步信任）
- 线索: 神秘芯片
- 结局: 加入地下抵抗组织
```

### 4.4 程序执行过程

```
═══════════ 第 1 步：解析区块标记 ═══════════
  区块 1: narrative:main
  区块 2: checkpoint (main) → end
  区块 3: adventure_log (main)

  注意：无 bridge 区块 ← 结局轮 LLM 省略了 bridge  [§4.2.3 结局轮 bridge 可选]

═══════════ 第 2 步：顺序扫描执行 ═══════════
初始: current_name = "main", key_dict = {}

▸ 区块 1: --- narrative:main ---
  路由: name="main" → ✓ 执行
  动作: 展示缓冲 += 结局叙事

▸ 区块 2: --- checkpoint ---
  解析: "end" → 结局触发！
  动作:
    - 标记游戏为 "结局阶段"
    - 不更新 current_node（已是终点）
    - checkpoint_summaries += [summary]
    - 最终存档

▸ 区块 3: --- adventure_log ---
  固定 main，始终执行
  动作: 展示缓冲 += adventure_log 内容

  无 bridge → 不组装下一轮 Prompt                          [§4.2.4: end 不组装]
  无 bridge → 不需要 bridge_text

═══════════ 第 3 步：进入结局阶段 ═══════════
  → 跳转到 §5 结局阶段逻辑（待编写）
  → 展示完整 narrative + adventure_log
  → 最终存档
  → 返回主菜单
```

### 4.5 用户界面展示

```
──────────────────────────────────────────
  仓库里等待着你的是一个你没想到的人——耗子。

  "你比我想象的快，"他坐在一张堆满显示器的桌前……
  （完整结局叙事）

  "欢迎加入抵抗组织，林焰。"

  ═══════════════════════════════════════
              ～ 冒险回顾 ～
  ═══════════════════════════════════════

  ## 冒险回顾：霓虹深渊

  ### 第一章：接头
  在霓虹深渊酒吧遇到了线人耗子……

  ### 第二章：交易
  接过了神秘芯片……

  ### 第三章：逃生
  通过下水道逃离追捕……

  ### 结局：真相
  芯片是一个信标……

  ### 最终状态
  - 体力: 25 / 100（需要休息）
  - 理智值: 50 / 100
  - 信任度: 20 / 100
  - 线索: 神秘芯片

  ═══════════════════════════════════════
  [按任意键返回主菜单]
──────────────────────────────────────────
```

---

## 5. 样例复盘：文档清晰度评估

### 5.1 已验证的机制（✅ 表达清晰）

| 机制 | 文档出处 | 样例位置 | 状态 |
|------|----------|----------|------|
| 区块正则解析 `^--- (\w+)(?::(\w+))? ---$` | §4.2.1 | R1–R4 每轮 | ✅ 明确 |
| 命名路由：name == current_name 或 "main" | §4.2.2 | R2, R3 | ✅ 明确 |
| options `-> name` 修改 current_name | §4.2.2 | R2, R3 | ✅ 明确 |
| state 无条件变更 `@var` | §4.2.3 | R1–R3 | ✅ 明确 |
| state 条件变更 `if ... -> @var` | §4.2.3 | R3 | ✅ 明确 |
| `@var` 操作符（+/-/=） | §4.2.3 | R1–R3 | ✅ 已补充 |
| key_dict 变量解析优先级 > state_vars | §1.3 | R3 | ✅ 明确 |
| checkpoint `if -> route` 大纲分支 | §4.2.3 | R2 | ✅ 明确 |
| checkpoint `end` 结局 | §4.2.3 | R4 | ✅ 明确 |
| bridge 触发下一轮 Prompt 组装 | §4.2.3 | R1–R3 | ✅ 明确 |
| bridge 之后不得有 state / checkpoint / options | §4.2.3 | R3 | ✅ 已修正 |
| bridge 之后命名 narrative 路径感知提取 | §4.2.3 | R3 | ✅ 已补充 |
| bridge_text 分隔符剥离 + narrative:main 包装 | §4.2.3 | R3 | ✅ 已补充 |
| LLM 先完整生成再插入 bridge | §1.3 | 全部 | ✅ 已补充 |
| 同段内 options key 唯一 | §4.2.4 | 每轮 key 不同 | ✅ 明确 |
| 拒绝反馈注入下一轮 Prompt | §4.3 | R2→R3 | ✅ 明确 |
| adventure_log 结局回顾 | §4.2.3 | R4 | ✅ 明确 |
| state 在 checkpoint 之前 | §4.2.4 | 区块顺序 | ✅ 明确 |

### 5.2 已解决的问题（✅ 已修改文档）

#### 问题 1：bridge 之后区块约束不足 → 已修正

原文档允许 bridge 之后有 `options + named narrative`，导致路由歧义（current_name 可能被 state 的 @name 修改，与 post-bridge 区块名不匹配）。

**修正**：
- bridge 之后禁止 options、state、checkpoint，仅允许命名 narrative
- 程序按 `current_name` 做路径感知提取——只提取匹配的那条 narrative 正文
- 剥离分隔符标记行，包装为 `--- narrative:main ---` 注入下一轮 User Message
- §1.3 新增"LLM 先完整生成再插入 bridge"原则，从源头避免 LLM 在 bridge 之后放交互性内容

#### 问题 2：options `@if` 条件变量解析源 → 已有答案

`@if` 中的变量按 §1.3 优先级解析（key_dict > state_vars）。若同轮有多个 options block，第二个 block 的 `@if` 可以引用第一个 block 已选中的 key——这是合法用法。未选中的选项不应作为条件依据，这是 LLM 的生成责任，不属于程序逻辑问题。

#### 问题 3：`@var` 操作符定义 → 已补充

§4.2.3 state 节已补充 `@var` 操作符表（加减 / 赋值 / 追加）。

#### 问题 4：bridge_text 包含区块标记 → 已修正

§4.2.3 bridge 节明确：程序提取 bridge_text 时剥离所有 `--- xxx ---` 标记行，仅保留纯文本，并在开头插入 `--- narrative:main ---`。

### 5.3 文档中明确但样例未覆盖的要点

| 要点 | 说明 |
|------|------|
| 程序超时截断 | §1.3 "超时截断由 LLM 收束"中的处理逻辑，样例未模拟 |
| 多 options block 同段 | 样例每轮只有 1 个 options block，未测试 "key 必须唯一" 约束的全貌 |
| checkpoint 无条件路由 | 样例的 checkpoint 都有条件或无分支，未测试"无条件命中 → 取首个分支 next_node" |
| API 失败/解析错误 | §1.3 程序拥有最终控制权中的异常处理，样例未模拟 |
| 状态变更的完整校验 | 只展示了"变量不存在"的拒绝，未展示值域超限、类型错误等 |

---

## 6. 结论

样例覆盖了 §4 定义的**核心执行模型**：命名路由、段内分支、大纲分支、条件解析、bridge 衔接与路径感知提取、结局处理。整体表达清晰，开发者可以据此编写解析器。

样例编写过程中发现的 4 个问题已全部通过文档修改解决，关键的补充包括：
- bridge 之后只允许命名 narrative，程序做路径感知提取 + 分隔符剥离
- LLM 先完整生成再插入 bridge 的工作流
- `@var` 操作符的明确定义

---
*样例编写完成。建议将此文件作为文档 review 的配套材料。*
