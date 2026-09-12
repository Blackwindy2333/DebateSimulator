import inspect
import json
import time
from dataclasses import dataclass

import httpx

# 互为配对的思考标签：开标签可出现在正文任意位置
REASONING_PAIRS = (("<thinking>", "</thinking>"), ("<thought>", "</thought>"))
# 中文锚定标签：仅在流的最开头（尚未输出任何正文）时才被识别为思考起始，
# 避免把“让我思考这个问题”这类正常表述误判为思考区。
ANCHORED_PAIR = ("思考", "结束")

OPEN_TAGS = tuple(pair[0] for pair in REASONING_PAIRS)


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
    """把内联思考内容从正文中剥离；标签可能跨 chunk 断开。"""

    def __init__(self):
        self._in_reasoning = False
        self._close_tag = None
        self._buf = ""
        self._at_start = True

    def _suffix_hold(self, tags):
        best = ""
        for tag in tags:
            for n in range(1, len(tag)):
                if n > len(best) and self._buf.endswith(tag[:n]):
                    best = tag[:n]
        return best

    def _find_opener(self):
        found = None
        for open_tag, close_tag in REASONING_PAIRS:
            idx = self._buf.find(open_tag)
            if idx >= 0 and (found is None or idx < found[0]):
                found = (idx, open_tag, close_tag)
        if found is None and self._at_start and self._buf.startswith(ANCHORED_PAIR[0]):
            found = (0, ANCHORED_PAIR[0], ANCHORED_PAIR[1])
        return found

    def feed(self, chunk):
        self._buf += chunk
        out = []
        while self._buf:
            if self._in_reasoning:
                idx = self._buf.find(self._close_tag)
                if idx < 0:
                    hold = self._suffix_hold((self._close_tag,))
                    emit = self._buf[: len(self._buf) - len(hold)] if hold else self._buf
                    if emit:
                        out.append(("reasoning", emit))
                    self._buf = self._buf[len(self._buf) - len(hold):] if hold else ""
                    break
                if idx > 0:
                    out.append(("reasoning", self._buf[:idx]))
                self._buf = self._buf[idx + len(self._close_tag):]
                self._in_reasoning = False
                self._close_tag = None
            else:
                found = self._find_opener()
                if found is None:
                    holds = OPEN_TAGS + ((ANCHORED_PAIR[0],) if self._at_start else ())
                    hold = self._suffix_hold(holds)
                    emit = self._buf[: len(self._buf) - len(hold)] if hold else self._buf
                    self._buf = self._buf[len(self._buf) - len(hold):] if hold else ""
                    if emit:
                        out.append(("content", emit))
                        if emit.strip():
                            self._at_start = False
                    break
                idx, open_tag, close_tag = found
                if idx > 0:
                    emit = self._buf[:idx]
                    out.append(("content", emit))
                    if emit.strip():
                        self._at_start = False
                self._buf = self._buf[idx + len(open_tag):]
                self._in_reasoning = True
                self._close_tag = close_tag
        return out

    def flush(self):
        if not self._buf:
            return []
        out = [("reasoning" if self._in_reasoning else "content", self._buf)]
        self._buf = ""
        return out


async def _maybe_await(value):
    if inspect.isawaitable(value):
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
                    delta = (chunk.get("choices") or [{}])[0].get("delta") or {}
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
    except Exception as exc:  # 网络/超时/JSON 解析失败
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
