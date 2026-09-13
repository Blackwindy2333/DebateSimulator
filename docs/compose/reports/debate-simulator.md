---
feature: debate-simulator
status: delivered
specs:
  - docs/compose/specs/2026-09-12-debate-simulator-design.md
plans:
  - docs/compose/plans/2026-09-12-debate-simulator.md
branch: main
commits: cdc0387..1714a65
---

# AI 辩论模拟器（DebateSimulator）— Final Report

## What Was Built

一个本地单机 Web 应用：通过 OpenAI 兼容接口驱动两个 AI 分别扮演辩论的正反方，
围绕一个辩题完成 **一辩立论 → 自由辩论 N 轮 → 总结陈词** 的完整赛制，
再由第三个 AI 担任评委判定「哪方更胜一筹」并说明理由。全过程以 SSE 逐字实时显示在网页上，
刷新浏览器不中断，结束后自动落盘。

应用解决了四个具体问题：**赛制编排**（把多阶段、多轮次、带完整上下文的对话序列自动化）、
**选题质量把关**（按仓库内 `DebateRequirements.txt` 的标准让 AI 判定辩题是否合格，
不合格则暂停并给出理由）、**推理内容与发言内容的分离显示**
（把 `reasoning_content` / `<thinking>` 等思考内容剥离到独立的可折叠区块），
以及 **可观测性**（双日志：操作日志记录全过程，请求日志记录每次 API 请求的完整请求体）。

## Architecture

单机双进程结构（同一进程内）：FastAPI 后端负责编排与落盘，原生 HTML/CSS/JS 前端负责渲染，
两者通过 SSE 单向推送 + REST 双向控制通信。辩论跑在服务端异步任务里，与前端连接解耦。

```
浏览器 (web/)
  │  GET /api/events  ← SSE 事件流
  │  POST /api/debate/start | /control
  ▼
app/main.py  ── FastAPI 路由、SSE 端点、config/history REST
  │
  ├─ app/debate.py   DebateRunner：状态机、控制信号、重试
  │     ├─ app/prompts.py   模板加载 + 消息组装（含上下文注入）
  │     ├─ app/llm.py       build_payload 请求体构造 + stream_chat 流式调用 + ReasoningSplitter
  │     ├─ app/storage.py   缓存生命周期 + 结果落盘
  │     ├─ app/logbook.py   双日志（操作日志 + API 请求日志）
  │     └─ app/events.py    EventBus 广播
  │
  ├─ app/config_store.py    config/config.json 持久化
  └─ prompts/*.md           7 个中文提示词模板
```

**状态机**（`DebateRunner._run`）：

```
IDLE → VALIDATING →[不合格]→ WARNING ──force──┐
                  └─[合格]──────────────────┐ │
                                          ▼ ▼
                       OPENING → FREE(1..N) → CLOSING → JUDGING → DONE → 落盘
```

每个发言阶段**开始前**会 `await` 一个 `asyncio.Event` 门闩（`_gate`），
控制指令通过写 `_decision` + 置位门闩来唤醒状态机，从而统一实现
暂停/继续/中止/重试/跳过/强行开始六种控制。

**关键接口**：

| 模块 | 主要符号 |
| --- | --- |
| `app/config_store.py` | `DEFAULT_CONFIG`、`load_config()`、`save_config()`、`merge_defaults()` |
| `app/storage.py` | `init_session()`、`append_message()`、`set_judge()`、`speaker_label()`、`format_transcript()`、`write_result()` |
| `app/llm.py` | `LLMConfig`、`LLMError`、`build_payload(cfg, messages)`、`ReasoningSplitter`、`stream_chat(cfg, messages, *, timeout, on_reasoning, on_content, logger)` |
| `app/logbook.py` | `start_session()`、`operation(action, detail)`、`api_request(nickname, url, payload, label)`、`paths()` |
| `app/prompts.py` | `build_stage_messages()`、`build_topic_check_messages()`、`build_topic_gen_messages()`、`build_judge_messages()` |
| `app/debate.py` | `DebateRunner(config, bus, llm=stream_chat, storage_mod=storage)`、`AbortError` |
| `app/events.py` | `EventBus.subscribe() / unsubscribe() / publish()` |

