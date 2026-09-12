import threading
import webbrowser

import uvicorn

from app import config_store

if __name__ == "__main__":
    cfg = config_store.load_config()
    host = "127.0.0.1"
    port = int(cfg["runtime"]["port"])
    url = f"http://{host}:{port}"
    if cfg["runtime"].get("auto_open_browser", True):
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    print(f"辩论模拟器已启动：{url}  （按 Ctrl+C 停止）")
    uvicorn.run("app.main:app", host=host, port=port, reload=False)
