"""端口占用探测：启动前预检绑定，失败时给出可读诊断。"""

from __future__ import annotations

import socket
import subprocess
from dataclasses import dataclass

# Windows 扩展错误码（socket 暴露为 errno 旁路 winerror）
WSAEACCES = 10013
WSAEADDRINUSE = 10048


@dataclass(frozen=True)
class Listener:
    pid: int
    local: str


def try_bind(host: str, port: int) -> OSError | None:
    """尝试绑定 TCP 端口。成功返回 None，失败返回 OSError。

    故意不设 SO_REUSEADDR：Windows 上它会掩盖占用，导致误判为空闲。
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind((host, port))
        return None
    except OSError as exc:
        return exc
    finally:
        sock.close()


def find_free_port(host: str, preferred: int, span: int = 20) -> int | None:
    """从 preferred 起向后找 span 个端口，返回第一个可绑定的；找不到返回 None。"""
    if span < 1:
        return None
    for port in range(preferred, preferred + span):
        if 1 <= port <= 65535 and try_bind(host, port) is None:
            return port
    return None


def listeners(port: int) -> list[Listener]:
    """列出正在 LISTEN 指定 TCP 端口的进程（解析 netstat -ano）。"""
    try:
        raw = subprocess.check_output(
            ["netstat", "-ano"],
            text=True,
            errors="replace",
            timeout=5,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        return []

    needle = f":{int(port)} "
    found: list[Listener] = []
    seen: set[tuple[int, str]] = set()
    for line in raw.splitlines():
        if "LISTENING" not in line.upper():
            continue
        if needle not in line:
            continue
        parts = line.split()
        if len(parts) < 5:
            continue
        local, pid_s = parts[1], parts[-1]
        try:
            pid = int(pid_s)
        except ValueError:
            continue
        key = (pid, local)
        if key in seen:
            continue
        seen.add(key)
        found.append(Listener(pid=pid, local=local))
    return found


def process_name(pid: int) -> str:
    """读取进程名；失败返回空串。"""
    try:
        raw = subprocess.check_output(
            ["tasklist", "/FI", f"PID eq {int(pid)}", "/FO", "CSV", "/NH"],
            text=True,
            errors="replace",
            timeout=5,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.upper().startswith("INFO"):
            continue
        if line.startswith('"'):
            name = line.split('","', 1)[0].strip('"')
            return name
    return ""


def describe_bind_error(err: OSError, host: str, port: int) -> str:
    """把 bind 失败翻译成中文诊断，并附上占用进程。"""
    winerror = getattr(err, "winerror", None) or err.errno
    if winerror == WSAEACCES:
        why = (
            f"端口 {port} 绑定被系统拒绝（WinError 10013，访问权限不允许）。"
            "常见原因：其他程序以独占方式占用了该端口，或端口落在系统排除范围内。"
        )
    elif winerror == WSAEADDRINUSE:
        why = f"端口 {port} 已被占用（WinError 10048）。"
    else:
        why = f"无法绑定 {host}:{port}（{err}）。"

    holders = listeners(port)
    if holders:
        lines = [f"  - PID {h.pid} {process_name(h.pid) or '未知进程'}  本地 {h.local}" for h in holders]
        return why + "\n当前监听该端口的进程：\n" + "\n".join(lines)
    return why + "\n未能在 netstat 中找到监听进程；可尝试更换端口或以管理员身份运行。"