**SSE 事件**：`state` · `message_start` · `reasoning_delta` · `content_delta` · `message_end` ·
`warning` · `error` · `judge_end` · `done`。评价阶段复用 `message_start`/`content_delta`/`message_end`
（`id="judge"`、`side=null`），前端据此把它渲染到点评面板而非正反方分栏。

### Design Decisions

- **辩论状态放在服务端而非浏览器**。状态机由 FastAPI 的 `create_task` 驱动，
  前端只是订阅者；因此刷新/掉线不会中断辩论，重连后 `/api/debate/state` 即可恢复现场。
- **控制信号统一走门闩 + 决策槽**，而不是为每种控制写一条状态转移分支。
  暂停与「等待用户决策」本质都是「阻塞直到被唤醒」，共用一套机制避免了状态爆炸。
- **`requirements.txt` 按实际测试版本钉死**（fastapi 0.141.1 / pydantic 2.13.4 等），
  而不是按设计时的预估版本——保证 `run.bat` 装出来的环境就是通过测试的那个。
- **思考标签只信任两类**：`<thinking>` / `<thought>`（可出现在正文任意位置）与
  `思考…结束`（**仅当位于整段输出的最开头**时才识别）。原因是后者是极常见的中文词汇，
  无锚定地识别会吞掉正常语句。
- **API Key 明文存本地、界面打码**。`GET /api/config` 返回 `sk-abc****mnop` 形式，
  `PUT` 时若收到含 `**` 的值则保留磁盘上的原密钥——用户无需重输即可改其它字段。
- **思考模式按接口独立控制**，请求体固定发送 `thinking.type`，并**仅在开启思考时才附带**
  `reasoning_effort`。理由：不接受该字段的端点在不启用思考时收到它容易直接报错，
  条件发送既表达了用户意图又保住了兼容性。
- **不再发送 `max_tokens`**，把输出长度交给服务端默认值，避免各家的上限差异导致截断或报错。
- **日志分两份而不是一份**。操作日志给人读（复盘流程），请求日志给机器读（逐字比对 payload）。
  两份都在应用启动时按时间戳新建，历史日志不被覆盖。

## Usage

```bat
run.bat                 :: 建虚拟环境 + 装依赖 + 起服务 + 自动开浏览器
```

手动：`pip install -r requirements.txt` 然后 `python -m app`（默认 `http://127.0.0.1:8000`）。

在设置抽屉中填写三项后点「开始辩论」：

| 配置项 | 说明 |
| --- | --- |
| 正方 / 反方 / 总结评价 接口 | 各自的 昵称 / API Key / Base URL / 模型 / 温度 |
| 思考模式 | 每份接口单独开关，对应请求体 `thinking.type` = `enabled` / `disabled` |
| 思考强度 | `low` / `high` / `max`，对应 `reasoning_effort`；关闭思考时不发送 |
| 辩题 | 手填，或点「生成候选选题」拿 3~5 个候选点选（此来源会**跳过**合理性校验） |
| 自由辩论轮数 | 设为 N，则正反双方在自由辩论阶段**各有 N 次**发言 |
| 辩论风格 | 可选，注入到对应方的 system prompt |

控制：开始 / 暂停 / 继续 / 中止；选题不合格时出现「强行开始 / 返回修改辩题」；
接口连续失败时出现「重试本次发言 / 跳过本次发言 / 中止辩论」。

离线验证（不消耗额度）：

```bash
python -m tests.mock_openai        # 终端 A：假接口，监听 8001
# 把三个 Base URL 改为 http://127.0.0.1:8001/v1，再 python -m app
```

