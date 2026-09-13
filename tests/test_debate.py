import asyncio

from app import debate as debate_mod
from app import logbook, storage
from app.events import EventBus


class FakeLLM:
    def __init__(self):
        self.calls = []

    async def __call__(self, cfg, messages, *, timeout=120.0, on_reasoning=None,
                       on_content=None, logger=None):
        self.calls.append(messages)
        if logger is not None:
            logger(cfg, f"{cfg.base_url.rstrip('/')}/chat/completions",
                   {"model": cfg.model, "messages": messages})
        user = messages[-1]["content"]
        if '"verdict"' in user:
            return {"content": '{"verdict": "合理", "reason": ""}',
                    "reasoning": "", "elapsed_ms": 1, "chars": 3}
        text = f"发言{len(self.calls)}"
        if on_content:
            await on_content(text)
        return {"content": text, "reasoning": "想了一下", "elapsed_ms": 2, "chars": len(text)}


def _cfg(rounds=2):
    api = {"api_key": "k", "base_url": "http://x", "model": "m", "temperature": 0.8,
           "thinking_enabled": True, "reasoning_effort": "high"}
    return {"apis": {"pro": {"nickname": "甲", **api},
                     "con": {"nickname": "乙", **api},
                     "judge": {"nickname": "丙", **api}},
            "debate": {"topic": "测试辩题", "rounds": rounds, "personas": {"pro": "", "con": ""}},
            "runtime": {"max_retries": 1, "timeout_seconds": 5, "port": 0, "auto_open_browser": False},
            "ui": {}}


def _patch(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "CACHE_PATH", tmp_path / "s.json")
    monkeypatch.setattr(storage, "RESULTS_DIR", tmp_path / "Results")
    monkeypatch.setattr(logbook, "LOGS_DIR", tmp_path / "Logs")
    monkeypatch.setattr(logbook, "_operations_path", None)
    monkeypatch.setattr(logbook, "_api_requests_path", None)


def test_llm_config_maps_thinking_params():
    from app.debate import _llm_config
    off = _llm_config({"thinking_enabled": False, "reasoning_effort": "max"})
    assert off.thinking_enabled is False
    assert off.reasoning_effort == "max"
    default = _llm_config({})
    assert default.thinking_enabled is True
    assert default.reasoning_effort == "high"


def test_llm_config_falls_back_on_unknown_effort():
    from app.debate import _llm_config
    assert _llm_config({"reasoning_effort": "turbo"}).reasoning_effort == "high"
    assert _llm_config({"reasoning_effort": ""}).reasoning_effort == "high"


def test_full_flow_order_and_cache(tmp_path, monkeypatch):
    _patch(tmp_path, monkeypatch)
    runner = debate_mod.DebateRunner(_cfg(), EventBus(), llm=FakeLLM())
    asyncio.run(runner.start())
    speakers = [m["speaker"] for m in runner.session["messages"]]
    assert speakers == ["正方一辩", "反方一辩",
                        "正方自由辩论第1轮", "反方自由辩论第1轮",
                        "正方自由辩论第2轮", "反方自由辩论第2轮",
                        "正方总结陈词", "反方总结陈词"]
    assert runner.status == "DONE"
    assert runner.session["judge"]["content"] == "发言10"
    assert len(list((tmp_path / "Results").glob("Result_*.txt"))) == 1


def test_force_skips_validation(tmp_path, monkeypatch):
    _patch(tmp_path, monkeypatch)
    llm = FakeLLM()
    runner = debate_mod.DebateRunner(_cfg(rounds=1), EventBus(), llm=llm)
    asyncio.run(runner.start(force=True))
    assert not any('"verdict"' in c[-1]["content"] for c in llm.calls)
    assert runner.status == "DONE"


def test_invalid_topic_warns_then_force(tmp_path, monkeypatch):
    _patch(tmp_path, monkeypatch)

    class BadTopicLLM(FakeLLM):
        async def __call__(self, cfg, messages, **kw):
            user = messages[-1]["content"]
            if '"verdict"' in user:
                self.calls.append(messages)
                return {"content": '{"verdict": "不合理", "reason": "过于宽泛"}',
                        "reasoning": "", "elapsed_ms": 1, "chars": 5}
            return await super().__call__(cfg, messages, **kw)

    runner = debate_mod.DebateRunner(_cfg(rounds=1), EventBus(), llm=BadTopicLLM())

    async def drive():
        task = asyncio.create_task(runner.start())
        await asyncio.sleep(0.05)
        assert runner.status == "WARNING"
        runner.control("force")
        await task

    asyncio.run(drive())
    assert runner.status == "DONE"


def test_abort_stops_debate(tmp_path, monkeypatch):
    _patch(tmp_path, monkeypatch)

    class BlockingLLM(FakeLLM):
        async def __call__(self, cfg, messages, **kw):
            await asyncio.sleep(0.05)
            return await super().__call__(cfg, messages, **kw)

    runner = debate_mod.DebateRunner(_cfg(rounds=5), EventBus(), llm=BlockingLLM())

    async def drive():
        task = asyncio.create_task(runner.start(force=True))
        await asyncio.sleep(0.08)
        runner.control("abort")
        await task

    asyncio.run(drive())
    assert runner.status == "ABORTED"
    assert len(runner.session["messages"]) < 8
