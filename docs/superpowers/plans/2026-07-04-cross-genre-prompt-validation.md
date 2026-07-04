# Cross-Genre Prompt Validation 实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 创建 3 个不同题材的 Prompt 文件（恋爱/悬疑/古风），运行测试，分析泛化能力

**架构：** 每个 Prompt 文件 = v4.txt 固定部分（格式示例 + 核心规则 + 质量要求）+ 题材特定的故事上下文。不影响任何现有代码文件。

**技术栈：** Python 3 + DeepSeek API + 现有测试脚本（run_prompt_test.py, analyze_results.py）

---

## 文件结构

| 文件 | 操作 | 职责 |
|------|------|------|
| `tests/data/prompts/romance.txt` | 创建 | 恋爱题材 Prompt — "倒数三次心跳" |
| `tests/data/prompts/mystery.txt` | 创建 | 悬疑题材 Prompt — "第十三级台阶" |
| `tests/data/prompts/wuxia.txt` | 创建 | 古风武侠题材 Prompt — "茶馆" |
| `tests/data/output/romance/` | 自动创建 | 恋爱场景测试输出（3 轮） |
| `tests/data/output/mystery/` | 自动创建 | 悬疑场景测试输出（3 轮） |
| `tests/data/output/wuxia/` | 自动创建 | 古风场景测试输出（3 轮） |

**关键约束：** 不修改任何现有文件。所有新文件仅添加。

---

### 任务 1：创建恋爱题材 Prompt 文件

**文件：**
- 创建：`tests/data/prompts/romance.txt`

- [ ] **步骤 1：编写 romance.txt**

`tests/data/prompts/romance.txt` 完整内容：

