"""双日志系统。

每次应用启动开启一个日志会话，生成两份文件：

- ``Logs/Operations_<时间>.log``   记录一切发生的操作与更改（配置保存、辩论阶段推进、
  控制指令、警告、错误、结果落盘等），供事后复盘。
- ``Logs/ApiRequests_<时间>.log``  记录每一次 API 请求的**完整**请求体
  （model / messages / thinking / reasoning_effort / stream / temperature）。

两者均为逐行追加的纯文本，便于直接查看与 grep。
"""
import json
from datetime import datetime
from pathlib import Path

LOGS_DIR = Path("Logs")

_operations_path = None
_api_requests_path = None


def _stamp():
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def start_session():
    """开启新的日志会话，创建两份日志文件。应用启动时调用一次。"""
    global _operations_path, _api_requests_path
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = _stamp()
    _operations_path = LOGS_DIR / f"Operations_{stamp}.log"
    _api_requests_path = LOGS_DIR / f"ApiRequests_{stamp}.log"
    _operations_path.write_text("", "utf-8")
    _api_requests_path.write_text("", "utf-8")
    operation("session.start", f"日志会话开始 -> {_operations_path.name} / {_api_requests_path.name}")
    return paths()


def _ensure():
    if _operations_path is None:
        start_session()


def operation(action, detail=""):
    """记录一次操作或变更。"""
    _ensure()
    line = f"[{_now()}] {action}"
    if detail:
        line += f" | {detail}"
    with _operations_path.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def api_request(nickname, url, payload, label=""):
    """记录一次 API 请求的完整请求体。"""
    _ensure()
    header = f"[{_now()}] {label or 'request'} | nickname={nickname} | POST {url}"
    body = json.dumps(payload, ensure_ascii=False, indent=2)
    with _api_requests_path.open("a", encoding="utf-8") as handle:
        handle.write(f"{header}\n{body}\n{'-' * 78}\n")


def paths():
    return {
        "operations": str(_operations_path) if _operations_path else None,
        "api_requests": str(_api_requests_path) if _api_requests_path else None,
    }
