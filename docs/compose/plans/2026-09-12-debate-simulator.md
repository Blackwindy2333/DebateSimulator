# AI 辩论模拟器 Implementation Plan

> [!NOTE]
> This document may not reflect the current implementation.
> See the final report for up-to-date state:
> [Final Report](../reports/debate-simulator.md)

> **For agentic workers:** REQUIRED SUB-SKILL: Use compose:subagent (recommended) or compose:execute to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建一个本地 Web 应用，让两个 OpenAI 兼容 API 扮演正反方进行结构化辩论，第三个 API 评价胜负，全过程实时显示并持久化。

**Architecture:** Python 3.13 + FastAPI 后端负责配置持久化、状态机编排、流式 LLM 调用与结果落盘；`EventBus` 通过 SSE 向前端广播实时事件；原生 HTML/CSS/JS 前端左右分栏展示。辩论在服务端异步任务中运行，与前端连接解耦。

**Tech Stack:** Python 3.13、FastAPI、uvicorn、httpx、pydantic、pytest、pytest-asyncio；前端原生 HTML/CSS/JS（无构建步骤）。

**Spec:** `docs/compose/specs/2026-09-12-debate-simulator-design.md`

## Global Constraints

- 界面文案与所有 prompt **全中文**。
- 每个 LLM 请求最前面必须注入 `context.md`（当前局面介绍）。
- 自由辩论与总结陈词阶段必须携带缓存中的**全部**过往发言；一辩发言阶段不携带发言正文。
- 缓存 `cache/session.json` 在进程启动时**清空重建**。
- 结果落盘为 `Results/Result_<YYYYMMDD_HHMMSS>.txt`，并同时输出同名 `.md`。
- 选题校验**强制 JSON** `{"verdict","reason"}`，解析失败降级；API 生成的选题**跳过校验**。
- 思考内容（`reasoning_content` / `reasoning` 字段、内联 `思考…` 标签）必须与正文分离。
- Git：每改动一个文件提交一次，前缀 `feat.`/`fix.`/`add.`/`del.`/`docs.` + 具体内容。
- 端口默认 8000，来自 `runtime.port`。

---

## File Structure

| 文件 | 职责 |
| --- | --- |
| `app/__init__.py` | 包标记 |
| `app/config_store.py` | 读写 `config/config.json`，默认值深合并 |
| `app/storage.py` | 缓存生命周期 + 结果落盘 + 发言者标签 + 记录格式化 |
| `app/llm.py` | OpenAI 兼容流式客户端、思考内容解析、重试 |
| `app/prompts.py` | 加载/渲染 `prompts/*.md`，组装 messages |
| `app/events.py` | `EventBus` 广播器 |
| `app/debate.py` | `DebateRunner` 状态机 |
| `app/main.py` | FastAPI 应用、REST、SSE、启动清缓存 |
| `prompts/*.md` | 7 个提示词模板 |
| `web/index.html`,`styles.css`,`app.js` | 前端 |
| `tests/*.py` | pytest 单元测试 |
| `run.bat`,`README.md`,`requirements.txt`,`.gitignore` | 工程配套 |

---

## Task 1: 工程脚手架与配置持久化

**Covers:** [S3, S4, S13]

**Files:**
- Create: `.gitignore`, `requirements.txt`, `app/__init__.py`, `app/config_store.py`, `tests/__init__.py`, `tests/test_config_store.py`

**Interfaces:**
- Consumes: 无
- Produces:
  - `app.config_store.DEFAULT_CONFIG: dict`
  - `app.config_store.merge_defaults(cfg: dict) -> dict`
  - `app.config_store.load_config() -> dict`
  - `app.config_store.save_config(cfg: dict) -> None`
  - `app.config_store.CONFIG_PATH: pathlib.Path`

- [ ] **Step 1: 写 `.gitignore`**

```gitignore
__pycache__/
*.pyc
.venv/
venv/
.pytest_cache/
cache/
Results/
config/config.json
.mimocode/
```

- [ ] **Step 2: 写 `requirements.txt`**

```
fastapi==0.115.6
uvicorn[standard]==0.34.0
httpx==0.28.1
pydantic==2.10.4
pytest==8.3.4
pytest-asyncio==0.25.0
```

- [ ] **Step 3: 写失败测试 `tests/test_config_store.py`**

```python
import json
from app import config_store


def test_merge_defaults_fills_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(config_store, "CONFIG_PATH", tmp_path / "config.json")
    merged = config_store.merge_defaults({"debate": {"rounds": 5}})
    assert merged["debate"]["rounds"] == 5
    assert merged["debate"]["personas"] == {"pro": "", "con": ""}
    assert merged["apis"]["pro"]["base_url"] == "https://api.openai.com/v1"
    assert merged["runtime"]["max_retries"] == 3


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
```

- [ ] **Step 4: 运行测试确认失败**

Run: `python -m pytest tests/test_config_store.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app'` 或 `AttributeError: merge_defaults`

- [ ] **Step 5: 实现 `app/config_store.py`**

```python
import json
from copy import deepcopy
from pathlib import Path

CONFIG_PATH = Path("config") / "config.json"

DEFAULT_CONFIG = {
    "apis": {
        "pro": {"nickname": "正方", "api_key": "", "base_url": "https://api.openai.com/v1",
                "model": "", "temperature": 0.8, "max_tokens": 2048},
        "con": {"nickname": "反方", "api_key": "", "base_url": "https://api.openai.com/v1",
                "model": "", "temperature": 0.8, "max_tokens": 2048},
        "judge": {"nickname": "裁判", "api_key": "", "base_url": "https://api.openai.com/v1",
                  "model": "", "temperature": 0.3, "max_tokens": 2048},
    },
    "debate": {"topic": "", "rounds": 7, "personas": {"pro": "", "con": ""}},
    "runtime": {"max_retries": 3, "timeout_seconds": 120, "port": 8000, "auto_open_browser": True},
    "ui": {"theme": "dark", "sound": True},
}


def merge_defaults(cfg):
    out = deepcopy(DEFAULT_CONFIG)
    for key, value in (cfg or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            for sub, subvalue in value.items():
                if isinstance(subvalue, dict) and isinstance(out[key].get(sub), dict):
                    out[key][sub].update(subvalue)
                else:
                    out[key][sub] = subvalue
        else:
            out[key] = value
    return out


def load_config():
    if CONFIG_PATH.exists():
        merged = merge_defaults(json.loads(CONFIG_PATH.read_text("utf-8")))
    else:
        merged = merge_defaults({})
    save_config(merged)
    return merged


def save_config(cfg):
    merged = merge_defaults(cfg)
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(merged, ensure_ascii=False, indent=2), "utf-8")
```

