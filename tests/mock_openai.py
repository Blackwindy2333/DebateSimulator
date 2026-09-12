"""离线端到端验证用的假 OpenAI 兼容接口。

用法：
    python -m tests.mock_openai        # 监听 http://127.0.0.1:8001

然后把 config/config.json 中三个 base_url 指向
    http://127.0.0.1:8001/v1
即可在不消耗真实额度的情况下跑完整场辩论。
"""
import asyncio
import json

import uvicorn
from fastapi import FastAPI
from fastapi.responses import StreamingResponse

app = FastAPI(title="MockOpenAI")

DEBATE_PIECES = [
    "首先，", "对方辩友的论点", "建立在一个", "未经证实的假设之上。",
    "我方认为，", "这一论断忽略了", "现实情境中的复杂性，", "因此难以成立。",
]
JUDGE_MARKER = "请依据以下完整辩论记录"


def _sse(delta):
    return f"data: {json.dumps({'choices': [{'delta': delta}]}, ensure_ascii=False)}\n\n"


def reply_for(payload):
    last = (payload.get("messages") or [{}])[-1].get("content", "")
    if '"verdict"' in last:
        return {"reasoning": "", "content": '{"verdict": "合理", "reason": ""}'}
    if "JSON 数组" in last:
        return {"reasoning": "", "content": json.dumps([
            {"topic": "人工智能应当被赋予法律人格",
             "note": "正方主张权利主体地位，反方强调责任归属难题"},
            {"topic": "短视频平台应强制公开创作者的实名信息",
             "note": "正方重知情权与治理，反方重创作自由与隐私"},
            {"topic": "城市应全面禁止私人燃油车上路",
             "note": "正方重环保与公共健康，反方重经济成本与出行公平"},
        ], ensure_ascii=False)}
    if JUDGE_MARKER in last:
        return {"reasoning": "先比较双方论证的完整度与针对性，再下判断。",
                "content": "判定：正方更胜一筹。\n理由：\n1) 立论结构更完整；\n"
                           "2) 反驳更贴合对方论点；\n3) 表达更凝练。\n"
                           "建议：反方需加强数据支撑，正方需回应举证责任问题。"}
    return {"reasoning": "我需要先梳理对方的论证结构，再给出针对性的回应。",
            "content": "".join(DEBATE_PIECES)}


@app.post("/v1/chat/completions")
async def chat_completions(payload: dict):
    reply = reply_for(payload)

    async def gen():
        if reply["reasoning"]:
            for i in range(0, len(reply["reasoning"]), 4):
                yield _sse({"reasoning_content": reply["reasoning"][i:i + 4]})
                await asyncio.sleep(0.005)
        for i in range(0, len(reply["content"]), 3):
            yield _sse({"content": reply["content"][i:i + 3]})
            await asyncio.sleep(0.005)
        yield "data: [DONE]\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8001, log_level="warning")
