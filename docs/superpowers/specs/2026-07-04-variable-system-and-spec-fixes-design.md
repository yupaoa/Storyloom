# 变量系统重构 & 规范矛盾修复 — 设计文档

> **日期**：2026-07-04  
> **状态**：已确认，待实现  
> **关联文档**：`spec/exec-flow.md`、`spec/block-spec.md`、`spec/data-model.md`、`design.md`

---

## 一、背景与动机

现有文档存在两类问题：

**设计层面**：三套硬编码状态模板（romance/adventure/mystery）是 Phase 2 之前的地桩——模板变量数量有限（5 个）、换题材即失效，与"LLM 自定义变量"的长期目标冲突。用户确认 Phase 1 即实现 LLM 自定义变量。

**规范层面**：文档审查发现 4 处直接矛盾（bridge 必选/可选、adventure_log 独立调用/嵌入区块、options 关键字 choice/key、条件解析优先级不一致），以及若干模糊表述。

本文档定义修复方案。优先级：**无缝体验 > 叙事质量 > 互动深度**。

---

## 二、变量系统：从硬编码模板到 LLM 自定义

### 2.1 砍掉的内容

| 移除项 | 原位置 | 原因 |
|--------|--------|------|
| `templates/states.json` | 文件系统 | 不再需要硬编码模板 |
| `TEMPLATES_PATH` 常量 | `config.py` | 不再加载模板文件 |
| `GENRE_TEMPLATE_MAP` 常量 | `config.py` | 不再做题材映射 |
| 三套题材（romance/adventure/mystery）概念 | `story_config.genre` | genre 降级为自由文本标签，不驱动变量选择 |
| `state_template` 字段 | GameState / 存档 | 变量定义存储在 `story_config.variables` 中 |

### 2.2 新增流程：共创阶段变量定义

在 story_config 生成（Step 3）和大纲生成（Step 4）之间插入 **Step 3.5**：

```
Step 3: 生成故事设定（--- story_config ---）
    ↓
Step 3.5: 生成变量定义（=== variables ===）  ← 新增
    ↓
Step 4: 生成大纲树（=== outline ===）
```

**Prompt 约束（注入变量生成 Prompt 中）：**

- 根据已确定的 story_config 定义 5–8 个游戏变量
- 数值型变量范围统一 [0, 100]
- 字符串型替代枚举（不设枚举类型，枚举归入 string）
- 列表型元素为 string（如背包、线索）
- 每个变量必须有中文名、类型、初始值

**LLM 输出格式：**

```
=== variables ===
体力: number, 初始 80
信任度: number, 初始 5
芯片状态: string, 初始 "未获得"
线索: list, 初始 []
理智值: number, 初始 60
```

**程序解析与校验：**

| 校验项 | 规则 | 失败处理 |
|--------|------|---------|
| 变量名唯一 | 无重复 | 拒绝，提示去重 |
| 变量名合法 | 非空、不含 `\n` / `:` | 拒绝 |
| 类型合法 | 仅 `number` / `string` / `list` | 拒绝 |
| number 初始值 | 在 [0, 100] 范围内 | 拒绝 |
| string 初始值 | 非空 | 拒绝 |
| list 初始值 | 可为 `[]`，元素须为 string | 拒绝 |

校验失败 → 重试（附带错误提示），最多 `MAX_RETRIES`（2）次。耗尽 → 告知用户，用户决策。

### 2.3 对现有系统的影响

**GameState 初始化变化：**

```python
# 旧
game_state.state_template = genre          # "romance"|"adventure"|"mystery"
game_state.state_vars = templates[genre].vars  # 模板深拷贝

# 新
game_state.variables = story_config.variables  # [{name, type, initial, range?}]
game_state.state_vars = init_from_variables(variables)  # {name: initial_value}
```

**存档变化：**

