# -*- coding: utf-8 -*-
"""08 真机采集 · 独立可跑服务（不依赖现有工作台即可先验证链路）。

  python server/capture_app.py            # http://127.0.0.1:8091
  然后用手机访问（需 HTTPS，见 scripts/serve.py）。

并入现有工作台见 server/capture_routes.py 顶部说明。
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

try:
    from capture_routes import router as capture_router
except ImportError:  # 包式导入（测试/工具链）
    from server.capture_routes import router as capture_router

PROJECT_ROOT = Path(__file__).resolve().parent.parent

app = FastAPI(title="Signal Desk · 真机采集")
app.include_router(capture_router)


@app.get("/api/health")
def health():
    return {"status": "ok", "schema_version": 1, "service": "signal-desk-capture",
            "module": "08_capture", "port_hint": 8091}


@app.get("/", include_in_schema=False)
@app.get("/capture.html", include_in_schema=False)
def capture_page():
    return FileResponse(PROJECT_ROOT / "app" / "capture.html", media_type="text/html")


app.mount("/", StaticFiles(directory=str(PROJECT_ROOT / "app"), html=True), name="app")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("CAPTURE_PORT", 8091)))