- [ ] **Step 6: 运行测试确认通过**

Run: `python -m pytest tests/test_config_store.py -v`
Expected: 3 passed

- [ ] **Step 7: 提交**

```bash
git add .gitignore requirements.txt app/__init__.py app/config_store.py tests/__init__.py tests/test_config_store.py
git commit -m "feat. 配置持久化与工程脚手架"
```

---

## Task 2: 缓存生命周期与结果落盘

**Covers:** [S11, S5]

**Files:**
- Create: `app/storage.py`, `tests/test_storage.py`

**Interfaces:**
- Consumes: 无
- Produces:
  - `app.storage.CACHE_PATH: Path`、`app.storage.RESULTS_DIR: Path`
  - `init_session() -> dict`（清空并写空缓存）
  - `load_session() -> dict`、`save_session(sess: dict) -> None`
  - `append_message(sess: dict, msg: dict) -> None`、`set_judge(sess: dict, judge: dict) -> None`
  - `speaker_label(side: str, role: str, round_no: int | None) -> str`
  - `format_transcript(sess: dict) -> str`（供 prompt 注入）
  - `write_result(sess: dict) -> tuple[Path, Path]`（返回 txt, md）

**发言者标签规则：** `opening`→`正方一辩`/`反方一辩`；`free`→`正方自由辩论第{n}轮`；
`closing`→`正方总结陈词`；`side` ∈ `pro|con` → `正方|反方`。

- [ ] **Step 1: 写失败测试 `tests/test_storage.py`**

```python
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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_storage.py -v`
Expected: FAIL — `AttributeError: module 'app.storage' has no attribute 'speaker_label'`

- [ ] **Step 3: 实现 `app/storage.py`**

```python
import json
from datetime import datetime
from pathlib import Path

CACHE_PATH = Path("cache") / "session.json"
RESULTS_DIR = Path("Results")

SIDE_CN = {"pro": "正方", "con": "反方"}
ROLE_LABEL = {"opening": "一辩", "closing": "总结陈词"}


def speaker_label(side, role, round_no=None):
    side_cn = SIDE_CN.get(side, side)
    if role == "free":
        return f"{side_cn}自由辩论第{round_no}轮"
    return f"{side_cn}{ROLE_LABEL.get(role, role)}"


def _empty_session():
    return {"topic": "", "topic_source": "manual", "status": "IDLE", "messages": [], "judge": None}


def init_session():
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    if CACHE_PATH.exists():
        CACHE_PATH.unlink()
    sess = _empty_session()
    save_session(sess)
    return sess


def load_session():
    if CACHE_PATH.exists():
        return json.loads(CACHE_PATH.read_text("utf-8"))
    return init_session()


def save_session(sess):
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(sess, ensure_ascii=False, indent=2), "utf-8")


def append_message(sess, msg):
    sess["messages"].append(msg)
    save_session(sess)


def set_judge(sess, judge):
    sess["judge"] = judge
    save_session(sess)


def format_transcript(sess):
    blocks = []
    for m in sess["messages"]:
        blocks.append(f"{m.get('speaker', '')}\n{m.get('content', '')}")
    return "\n\n".join(blocks)


def _render_text(sess):
    lines = [sess.get("topic", "")]
    for m in sess["messages"]:
        lines.append(m.get("speaker", ""))
        lines.append(m.get("content", ""))
    if sess.get("judge"):
        lines.append("总结评价")
        lines.append(sess["judge"].get("content", ""))
    return "\n".join(lines) + "\n"


def _render_markdown(sess):
    out = [f"# {sess.get('topic', '')}", ""]
    for m in sess["messages"]:
        out.append(f"## {m.get('speaker', '')}")
        out.append("")
        out.append(m.get("content", ""))
        out.append("")
    if sess.get("judge"):
        out.append("## 总结评价")
        out.append("")
        out.append(sess["judge"].get("content", ""))
        out.append("")
    return "\n".join(out)


def write_result(sess):
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    txt_path = RESULTS_DIR / f"Result_{stamp}.txt"
    md_path = RESULTS_DIR / f"Result_{stamp}.md"
    txt_path.write_text(_render_text(sess), "utf-8")
    md_path.write_text(_render_markdown(sess), "utf-8")
    return txt_path, md_path
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_storage.py -v`
Expected: 4 passed

- [ ] **Step 5: 提交**

```bash
git add app/storage.py tests/test_storage.py
git commit -m "feat. 缓存生命周期与结果落盘"
```

---

## Task 3: 流式 LLM 客户端与思考内容解析

**Covers:** [S8, S10]

**Files:**
- Create: `app/llm.py`, `tests/test_llm.py`

**Interfaces:**
- Consumes: 无
- Produces:
  - `app.llm.LLMConfig`（dataclass：`nickname, api_key, base_url, model, temperature, max_tokens`）
  - `app.llm.LLMError(Exception)`
  - `app.llm.ReasoningSplitter` — `feed(chunk: str) -> list[tuple[str, str]]` 返回 `(channel, text)`，channel ∈ `content|reasoning`
  - `async def stream_chat(cfg, messages, *, timeout, on_reasoning=None, on_content=None) -> dict`

**返回 dict 字段：** `{"content": str, "reasoning": str, "elapsed_ms": int, "chars": int}`。
`chars` = 正文中非空白字符数。

- [ ] **Step 1: 写失败测试 `tests/test_llm.py`**

