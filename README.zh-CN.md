# Storyloom

> AI 驱动的互动文字小说引擎 —— LLM 叙事，引擎编排。
>
> [English Version](./README.md)

Storyloom 将大语言模型变成游戏主持人。你与 AI 协作构建故事世界、定义角色和游戏机制，然后展开分支叙事——你的每个选择都会影响结局。引擎负责状态管理、上下文窗口维护和实时流式处理，LLM 专注于讲好故事。

**当前状态（2026-07-17）：** Phase 1 核心引擎已完成，可通过开发 CLI 游玩，Web 界面规划中。

## 亮点

- **无缝叙事** — 桥接预取机制在当前段落播放期间触发下一次 API 调用，将 LLM 延迟隐藏在文本展示背后。段落之间不会出现"等待响应"的停顿。
- **本地数据源** — 所有游戏状态驻留在引擎中。LLM 只能*建议*修改；引擎在应用前进行验证（类型检查、范围检查）。被拒绝的建议会反馈给 LLM 作为纠正。
- **双层分支** — 段落内叙事分支（场景内玩家选择）和剧情级路线分叉（检查点处的故事方向改变）。前者可逆，后者不可逆。
- **对话式上下文** — 最近轮次的滑动窗口 + 永久 Round 1 锚定 + 检查点压缩。在约 50K token 内维持长篇游戏的连贯性。
- **流式 XML 输出** — LLM 在 `<story>` 文档中输出 `<seg>`、`<choice>`、`<bridge/>`、`<set>`、`<checkpoint>` 等元素。逐行解析——不缓冲，不等待完整响应。
- **共创流程** — 不止于"选个题材"。AI 会就你的故事创意进行访谈，然后生成量身定制的世界观、主角、游戏变量和剧情大纲。

## 快速开始

```bash
# 安装
pip install -e .

# 配置 — 编辑 config.json 填入你的 API 凭据
# （首次运行自动创建，也可手动创建）
cat > config.json << 'EOF'
{
  "api_key": "sk-your-key-here",
  "api_base_url": "https://api.deepseek.com",
  "api_model": "deepseek-v4-pro",
  "language": "zh-CN"
}
EOF

# 游玩
python -m storyloom.dev_cli
```

任何 OpenAI 兼容的 API 均可使用——DeepSeek、OpenAI、本地 llama.cpp 等。调整 `api_base_url` 和 `api_model` 以匹配你的服务商。

CLI 控制方式及观察者模式详见 [`src/storyloom/dev_cli/README.md`](./src/storyloom/dev_cli/README.md)。

## 架构

Storyloom 是一个**单 Python 应用**——不是客户端-服务器系统。核心引擎与 UI 无关，通过生成器事件流暴露接口，任何表现层通过 `GameSession` 消费。

```
┌─────────────────────────────────────────────────┐
│              Storyloom 核心引擎                  │
│  ┌──────────┐  ┌───────────┐  ┌──────────────┐  │
│  │GameLoop  │  │ContextMgr │  │StreamXmlPrs  │  │
│  └──────────┘  └───────────┘  └──────────────┘  │
│  ┌──────────┐  ┌───────────┐  ┌──────────────┐  │
│  │PromptBldr│  │CoCreate   │  │SaveManager   │  │
│  └──────────┘  └───────────┘  └──────────────┘  │
└─────────────────────┬───────────────────────────┘
                      │ GameSession（公开 API）
              ┌───────┴────────┐
              ▼                ▼
       ┌──────────┐    ┌──────────────┐
       │ Dev CLI  │    │  Web UI      │
       │ (当前)   │    │  (规划中)    │
       └──────────┘    └──────────────┘
```

### 单轮工作流程

```
玩家阅读文字 ──→ 做出选择 ──→ 引擎发送 prompt ──→ LLM 流式输出 XML
                                                           │
                    ┌──────────────────────────────────────┘
                    ▼
            StreamingXmlParser（逐行解析）
                    │
       ┌────────────┼────────────┬────────────┐
       ▼            ▼            ▼            ▼
    <seg>        <choice>    <bridge/>     <set>
    展示叙事     呈现选项    发起下一次    验证并应用
    文字                     API 调用      状态变更
```

