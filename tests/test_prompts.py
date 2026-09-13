from app import prompts, storage


def test_render_substitutes():
    assert prompts.render("你好{{name}}！", name="世界") == "你好世界！"


def test_build_stage_messages_first_opening_has_no_transcript(tmp_path, monkeypatch):
    """正方一辩是全场第一条发言，此时缓存为空，不应出现记录块。"""
    monkeypatch.setattr(storage, "CACHE_PATH", tmp_path / "s.json")
    sess = storage.init_session()
    sess["topic"] = "T"
    cfg = {"apis": {"pro": {"nickname": "甲"}, "con": {"nickname": "乙"}},
           "debate": {"personas": {"pro": "", "con": ""}}}
    msgs = prompts.build_stage_messages(stage="opening", side="pro", round_no=None,
                                        total_rounds=7, session=sess, config=cfg)
    assert msgs[0]["role"] == "system" and "T" in msgs[0]["content"]
    assert "【此前发言记录】" not in msgs[1]["content"]


def test_con_opening_sees_pro_opening(tmp_path, monkeypatch):
    """反方一辩必须能看到正方一辩的立论。"""
    monkeypatch.setattr(storage, "CACHE_PATH", tmp_path / "s.json")
    sess = storage.init_session()
    sess["topic"] = "T"
    storage.append_message(sess, {"id": "m1", "side": "pro", "role": "opening",
                                  "round": None, "speaker": "正方一辩", "content": "我方立论A"})
    cfg = {"apis": {"pro": {"nickname": "甲"}, "con": {"nickname": "乙"}},
           "debate": {"personas": {"pro": "", "con": ""}}}
    msgs = prompts.build_stage_messages(stage="opening", side="con", round_no=None,
                                        total_rounds=7, session=sess, config=cfg)
    assert "【此前发言记录】" in msgs[1]["content"]
    assert "正方一辩" in msgs[1]["content"]
    assert "我方立论A" in msgs[1]["content"]


def test_build_stage_messages_free_includes_transcript(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "CACHE_PATH", tmp_path / "s.json")
    sess = storage.init_session()
    sess["topic"] = "T"
    storage.append_message(sess, {"id": "m1", "side": "pro", "role": "opening",
                                  "round": None, "speaker": "正方一辩", "content": "论点A"})
    cfg = {"apis": {"pro": {"nickname": "甲"}, "con": {"nickname": "乙"}},
           "debate": {"personas": {"pro": "", "con": ""}}}
    msgs = prompts.build_stage_messages(stage="free", side="con", round_no=2,
                                        total_rounds=7, session=sess, config=cfg)
    assert "【此前发言记录】" in msgs[1]["content"] and "论点A" in msgs[1]["content"]
    assert "第 2 轮" in msgs[1]["content"]


def test_persona_injected_into_system():
    cfg = {"apis": {"pro": {"nickname": "甲"}, "con": {"nickname": "乙"}},
           "debate": {"personas": {"pro": "犀利直接", "con": ""}}}
    sess = {"topic": "T", "messages": []}
    msgs = prompts.build_stage_messages(stage="opening", side="pro", round_no=None,
                                        total_rounds=3, session=sess, config=cfg)
    assert "犀利直接" in msgs[0]["content"]
