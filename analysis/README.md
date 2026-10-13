# analysis — 导出记录的离线关系分析（本地模型）

把导出器产出的 TXT 喂给你自己的本地模型，两段式生成：关系变化分析 `report.md`、人格画像 `persona.md`、心理学视角 `psych.md`、回复守则 `rules.md`，以及统计摘要 `stats.md`。聊天正文只发往你配置的端点。

```bash
# 1) 解析 TXT：统计 + 按消息数切块（导出的时间戳为本机时区，默认 +12h 换成北京时间，可用 --tz-shift-hours 0 关闭）
python3 -I analysis/prepare.py <导出.txt> <输出目录> [--tz-shift-hours 12] [--chunk-msgs 450]
# 2) 本地模型：map（每块一份结构化笔记）→ reduce（关系报告）→ persona → psych → rules；可中断重跑
python3 -I analysis/run_local.py map <输出目录> --workers 4
python3 -I analysis/run_local.py reduce <输出目录>
python3 -I analysis/run_local.py persona <输出目录>
python3 -I analysis/run_local.py psych <输出目录>
python3 -I analysis/run_local.py rules <输出目录>
```

模型端点通过 `LOCAL_LLM_ENDPOINTS` 环境变量或仓库根目录的 `llm_endpoints.json` 配置，见 `core/llm_endpoints.py` 与 `llm_endpoints.example.json`。输出目录含敏感明文，请放在仓库之外。
