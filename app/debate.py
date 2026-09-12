import asyncio
import json
import re

from app import prompts, storage
from app.llm import LLMConfig, LLMError, stream_chat

SKIP_NOTICE = "（本次发言因接口连续失败被跳过）"


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

    # ---- 外部接口 ----
    async def start(self, force=False):
        if not self.session.get("topic"):
            self.session["topic"] = self.config["debate"].get("topic", "")
        await self._run(force)

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

    # ---- 内部 ----
    async def _set_status(self, status, stage=None):
        self.status = status
        if stage is not None:
            self.stage = stage
        self.session["status"] = status
        self.storage.save_session(self.session)
        await self.bus.publish("state", {"status": status, "stage": self.stage,
                                         "totalRounds": self.rounds})

    async def _await_gate(self):
        await self._gate.wait()
        if self._aborted:
            raise AbortError()

    async def _await_decision(self):
        """等待 retry/skip/force/abort 之一；若仅被 resume 唤醒则继续等待。"""
        while True:
            await self._await_gate()
            decision, self._decision = self._decision, None
            if decision:
                return decision
            self._gate.clear()

    async def _call(self, messages, side_key, msg_id=None):
        cfg = _llm_config(self.config["apis"][side_key])
        retries = int(self.config["runtime"].get("max_retries", 3))
        timeout = float(self.config["runtime"].get("timeout_seconds", 120))
        attempt = 0
        while True:
            await self._await_gate()
            on_reasoning = on_content = None
            if msg_id is not None:
                await self.bus.publish("message_start", dict(self.current))
                accumulator = {"reasoning": "", "content": ""}

                async def on_reasoning(text):
                    accumulator["reasoning"] += text
                    self.current["reasoning"] = accumulator["reasoning"]
                    await self.bus.publish("reasoning_delta", {"id": msg_id, "text": text})

                async def on_content(text):
                    accumulator["content"] += text
                    self.current["content"] = accumulator["content"]
                    await self.bus.publish("content_delta", {"id": msg_id, "text": text})

            try:
                return await self.llm(cfg, messages, timeout=timeout,
                                      on_reasoning=on_reasoning, on_content=on_content)
            except LLMError as exc:
                attempt += 1
                if attempt <= retries:
                    await asyncio.sleep(min(2 ** attempt, 8))
                    continue
                await self._set_status("PAUSED")
                await self.bus.publish("error", {"stage": self.stage, "message": str(exc),
                                                 "retries": retries})
                self._gate.clear()
                decision = await self._await_decision()
                if decision == "retry":
                    attempt = 0
                    continue
                if decision == "skip":
                    return {"content": SKIP_NOTICE, "reasoning": "", "elapsed_ms": 0, "chars": 0}
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
        await self.bus.publish("warning", {"topic": self.session["topic"], "reason": reason})
        self._gate.clear()
        decision = await self._await_decision()
        if decision == "force":
            return True
        raise AbortError()

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
