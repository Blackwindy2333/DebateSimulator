from fastapi.testclient import TestClient

from app import config_store, storage
from app.main import create_app


def _patch(tmp_path, monkeypatch):
    monkeypatch.setattr(config_store, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(storage, "CACHE_PATH", tmp_path / "cache" / "session.json")
    monkeypatch.setattr(storage, "RESULTS_DIR", tmp_path / "Results")


def test_config_endpoints(tmp_path, monkeypatch):
    _patch(tmp_path, monkeypatch)
    client = TestClient(create_app())
    got = client.get("/api/config").json()
    assert got["runtime"]["port"] == 8000
    got["debate"]["rounds"] = 4
    assert client.put("/api/config", json=got).status_code == 200
    assert client.get("/api/config").json()["debate"]["rounds"] == 4


def test_api_key_masked_and_preserved(tmp_path, monkeypatch):
    _patch(tmp_path, monkeypatch)
    client = TestClient(create_app())
    cfg = client.get("/api/config").json()
    cfg["apis"]["pro"]["api_key"] = "sk-abcdefghijklmnop"
    client.put("/api/config", json=cfg)

    masked = client.get("/api/config").json()
    assert masked["apis"]["pro"]["api_key"] == "sk-****mnop"

    # 再次保存时携带打码值，应保留真实密钥
    client.put("/api/config", json=masked)
    assert config_store.load_config()["apis"]["pro"]["api_key"] == "sk-abcdefghijklmnop"


def test_state_endpoint(tmp_path, monkeypatch):
    _patch(tmp_path, monkeypatch)
    client = TestClient(create_app())
    assert client.get("/api/debate/state").json()["status"] == "IDLE"


def test_history_empty(tmp_path, monkeypatch):
    _patch(tmp_path, monkeypatch)
    client = TestClient(create_app())
    assert client.get("/api/history").json()["files"] == []


def test_history_reads_result_file(tmp_path, monkeypatch):
    _patch(tmp_path, monkeypatch)
    results = tmp_path / "Results"
    results.mkdir(parents=True, exist_ok=True)
    (results / "Result_20260101_000000.txt").write_text("辩题\n正方一辩\n内容\n", "utf-8")
    client = TestClient(create_app())
    assert client.get("/api/history").json()["files"] == ["Result_20260101_000000.txt"]
    item = client.get("/api/history/Result_20260101_000000.txt").json()
    assert item["ok"] is True and "正方一辩" in item["content"]


def test_history_rejects_traversal(tmp_path, monkeypatch):
    _patch(tmp_path, monkeypatch)
    client = TestClient(create_app())
    for attempt in ("..%2Fconfig.json", "%2E%2E%2Fconfig.json", "nope.txt"):
        assert client.get(f"/api/history/{attempt}").json()["ok"] is False