```python
import pytest
from app.llm import ReasoningSplitter


def test_splitter_plain_content():
    s = ReasoningSplitter()
    out = s.feed("你好")
    assert out == [("content", "你好")]


def test_splitter_inline_think_block():
    s = ReasoningSplitter()
    a = s.feed("先说")
    b = s.feed("思考这段是思考")
    c = s.feed("结束。正文")
    assert a == [("content", "先说")]
    assert b == [("reasoning", "这段是思考")]
    assert c == [("content", "。正文")]


def test_splitter_tag_split_across_chunks():
    s = ReasoningSplitter()
    out1 = s.feed("思考开")
    out2 = s.feed("始推理")
    reasoning = "".join(t for c, t in out1 + out2 if c == "reasoning")
    assert reasoning == "开始推理"
    assert all("思考" not in t for c, t in out1 + out2 if c == "content")


def test_splitter_flush_emits_held_buffer():
    s = ReasoningSplitter()
    out = s.feed("正文<")
    assert out == [("content", "正文")]
    assert s.flush() == [("content", "<")]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_llm.py -v`
Expected: FAIL — `ImportError: cannot import name 'ReasoningSplitter'`

- [ ] **Step 3: 实现 `app/llm.py`**

要点：`ReasoningSplitter` 用状态机处理 `思考` / `结束` 与 `<thinking>` / `</thinking>` 标签，
标签可能跨 chunk 断开（用缓冲 hold 住可能成为标签前缀的尾部）。`stream_chat` 用 `httpx.AsyncClient`
以 `stream=True` 请求 `{base_url}/chat/completions`，逐行解析 `data:` 帧；同时读取 `delta.reasoning_content`
与 `delta.reasoning` 直接分流到 reasoning，其余文本喂给 splitter。失败按 `max_retries` 由调用方控制，
本函数对单次请求失败抛出 `LLMError`。

```python
import asyncio
import json
import time
from dataclasses import dataclass
from typing import Awaitable, Callable

import httpx

OPEN_TAGS = ("思考", "<thinking>")
CLOSE_TAGS = ("结束", "</thinking>")


class LLMError(Exception):
    pass


@dataclass
class LLMConfig:
    nickname: str
    api_key: str
    base_url: str
    model: str
    temperature: float = 0.8
    max_tokens: int = 2048


class ReasoningSplitter:
    """把内联思考标签从正文中剥离；标签可能跨 chunk。"""

    def __init__(self):
        self._in_reasoning = False
        self._buf = ""

    def _longest_suffix(self, texts):
        best = ""
        for t in texts:
            for n in range(1, len(t)):
                if self._buf.endswith(t[:n]) and n > len(best):
                    best = t[:n]
        return best

    def feed(self, chunk):
        self._buf += chunk
        out = []
        while self._buf:
            if not self._in_reasoning:
                idx = self._buf.find(OPEN_TAGS[0])
                idx2 = self._buf.find(OPEN_TAGS[1])
                cands = [i for i in (idx, idx2) if i >= 0]
                if not cands:
                    hold = self._longest_suffix(OPEN_TAGS)
                    emit = self._buf[: len(self._buf) - len(hold)] if hold else self._buf
                    if emit:
                        out.append(("content", emit))
                    self._buf = self._buf[len(self._buf) - len(hold):] if hold else ""
                    break
                pos = min(cands)
                if pos > 0:
                    out.append(("content", self._buf[:pos]))
                tag = OPEN_TAGS[0] if self._buf.startswith(OPEN_TAGS[0]) else OPEN_TAGS[1]
                self._buf = self._buf[pos + len(tag):]
                self._in_reasoning = True
            else:
                cands = [self._buf.find(t) for t in CLOSE_TAGS]
                cands = [i for i in cands if i >= 0]
                if not cands:
                    hold = self._longest_suffix(CLOSE_TAGS)
                    emit = self._buf[: len(self._buf) - len(hold)] if hold else self._buf
                    if emit:
                        out.append(("reasoning", emit))
                    self._buf = self._buf[len(self._buf) - len(hold):] if hold else ""
                    break
                pos = min(cands)
                if pos > 0:
                    out.append(("reasoning", self._buf[:pos]))
                tag = next(t for t in CLOSE_TAGS if self._buf.startswith(t))
                self._buf = self._buf[pos + len(tag):]
                self._in_reasoning = False
        return out

    def flush(self):
        if not self._buf:
            return []
        out = [("reasoning" if self._in_reasoning else "content", self._buf)]
        self._buf = ""
        return out


async def _maybe_await(value):
    if asyncio.iscoroutine(value) or isinstance(value, Awaitable):
        await value


async def stream_chat(cfg, messages, *, timeout=120.0, on_reasoning=None, on_content=None):
    url = f"{cfg.base_url.rstrip('/')}/chat/completions"
    payload = {"model": cfg.model, "messages": messages, "stream": True,
               "temperature": cfg.temperature, "max_tokens": cfg.max_tokens}
    headers = {"Authorization": f"Bearer {cfg.api_key}", "Content-Type": "application/json"}
    splitter = ReasoningSplitter()
    reasoning_parts, content_parts = [], []
    started = time.time()
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream("POST", url, json=payload, headers=headers) as resp:
                if resp.status_code >= 400:
                    body = (await resp.aread()).decode("utf-8", "ignore")
                    raise LLMError(f"HTTP {resp.status_code}: {body[:300]}")
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data in ("", "[DONE]"):
                        continue
                    chunk = json.loads(data)
                    delta = (chunk.get("choices") or [{}])[0].get("delta", {}) or {}
                    for field in ("reasoning_content", "reasoning"):
                        text = delta.get(field)
                        if text:
                            reasoning_parts.append(text)
                            if on_reasoning:
                                await _maybe_await(on_reasoning(text))
                    text = delta.get("content")
                    if text:
                        for channel, piece in splitter.feed(text):
                            if channel == "reasoning":
                                reasoning_parts.append(piece)
                                if on_reasoning:
                                    await _maybe_await(on_reasoning(piece))
                            else:
                                content_parts.append(piece)
                                if on_content:
                                    await _maybe_await(on_content(piece))
    except LLMError:
        raise
    except Exception as exc:  # 网络/超时/解析
        raise LLMError(str(exc)) from exc
    for channel, piece in splitter.flush():
        if channel == "reasoning":
            reasoning_parts.append(piece)
            if on_reasoning:
                await _maybe_await(on_reasoning(piece))
        else:
            content_parts.append(piece)
            if on_content:
                await _maybe_await(on_content(piece))
    content = "".join(content_parts)
    return {"content": content, "reasoning": "".join(reasoning_parts),
            "elapsed_ms": int((time.time() - started) * 1000),
            "chars": len("".join(content.split()))}
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_llm.py -v`
Expected: 4 passed

