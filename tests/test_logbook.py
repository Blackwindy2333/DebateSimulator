from pathlib import Path

from app import logbook


def _patch(tmp_path, monkeypatch):
    monkeypatch.setattr(logbook, "LOGS_DIR", tmp_path / "Logs")
    monkeypatch.setattr(logbook, "_operations_path", None)
    monkeypatch.setattr(logbook, "_api_requests_path", None)
    return logbook.start_session()


def test_session_creates_two_files(tmp_path, monkeypatch):
    paths = _patch(tmp_path, monkeypatch)
    assert paths["operations"] and paths["api_requests"]
    assert paths["operations"] != paths["api_requests"]
    assert Path(paths["operations"]).exists()
    assert Path(paths["api_requests"]).exists()
    assert Path(paths["operations"]).name.startswith("Operations_")
    assert Path(paths["api_requests"]).name.startswith("ApiRequests_")


def test_operations_log_records_actions(tmp_path, monkeypatch):
    paths = _patch(tmp_path, monkeypatch)
    logbook.operation("config.save", "rounds=3")
    logbook.operation("debate.start", "topic=测试辩题")
    text = Path(paths["operations"]).read_text("utf-8")
    assert "config.save" in text and "rounds=3" in text
    assert "debate.start" in text and "topic=测试辩题" in text


def test_api_log_records_full_payload(tmp_path, monkeypatch):
    paths = _patch(tmp_path, monkeypatch)
    payload = {
        "model": "deepseek-flash",
        "messages": [{"role": "system", "content": "You are a helpful assistant."},
                     {"role": "user", "content": "Hello!"}],
        "thinking": {"type": "enabled"},
        "reasoning_effort": "high",
        "stream": True,
    }
    logbook.api_request("正方", "https://api.example.com/v1/chat/completions",
                        payload, label="正方一辩")
    text = Path(paths["api_requests"]).read_text("utf-8")
    assert "正方一辩" in text
    assert "https://api.example.com/v1/chat/completions" in text
    assert '"model": "deepseek-flash"' in text
    assert '"thinking": {' in text and '"type": "enabled"' in text
    assert '"reasoning_effort": "high"' in text
    assert '"role": "user"' in text and '"content": "Hello!"' in text


def test_operations_written_before_session_autostarts(tmp_path, monkeypatch):
    monkeypatch.setattr(logbook, "LOGS_DIR", tmp_path / "Logs")
    monkeypatch.setattr(logbook, "_operations_path", None)
    monkeypatch.setattr(logbook, "_api_requests_path", None)
    logbook.operation("auto.start", "未显式开会话也应落盘")
    assert "auto.start" in Path(logbook.paths()["operations"]).read_text("utf-8")
