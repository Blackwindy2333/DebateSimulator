# DebateSimulator · AI 辩论模拟器

让两个 OpenAI 兼容接口分别扮演辩论的正方与反方，围绕一个辩题完成
**开场立论 → 自由辩论 → 总结陈词** 的完整赛制，最后由第三个接口担任评委判定胜负。
全过程在网页上逐字实时显示，所有记录落盘保存。

## 功能

- **三方接口独立配置**：正方、反方、总结评价各用一套 `昵称 / API Key / Base URL / 模型 / 温度 / 思考模式 / 思考强度`。
- **思考模式可控**：每份接口可单独开关思考并设定强度，请求体按 `{"thinking": {"type": "enabled"|"disabled"}}`
  与 `{"reasoning_effort": "low"|"high"|"max"}` 发送（关闭思考时不发送 `reasoning_effort`）。
- **辩题校验**：开始前调用总结评价接口，依据 [`DebateRequirements.txt`](DebateRequirements.txt)
  判断选题是否合理；不合理时给出简短理由并暂停，可改题或**强行开始**。API 生成的选题自动跳过校验。
- **选题生成**：一次生成 3~5 个候选辩题并附论证空间说明，点选即用。
- **完整赛制**：一辩立论（正 → 反）→ 自由辩论 N 轮（每轮正 → 反）→ 总结陈词（正 → 反）→ 评委点评。
- **上下文完整传递**：除全场第一条发言外，每次请求都携带此前全部发言记录——**包括一辩阶段**，
  因此反方一辩能看到正方一辩的立论并据此回应。
- **思考内容分离**：自动识别 `reasoning_content` / `reasoning` 字段与 `<thinking>` 等内联标签，
  剥离为独立的可折叠「思考过程」区块，不与正式发言混淆。
- **思考计时**：思考时实时显示 `Thinking 12.3s`，思考结束转为灰色 `Thought 12.3s`（保留一位小数）；
  每条发言仍同时显示字数与总耗时。
- **Markdown 渲染**：发言内容按 Markdown 渲染（标题、列表、引用、行内/围栏代码、粗斜体、链接、
  分隔线）。渲染器先转义 HTML 再生成白名单标签，模型输出无法注入脚本。
- **实时显示**：SSE 逐字推送；刷新浏览器不中断辩论，重连后自动恢复现场。
- **过程控制**：暂停 / 继续 / 中止；接口失败自动重试，仍失败则暂停并可选 重试 / 跳过 / 中止。
- **双日志**：每次运行生成操作日志与 API 请求日志各一份，详见下方「日志」。
- **持久化**：配置存于 `config/config.json`（已加入 `.gitignore`，不纳入版本控制；
  启动时若不存在则按默认值生成，已存在则直接读取、不改写）；结果存为
  `Results/Result_<时间>.txt`（另附同名 `.md`）。
- **其他**：双方自定义辩论风格、发言计时与字数、深/浅主题（默认浅色）、结束提示音、历史辩论回放。

## 快速开始

Windows 下双击 `run.bat` 即可（自动建虚拟环境、装依赖、起服务并打开浏览器）。
脚本行为：

1. **先检查端口占用** —— 端口取自 `config/config.json` 的 `runtime.port`（读不到则用 8000）；
   若已被占用，会打印占用进程 PID 并将其关闭，避免「端口已被占用」导致启动失败。
2. 用 `.venv\Scripts\python.exe` 直接运行，不依赖 `activate`。
3. 任何一步出错都会打印具体原因，并停在「按任意键关闭此窗口」，不会一闪而过。

手动启动：

```bash
python -m venv .venv
.venv\Scripts\activate            # macOS / Linux: source .venv/bin/activate
pip install -r requirements.txt
python -m app
```

服务默认监听 `http://127.0.0.1:8000`（端口可在设置中修改，或直接改 `config/config.json` 的 `runtime.port`）。

首次启动后点击右上角 **设置**，至少填写：

| 项目 | 说明 |
| --- | --- |
| 正方 / 反方 / 总结评价 接口 | 昵称、API Key、Base URL、模型名、温度 |
| 思考模式 | 每份接口可单独开关；开启时才附带思考强度 |
| 思考强度 | `low` / `high` / `max`，仅开启思考模式时生效 |
| 辩题 | 直接填写，或点「生成候选选题」挑选 |
| 自由辩论轮数 | 设为 N 时，正反双方在自由辩论阶段各有 N 次发言 |

保存后点击 **开始辩论**。

## 目录结构

```
app/
  main.py          FastAPI 入口：REST + SSE
  debate.py        辩论状态机（编排 / 控制 / 重试）
  llm.py           OpenAI 兼容流式客户端、请求体构造与思考内容剥离
  prompts.py       提示词加载与消息组装
  config_store.py  config/config.json 读写
  storage.py       缓存管理与结果落盘
  events.py        SSE 事件广播器
  logbook.py       双日志（操作日志 + API 请求日志）
prompts/           context / opening / free_debate / closing / topic_check / topic_gen / judge
web/               index.html · styles.css · app.js
config/config.json 持久化配置（API Key 明文存储于本机，界面仅显示打码值）
cache/session.json 运行时缓存（进程启动时清空）
Results/           结果输出
Logs/              操作日志与 API 请求日志
tests/             pytest 单元测试与假接口
```

## 请求体

每次调用都按以下结构发送（`stream` 恒为 `true`，以支持逐字实时显示）：

```json
{
  "model": "deepseek-flash",
  "messages": [
    {"role": "system", "content": "……当前局面介绍……"},
    {"role": "user", "content": "……阶段指令 与 此前发言记录……"}
  ],
  "stream": true,
  "temperature": 0.8,
  "thinking": {"type": "enabled"},
  "reasoning_effort": "high"
}
```

关闭思考模式时 `thinking.type` 为 `"disabled"`，且不再发送 `reasoning_effort`。

## 日志

每次启动应用都会在 `Logs/` 下新建一对日志文件，历史日志不会被覆盖：

| 文件 | 内容 |
| --- | --- |
| `Operations_<时间>.log` | 一切发生的操作与更改：配置保存、辩题校验结果、阶段推进、控制指令、重试与失败、结果落盘等 |
| `ApiRequests_<时间>.log` | 每一次 API 请求的**完整请求体**（model / messages / thinking / reasoning_effort / stream / temperature） |

界面右上角 **历史** 抽屉底部会显示当前两个日志文件的实际路径。

## 结果文件格式

`Results/Result_YYYYMMDD_HHMMSS.txt`：

```
<辩题>
正方一辩
<发言正文>
反方一辩
<发言正文>
...
总结评价
<评委点评正文>
```

同时输出同名 `.md` 便于阅读。

## 离线验证（不消耗额度）

项目内置一个假接口，可在没有真实 Key 的情况下跑通全流程：

```bash
# 终端 A：启动假接口（监听 8001）
python -m tests.mock_openai

# 终端 B：把设置里三个 Base URL 改成 http://127.0.0.1:8001/v1
python -m app
```

运行测试：

```bash
python -m pytest -v
```

## 说明

- 本工具面向本地个人使用；`config/config.json` 中的 API Key 为明文保存，请勿提交到版本库（已在 `.gitignore` 中排除）。
- 辩题评价标准见 [`DebateRequirements.txt`](DebateRequirements.txt)。