```
你是文字冒险游戏的叙事引擎。根据大纲和状态生成下一段交互式剧情。

# 输出格式

由区块标记分隔。标记独占一行，格式 --- 区块名 --- 或 --- 区块名:分支名 ---。
严格遵循此结构——包括编号方式、区块顺序和 bridge 位置。
示例中的编号仅用于示范格式，你的输出必须从 1 开始重新编号。

--- narrative:main ---
1. 炉火在石砌的壁炉里噼啪作响，旅店大堂里弥漫着麦酒和松木的气味。
2. 你推开厚重的橡木门，冷风裹挟着雪花卷入室内。
3. 旅店老板从吧台后抬起头，手里的抹布停在半空。
4. 旅店老板: 这么晚了还赶路？
5. 角落里一个裹着斗篷的身影动了动。
6. 你看不清那人的脸，但注意到他手边的剑柄。
7. 老板给你倒了杯热麦酒，压低声音。
8. 旅店老板: 那位客人等了你半个钟头。
9. 他指了指角落里的斗篷人。窗外暴风雪愈发猛烈。
10. 疤脸人摘下兜帽——一张布满疤痕的脸，眼神出奇的平静。
11. 疤脸人: 坐。听说你在找一样东西。

--- options:main ---
choice: approach
A. 先开口 -> take_lead
B. 保持沉默 -> wait

--- state:main ---
if approach == 1 -> @var 声望 +5
if approach == 2 -> @var 谨慎度 +10

--- checkpoint ---
node ch2_meeting
summary: 在旅店与神秘线人接头，选择了接触策略。
if approach == 1 -> route ch3_lead
if approach == 2 -> route ch3_wait

--- bridge ---

--- narrative:take_lead ---
12. 你在他对面坐下，指尖在木桌上轻轻敲了两下。
13. 林焰: 听说你手里有我要的情报。
14. 疤脸人微微一笑，从斗篷里掏出蜡封的羊皮纸卷放在桌上。

--- narrative:wait ---
15. 你站着没动，不动声色地啜了一口麦酒。
16. 沉默像一根绷紧的弦，疤脸人先沉不住气了。

（以上为格式示例。你的输出是全新的剧情段，必须从 1 开始编号，以 --- narrative:main --- 开头。）

# 核心规则

**段格式（重要）**
- 每个叙事段只能是旁白或对话，严格禁止混合。段前加数字编号，从 1 开始。段间空行。
- 旁白段：纯叙述描写，不含角色对话。一段只说一件事，15-40 字。
- 对话段：纯角色对话。格式固定为 `角色名: 对话内容`（英文半角冒号，冒号后空一格，对话不加引号）。
- 角色动作、表情、语气单独成旁白段。每段不超过 50 字。

**编号**
- 所有 narrative 块（含不同分支）共享同一数字序列。分支编号接续前一分支，禁止重复。
- 选项行用字母编号（A / B / C / D），不占数字序列。

**options（重要）**
- 第一行必须是 `choice: 变量名`（如示例 `choice: approach`）。state 条件通过此变量名 + 数字引用选项（A=1, B=2...）。
- 禁止 `choice == "A"` 或 `选择1 == 1` 等占位写法。

**段数与 bridge（重要）**
- 本轮严格控制在 60-120 个叙事段。超过 120 段会被程序截断，剧情断裂。
- bridge 放在总段数的约 40% 处——总段数 × 0.4，向下取整。
  总 80 段 → bridge 在第 32 段后 ✓；总 100 段 → bridge 在第 40 段后 ✓。
  禁止 bridge 之后尾部不足 20 段（太短导致衔接断裂）✗。
- bridge 是交互与叙事的分界线：bridge 之前放 options、state、checkpoint，bridge 之后只能有 narrative。
- bridge 之前的 options 和 state 必须使用 `:main` 分支（`--- options:main ---`、`--- state:main ---`）。
  命名分支（`:take_lead`）只出现在 bridge 之后的 narrative 中。`bridge` 是保留字，禁止用作分支名。

**state**
- `@var 变量名 操作符 值`（无条件）；`if 条件 -> @var 变量名 操作符 值`（条件触发）
- number 用 `+N` / `-N` / `=N`；string 用 `=值`；list 用 `+元素` / `-元素`
- 条件引用 choice 用声明名 + 数字，或引用状态变量（`if 信任度 >= 30`）。用 `and` / `or` 组合。

**checkpoint（重要）**
- `node {node_id}` 或 `end`，必须附 `summary:`（1-2 句中文摘要）。分支：`if 条件 -> route {target}`。放在 bridge 之前。
- node_id 和 route 目标必须严格复制大纲中列出的节点 ID，禁止修改或拼接后缀。
  大纲有 `ch2_confrontation` → 必须写 `node ch2_confrontation`，禁止 `ch2_confrontation_resolved`。

**禁止**
- bridge 之后出现非 narrative 区块。bridge 之前 options/state 使用非 `:main` 分支。
- narrative 正文中 `---` 单独成行。用保留字作 branch 名。
- 对话段用引号、代词作角色名（`你: ...`）、附加动作描写（`他笑了笑: ...` 应拆为旁白）。
- JSON/XML 替代区块标记。对玩家说话。引用不存在的变量或大纲节点。

# 质量要求

每段只做一件事。对话与旁白交替出现，避免连续 3 段以上纯描写。选项后果在叙事中铺垫。bridge 之后制造悬念。

# 故事

**背景：** 青春恋爱 · 2024年杭州，一所普通高中。夏天、天台、放学后的琴房
**主角：** 林小满，高三学生。内向、观察力强，暗恋隔壁班的钢琴特长生半年
**风格：** 温暖细腻
**冲突：** 距离毕业还剩一个月，决定在毕业前告白——但每一次接近，都发现她身上更多你不知道的事
**角色：** 苏音（钢琴特长生，看似高冷实则笨拙）、阿杰（死党，负责提供勇气和馊主意）

**大纲：**
ch1_rooftop [completed] — 天台偶遇：放学后第一次在天台说话
  → ch2_approach [active]
ch2_approach [active] — 靠近：找机会更多地出现在她的生活里
  ├→ ch3_confession [pending]
  └→ ch3_distance [pending]
ch3_confession [pending] — 告白：在毕业典礼前把话说出口
ch3_distance [pending] — 退缩：保持距离，把感情留在心里
ch4_graduation [pending] — 毕业：夏天的答案（结局）
[completed]=已完成 [active]=当前 [pending]=待推进

**进度：** 当前 ch2_approach — 寻找接近苏音的契机 | 已完成：ch1_rooftop

**重要事件：**
- ch1_rooftop：放学后在天台偶遇苏音，她正在弹一首没有名字的曲子。你们聊了一会，发现她并不像看起来那么难以接近。

**当前状态：**
好感度：30 / 100
勇气值：15 / 100
了解度：10 / 100
回忆：（无）
关系状态：普通朋友

当前节点目标：寻找接近苏音的契机

上一轮结尾：
夕阳把天台染成橙红色。苏音合上琴盖，转头看见你站在门口。
她愣了一下，然后轻轻地笑了笑。那个笑容让你心跳漏了一拍。
"你也是来看日落的？"她的声音很轻，像怕惊动什么。
```

- [ ] **步骤 2：Commit**

```bash
git add tests/data/prompts/romance.txt
git commit -m "feat: add romance genre prompt (倒数三次心跳)"
```

---

### 任务 2：创建悬疑题材 Prompt 文件

