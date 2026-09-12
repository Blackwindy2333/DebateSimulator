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
