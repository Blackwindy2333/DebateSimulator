import asyncio
import json
from pathlib import Path

from fastapi import Body, FastAPI
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from app import config_store, prompts, storage
from app.debate import DebateRunner, _llm_config
from app.events import EventBus
from app.llm import stream_chat

WEB_DIR = Path(__file__).resolve().parent.parent / "web"
SETTINGS_KEYS = ("pro", "con", "judge")


def _mask(key):
    if not key:
        return ""
    if len(key) <= 8:
        return "****"
    return f"{key[:3]}****{key[-4:]}"


def _masked_config(cfg):
    out = json.loads(json.dumps(cfg))
    for name in SETTINGS_KEYS:
        out["apis"][name]["api_key"] = _mask(out["apis"][name].get("api_key", ""))
    return out


def _sse(event, data):
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def create_app():
    app = FastAPI(title="DebateSimulator")
    bus = EventBus()
    state = {"runner": None, "task": None}

    if WEB_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")

    @app.get("/")
    def index():
        return FileResponse(str(WEB_DIR / "index.html"))

    @app.get("/api/config")
    def get_config():
        return _masked_config(config_store.load_config())

    @app.put("/api/config")
    def put_config(payload: dict = Body(...)):
        old = config_store.load_config()
        merged = config_store.merge_defaults(payload)
        for name in SETTINGS_KEYS:
            if "**" in str(merged["apis"][name].get("api_key", "")):
                merged["apis"][name]["api_key"] = old["apis"][name].get("api_key", "")
        config_store.save_config(merged)
        return {"ok": True}

    @app.post("/api/topic/generate")
    async def generate_topics(payload: dict = Body(default={})):
        cfg = config_store.load_config()
        n = int(payload.get("n", 4))
        messages = prompts.build_topic_gen_messages(prompts.load_requirements(), n)
        result = await stream_chat(_llm_config(cfg["apis"]["judge"]), messages,
                                   timeout=float(cfg["runtime"]["timeout_seconds"]))
        text = result["content"]
        start, end = text.find("["), text.rfind("]")
        try:
            topics = json.loads(text[start:end + 1]) if start >= 0 and end > start else []
        except json.JSONDecodeError:
            topics = []
        return {"topics": topics}

    @app.post("/api/debate/start")
    async def start(payload: dict = Body(default={})):
        cfg = config_store.load_config()
        if payload.get("topic"):
            cfg["debate"]["topic"] = payload["topic"]
            config_store.save_config(cfg)
        runner = DebateRunner(cfg, bus)
        runner.session["topic"] = cfg["debate"]["topic"]
        runner.session["topic_source"] = payload.get("topic_source", "manual")
        storage.save_session(runner.session)
        state["runner"] = runner
        state["task"] = asyncio.create_task(runner.start(force=bool(payload.get("force"))))
        return {"ok": True}

    @app.post("/api/debate/control")
    def control(payload: dict = Body(...)):
        runner = state.get("runner")
        if runner:
            runner.control(payload.get("action", ""))
        return {"ok": True}

    @app.get("/api/debate/state")
    def debate_state():
        runner = state.get("runner")
        if not runner:
            return {"status": "IDLE", "stage": None, "total_rounds": 0,
                    "topic": "", "messages": [], "judge": None, "current": None}
        return runner.snapshot()

    @app.get("/api/events")
    async def events():
        queue = bus.subscribe()

        async def gen():
            try:
                while True:
                    event, data = await queue.get()
                    yield _sse(event, data)
            finally:
                bus.unsubscribe(queue)

        return StreamingResponse(gen(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache",
                                          "X-Accel-Buffering": "no"})

    @app.get("/api/history")
    def history():
        storage.RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        return {"files": sorted((p.name for p in storage.RESULTS_DIR.glob("Result_*.txt")),
                                reverse=True)}

    @app.get("/api/history/{name:path}")
    def history_item(name: str):
        results = storage.RESULTS_DIR.resolve()
        target = (results / name).resolve()
        if not target.exists() or target.suffix != ".txt" or results not in target.parents:
            return {"ok": False}
        return {"ok": True, "content": target.read_text("utf-8")}

    return app


app = create_app()