```json
{
  "version": 1,
  "story_config": {
    "variables": [
      {"name": "体力", "type": "number", "initial": 80, "min": 0, "max": 100},
      {"name": "信任度", "type": "number", "initial": 5, "min": 0, "max": 100},
      {"name": "芯片状态", "type": "string", "initial": "未获得"},
      {"name": "线索", "type": "list", "initial": []}
    ]
  },
  "state_vars": {
    "体力": 80,
    "信任度": 5,
    "芯片状态": "未获得",
    "线索": []
  }
}
```

移除 `state_template` 字段。存档加载时不再校验模板存在性（3.4 校验步骤 4 移除）。

**state 变更校验变化：**

原校验依赖 `state_template.vars` 获取变量类型定义，改为从 `story_config.variables` 获取。规则不变：

| 校验 | 规则 |
|------|------|
| 变量存在 | `story_config.variables` 中查找 |
| 类型匹配 | number 仅接受 `+N` / `-N` / `=N`；string 仅接受 `=值`；list 仅接受 `+元素` / `-元素` |
| number 范围 | 计算结果 clamp 到 [0, 100] |

---

## 三、规范矛盾修复

### 矛盾 1：结局轮是否需要 bridge

**决议：需要。** bridge 在结局轮是必选的。

```
结局轮 LLM 输出结构：

--- narrative:main ---
（结局叙事……）

--- checkpoint ---
end
summary: ...

--- bridge ---              ← 必选

--- narrative:main ---      ← 缓冲叙事
（结局衔接文本……）
```

程序在 bridge 处检测 `ending_flag == true` → 组装冒险日志 Prompt（独立 LLM 调用，不等下一轮叙事循环）。

**修改文件：**
- `spec/block-spec.md` §3 bridge 节：结局轮 bridge 标注保持"必选"，补充程序行为描述
- `spec/walkthrough.md`：后续重新生成时与之一致

### 矛盾 2：adventure_log 生成方式

**决议：独立 LLM 调用。** 与 `exec-flow.md` §5.4 一致。

adventure_log **不**嵌入叙事循环的 LLM 输出。程序在结局轮 bridge 处检测到 `ending_flag` 后，组装专用 Prompt（注入 story_config + state_vars + checkpoint_summaries + checkpoint_history），发起独立 LLM 调用。

**修改文件：**
- `spec/walkthrough.md` R4：移除嵌入的 `--- adventure_log ---` 区块，改为程序侧独立调用描述
- `spec/block-spec.md` §1 速查表：`adventure_log` 从区块表移除（它不是叙事循环区块）

### 矛盾 3：options 声明关键字

**决议：统一用 `choice:`。**

```
--- options:main ---
choice: chip_choice           ← 统一，不是 key:
1. 接过芯片 -> took_chip
2. 推回去 -> refused
```

**修改文件：**
- `spec/walkthrough.md`：所有 `key:` → `choice:`

### 矛盾 4：choice_dict 的值含义

**决议：存储玩家选择的选项编号（1/2/3...）。**

`choice_dict["chip_choice"] = 1` 表示玩家在 `chip_choice` 组中选择了第 1 个选项。

在 `block-spec.md` §3 state 节明确：`if chip_choice == 1` 中的数字为选项编号。

---

## 四、条件变量解析统一

**决议：在所有条件求值场景中统一优先级 `choice_dict > state_vars`。**

适用场景：
- options `@if:条件`（选项置灰判断）
- state `if 条件 -> @var/@branch`
- checkpoint `if 条件 -> route`

**修改文件：**
- `spec/data-model.md` §2 节点推进：补充 choice_dict 优先级说明
- `spec/block-spec.md` §2 路由机制：明确 choice_dict 作用域

---

## 五、文档结构调整

