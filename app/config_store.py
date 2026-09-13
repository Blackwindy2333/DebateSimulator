import json
from copy import deepcopy
from pathlib import Path

CONFIG_PATH = Path("config") / "config.json"

DEFAULT_CONFIG = {
    "apis": {
        "pro": {"nickname": "正方", "api_key": "", "base_url": "https://api.openai.com/v1",
                "model": "", "temperature": 0.8,
                "thinking_enabled": True, "reasoning_effort": "high"},
        "con": {"nickname": "反方", "api_key": "", "base_url": "https://api.openai.com/v1",
                "model": "", "temperature": 0.8,
                "thinking_enabled": True, "reasoning_effort": "high"},
        "judge": {"nickname": "裁判", "api_key": "", "base_url": "https://api.openai.com/v1",
                  "model": "", "temperature": 0.3,
                  "thinking_enabled": True, "reasoning_effort": "high"},
    },
    "debate": {"topic": "", "rounds": 7, "personas": {"pro": "", "con": ""}},
    "runtime": {"max_retries": 3, "timeout_seconds": 120, "port": 8000, "auto_open_browser": True},
    "ui": {"theme": "light", "sound": True},
}

REASONING_EFFORTS = ("low", "high", "max")


def merge_defaults(cfg):
    out = deepcopy(DEFAULT_CONFIG)
    for key, value in (cfg or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            for sub, subvalue in value.items():
                if isinstance(subvalue, dict) and isinstance(out[key].get(sub), dict):
                    out[key][sub].update(subvalue)
                else:
                    out[key][sub] = subvalue
        else:
            out[key] = value
    return out


def load_config():
    """启动时读取配置。

    文件不存在 → 按默认值生成一份；已存在 → 直接读取（缺失字段在内存中补齐，
    但**不改写磁盘**），避免每次启动都覆盖用户的文件。

    `config/config.json` 已列入 .gitignore，不纳入版本控制。
    """
    if CONFIG_PATH.exists():
        return merge_defaults(json.loads(CONFIG_PATH.read_text("utf-8")))
    fresh = merge_defaults({})
    save_config(fresh)
    return fresh


def save_config(cfg):
    merged = merge_defaults(cfg)
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(merged, ensure_ascii=False, indent=2), "utf-8")
