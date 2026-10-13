# live — 微信实时参谋（macOS）

在导出器的密钥缓存 / 分片定位 / 消息解析之上，做实时监听与本地模型回复建议。内容只走本机与你自己配置的模型端点（`LOCAL_LLM_ENDPOINTS` 或根目录 `llm_endpoints.json`，见 `core/llm_endpoints.py`），不自动发送任何消息。

- `live.py`：监听进程。SQLCipher 只读打开微信正在写的库，按 local_id 增量拉新消息；对方来消息 → debounce → 本地模型给出情绪判断与候选回复；页面 `127.0.0.1:8765`，支持搜索切换联系人（按最近聊天排序）、群聊只在 @我 / 引用我时触发、建议与实际回复配对记录、可切换参谋风格。
- `dock.py`：悬浮面板，跟随微信窗口贴在右侧，可折叠，折叠时有新建议会闪红点。
- `styles/`：参谋风格指令。`*.md` 为本地模型压缩后的风格指令，`distill.py` 为压缩脚本；第三方 skill 原文（`*.source.md`）不入库，自行从其 GitHub 仓取回后用 `distill.py` 压缩。
- 运行时数据全部在仓库外 `~/.wechat_live/`：`state.json`、`<wxid>.jsonl` 消息日志、`<wxid>_feedback.jsonl` 对照记录、`memory/<wxid>.md` 长期记忆、`last_contact` / `last_style`。

```bash
cd live
../.venv/bin/python -u live.py            # 监听（首次加 --contact <wxid|备注>）
../.venv/bin/python -u dock.py --always   # 悬浮窗
```

`../analysis/` 是离线分析流水线（导出 txt → 统计 + 分块 → 本地模型 map/reduce → 关系报告 / 人格画像 / 心理学分析 / 回复守则），产物放在 `~/.wechat_live/analysis/`。