`<bridge/>` 元素在当前段落剩余文字仍在展示时即触发下一次 API 请求——玩家感知到的是连续叙事，没有段落边界停顿。

## 模块地图

| 模块 | 用途 |
|--------|---------|
| `storyloom.core.game_loop` | 叙事循环、轮次编排、结局检测、状态验证 |
| `storyloom.core.context_manager` | 消息数组、滑动窗口、检查点压缩 |
| `storyloom.core.prompt_builder` | Round 1 / Round N prompt 组装 |
| `storyloom.core.co_create` | 共创流程（Q&A → 故事配置 → 大纲） |
| `storyloom.core.save_manager` | 按游戏目录原子化 JSON 存档/读档/删除/列表 |
| `storyloom.core.session` | `GameSession` 生命周期编排器——UI 集成 API |
| `storyloom.parser.streaming_parser` | LLM 输出的逐行 XML 解析器 |
| `storyloom.io.api_client` | OpenAI 兼容的流式/非流式 API 客户端 |
| `storyloom.i18n` | gettext 国际化（zh-CN, en） |
| `storyloom.user_config` | 通过 `config.json` 集中管理配置（API key、语言、模型） |
| `storyloom.dev_cli` | 终端界面——游玩模式 + 开发者观察者 |

## 文档

| 文档 | 内容 |
|----------|------|
| [`docs/spec/exec-flow.md`](./docs/spec/exec-flow.md) | Phase 1 执行管线 — **权威规范** |
| [`docs/spec/block-spec.md`](./docs/spec/block-spec.md) | XML 元素语法、分支路由、状态验证 |
| [`docs/spec/prompt-design.md`](./docs/spec/prompt-design.md) | Prompt 模板与对话架构 |
| [`docs/spec/data-model.md`](./docs/spec/data-model.md) | GameState、存档系统、配置常量 |
| [`docs/engineering-journal.md`](./docs/engineering-journal.md) | 设计决策日志（2026-07-02 → 至今） |
| [`docs/README.md`](./docs/README.md) | 完整文档索引 |

## 开发

```bash
# 运行测试（mock 模式——无需 API key）
pytest --ignore=tests/test_api_client.py

# 运行全部测试（含 API 测试）
pytest

# 运行单个测试文件
pytest tests/test_game_loop.py -v
```

**技术栈：** Python 3.10+（优先标准库）、OpenAI 兼容 API、本地 JSON 存储、gettext 国际化。

**规范：** Conventional Commits、英文代码注释与 git 提交信息、中文 prompt 变量。

### UI 集成 API

UI 开发者通过 `GameSession` 与引擎交互：

```python
from storyloom.core import GameSession

session = GameSession()

# 共创
flow = session.new_co_create()
event = flow.start()                     # → {phase: "awaiting_idea"}
event = flow.send("一个赛博朋克故事")      # → {phase: "awaiting_answer"}
# ... 继续问答直到 phase == "complete"
gl = session.start_game(event["result"]) # → GameLoop

# 叙事循环
for event in gl.start_round1_stream():
    ...  # 处理 token / segment / options / state / error / done 事件

gl.continue_round_stream(choice_key="1")

# 存档 & 读档
gl.request_save("劫案前夕")
gl = session.load_game("劫案前夕")
```

## 路线图

- [x] Phase 1 核心引擎 —— 游戏循环、共创、存档、结局检测、国际化
- [x] 桥接预取——实现无缝叙事
- [x] 对话式上下文——滑动窗口 + 压缩
- [x] 流式 XML 解析器——逐行输出
- [x] UserConfig——集中配置管理
- [ ] Web UI（FastAPI + SSE）
- [ ] Phase 2 —— 多章节支持、物品系统、战斗机制
- [ ] Phase 3 —— 多人/合作模式

## 许可证

MIT