结果：`Results/Result_YYYYMMDD_HHMMSS.txt`（第 1 行辩题，其后每条为「发言者身份」+ 正文，
末尾附「总结评价」段），并输出同名 `.md`。

日志：`Logs/Operations_<时间>.log`（操作与变更）与 `Logs/ApiRequests_<时间>.log`
（每次请求的完整请求体）。

## Verification

`python -m pytest -q` → **39 passed**（9 个测试文件，约 26 秒）。

| 测试文件 | 覆盖 |
| --- | --- |
| `test_config_store.py` (4) | 默认值深合并、文件创建、读写往返、**默认浅色且无 max_tokens** |
| `test_storage.py` (4) | 发言者标签、启动清缓存、txt 落盘格式、记录拼接 |
| `test_llm.py` (6) | 思考标签剥离：纯文本、`<thinking>` 块、跨 chunk 断标签、中文锚定、**中文误伤防护**、flush |
| `test_payload.py` (2) | 请求体构造：开思考时含 `reasoning_effort`、关思考时省略、**无 max_tokens** |
| `test_logbook.py` (4) | 双日志文件创建、操作记录落盘、请求日志含完整 payload、未显式开会话时自动落盘 |
| `test_prompts.py` (4) | 变量替换、一辩不带过往发言、自由辩论带全部发言、人设注入 |
| `test_debate.py` (6) | 8 条发言顺序与落盘、force 跳过校验、不合格→WARNING→force、中止中断、思考参数映射与非法值回退 |
| `test_api.py` (6) | 配置读写、密钥打码与保留、状态端点、历史读写、**路径穿越拦截**、**启动清缓存** |
| `test_e2e.py` (2) | 对着进程内假接口跑完整辩论；校验请求携带全量历史且日志记录了完整 payload |

端到端测试是真正的验证证据：它在后台线程起一个假 OpenAI 接口（会先吐 `reasoning_content`
再吐 `content` 的 SSE 流），用**真实的** `stream_chat` 跑完 2 轮完整辩论，断言
8 条发言的先后顺序、正文非空、思考内容**未混入正文**、评委点评含「更胜一筹」、
以及 `Results/*.txt` 的行序格式正确。

前端另经一次真实浏览器（Edge via Playwright）加载确认：页面渲染、`app.js` 正常初始化
（快照中「共 7 轮」来自读到的配置）、按钮初始禁用态正确。

## Journey Log

- [pivot] 思考标签原本设计为无锚定的 `思考` / `结束`，复查时发现会吞掉「让我思考这个问题」这类正常语句——改为 `<thinking>` 可任意位置、中文标记仅锚定流首。
- [pivot] `DebateRunner.start` 原计划写成用 `asyncio.create_task` 的同步方法，在无运行循环处构造时直接抛错——改成协程，由 API 层 `create_task` 驱动。
- [fix] `_judge` 曾以 `msg_id="judge"` 调用公共 `_call`，而那时 `self.current` 是 `None`，`dict(None)` 崩溃——为评价调用补上自己的 live 条目。
- [fix] 历史下载路由用普通 `{name}` 路径参数时，Starlette 根本不会把 `..` 路由进来，守卫形同虚设——改用 `{name:path}` + `resolve()` 包含性检查，让守卫真正生效。
- [lesson] `requirements.txt` 一开始按预估钉版本，与实际环境不符；改为按跑通测试的版本钉死，环境可复现。

## Source Materials

| File | Role | Notes |
|------|------|-------|
| `docs/compose/specs/2026-09-12-debate-simulator-design.md` | 设计文档 | 13 个带锚点小节，架构与约定的权威来源 |
| `docs/compose/plans/2026-09-12-debate-simulator.md` | 实施计划 | 9 个任务；实现时对 `ReasoningSplitter` 与 `start()` 做了上面 Journey Log 记录的修正 |
| `DebateRequirements.txt` | 选题评价标准 | 运行时由 `prompts.py` 读入并注入校验/生成提示词 |
