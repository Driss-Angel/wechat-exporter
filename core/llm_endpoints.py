"""Local OpenAI-compatible model endpoints for `live/` and `analysis/`.

Nothing is hard-coded here. Configure the endpoints you own (vLLM, Ollama,
LM Studio, ...) in one of two ways; the first reachable one is used:

1. Environment variable, several entries separated by ``;``::

       export LOCAL_LLM_ENDPOINTS="http://10.0.0.5:8001|Qwen3-27B;http://127.0.0.1:11434|qwen3:32b"

2. A JSON file ``llm_endpoints.json`` in the repository root (git-ignored)::

       [{"url": "http://10.0.0.5:8001", "model": "Qwen3-27B"},
        {"url": "http://127.0.0.1:11434", "model": "qwen3:32b"}]

See ``llm_endpoints.example.json``. Chat traffic goes only to the hosts listed
here, so keep them on your own LAN if the content must not leave it.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request
from typing import List, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_FILE = os.path.join(ROOT, "llm_endpoints.json")
ENV_VAR = "LOCAL_LLM_ENDPOINTS"

HELP = (
    "未配置本地模型端点。两种方式任选其一：\n"
    "  1) 环境变量  export %s=\"http://主机:端口|模型名;http://主机2:端口|模型名\"\n"
    "  2) 配置文件  %s（参考 llm_endpoints.example.json）\n"
    "端点需兼容 OpenAI 接口（vLLM / Ollama / LM Studio 均可）。" % (ENV_VAR, CONFIG_FILE)
)


def load_endpoints() -> List[Tuple[str, str]]:
    """Configured ``(url, model)`` pairs, env first, then the JSON file."""
    out: List[Tuple[str, str]] = []
    raw = os.environ.get(ENV_VAR, "").strip()
    if raw:
        for item in raw.split(";"):
            item = item.strip()
            if not item:
                continue
            url, _, model = item.partition("|")
            if url and model:
                out.append((url.rstrip("/"), model.strip()))
    if not out and os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError) as exc:
            sys.exit("读取 %s 失败：%s" % (CONFIG_FILE, exc))
        for entry in data if isinstance(data, list) else []:
            url, model = (entry.get("url") or "").strip(), (entry.get("model") or "").strip()
            if url and model:
                out.append((url.rstrip("/"), model))
    return out


def pick_endpoint(timeout: float = 3.0) -> Tuple[str, str]:
    """First configured endpoint whose ``/v1/models`` answers; exits with help otherwise."""
    endpoints = load_endpoints()
    if not endpoints:
        sys.exit(HELP)
    for url, model in endpoints:
        try:
            urllib.request.urlopen(url + "/v1/models", timeout=timeout)
            return url, model
        except Exception:
            continue
    sys.exit("本地模型端点都不通：%s" % ", ".join(u for u, _ in endpoints))
