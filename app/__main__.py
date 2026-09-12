import uvicorn

from app import config_store

if __name__ == "__main__":
    cfg = config_store.load_config()
    uvicorn.run("app.main:app", host="127.0.0.1", port=int(cfg["runtime"]["port"]), reload=False)