- [ ] **Step 5: 提交**

```bash
git add app/llm.py tests/test_llm.py
git commit -m "feat. 流式LLM客户端与思考内容剥离"
```

---

## Task 4: 提示词模板与消息组装

**Covers:** [S6]

**Files:**
- Create: `prompts/context.md`, `prompts/topic_check.md`, `prompts/topic_gen.md`, `prompts/opening.md`, `prompts/free_debate.md`, `prompts/closing.md`, `prompts/judge.md`
- Create: `app/prompts.py`, `tests/test_prompts.py`

**Interfaces:**
- Consumes: `app.storage.format_transcript`
- Produces:
  - `app.prompts.render(text, **vars) -> str`
  - `app.prompts.load_template(name) -> str`
  - `app.prompts.load_requirements() -> str`
  - `app.prompts.build_stage_messages(*, stage, side, round_no, total_rounds, session, config) -> list[dict]`
  - `app.prompts.build_topic_check_messages(topic, requirements) -> list[dict]`
  - `app.prompts.build_topic_gen_messages(requirements, n=4) -> list[dict]`
  - `app.prompts.build_judge_messages(session, config) -> list[dict]`

- [ ] **Step 1: 写 7 个模板**（内容见下方各代码块）

`prompts/context.md`
```markdown
你正在参加一场正式的辩论大赛。以下为当前局面说明。

- 辩题：{{topic}}
- 正方：{{pro_name}}（立场：支持该辩题）
- 反方：{{con_name}}（立场：反对该辩题）
- 赛制：开场立论（一辩）→ 自由辩论（共 {{total_rounds}} 轮）→ 总结陈词 → 评委点评
- 当前阶段：{{stage_desc}}
- 你的身份：{{side_cn}}{{role_cn}}{{persona_block}}

辩论要求：立场明确、逻辑清晰、论据充分、语言凝练；须针对对方观点进行有效回应；
不得人身攻击或使用煽动性语言；使用中文作答；直接输出发言内容，不要复述本说明。
```

`prompts/opening.md`
```markdown
现在是开场立论（一辩发言）环节。请作为{{side_cn}}一辩，就辩题「{{topic}}」进行立论陈词：
明确阐述你方立场，提出 2~3 个核心论点并给出简要论证。
```

`prompts/free_debate.md`
```markdown
现在是自由辩论第 {{round}} 轮（共 {{total_rounds}} 轮）。请作为{{side_cn}}发言：
可补充己方论据、反驳对方观点、或指出对方论证中的漏洞。发言应简洁有力。
```

`prompts/closing.md`
```markdown
现在是总结陈词环节。请作为{{side_cn}}进行总结陈词：回顾并强化己方核心论点，
集中回应对方的主要质疑，并做最终升华。
```

`prompts/topic_check.md`
```markdown
请依据以下辩题评价标准，判断给定辩题是否合理。

【评价标准】
{{requirements}}

【待评价辩题】
{{topic}}

请仅输出一个 JSON 对象，不要输出任何其它内容：
{"verdict": "合理" 或 "不合理", "reason": "若不合理，用一句不超过30字的话说明理由；若合理则为空字符串"}
```

`prompts/topic_gen.md`
```markdown
请依据以下辩题评价标准，生成 {{n}} 个高质量且彼此不同的辩论题目
（须有争议、双方均衡、表述清晰、有现实意义并安全合规）。

【评价标准】
{{requirements}}

请仅输出一个 JSON 数组，不要输出任何其它内容：
[{"topic": "辩题内容", "note": "一句话说明双方论证空间"}]
```

`prompts/judge.md`
```markdown
你是本场辩论赛的评委。请依据以下完整辩论记录评判胜负。

辩题：{{topic}}
正方：{{pro_name}}；反方：{{con_name}}

【完整辩论记录】
{{transcript}}

请输出：
1) 明确判定哪一方更胜一筹；
2) 分点说明理由（可从立论、论证、反驳、临场应变、表达等方面评价）；
3) 分别给出双方改进建议。
使用中文作答。
```

- [ ] **Step 2: 写失败测试 `tests/test_prompts.py`**

```python
from app import prompts, storage


def test_render_substitutes():
    assert prompts.render("你好{{name}}！", name="世界") == "你好世界！"


def test_build_stage_messages_opening_has_no_transcript(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "CACHE_PATH", tmp_path / "s.json")
    sess = storage.init_session()
    sess["topic"] = "T"
    cfg = {"apis": {"pro": {"nickname": "甲"}, "con": {"nickname": "乙"}},
           "debate": {"personas": {"pro": "", "con": ""}}}
    msgs = prompts.build_stage_messages(stage="opening", side="pro", round_no=None,
                                        total_rounds=7, session=sess, config=cfg)
    assert msgs[0]["role"] == "system" and "T" in msgs[0]["content"]
    assert "【此前发言记录】" not in msgs[1]["content"]


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
```

- [ ] **Step 3: 运行测试确认失败**

Run: `python -m pytest tests/test_prompts.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.prompts'`

- [ ] **Step 4: 实现 `app/prompts.py`**

