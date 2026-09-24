import sys
import threading
import webbrowser

import uvicorn

from app import config_store, portcheck


def main() -> int:
    cfg = config_store.load_config()
    host = "127.0.0.1"
    port = int(cfg["runtime"]["port"])

    err = portcheck.try_bind(host, port)
    if err is not None:
        print(portcheck.describe_bind_error(err, host, port))
        alt = portcheck.find_free_port(host, port + 1, span=20)
        if alt is None:
            print(f"\n{port} 起连续 20 个端口均不可用。请结束后占用进程，或修改 config/config.json 的 runtime.port。")
            return 1
        print(f"\n端口 {port} 不可用，自动改用 {alt}。可在设置中修改默认端口。")
        port = alt

    url = f"http://{host}:{port}"
    if cfg["runtime"].get("auto_open_browser", True):
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    print(f"辩论模拟器已启动：{url}  （按 Ctrl+C 停止）")
    uvicorn.run("app.main:app", host=host, port=port, reload=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
