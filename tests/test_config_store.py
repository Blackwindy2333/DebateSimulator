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


def test_load_config_does_not_rewrite_existing_file(tmp_path, monkeypatch):
    """已存在配置时只读取，不覆盖用户文件。"""
    monkeypatch.setattr(config_store, "CONFIG_PATH", tmp_path / "config.json")
    handwritten = {
        "apis": {"pro": {"nickname": "我的正方", "api_key": "sk-mine"}},
        "debate": {"topic": "手写的辩题", "rounds": 3},
        "custom_section": {"keep": "me"},
    }
    config_store.CONFIG_PATH.write_text(json.dumps(handwritten, ensure_ascii=False), "utf-8")
    before = config_store.CONFIG_PATH.read_text("utf-8")

    cfg = config_store.load_config()

    # 返回值补齐了默认字段……
    assert cfg["apis"]["judge"]["base_url"] == "https://api.openai.com/v1"
    assert cfg["apis"]["pro"]["nickname"] == "我的正方"
    assert cfg["debate"]["rounds"] == 3
    # ……但磁盘文件保持原样，未被回写
    assert config_store.CONFIG_PATH.read_text("utf-8") == before