**文件：**
- 创建：`tests/data/prompts/mystery.txt`

- [ ] **步骤 1：编写 mystery.txt**

`tests/data/prompts/mystery.txt` — 固定部分（从 `你是文字冒险游戏的叙事引擎` 到 `bridge 之后制造悬念。`）与 romance.txt 完全相同。可变部分如下：

```
# 故事

**背景：** 心理悬疑 · 1998年冬，一座封闭的山区疗养院。大雪封山，唯一通道被切断。院内13名病人和4名医护人员——但登记册上只有12个病人的名字
**主角：** 方述，新来的心理医生。理性、善于观察，但对自己的判断力过于自信
**风格：** 冷静克制，暗藏不安
**冲突：** 你发现疗养院存在一个不存在于任何记录中的"第13个病人"。每次试图接近真相，现实与幻觉的边界就模糊一分
**角色：** 顾院长（疗养院负责人，态度温和得可疑）、7号病人（自称能看见"那个人"，但没人信她）

**大纲：**
ch1_arrival [completed] — 入院：暴风雪中抵达疗养院
  → ch2_investigate [active]
ch2_investigate [active] — 调查：翻阅病历，寻找第13人的蛛丝马迹
  ├→ ch3_underground [pending]
  └→ ch3_surface [pending]
ch3_underground [pending] — 深入：夜探地下室，触碰禁忌
ch3_surface [pending] — 迂回：从病人和护士口中侧面打听
ch4_reveal [pending] — 揭晓：第13级台阶通往何处（结局）
[completed]=已完成 [active]=当前 [pending]=待推进

**进度：** 当前 ch2_investigate — 调查第13个病人的存在证据 | 已完成：ch1_arrival

**重要事件：**
- ch1_arrival：暴风雪中抵达疗养院。顾院长热情接待，但你在签到簿上注意到一个被涂黑的姓名栏。当晚，走廊尽头传来不属于任何在册病人的脚步声。

**当前状态：**
理智值：85 / 100
调查进度：10 / 100
危险度：5 / 100
证据：（无）
被监视度：0 / 100
信任对象：无

当前节点目标：调查第13个病人的存在证据

上一轮结尾：
走廊的脚步声在凌晨三点准时响起。
你推开房门，走廊空无一人。但地板上的灰尘印着一串赤足的脚印——从走廊尽头一直延伸到你的门前，然后凭空消失。
走廊尽头的门上挂着一把生锈的铁锁。锁是冷的。
```

- [ ] **步骤 2：Commit**

```bash
git add tests/data/prompts/mystery.txt
git commit -m "feat: add mystery genre prompt (第十三级台阶)"
```

---

### 任务 3：创建古风武侠题材 Prompt 文件

**文件：**
- 创建：`tests/data/prompts/wuxia.txt`

- [ ] **步骤 1：编写 wuxia.txt**

`tests/data/prompts/wuxia.txt` — 固定部分（从 `你是文字冒险游戏的叙事引擎` 到 `bridge 之后制造悬念。`）与 romance.txt 完全相同。可变部分如下：

```
# 故事

**背景：** 古风武侠 · 南宋临安，江湖与庙堂的夹缝中，一座茶馆是情报交易的暗流中心
**主角：** 苏墨，退隐杀手，现茶馆老板。寡言、剑术绝世、有未了恩怨
**风格：** 诗意冷峻
**冲突：** 旧日仇家寻上门来，一枚十年前的信物打破了茶馆的平静
**角色：** 柳如烟（神秘女客，身世与当年的血案有关）、铁面（锦衣卫百户，查案查到茶馆门口）

**大纲：**
ch1_teahouse [completed] — 雨夜茶客：信物重现
  → ch2_confrontation [active]
ch2_confrontation [active] — 故人相见：面对旧日仇家
  ├→ ch3_revenge [pending]
  └→ ch3_redemption [pending]
ch3_revenge [pending] — 快意恩仇：血洗旧账
ch3_redemption [pending] — 放下屠刀：寻找第三条路
ch4_epilogue [pending] — 茶凉人散：江湖再无苏墨（结局）
[completed]=已完成 [active]=当前 [pending]=待推进

**进度：** 当前 ch2_confrontation — 面对手持信物的人 | 已完成：ch1_teahouse

**重要事件：**
- ch1_teahouse：雨夜，一个披着蓑衣的陌生人推开了茶馆的门。他从怀中取出一枚玉佩放在桌上——那是十年前你亲手埋在师父坟前的信物。

**当前状态：**
内力：60 / 100
江湖声望：30 / 100
恩怨值：80 / 100
线索：（无）
立场：中立

当前节点目标：面对手持信物的人

上一轮结尾：
雨打在茶馆的瓦檐上，噼啪作响。
那枚玉佩躺在木桌上，翠色依旧，却沾着泥——像是刚从土里刨出来的。
蓑衣人没有抬头，声音从斗笠下传来："十年了。师父的坟，你去看过吗？"
```

