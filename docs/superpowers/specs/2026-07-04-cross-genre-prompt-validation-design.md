# Cross-Genre Prompt Validation Design

> 验证 v4 Prompt 模板在四种不同题材下的泛化能力。

## 目标

当前 v4 Prompt 模板仅在**赛博朋克**场景下测试过（2/3 正确，3/3 无缝）。需要验证同一套规则模板在其他题材下是否同样有效。

## 策略

快速验证（方案 A）：3 个新题材 × 每场景 3 轮测试。关注两个核心指标：
- **正确性**：choice 声明、分支命名、node 引用、编号起始
- **无缝性**：FirstSegment ≤ tail_time

## 测试场景

### 场景 1：恋爱 — "倒数三次心跳"

| 维度 | 内容 |
|------|------|
| 题材 | 青春恋爱 |
| 世界观 | 2024年杭州，一所普通高中 |
| 主角 | 林小满，高三学生。内向、观察力强 |
| 风格 | 温暖细腻 |
| 冲突 | 距离毕业还剩一个月，决定在毕业前告白 |
| 角色 | 苏音（钢琴特长生）、阿杰（死党） |
| 对话密度 | 极高 |
| 描写主导 | 心理/情感 |
| 交互核心 | 情感选择 |

**大纲（5 节点）：**
```
ch1_rooftop [completed] — 天台偶遇
ch2_approach [active] — 靠近
  ├→ ch3_confession [pending]
  └→ ch3_distance [pending]
ch3_confession [pending] — 告白
ch3_distance [pending] — 退缩
ch4_graduation [pending] — 毕业（结局）
```

**状态变量：** 好感度:30, 勇气值:15, 了解度:10, 回忆:[], 关系状态:"普通朋友"

### 场景 2：悬疑 — "第十三级台阶"

| 维度 | 内容 |
|------|------|
| 题材 | 心理悬疑 |
| 世界观 | 1998年冬，封闭山区疗养院，大雪封山 |
| 主角 | 方述，新来的心理医生。理性、善于观察 |
| 风格 | 冷静克制，暗藏不安 |
| 冲突 | 疗养院存在一个不存在于任何记录中的"第13个病人" |
| 角色 | 顾院长（可疑的负责人）、7号病人（唯一目击者） |
| 对话密度 | 中 |
| 描写主导 | 氛围/环境 |
| 交互核心 | 推理选择 |

**大纲（5 节点）：**
```
ch1_arrival [completed] — 入院
ch2_investigate [active] — 调查
  ├→ ch3_underground [pending]
  └→ ch3_surface [pending]
ch3_underground [pending] — 深入地下室
ch3_surface [pending] — 迂回打听
ch4_reveal [pending] — 揭晓（结局）
```

**状态变量：** 理智值:85, 调查进度:10, 危险度:5, 证据:[], 被监视度:0, 信任对象:"无"

### 场景 3：古风武侠 — "茶馆"

| 维度 | 内容 |
|------|------|
| 题材 | 古风武侠 |
| 世界观 | 南宋临安，江湖情报暗流中心 |
| 主角 | 苏墨，退隐杀手，现茶馆老板。寡言、剑术绝世 |
| 风格 | 诗意冷峻 |
| 冲突 | 十年前的信物打破茶馆平静，旧日仇家寻上门 |
| 角色 | 柳如烟（神秘女客）、铁面（锦衣卫百户） |
| 对话密度 | 中 |
| 描写主导 | 意境/动作 |
| 交互核心 | 道义选择 |

**大纲（5 节点）：**
```
ch1_teahouse [completed] — 雨夜茶客
ch2_confrontation [active] — 故人相见
  ├→ ch3_revenge [pending]
  └→ ch3_redemption [pending]
ch3_revenge [pending] — 快意恩仇
ch3_redemption [pending] — 放下屠刀
ch4_epilogue [pending] — 茶凉人散（结局）
```

**状态变量：** 内力:60, 江湖声望:30, 恩怨值:80, 线索:[], 立场:"中立"

## 四题材对比

| 维度 | 赛博朋克（已有） | 恋爱 | 悬疑 | 古风武侠 |
|------|:--:|:--:|:--:|:--:|
| 题材 | 科幻动作 | 青春恋爱 | 心理悬疑 | 古风武侠 |
| 对话密度 | 中 | 极高 | 中 | 中 |
| 描写主导 | 科技感 | 心理/情感 | 氛围/环境 | 意境/动作 |
| 叙事节奏 | 快 | 慢（铺垫型） | 中（悬念型） | 中（张力型） |
| 交互核心 | 行动选择 | 情感选择 | 推理选择 | 道义选择 |

## Prompt 文件结构

每个场景的 Prompt 文件分为两部分：

1. **固定部分**（与 v4.txt 完全一致）：格式示例 + 核心规则 + 质量要求 + 禁止项
2. **可变部分**（场景特定）：故事背景、主角、风格、冲突、角色、大纲、进度、重要事件、当前状态、当前节点目标、上一轮结尾

## 测试流程

```bash
# 1. 运行测试（每个场景 3 轮，streaming sequential）
python3 tests/run_prompt_test.py --prompt tests/data/prompts/romance.txt --runs 3
python3 tests/run_prompt_test.py --prompt tests/data/prompts/mystery.txt --runs 3
python3 tests/run_prompt_test.py --prompt tests/data/prompts/wuxia.txt --runs 3

# 2. 分析结果
python3 tests/analyze_results.py --prompt tests/data/prompts/romance.txt --output-dir tests/data/output/romance/
python3 tests/analyze_results.py --prompt tests/data/prompts/mystery.txt --output-dir tests/data/output/mystery/
python3 tests/analyze_results.py --prompt tests/data/prompts/wuxia.txt --output-dir tests/data/output/wuxia/

# 3. 与 v4 基准对比
python3 tests/analyze_results.py --prompt tests/data/prompts/v4.txt --output-dir tests/data/output/v4/
```

## 成功标准

- 每个场景的正确性 ≥ 2/3（与 v4 基准持平或更好）
- 每个场景的无缝性 ≥ 2/3
- 如果某个场景出现系统性失败（如 0/3 正确），定位根因并记录是否需要调整 Prompt 模板

## 预期风险

| 风险 | 场景 | 缓解 |
|------|------|------|
| 恋爱场景对话占比过高导致段数超标 | romance | 规则中已有段数上限，观察 LLM 是否遵守 |
| 悬疑场景 bridge 打断悬念节奏 | mystery | 观察无缝性指标，bridge 位置是否合理 |
| 古风场景 LLM 对话中出现文言化倾向 | wuxia | 观察对话段格式是否仍符合规范 |
