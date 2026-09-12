# AI 辩论模拟器（DebateSimulator）设计文档

> [!NOTE]
> This document may not reflect the current implementation.
> See the final report for up-to-date state:
> [Final Report](../reports/debate-simulator.md)

**日期：** 2026-09-12
**状态：** 已批准

## [S1] 问题陈述

需要一个本地运行的 Web 应用：通过 OpenAI 格式的 API 让两个 AI 分别扮演辩论的正方与反方，
围绕一个辩题进行结构化辩论（一辩发言 → 自由辩论 → 总结陈词），由第三个 AI 对辩论结果进行
评价，全过程在网页上实时显示。所有配置需持久化保存，所有发言记录需落盘。

辩题合理性判定依据仓库根目录的 `DebateRequirements.txt`。

## [S2] 方案总览

单机应用，分为后端编排与前端展示两层：

- **后端**：Python 3.13 + FastAPI + uvicorn。负责配置持久化、辩论状态机编排、调用三家
  OpenAI 兼容接口、解析流式响应（含思考内容）、落盘结果，并通过 SSE 向前端推送实时事件。
- **前端**：原生 HTML/CSS/JS 单页。左右分栏展示正反双方，实时流式渲染发言与思考区块，
  提供设置面板、控制条与历史回放。
- **运行模型**：辩论作为服务端异步任务运行；前端通过 SSE 订阅事件，刷新页面不中断辩论
  （前端重连后可拉取当前完整状态）。

## [S3] 项目结构

```
DebateSimulator/
├─ app/
│  ├─ __init__.py
│  ├─ main.py          # FastAPI 入口：静态资源、REST 路由、SSE 事件流
│  ├─ debate.py        # 辩论状态机（编排、暂停/继续/中止、重试）
│  ├─ llm.py           # OpenAI 格式客户端：流式请求 + 思考内容解析
│  ├─ config_store.py  # config/config.json 读写
│  ├─ storage.py       # cache/session.json 管理 + Results 落盘
│  ├─ prompts.py       # 加载 prompts/*.md 并拼装上下文
│  └─ events.py        # 广播器：向所有 SSE 订阅者推送事件
├─ prompts/
│  ├─ context.md       # 每个请求前置的“当前局面”介绍
│  ├─ topic_check.md   # 选题合理性校验
│  ├─ topic_gen.md     # 选题生成
│  ├─ opening.md       # 一辩发言
│  ├─ free_debate.md   # 自由辩论
│  ├─ closing.md       # 总结陈词
│  └─ judge.md         # 最终评价
├─ web/
│  ├─ index.html
│  ├─ styles.css
│  └─ app.js
├─ config/config.json          # 持久化配置（明文，前端打码显示）
├─ cache/session.json          # 运行时缓存（进程启动时删除重建）
├─ Results/                    # 结果输出目录
├─ tests/                      # pytest 测试
├─ requirements.txt
├─ run.bat
└─ README.md
```

## [S4] 配置与持久化

配置文件 `config/config.json`，结构如下（缺失字段以默认值补全后写回）：

```jsonc
{
  "apis": {
    "pro":   { "nickname": "正方", "api_key": "", "base_url": "https://api.openai.com/v1",
               "model": "", "temperature": 0.8, "max_tokens": 2048 },
    "con":   { "nickname": "反方", "api_key": "", "base_url": "https://api.openai.com/v1",
               "model": "", "temperature": 0.8, "max_tokens": 2048 },
    "judge": { "nickname": "裁判", "api_key": "", "base_url": "https://api.openai.com/v1",
               "model": "", "temperature": 0.3, "max_tokens": 2048 }
  },
  "debate": { "topic": "", "rounds": 7, "personas": { "pro": "", "con": "" } },
  "runtime": { "max_retries": 3, "timeout_seconds": 120, "port": 8000, "auto_open_browser": true },
  "ui": { "theme": "dark", "sound": true }
}
```

规则：
- 读取时与默认值深合并，保证向后兼容；写回时保留未知字段。
- `api_key` 本地明文存储；前端展示时打码（如 `sk-****1234`），仅在用户重新输入时覆盖。
- 同一时刻只保留一套活动配置。

## [S5] 辩论流程状态机

