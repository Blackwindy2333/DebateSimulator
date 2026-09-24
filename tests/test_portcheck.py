import socket

import app.portcheck as portcheck


def test_try_bind_success_and_failure(monkeypatch):
    assert portcheck.try_bind("127.0.0.1", 0) is None

    class Boom(socket.socket):
        def bind(self, addr):
            raise OSError(10013, "denied")

    monkeypatch.setattr(portcheck.socket, "socket", lambda *a, **k: Boom())
    err = portcheck.try_bind("127.0.0.1", 8000)
    assert isinstance(err, OSError)


def test_find_free_port_skips_busy(monkeypatch):
    busy = {8000, 8001}
    monkeypatch.setattr(portcheck, "try_bind", lambda h, p: OSError(10048, "busy") if p in busy else None)
    assert portcheck.find_free_port("127.0.0.1", 8000, span=5) == 8002
    assert portcheck.find_free_port("127.0.0.1", 8000, span=2) is None
    assert portcheck.find_free_port("127.0.0.1", 8000, span=0) is None


def test_listeners_parses_netstat(monkeypatch):
    sample = (
        "  TCP    0.0.0.0:8000           0.0.0.0:0              LISTENING       14400\n"
        "  TCP    [::]:8000              [::]:0                 LISTENING       14400\n"
        "  TCP    127.0.0.1:8000         127.0.0.1:52197        TIME_WAIT       0\n"
        "  TCP    0.0.0.0:8001           0.0.0.0:0              LISTENING       99\n"
    )
    monkeypatch.setattr(portcheck.subprocess, "check_output", lambda *a, **k: sample)
    got = portcheck.listeners(8000)
    assert [(x.pid, x.local) for x in got] == [(14400, "0.0.0.0:8000"), (14400, "[::]:8000")]


def test_describe_bind_error_mentions_pid(monkeypatch):
    monkeypatch.setattr(portcheck, "listeners", lambda p: [portcheck.Listener(pid=7, local="0.0.0.0:8000")])
    monkeypatch.setattr(portcheck, "process_name", lambda p: "python.exe")
    err = OSError(13, "denied")
    err.winerror = 10013
    text = portcheck.describe_bind_error(err, "127.0.0.1", 8000)
    assert "10013" in text
    assert "PID 7" in text
    assert "python.exe" in text