```python
import re
from pathlib import Path

from app import storage

PROMPTS_DIR = Path("prompts")
REQUIREMENTS_PATH = Path("DebateRequirements.txt")
ROLE_CN = {"opening": "一辩", "free": "自由辩论", "closing": "总结陈词"}
_cache = {}


def load_template(name):
    if name not in _cache:
        _cache[name] = (PROMPTS_DIR / f"{name}.md").read_text("utf-8")
    return _cache[name]


def load_requirements():
    return REQUIREMENTS_PATH.read_text("utf-8") if REQUIREMENTS_PATH.exists() else ""


def render(text, **vars):
    return re.sub(r"\{\{\s*(\w+)\s*\}\}", lambda m: str(vars.get(m.group(1).strip(), "")), text)


def _stage_desc(stage, round_no, total_rounds):
    if stage == "opening":
        return "开场立论（一辩发言）"
    if stage == "free":
        return f"自由辩论第 {round_no} 轮（共 {total_rounds} 轮）"
    return "总结陈词"


def build_stage_messages(*, stage, side, round_no, total_rounds, session, config):
    apis, debate = config["apis"], config["debate"]
    topic = session.get("topic") or debate.get("topic", "")
    side_cn = "正方" if side == "pro" else "反方"
    persona = (debate.get("personas") or {}).get(side, "")
    persona_block = f"\n- 你的辩论风格：{persona}" if persona else ""
    system = render(
        load_template("context"),
        topic=topic, pro_name=apis["pro"]["nickname"], con_name=apis["con"]["nickname"],
        total_rounds=total_rounds, stage_desc=_stage_desc(stage, round_no, total_rounds),
        side_cn=side_cn, role_cn=ROLE_CN[stage], persona_block=persona_block,
    )
    if stage == "opening":
        user = render(load_template("opening"), side_cn=side_cn, topic=topic)
    elif stage == "free":
        user = render(load_template("free_debate"), side_cn=side_cn,
                      round=round_no, total_rounds=total_rounds)
    else:
        user = render(load_template("closing"), side_cn=side_cn)
    transcript = storage.format_transcript(session)
    if stage in ("free", "closing") and transcript:
        user += "\n\n【此前发言记录】\n" + transcript
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def build_topic_check_messages(topic, requirements):
    return [{"role": "user", "content": render(load_template("topic_check"),
                                               topic=topic, requirements=requirements)}]


def build_topic_gen_messages(requirements, n=4):
    return [{"role": "user", "content": render(load_template("topic_gen"),
                                               n=n, requirements=requirements)}]


def build_judge_messages(session, config):
    apis = config["apis"]
    return [{"role": "user", "content": render(
        load_template("judge"), topic=session.get("topic", ""),
        pro_name=apis["pro"]["nickname"], con_name=apis["con"]["nickname"],
        transcript=storage.format_transcript(session))}]
```

- [ ] **Step 5: 运行测试确认通过**

Run: `python -m pytest tests/test_prompts.py -v`
Expected: 3 passed

- [ ] **Step 6: 提交**

```bash
git add prompts/ app/prompts.py tests/test_prompts.py
git commit -m "feat. 提示词模板与消息组装"
```

---

## Task 5: 事件广播器

**Covers:** [S7]

**Files:**
- Create: `app/events.py`

**Interfaces:**
- Produces: `app.events.EventBus` — `subscribe() -> asyncio.Queue`、`unsubscribe(q)`、`async publish(event, data)`

- [ ] **Step 1: 实现 `app/events.py`**

```python
import asyncio


class EventBus:
    def __init__(self):
        self._subscribers = set()

    def subscribe(self):
        q = asyncio.Queue()
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q):
        self._subscribers.discard(q)

    async def publish(self, event, data):
        for q in list(self._subscribers):
            await q.put((event, data))
```

- [ ] **Step 2: 提交**

```bash
git add app/events.py
git commit -m "feat. SSE事件广播器"
```

---

## Task 6: 辩论状态机

**Covers:** [S5, S9, S10, S12]

**Files:**
- Create: `app/debate.py`, `tests/test_debate.py`

**Interfaces:**
- Consumes: `app.llm.{stream_chat,LLMConfig,LLMError}`、`app.prompts.*`、`app.storage.*`、`app.events.EventBus`
- Produces:
  - `app.debate.AbortError`
  - `app.debate.DebateRunner(config, bus, llm=stream_chat, storage_mod=storage)`，方法 `start(force=False)`、`control(action)`、`snapshot()`；属性 `status`、`stage`、`session`

**控制语义：** `pause` 清除 `_gate`；`resume` 置位；`abort` 置 `_aborted` 并置位；`retry`/`skip`/`force`
写入 `_decision` 并置位 `_gate`（唤醒等待中的状态机）。

- [ ] **Step 1: 写失败测试 `tests/test_debate.py`**

```python
import asyncio

from app import debate as debate_mod
from app import storage
from app.events import EventBus


class FakeLLM:
    def __init__(self):
        self.calls = []

    async def __call__(self, cfg, messages, *, timeout=120.0, on_reasoning=None, on_content=None):
        self.calls.append(messages)
        user = messages[-1]["content"]
        if '"verdict"' in user:
            return {"content": '{"verdict": "合理", "reason": ""}',
                    "reasoning": "", "elapsed_ms": 1, "chars": 3}
        text = f"发言{len(self.calls)}"
        if on_content:
            await on_content(text)
        return {"content": text, "reasoning": "想了一下", "elapsed_ms": 2, "chars": len(text)}


def _cfg(rounds=2):
    api = {"api_key": "k", "base_url": "http://x", "model": "m",
           "temperature": 0.8, "max_tokens": 10}
    return {"apis": {"pro": {"nickname": "甲", **api},
                     "con": {"nickname": "乙", **api},
                     "judge": {"nickname": "丙", **api}},
            "debate": {"topic": "测试辩题", "rounds": rounds, "personas": {"pro": "", "con": ""}},
            "runtime": {"max_retries": 1, "timeout_seconds": 5, "port": 0, "auto_open_browser": False},
            "ui": {}}


def test_full_flow_order_and_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "CACHE_PATH", tmp_path / "s.json")
    monkeypatch.setattr(storage, "RESULTS_DIR", tmp_path / "Results")
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
    monkeypatch.setattr(storage, "CACHE_PATH", tmp_path / "s.json")
    monkeypatch.setattr(storage, "RESULTS_DIR", tmp_path / "Results")
    llm = FakeLLM()
    runner = debate_mod.DebateRunner(_cfg(rounds=1), EventBus(), llm=llm)
    asyncio.run(runner.start(force=True))
    assert not any('"verdict"' in c[-1]["content"] for c in llm.calls)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_debate.py -v`
