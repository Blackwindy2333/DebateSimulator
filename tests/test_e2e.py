import asyncio
import threading
import time
from pathlib import Path

import uvicorn

from app import debate, logbook, storage
from app.events import EventBus
from tests.mock_openai import app as mock_app

PORT = 8123
_server = None


def _ensure_server():
    """在后台线程启动假接口，整个测试会话只启动一次。"""
    global _server
    if _server is not None:
        return
    config = uvicorn.Config(mock_app, host="127.0.0.1", port=PORT, log_level="error")
    server = uvicorn.Server(config)
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(200):
        if server.started:
            _server = server
            return
        time.sleep(0.05)
    raise RuntimeError("mock 接口未能启动")


def _cfg():
    api = {"api_key": "test-key", "base_url": f"http://127.0.0.1:{PORT}/v1",
           "model": "mock-model", "temperature": 0.7,
           "thinking_enabled": True, "reasoning_effort": "high"}
    return {"apis": {"pro": {"nickname": "正方甲", **api},
                     "con": {"nickname": "反方乙", **api},
                     "judge": {"nickname": "评委丙", **api}},
            "debate": {"topic": "人工智能应当被赋予法律人格", "rounds": 2,
                       "personas": {"pro": "", "con": ""}},
            "runtime": {"max_retries": 2, "timeout_seconds": 30,
                        "port": 0, "auto_open_browser": False},
            "ui": {}}


def _patch(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "CACHE_PATH", tmp_path / "cache" / "session.json")
    monkeypatch.setattr(storage, "RESULTS_DIR", tmp_path / "Results")
    monkeypatch.setattr(logbook, "LOGS_DIR", tmp_path / "Logs")
    monkeypatch.setattr(logbook, "_operations_path", None)
    monkeypatch.setattr(logbook, "_api_requests_path", None)


def test_end_to_end_against_mock_api(tmp_path, monkeypatch):
    _ensure_server()
    _patch(tmp_path, monkeypatch)

    runner = debate.DebateRunner(_cfg(), EventBus())
    asyncio.run(runner.start())

    assert runner.status == "DONE"

    messages = runner.session["messages"]
    assert [m["speaker"] for m in messages] == [
        "正方一辩", "反方一辩",
        "正方自由辩论第1轮", "反方自由辩论第1轮",
        "正方自由辩论第2轮", "反方自由辩论第2轮",
        "正方总结陈词", "反方总结陈词",
    ]

    # 每条发言都有正文与用量信息
    assert all(m["content"] for m in messages)
    assert all(m["chars"] > 0 and m["elapsed_ms"] >= 0 for m in messages)

    # 思考计时：假接口先吐 reasoning_content 再吐 content，故思考耗时必然大于 0
    assert all(m["thinking_ms"] > 0 for m in messages)
    assert runner.session["judge"]["thinking_ms"] > 0

    # 思考内容被剥离到独立字段，未混入正文
    assert all(m["reasoning"] for m in messages)
    assert all("我需要先梳理对方的论证结构" not in m["content"] for m in messages)

    # 自由辩论与总结陈词携带了此前全部发言
    free_from_round2 = next(m for m in messages if m["speaker"] == "正方自由辩论第2轮")
    assert free_from_round2["content"]

    # 评委点评
    assert runner.session["judge"]["content"].strip()
    assert "更胜一筹" in runner.session["judge"]["content"]

    # 落盘格式：第 1 行辩题，之后为「身份 + 正文」，末尾附总结评价
    txts = list((tmp_path / "Results").glob("Result_*.txt"))
    assert len(txts) == 1
    lines = txts[0].read_text("utf-8").splitlines()
    assert lines[0] == "人工智能应当被赋予法律人格"
    assert lines[1] == "正方一辩" and lines[2]
    assert "总结评价" in lines
    assert (tmp_path / "Results" / txts[0].name.replace(".txt", ".md")).exists()

    # 双日志：操作日志记录全过程，请求日志记录每次请求的完整请求体
    logs = logbook.paths()
    operations = Path(logs["operations"]).read_text("utf-8")
    requests = Path(logs["api_requests"]).read_text("utf-8")
    assert "debate.start" in operations and "debate.result" in operations
    assert "debate.speech" in operations and "debate.judge" in operations
    assert "正方一辩" in requests
    # 请求体包含必要的控制字段
    assert '"thinking": {' in requests and '"type": "enabled"' in requests
    assert '"reasoning_effort": "high"' in requests
    assert '"model": "mock-model"' in requests and '"stream": true' in requests
    # 不再发送 max_tokens
    assert "max_tokens" not in requests


def test_transcript_carries_full_history_to_prompt(tmp_path, monkeypatch):
    """自由辩论第 2 轮 / 总结陈词的请求里必须包含此前所有发言。"""
    _ensure_server()
    _patch(tmp_path, monkeypatch)

    captured = []

    async def spy(cfg, messages, **kwargs):
        captured.append(messages)
        from app.llm import stream_chat
        return await stream_chat(cfg, messages, **kwargs)

    runner = debate.DebateRunner(_cfg(), EventBus(), llm=spy)
    asyncio.run(runner.start())

    # 反方一辩必须看到正方一辩的立论；正方一辩是全场首条发言，不带记录块
    pro_opening = captured[1]
    assert "【此前发言记录】" not in pro_opening[-1]["content"]
    con_opening = captured[2]
    assert "【此前发言记录】" in con_opening[-1]["content"]
    assert "正方一辩" in con_opening[-1]["content"]

    closing = captured[-2]  # 总结陈词（其后为评委）
    closing_text = closing[-1]["content"]
    assert "【此前发言记录】" in closing_text
    assert "正方一辩" in closing_text
    assert "反方自由辩论第2轮" in closing_text

    opening = captured[0]  # 校验选题
    assert '"verdict"' in opening[-1]["content"]
