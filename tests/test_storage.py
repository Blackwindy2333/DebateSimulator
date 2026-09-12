from app import storage


def _use_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "CACHE_PATH", tmp_path / "cache" / "session.json")
    monkeypatch.setattr(storage, "RESULTS_DIR", tmp_path / "Results")


def test_speaker_label():
    assert storage.speaker_label("pro", "opening", None) == "正方一辩"
    assert storage.speaker_label("con", "opening", None) == "反方一辩"
    assert storage.speaker_label("pro", "free", 3) == "正方自由辩论第3轮"
    assert storage.speaker_label("con", "closing", None) == "反方总结陈词"


def test_init_session_clears_previous(tmp_path, monkeypatch):
    _use_tmp(tmp_path, monkeypatch)
    storage.CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    storage.CACHE_PATH.write_text('{"topic": "旧"}', "utf-8")
    s = storage.init_session()
    assert s["topic"] == "" and s["messages"] == []


def test_write_result_txt_format(tmp_path, monkeypatch):
    _use_tmp(tmp_path, monkeypatch)
    sess = storage.init_session()
    sess["topic"] = "测试辩题"
    storage.append_message(sess, {"id": "m1", "side": "pro", "role": "opening",
                                  "round": None, "speaker": "正方一辩", "content": "正方发言。"})
    storage.append_message(sess, {"id": "m2", "side": "con", "role": "opening",
                                  "round": None, "speaker": "反方一辩", "content": "反方发言。"})
    storage.set_judge(sess, {"content": "正方更胜一筹。", "reasoning": "", "elapsed_ms": 1, "chars": 7})
    txt_path, md_path = storage.write_result(sess)
    lines = txt_path.read_text("utf-8").splitlines()
    assert lines[0] == "测试辩题"
    assert lines[1] == "正方一辩" and lines[2] == "正方发言。"
    assert "反方一辩" in lines and "总结评价" in lines
    assert md_path.exists() and md_path.suffix == ".md"


def test_format_transcript_includes_all(tmp_path, monkeypatch):
    _use_tmp(tmp_path, monkeypatch)
    sess = storage.init_session()
    sess["topic"] = "T"
    storage.append_message(sess, {"id": "m1", "side": "pro", "role": "opening",
                                  "round": None, "speaker": "正方一辩", "content": "A"})
    out = storage.format_transcript(sess)
    assert "正方一辩" in out and "A" in out
