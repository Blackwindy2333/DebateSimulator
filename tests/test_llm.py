from app.llm import ReasoningSplitter


def test_plain_content_passthrough():
    s = ReasoningSplitter()
    assert s.feed("你好") == [("content", "你好")]


def test_thinking_tag_block():
    s = ReasoningSplitter()
    assert s.feed("先说") == [("content", "先说")]
    assert s.feed("<thinking>推理中</thinking>") == [("reasoning", "推理中")]
    assert s.feed("结论") == [("content", "结论")]


def test_tag_split_across_chunks():
    s = ReasoningSplitter()
    assert s.feed("<thin") == []
    assert s.feed("king>内心</thinking>") == [("reasoning", "内心")]


def test_anchored_chinese_thinking_at_start():
    s = ReasoningSplitter()
    out = s.feed("思考\n先想一下\n结束\n正文开始")
    reasoning = "".join(t for c, t in out if c == "reasoning")
    content = "".join(t for c, t in out if c == "content")
    assert "先想一下" in reasoning
    assert "正文开始" in content


def test_midtext_chinese_not_treated_as_reasoning():
    s = ReasoningSplitter()
    out = s.feed("让我思考")
    out += s.feed("这个问题。")
    content = "".join(t for c, t in out if c == "content")
    reasoning = "".join(t for c, t in out if c == "reasoning")
    assert content == "让我思考这个问题。"
    assert reasoning == ""


def test_flush_emits_held_buffer():
    s = ReasoningSplitter()
    assert s.feed("正文<") == [("content", "正文")]
    assert s.flush() == [("content", "<")]