状态枚举：`IDLE` → `VALIDATING` → (`OPENING` → `FREE` → `CLOSING` → `JUDGING` → `DONE`)，另有
`WARNING`（选题不合格暂停）与 `PAUSED`（运行中暂停/出错暂停）两个挂起态。

```
IDLE ─点击开始→ VALIDATING ─┬─合理→ OPENING ─→ FREE(1..N) ─→ CLOSING ─→ JUDGING ─→ DONE ─落盘
                            └─不合理→ WARNING(附理由) ─┬─用户改题→ VALIDATING
                                                       └─强行开始→ OPENING
```

阶段规则：
- **VALIDATING**：调用总结评价 API，按 [S6] 校验辩题。若辩题来源为 `generated`（API 生成）则
  **跳过校验**直接进入 OPENING。
- **OPENING**：依次请求正方、反方进行一辩发言。此阶段 prompt 仅简述现状并请其发言，
  **不携带过往发言正文**。
- **FREE**：共 `rounds` 轮；每轮先正方后反方，双方各有 `rounds` 次发言机会（共 2N 条）。
  每次请求**携带缓存中的全部过往发言**。
- **CLOSING**：依次请求正方、反方总结陈词，**携带全部过往发言**。
- **JUDGING**：将全量记录发往总结评价 API，产出「哪方更胜一筹 + 原因」。
- **DONE**：落盘结果（[S11]）。

每个发言步骤**开始前**检查控制信号：`pause` 阻塞等待、`abort` 立即终止并落盘已生成内容。

## [S6] Prompt 体系与上下文注入

- `prompts/*.md` 为模板，使用 `{{var}}` 占位符，由 `prompts.py` 渲染。
- 每个请求的最终消息结构：
  1. **system**：`context.md` 渲染后的「当前局面介绍」——辩题、双方昵称、当前所处阶段与位置、
     规则说明、双方人设。
  2. **user**：阶段固定 prompt（如「你正在参加一场辩论大赛，作为正方，主题是…，现在是自由
     辩论第 x 轮，共 y 轮」）+ 过往发言记录块（按 [S11] 缓存格式，OPENING 阶段为空）。
- **选题校验**（`topic_check.md`）：注入 `DebateRequirements.txt` 全文与待检辩题，
  **强制 JSON 输出** `{"verdict": "合理"|"不合理", "reason": "…"}`。理由必须简短。
  若端点不支持 `response_format: json_object`，降级为强格式 prompt + 正则提取；再失败则视为
  `不合理` 并附带「无法解析校验结果」理由。
- **选题生成**（`topic_gen.md`）：一次生成 3~5 个候选，JSON 数组
  `[{"topic": "...", "note": "..."}]`，其中 note 为简短说明，供前端挑选。
- **人设**：若配置了 `personas.pro` / `personas.con`，拼入对应固定 prompt。

## [S7] 流式与 SSE 事件协议

后端→前端事件（`text/event-stream`，每事件 `event: <type>` + `data: <json>`）：

| 事件 | data | 说明 |
| --- | --- | --- |
| `state` | `{status, stage, round?, totalRounds?}` | 阶段/状态变化 |
| `message_start` | `{id, side, role, round?, speaker}` | 一条发言开始 |
| `reasoning_delta` | `{id, text}` | 思考内容增量 |
| `content_delta` | `{id, text}` | 正式发言增量 |
| `message_end` | `{id, elapsed_ms, chars}` | 一条发言结束 |
| `warning` | `{topic, reason}` | 选题不合格，进入 WARNING |
| `error` | `{stage, message, retries}` | 调用失败，进入 PAUSED |
| `judge_delta` | `{text}` | 评价正文增量 |
| `judge_end` | `{elapsed_ms, chars}` | 评价结束 |
| `done` | `{txt_path, md_path}` | 全流程结束并落盘 |

REST 路由：
- `GET /` 返回前端页面；`/static/*` 静态资源。
- `GET /api/config` / `PUT /api/config` 读写配置。
- `POST /api/topic/generate` 生成候选选题。
- `POST /api/debate/start` 开始（`force` 布尔字段用于强行开始）。
- `POST /api/debate/control` 控制（`action`: `pause` | `resume` | `abort` | `retry` | `skip`）。
- `GET /api/debate/state` 拉取当前完整状态（用于前端重连恢复）。
- `GET /api/events` SSE 事件流。
- `GET /api/history` 列出历史结果；`GET /api/history/{name}` 读取单条。