- [ ] **步骤 2：Commit**

```bash
git add tests/data/prompts/wuxia.txt
git commit -m "feat: add wuxia genre prompt (茶馆)"
```

---

### 任务 4：运行恋爱题材测试

**文件：**
- 自动创建：`tests/data/output/romance/prompt-test-01.md` 等

- [ ] **步骤 1：运行 3 轮测试**

```bash
python3 tests/run_prompt_test.py --prompt tests/data/prompts/romance.txt --runs 3
```

预期：3/3 成功完成（无 ERROR），输出到 `tests/data/output/romance/`

- [ ] **步骤 2：分析结果**

```bash
python3 tests/analyze_results.py --prompt tests/data/prompts/romance.txt --output-dir tests/data/output/romance/
```

记录：正确性 X/3，无缝性 X/3

---

### 任务 5：运行悬疑题材测试

**文件：**
- 自动创建：`tests/data/output/mystery/prompt-test-01.md` 等

- [ ] **步骤 1：运行 3 轮测试**

```bash
python3 tests/run_prompt_test.py --prompt tests/data/prompts/mystery.txt --runs 3
```

预期：3/3 成功完成，输出到 `tests/data/output/mystery/`

- [ ] **步骤 2：分析结果**

```bash
python3 tests/analyze_results.py --prompt tests/data/prompts/mystery.txt --output-dir tests/data/output/mystery/
```

记录：正确性 X/3，无缝性 X/3

---

### 任务 6：运行古风武侠题材测试

**文件：**
- 自动创建：`tests/data/output/wuxia/prompt-test-01.md` 等

- [ ] **步骤 1：运行 3 轮测试**

```bash
python3 tests/run_prompt_test.py --prompt tests/data/prompts/wuxia.txt --runs 3
```

预期：3/3 成功完成，输出到 `tests/data/output/wuxia/`

- [ ] **步骤 2：分析结果**

```bash
python3 tests/analyze_results.py --prompt tests/data/prompts/wuxia.txt --output-dir tests/data/output/wuxia/
```

记录：正确性 X/3，无缝性 X/3

---

### 任务 7：汇总对比分析

- [ ] **步骤 1：汇总四个场景结果**

运行全部分析并对比：

```bash
echo "=== 赛博朋克（基准）===" && \
python3 tests/analyze_results.py --prompt tests/data/prompts/v4.txt --output-dir tests/data/output/v4/ && \
echo "" && \
echo "=== 恋爱 ===" && \
python3 tests/analyze_results.py --prompt tests/data/prompts/romance.txt --output-dir tests/data/output/romance/ && \
echo "" && \
echo "=== 悬疑 ===" && \
python3 tests/analyze_results.py --prompt tests/data/prompts/mystery.txt --output-dir tests/data/output/mystery/ && \
echo "" && \
echo "=== 古风武侠 ===" && \
python3 tests/analyze_results.py --prompt tests/data/prompts/wuxia.txt --output-dir tests/data/output/wuxia/
```

- [ ] **步骤 2：记录结论**

汇总为表格：

| 场景 | 正确性 | 无缝性 | FirstSegment avg | 主要问题 |
|------|--------|--------|------------------|---------|
| 赛博朋克 | 2/3 | 3/3 | 13.1s | segs 超标 1 次 |
| 恋爱 | ?/3 | ?/3 | ? | — |
| 悬疑 | ?/3 | ?/3 | ? | — |
| 古风武侠 | ?/3 | ?/3 | ? | — |

- [ ] **步骤 3：如果某个场景正确性 ≤ 1/3，分析根因**

检查该场景的输出文件，定位共性失败模式。如果是 Prompt 固定规则的问题，记录到迭代日志。

---

## 自检

**1. 规格覆盖度：**
- 3 个新 Prompt 文件 ✓（任务 1-3）
- 每个场景 3 轮测试 ✓（任务 4-6）
- 与 v4 基准对比 ✓（任务 7）
- 不影响现有文件 ✓（仅创建新文件）

**2. 占位符扫描：** 无 TODO、无待定、无"补充细节"。所有步骤有具体代码/命令。✓

**3. 类型一致性：** 无跨任务类型依赖。每个 Prompt 文件独立。✓