Expected: FAIL — `AttributeError: module 'app.debate' has no attribute 'DebateRunner'`

- [ ] **Step 3: 实现 `app/debate.py`**

```python
import asyncio
import json
import re

from app import prompts, storage
from app.llm import LLMConfig, LLMError, stream_chat


class AbortError(Exception):
    pass


def _llm_config(api):
    return LLMConfig(nickname=api.get("nickname", ""), api_key=api.get("api_key", ""),
                     base_url=api.get("base_url", ""), model=api.get("model", ""),
                     temperature=float(api.get("temperature", 0.8)),
                     max_tokens=int(api.get("max_tokens", 2048)))


class DebateRunner:
    def __init__(self, config, bus, llm=stream_chat, storage_mod=storage):
        self.config = config
        self.bus = bus
        self.llm = llm
        self.storage = storage_mod
        self.rounds = int(config["debate"].get("rounds", 7))
        self.session = storage_mod.init_session()
        self.status = "IDLE"
        self.stage = None
        self.current = None
        self._gate = asyncio.Event()
        self._gate.set()
        self._aborted = False
        self._decision = None
        self.task = None

    def start(self, force=False):
        if not self.session.get("topic"):
            self.session["topic"] = self.config["debate"].get("topic", "")
        self.task = asyncio.create_task(self._run(force))
        return self.task

    def control(self, action):
        if action == "pause":
            self._gate.clear()
        elif action == "resume":
            self._gate.set()
        elif action == "abort":
            self._aborted = True
            self._gate.set()
        elif action in ("retry", "skip", "force"):
            self._decision = action
            self._gate.set()

    def snapshot(self):
        return {"status": self.status, "stage": self.stage,
                "total_rounds": self.rounds, "topic": self.session.get("topic", ""),
                "messages": self.session["messages"], "judge": self.session.get("judge"),
                "current": self.current}

    async def _set_status(self, status, stage=None):
        self.status = status
        self.stage = stage if stage is not None else self.stage
        self.session["status"] = status
        self.storage.save_session(self.session)
        await self.bus.publish("state", {"status": status, "stage": self.stage,
                                         "totalRounds": self.rounds})

    async def _await_gate(self):
        await self._gate.wait()
        if self._aborted:
            raise AbortError()

    async def _call(self, messages, side_key, msg_id=None):
        cfg = _llm_config(self.config["apis"][side_key])
        retries = int(self.config["runtime"].get("max_retries", 3))
        timeout = float(self.config["runtime"].get("timeout_seconds", 120))
        attempt = 0
        while True:
            await self._await_gate()
            if msg_id:
                await self.bus.publish("message_start", dict(self.current))
            accumulator = {"reasoning": "", "content": ""}

            async def on_reasoning(t):
                accumulator["reasoning"] += t
                if self.current is not None:
                    self.current["reasoning"] = accumulator["reasoning"]
                await self.bus.publish("reasoning_delta", {"id": msg_id, "text": t})

            async def on_content(t):
                accumulator["content"] += t
                if self.current is not None:
                    self.current["content"] = accumulator["content"]
                await self.bus.publish("content_delta", {"id": msg_id, "text": t})

            try:
                return await self.llm(cfg, messages, timeout=timeout,
                                      on_reasoning=on_reasoning, on_content=on_content)
            except LLMError as exc:
                attempt += 1
                if attempt <= retries:
                    await asyncio.sleep(min(2 ** attempt, 8))
                    continue
                await self._set_status("PAUSED")
                self._decision = None
                self._gate.clear()
                await self.bus.publish("error", {"stage": self.stage,
                                                 "message": str(exc), "retries": retries})
                await self._await_gate()
                decision, self._decision = self._decision, None
                if decision == "retry":
                    attempt = 0
                    continue
                if decision == "skip":
                    return {"content": "（本次发言因接口连续失败被跳过）", "reasoning": "",
                            "elapsed_ms": 0, "chars": 0}
                raise AbortError()

    async def _say(self, side, role, round_no=None):
        speaker = self.storage.speaker_label(side, role, round_no)
        msg_id = f"m{len(self.session['messages']) + 1}"
        self.current = {"id": msg_id, "side": side, "role": role, "round_no": round_no,
                        "speaker": speaker, "content": "", "reasoning": ""}
        messages = prompts.build_stage_messages(stage=role, side=side, round_no=round_no,
                                                total_rounds=self.rounds,
                                                session=self.session, config=self.config)
        result = await self._call(messages, side, msg_id=msg_id)
        self.current = None
        msg = {"id": msg_id, "side": side, "role": role, "round": round_no,
               "speaker": speaker, "content": result["content"], "reasoning": result["reasoning"],
               "elapsed_ms": result["elapsed_ms"], "chars": result["chars"]}
        self.storage.append_message(self.session, msg)
        await self.bus.publish("message_end", {"id": msg_id, "elapsed_ms": result["elapsed_ms"],
                                               "chars": result["chars"]})

    @staticmethod
    def _parse_verdict(text):
        match = re.search(r"\{.*\}", text, re.S)
        if not match:
            return False, "无法解析校验结果"
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            return False, "无法解析校验结果"
        if data.get("verdict") == "合理":
            return True, ""
        return False, data.get("reason") or "未给出理由"

    async def _validate_topic(self):
        if self.session.get("topic_source") == "generated":
            return True
        messages = prompts.build_topic_check_messages(self.session["topic"],
                                                      prompts.load_requirements())
        result = await self._call(messages, "judge")
        ok, reason = self._parse_verdict(result["content"])
        if ok:
            return True
        await self._set_status("WARNING")
        self._decision = None
        self._gate.clear()
        await self.bus.publish("warning", {"topic": self.session["topic"], "reason": reason})
        while True:
            await self._await_gate()
            decision, self._decision = self._decision, None
            if decision == "force":
                return True
            if decision:
                raise AbortError()
            self._gate.clear()

    async def _judge(self):
        self.current = {"id": "judge", "side": None, "role": "judge",
                        "speaker": "总结评价", "content": "", "reasoning": ""}
        messages = prompts.build_judge_messages(self.session, self.config)
        result = await self._call(messages, "judge", msg_id="judge")
        self.current = None
        judge = {"content": result["content"], "reasoning": result["reasoning"],
                 "elapsed_ms": result["elapsed_ms"], "chars": result["chars"]}
        self.storage.set_judge(self.session, judge)
        await self.bus.publish("judge_end", {"elapsed_ms": judge["elapsed_ms"],
                                             "chars": judge["chars"]})

    async def _run(self, force):
        try:
            if not self.session.get("topic"):
                await self._set_status("IDLE")
                return
            await self._set_status("VALIDATING", "validating")
            if not force and not await self._validate_topic():
                return
            await self._set_status("OPENING", "opening")
            await self._say("pro", "opening")
            await self._say("con", "opening")
            await self._set_status("FREE", "free")
            for r in range(1, self.rounds + 1):
                await self._say("pro", "free", r)
                await self._say("con", "free", r)
            await self._set_status("CLOSING", "closing")
            await self._say("pro", "closing")
            await self._say("con", "closing")
            await self._set_status("JUDGING", "judging")
            await self._judge()
            txt_path, md_path = self.storage.write_result(self.session)
            await self._set_status("DONE", "done")
            await self.bus.publish("done", {"txt_path": str(txt_path), "md_path": str(md_path)})
        except AbortError:
            self.storage.save_session(self.session)
            await self._set_status("ABORTED", "aborted")
```