## [S8] 思考内容处理

- 兼容三种来源：响应增量中的 `reasoning_content` 字段（DeepSeek 等）、`reasoning` 字段、
  以及正文内联的 `思考…`/`<thinking>…</thinking>` 标签。
- 字段来源直接分流到 `reasoning_delta`；内联标签在流式解析时按状态机剥离到思考流。
- 前端将思考渲染为**默认折叠**的独立区块，与正式发言分离；生成过程中实时更新。

## [S9] 前端界面

- **布局**：顶部标题栏（显示双方昵称）；中间左右分栏——正方在左、反方在右；底部控制条。
- **时间线**：每条发言一张卡片，含说话者徽标、角色标签、正文、可折叠思考区块、计时与字数。
- **控制条**：开始 / 暂停 / 继续 / 中止 / 强行开始（WARNING 态出现）。
- **设置抽屉**：三份 API 表单（昵称、apiKey、baseURL、模型、温度、maxTokens）+ 辩论配置
  （辩题手填或生成 3~5 候选挑选、轮数、双方人设）+ 运行配置（重试次数、超时）+ UI
  （主题、提示音）。
- **历史面板**：列出 `Results/` 下记录，点击回放。
- **实时**：SSE 逐字渲染；掉线自动重连并拉取 `/api/debate/state` 恢复。
- 主题通过 `ui.theme` 与 localStorage 保持；完成时按 `ui.sound` 播放提示音。

## [S10] 错误处理与重试

- 每次 LLM 调用失败（超时/网络/HTTP 错误/拒答）自动重试，次数为 `runtime.max_retries`
  （默认 3），指数退避。
- 重试耗尽：发出 `error` 事件，进入 `PAUSED`，保存已生成内容；前端提供 重试 / 跳过 / 中止。
- 单次请求超时 `runtime.timeout_seconds`（默认 120s）。
- 校验接口解析失败按 [S6] 降级处理。

## [S11] 结果持久化与历史回放

- **缓存** `cache/session.json`：结构
  ```jsonc
  { "topic": "", "topic_source": "manual|generated", "status": "…",
    "messages": [ { "id": "m1", "side": "pro", "role": "opening", "round": 1,
                    "speaker": "正方一辩", "content": "…", "reasoning": "…",
                    "elapsed_ms": 1234, "chars": 567 } ],
    "judge": { "content": "…", "reasoning": "…", "elapsed_ms": 0, "chars": 0 } }
  ```
  进程启动时删除旧缓存文件并重建空结构（清缓存）。
- **发言者身份命名**：`正方一辩` / `反方一辩` / `正方自由辩论第1轮`… / `正方总结陈词` /
  `反方总结陈词`。
- **txt 格式（严格）**：第 1 行为辩题；其后每条记录为「发言者身份」独占一行 + 换行 + 发言正文；
  末尾追加「总结评价」段（标签行 + 评价正文）。
- **文件名**：`Result_<时间>.txt`，时间格式 `YYYYMMDD_HHMMSS`；同时输出同名 `.md` 便于阅读。
- 历史回放读取 `Results/` 目录下的 txt/md 文件。

## [S12] 增强功能

暂停/继续/中止、历史回放、双方人设、可调温度与 maxTokens、发言计时与字数、
深色/浅色主题、Markdown 导出、完成提示音。落点见 [S5][S7][S9][S11]。

## [S13] 工程约定

- **Git**：每改动一个文件提交一次，提交信息前缀 `feat.` / `fix.` / `add.` / `del.` / `docs.`
  等 + 具体内容（如 `add. web/index.html 辩论主界面骨架`）。
- **端口**：默认 8000，来自 `runtime.port`。
- **启动**：`run.bat` 创建 venv、安装依赖、启动 uvicorn，并按 `runtime.auto_open_browser`
  打开浏览器。
- **语言**：界面文案与所有 prompt 均为中文。
- **测试**：pytest；LLM 调用通过注入的假客户端测试状态机与解析逻辑，不依赖真实网络。
