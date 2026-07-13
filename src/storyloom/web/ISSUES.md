# Web 前端问题清单

> 2026-07-13 | 来自实际运行反馈 + 调试过程

---

## Issue #1: 缺少展示速度控制

**状态**：✅ 已修复

**现象**：引擎输出事件速度远快于人眼阅读速度，段落瞬间全部显示，看不清内容。

**修复**：
- `setTimeout` 链式展示队列（Normal 800ms / Fast 300ms / Slow 2000ms / Instant / Manual）
- 速度预设放在主菜单，开始游戏后固定不变（**不做热切换**，见 Issue #12）

---

## Issue #2: 语言切换下拉菜单无效

**状态**：✅ 已修复

**修复**：删除菜单页语言 `<select>`，保留 JS `T` 字典和 `t()` 函数供按钮文本使用。

---

## Issue #3: variables[].initial 类型在 JSON 往返中可能丢失

**状态**：✅ 已修复

**修复**：`server.py:game_new()` 中遍历 variables，显式修复 number→int、list→list。

---

## Issue #4: generate() 后没有输入框

**状态**：✅ 已修复

**修复**：生成成功后展示过渡面板（故事名 + 题材 + 节点数），大按钮"▶ 开始冒险"。

---

## Issue #5: 原始 XML 泄露 + 文字堆叠

**状态**：✅ 已修复

**根因**：`token` handler 直接把 LLM 原始输出（含 XML 标签）追加到 DOM。

**修复**：token handler 改为空函数；CSS 加 `white-space: pre-line` + `margin-bottom` + `line-height: 1.8`。

---

## Issue #6: 进入游戏视图后无反馈

**状态**：✅ 已修复

**修复**：游戏视图加载时显示 `⏳ 等待 LLM 回复...`，第一个 segment 到达时自动清除。

---

## Issue #7: 故事文字竖排——每行只有一个字符

**状态**：✅ 已修复

**根因**：`.game-view` 用 `flex-direction: row`，toolbar + main + sidebar 并列，`.game-main` 的 `min-width: 0` 使其塌缩成一字符宽。

**修复**：`.game-view` → `flex-direction: column`；新增 `.game-body` 包裹层。

---

## Issue #8: 选项面板不显示——`.every()` 崩溃

**状态**：✅ 已修复

**根因**：引擎的 `conditions` 字段是 `dict[str, str|null]`（key 为 branch 名），DESIGN.md 错误记录为 `list[str|null]`。前端 `showChoices()` 对其调用 `.every()` 导致 TypeError 崩溃。

**修复**：`display.js:showChoices()` 改为从 `conds[branch]` 取值；DESIGN.md 更正文档。

---

## Issue #9: CoCreateParser 不接受 Markdown 代码围栏

**状态**：✅ 已修复（引擎侧）

**现象**：LLM 输出 `=== variables ===` 区块时包裹 Markdown 围栏 ` ``` `，`CoCreateParser.parse_variables()` 无法解析。三次测试三次必现。

**修复**：`co_create.py:split_blocks()` 添加 `_FENCE_RE`，跳过 ` ``` ` 行。

---

## Issue #10: CoCreateParser 不接受 `|` 分隔符

**状态**：✅ 已修复（引擎侧）

**现象**：LLM 输出 `好感度 | number | 30`（用 `|` 分隔），parser 只接受 `好感度: number, 30`（用 `:` 和 `,` 分隔）。

**修复**：`co_create.py:parse_variables()` 增加 `VAR_LINE_RE_PIPE` 正则兼容 `|` 格式。

---

## Issue #11: SSE `close()` 导致 connect Promise 永不 resolve

**状态**：✅ 已修复

**根因**：`sse-client.js:close()` 先设 `_es = null`，然后 `onerror` 触发时检查 `this._es` 已是 null，Promise 永不 resolve。外层 `runGameLoop` await 挂死。

**修复**：`close()` 手动调用 `_resolve("closed")`；添加 `_resolve` 存储。

---

## Issue #12: Manual 模式热切换有 bug

**状态**：✅ 已修复（改为全局预设，不做热切换）

**现象**：Manual → Fast 切换时所有积压段落瞬间全部蹦出；Manual 模式切换到一半，新增段落仍在自动显示。

**根因**：热切换时 `_segTimer` / `_manualWaiting` 状态交织，`_enqueue` 在 Manual 模式下因 `_segTimer === null` 不断触发 `_processNext()`。多次修复后仍有边界情况。

**决定**：放弃热切换。速度改为全局预设——在菜单页选择，游戏内固定不变。复杂度不值得。

---

## Issue #13: 选项交互只有按钮，缺少键盘快捷键和自定义输入

**状态**：✅ 已修复

**修复**：
- 选项按钮支持键盘数字键 1-5 快捷选择
- Q 键退出到主菜单
- 选项面板底部添加"或输入自定义操作..."文本框（Enter 确认，走第一个选项分支）
