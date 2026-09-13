import json
from app import config_store


def test_merge_defaults_fills_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(config_store, "CONFIG_PATH", tmp_path / "config.json")
    merged = config_store.merge_defaults({"debate": {"rounds": 5}})
    assert merged["debate"]["rounds"] == 5
    assert merged["debate"]["personas"] == {"pro": "", "con": ""}
    assert merged["apis"]["pro"]["base_url"] == "https://api.openai.com/v1"
    assert merged["runtime"]["max_retries"] == 3


def test_defaults_use_light_theme_and_no_max_tokens():
    for name in ("pro", "con", "judge"):
        api = config_store.DEFAULT_CONFIG["apis"][name]
        assert "max_tokens" not in api
        assert api["thinking_enabled"] is True
        assert api["reasoning_effort"] in config_store.REASONING_EFFORTS
    assert config_store.DEFAULT_CONFIG["ui"]["theme"] == "light"


def test_load_config_creates_file_with_defaults(tmp_path, monkeypatch):
    monkeypatch.setattr(config_store, "CONFIG_PATH", tmp_path / "config.json")
    cfg = config_store.load_config()
    assert cfg["runtime"]["port"] == 8000
    assert config_store.CONFIG_PATH.exists()


def test_save_then_load_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(config_store, "CONFIG_PATH", tmp_path / "config.json")
    cfg = config_store.load_config()
    cfg["debate"]["topic"] = "人工智能应当被赋予法律人格"
    config_store.save_config(cfg)
    assert config_store.load_config()["debate"]["topic"] == "人工智能应当被赋予法律人格"
    assert json.loads(config_store.CONFIG_PATH.read_text("utf-8"))["debate"]["topic"] == "人工智能应当被赋予法律人格"