> 说明：`_call` 每次尝试开头重发 `message_start`，前端据此重置该气泡以免重试内容重复；
> 评价阶段复用 `message_start`/`content_delta`/`message_end`（`msg_id="judge"`），前端单独渲染评价卡片。

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_debate.py -v`
Expected: 2 passed

- [ ] **Step 5: 提交**

```bash
git add app/debate.py tests/test_debate.py
git commit -m "feat. 辩论状态机与流程编排"
```

---

## Task 7: FastAPI 应用与路由

**Covers:** [S7, S10]

**Files:**
- Create: `app/main.py`, `app/__main__.py`, `tests/test_api.py`

**Interfaces:**
- Consumes: 全部 `app.*` 模块
- Produces: FastAPI 实例 `app.main.app`；路由见 [S7]

- [ ] **Step 1: 写失败测试 `tests/test_api.py`**

```python
from fastapi.testclient import TestClient

from app import config_store, storage
from app.main import create_app


def test_config_endpoints(tmp_path, monkeypatch):
    monkeypatch.setattr(config_store, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(storage, "CACHE_PATH", tmp_path / "cache" / "session.json")
    monkeypatch.setattr(storage, "RESULTS_DIR", tmp_path / "Results")
    client = TestClient(create_app())
    got = client.get("/api/config").json()
    assert got["runtime"]["port"] == 8000
    got["debate"]["rounds"] = 4
    assert client.put("/api/config", json=got).status_code == 200
    assert client.get("/api/config").json()["debate"]["rounds"] == 4


def test_state_endpoint(tmp_path, monkeypatch):
    monkeypatch.setattr(config_store, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(storage, "CACHE_PATH", tmp_path / "cache" / "session.json")
    monkeypatch.setattr(storage, "RESULTS_DIR", tmp_path / "Results")
    client = TestClient(create_app())
    assert client.get("/api/debate/state").json()["status"] == "IDLE"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_api.py -v`
Expected: FAIL — `ImportError: cannot import name 'create_app'`

- [ ] **Step 3: 实现 `app/main.py`**

```python
import asyncio
import json
from pathlib import Path

from fastapi import Body, FastAPI
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from app import config_store, prompts, storage
from app.debate import DebateRunner
from app.events import EventBus

WEB_DIR = Path("web")


def _sse(event, data):
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def create_app():
    app = FastAPI(title="DebateSimulator")
    bus = EventBus()
    state = {"runner": None, "config": None}

    if WEB_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")

    @app.get("/")
    def index():
        return FileResponse(str(WEB_DIR / "index.html"))

    @app.get("/api/config")
    def get_config():
        return config_store.load_config()

    @app.put("/api/config")
    def put_config(payload: dict = Body(...)):
        config_store.save_config(payload)
        return {"ok": True}

    @app.post("/api/topic/generate")
    async def generate_topics(payload: dict = Body(default={})):
        from app.llm import stream_chat
        cfg = config_store.load_config()
        n = int(payload.get("n", 4))
        messages = prompts.build_topic_gen_messages(prompts.load_requirements(), n)
        from app.debate import _llm_config
        result = await stream_chat(_llm_config(cfg["apis"]["judge"]), messages,
                                   timeout=float(cfg["runtime"]["timeout_seconds"]))
        text = result["content"]
        start, end = text.find("["), text.rfind("]")
        try:
            topics = json.loads(text[start:end + 1])
        except Exception:
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
        state["runner"] = runner
        runner.start(force=bool(payload.get("force")))
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
            return {"status": "IDLE", "stage": None, "messages": [], "judge": None,
                    "current": None, "topic": ""}
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

        return StreamingResponse(gen(), media_type="text/event-stream")

    @app.get("/api/history")
    def history():
        storage.RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        return {"files": sorted(p.name for p in storage.RESULTS_DIR.glob("Result_*.txt"), reverse=True)}

    @app.get("/api/history/{name}")
    def history_item(name: str):
        path = storage.RESULTS_DIR / name
        if not path.exists() or path.suffix != ".txt":
            return {"ok": False}
        return {"ok": True, "content": path.read_text("utf-8")}

    return app


app = create_app()
```

`app/__main__.py`
```python
import uvicorn

from app import config_store

if __name__ == "__main__":
    cfg = config_store.load_config()
    uvicorn.run("app.main:app", host="127.0.0.1", port=int(cfg["runtime"]["port"]), reload=False)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_api.py -v`
Expected: 2 passed

- [ ] **Step 5: 提交**

```bash
git add app/main.py app/__main__.py tests/test_api.py
git commit -m "feat. FastAPI应用与SSE路由"
```

---

## Task 8: 前端界面

**Covers:** [S9, S12, S7]

**Files:**
- Create: `web/index.html`, `web/styles.css`, `web/app.js`

**Interfaces:**
- Consumes: REST + SSE（[S7]）
- Produces: 用户界面

- [ ] **Step 1: 写 `web/index.html`** — 骨架：顶部（双方昵称）、中部左右分栏 + 中间时间线容器、底部控制条、设置抽屉、历史面板、`<script src="/static/app.js">`、`<link rel="stylesheet" href="/static/styles.css">`。

- [ ] **Step 2: 写 `web/styles.css`** — CSS 变量实现深/浅主题；`.col.pro` 左侧、`.col.con` 右侧；`.bubble`、`.thinking`（默认 `max-height:0` 折叠，`.open` 展开）、`.badge`；控制条与抽屉样式。

- [ ] **Step 3: 写 `web/app.js`** — 关键逻辑：

```javascript
const $ = (s) => document.querySelector(s);
let config = null;

async function loadConfig() {
  config = await (await fetch("/api/config")).json();
  // 填充表单（api_key 打码显示，仅用户重输时覆盖）
}
async function saveConfig() { /* 收集表单 -> PUT /api/config */ }

const bubbles = new Map();
function ensureBubble(d) {
  let el = bubbles.get(d.id);
  if (el) { el.querySelector(".content").textContent = ""; el.querySelector(".thinking-body").textContent = ""; return el; }
  el = document.createElement("div");
  el.className = `bubble ${d.side || ""}`;
  el.innerHTML = `<div class="badge">${d.speaker || "评价"}</div>
    <div class="thinking"><button class="toggle">思考</button><div class="thinking-body"></div></div>
    <div class="content"></div><div class="meta"></div>`;
  el.querySelector(".toggle").onclick = () => el.querySelector(".thinking").classList.toggle("open");
  ($(`#col-${d.side}`) || $("#timeline")).appendChild(el);
  bubbles.set(d.id, el);
  return el;
}
function appendText(id, cls, text) {
  const el = bubbles.get(id); if (!el) return;
  el.querySelector(cls).textContent += text;
  el.scrollIntoView({ block: "nearest" });
}

function connect() {
  const es = new EventSource("/api/events");
  es.addEventListener("state", (e) => setStatus(JSON.parse(e.data)));
  es.addEventListener("message_start", (e) => ensureBubble(JSON.parse(e.data)));
  es.addEventListener("reasoning_delta", (e) => { const d = JSON.parse(e.data); appendText(d.id, ".thinking-body", d.text); });
  es.addEventListener("content_delta", (e) => { const d = JSON.parse(e.data); appendText(d.id, ".content", d.text); });
  es.addEventListener("message_end", (e) => { const d = JSON.parse(e.data); const el = bubbles.get(d.id); if (el) el.querySelector(".meta").textContent = `${d.chars} 字 · ${(d.elapsed_ms/1000).toFixed(1)}s`; });
  es.addEventListener("warning", (e) => showWarning(JSON.parse(e.data)));
  es.addEventListener("error", (e) => showError(JSON.parse(e.data)));
  es.addEventListener("done", (e) => { const d = JSON.parse(e.data); finish(d, config); });
  es.onerror = () => { es.close(); setTimeout(connect, 1500); };
}

async function recover() {
  const s = await (await fetch("/api/debate/state")).json();
  setStatus(s);
  (s.messages || []).forEach((m) => { ensureBubble(m);
    bubbles.get(m.id).querySelector(".content").textContent = m.content;
    bubbles.get(m.id).querySelector(".thinking-body").textContent = m.reasoning || ""; });
  if (s.judge) { ensureBubble({ id: "judge", speaker: "总结评价" });
    bubbles.get("judge").querySelector(".content").textContent = s.judge.content; }
}

connect(); loadConfig(); recover();
```

控制条按钮调用 `/api/debate/control`（`pause`/`resume`/`abort`/`retry`/`skip`/`force`）；
「生成选题」调用 `/api/topic/generate` 渲染候选列表；`finish()` 按 `ui.sound` 播放提示音；
主题通过 `document.documentElement.dataset.theme` 切换并写入 `ui.theme`。

- [ ] **Step 4: 手动验证**

Run: `python -m app`（另开终端）
Expected: 浏览器打开 `http://127.0.0.1:8000`，界面正常渲染，设置可保存。

- [ ] **Step 5: 提交**

```bash
git add web/index.html web/styles.css web/app.js
git commit -m "feat. 前端辩论界面与实时渲染"
```

---

## Task 9: 启动脚本、文档与端到端验证

**Covers:** [S13, S1]

**Files:**
- Create: `run.bat`, `README.md`, `tests/mock_openai.py`

**Interfaces:**
- Consumes: 全部
- Produces: 可运行交付

- [ ] **Step 1: 写 `tests/mock_openai.py`** — 一个最小的 FastAPI/`http.server` 实现 `/v1/chat/completions`，按请求内容返回流式 `data:` 帧（含 `reasoning_content` 与 `content`），用于离线端到端验证。

- [ ] **Step 2: 写 `run.bat`**

```bat
@echo off
setlocal
cd /d %~dp0
if not exist .venv python -m venv .venv
call .venv\Scripts\activate
python -m pip install -q -r requirements.txt
start "" http://127.0.0.1:8000
python -m app
```

- [ ] **Step 3: 写 `README.md`** — 项目简介、安装、配置说明（三份 API、辩题、轮数）、启动方式、结果文件说明、目录结构。

- [ ] **Step 4: 端到端验证**

1. 启动 mock：`python -m tests.mock_openai`（监听 8001）。
2. 将 `config/config.json` 的三个 `base_url` 指向 `http://127.0.0.1:8001/v1`。
3. 启动应用：`python -m app`。
4. 设置辩题与轮数（如 2 轮），点击开始，观察：
   - SSE 逐字渲染、思考区块折叠正常；
   - 全流程 8 条发言（2 轮时）→ 评价 → `Results/Result_*.txt` 生成。
5. 校验 txt 首行为辩题、每条为「身份+正文」。
6. 运行全量测试：`python -m pytest -v`，Expected: 全部通过。

- [ ] **Step 5: 提交**

```bash
git add run.bat README.md tests/mock_openai.py
git commit -m "add. 启动脚本、文档与端到端验证工具"
```