| 文档 | 变更 |
|------|------|
| `spec/exec-flow.md` | §3 共创阶段：Step 3 和 Step 4 之间插入 Step 3.5（变量定义）；移除 `state_template` 相关引用 |
| `spec/block-spec.md` | §1 速查表：移除 `adventure_log` 行；§3 bridge 节：明确结局轮 bridge 必选；§3 options 节：统一 `choice:`；§3 state 节：移除枚举操作符，type 仅 number/string/list |
| `spec/data-model.md` | §1 GameState 初始化：替换为变量定义驱动；§2 节点推进：补充 choice_dict 优先级；§3 存档：移除 `state_template` 字段，新增 `story_config.variables`；§A 常量：移除 `GENRE_TEMPLATE_MAP`、`TEMPLATES_PATH`；§B 全局约定：更新变量命名规则 |
| `design.md` | §4 状态系统：重写为 LLM 自定义变量方案；§5 上下文与成本策略：缩减到 Phase 1 相关内容；§8 存档设计：移除模板引用；移除过时的 Phase 2+ 详细内容，标注"Phase 1 完成后细化" |
| `spec/walkthrough.md` | 暂不重写（需进一步确认）。当前版本标注"草稿，与规范存在不一致" |

---

## 六、更新后的共创阶段流程

```
用户输入初始想法
      ↓
Step 1-2: 追问循环（LLM 提问 → 用户回答）
      ↓ 用户确认
Step 3: 生成故事设定（=== story_config ===）
      ↓
Step 3.5: 生成变量定义（=== variables ===）  ← 新增
      ↓
Step 4: 生成大纲树（=== outline ===）
      ↓
Step 5: 初始化 GameState → 叙事循环
```

### 6.1 story_config 字段变化

| 字段 | 变化 |
|------|------|
| `题材` (genre) | 降级为自由文本标签，不驱动模板选择。可保留用于 Prompt 上下文 |
| `variables` | **新增**。`[{name, type, initial}]` 列表，Step 3.5 产出 |

### 6.2 重试策略更新

变量生成（Step 3.5）的解析/校验失败使用 `MAX_RETRIES`（与 story_config、outline 一致）。

---

## 七、实现影响汇总

| 模块 | 影响 |
|------|------|
| `config.py` | 移除 `TEMPLATES_PATH`、`GENRE_TEMPLATE_MAP` |
| `templates/states.json` | **删除文件** |
| 共创阶段 (`co_create.py`) | 新增 Step 3.5 变量生成；移除题材→模板映射逻辑 |
| GameState 初始化 | 从 `story_config.variables` 初始化 `state_vars`，不再加载模板 |
| state 校验 (`state_validator.py`) | 变量类型定义来源从模板改为 `story_config.variables`；移除枚举类型支持 |
| 存档系统 (`save_manager.py`) | 移除 `state_template` 字段；加载时移除模板存在性校验；新增 `story_config.variables` 序列化 |
| Prompt 组装 (`prompt_builder.py`) | System Prompt 中状态部分直接格式化 `state_vars`，无需模板驱动 |
| `spec/block-spec.md` | 移除枚举操作符（`@var 芯片状态 "已获得"` 改为 string 赋值，语法不变） |

---

## 八、未解决的开放问题

以下问题已识别但不在此设计文档范围内解决：

1. **"LLM 先生成再插入 bridge"的表述**：LLM 只能顺序生成，提示词应改为"在合适位置放置 bridge 标记"。需在 Prompt 中体现。
2. **追问循环"是否开始生成故事"检测**：缺具体实现机制，需在实现阶段确定（正则匹配 / 关键词检测）。
3. **大纲质量的语义校验**：程序只能做静态校验（节点存在、变量存在），大纲逻辑连贯性无自动校验手段。Phase 1 通过 Prompt 约束和用户重试来缓解。
4. **共创阶段"不透露情节"约束**：依赖 Prompt 中的指令，无程序侧防护。
5. **bridge 触发下一轮的异步模型**：CLI 中的"后台组装"需在实现阶段明确——是展示 bridge_text 期间同步等待还是多线程预请求。

---

*设计文档完成。下一步：按模块更新各 spec 文件。*
