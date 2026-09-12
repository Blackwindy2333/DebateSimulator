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
