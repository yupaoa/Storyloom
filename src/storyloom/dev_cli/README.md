# dev_cli

极简 CLI 游戏界面 + 开发者检查工具。删除此目录即可从发布版本移除。

## 快速开始

```bash
python -m storyloom.dev_cli
```

默认进入开发者模式，进行共创 Q&A 后开始游戏，原始数据写入 `dev_output/`。

## 参数

```
--mode dev|normal    默认 dev（记录原始数据）
--story FILE         JSON 故事配置，跳过共创
--no-save            禁用自动存档
--lang zh-CN|en      默认 zh-CN
```

## 示例

```bash
# 纯游戏模式，跳过共创
python -m storyloom.dev_cli --mode normal --story tests/data/test_story.json

# 开发者模式，不存档
python -m storyloom.dev_cli --no-save
```

## 游戏操作

- 输入数字选择分支
- 输入 `q` 退出
- `Ctrl+C` 退出

## 开发者模式输出

`dev_output/` 目录（已 gitignore）：

| 文件 | 内容 |
|------|------|
| `prompts.txt` | 每轮发送给 LLM 的完整 prompt |
| `responses.txt` | LLM 返回的原始文本（含 ttft / token 统计） |
| `checks.txt` | 解析摘要（segments、bridge、checkpoint、sets、choices） |

所有文件追加写入，跨游戏会话不覆盖。自行清理。

## 故事配置文件格式

```json
{
    "story_config": {
        "genre": "...",
        "tier": "short|medium|long",
        "label": "标题",
        "setting": "...",
        "protagonist_name": "...",
        "protagonist_identity": "...",
        "protagonist_traits": "...",
        "tone": "...",
        "conflict": "...",
        "characters": "...",
        "variables": [...]
    },
    "outline_text": "ch1 [active] — ...\n  → ch2 [pending]\n...",
    "outline_nodes": [
        {"id": "ch1", "status": "active", "goal": "..."}
    ]
}
```
