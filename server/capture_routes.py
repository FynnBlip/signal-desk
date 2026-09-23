# -*- coding: utf-8 -*-
"""08 真机采集的 HTTP 接口。

挂载方式（二选一）：
A. 独立跑：直接 `python server/capture_app.py`，自带采集页，先验证链路是否通。
B. 并入现有工作台：在 server/main.py 里加三行
       from capture_routes import router as capture_router
       app.include_router(capture_router)
       app.mount("/capture", StaticFiles(directory=str(PROJECT_ROOT / "app"), html=True),
                 name="capture")
   并把 host 从 127.0.0.1 改成 0.0.0.0（或交给 Tailscale Serve）。

鉴权：设了 SIGNAL_DESK_CAPTURE_TOKEN 就要求带 token。
手机扫码进来的 URL 里带 ?t=<token>，页面存进 sessionStorage，后续请求放 header。
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

from fastapi import APIRouter, Body, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _load_module(file_path: Path):
    """目录名以编号开头（08_capture）不能直接 import，按文件路径加载。"""
    spec = importlib.util.spec_from_file_location(file_path.stem, file_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


capture = _load_module(PROJECT_ROOT / "modules" / "08_capture" / "capture.py")

router = APIRouter()

LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost", "::ffff:127.0.0.1"}


def _capture_token() -> str:
    """每次请求现读环境变量。

    之前是在 import 期读一次缓存下来：只要有人换成「先 import app、再 load_dotenv()」
    的启动方式，令牌就会是空串，而空串等于放行 —— 静默 fail-open，没有任何日志。
    """
    return os.environ.get("SIGNAL_DESK_CAPTURE_TOKEN", "").strip()


def _is_loopback(request: Request) -> bool:
    client = request.client
    return bool(client) and client.host in LOOPBACK_HOSTS


def _guard(request: Request, token_header: str | None, token_query: str | None) -> None:
    """无令牌时只放行本机请求。

    守卫必须落在请求层，不能只写在 server/main.py 的 __main__ 分支里：
    `uvicorn server.main:app --host 0.0.0.0`、gunicorn、Docker CMD 都绕过那个分支，
    绕过之后旧写法「没设令牌就 return」会让局域网内任何人都能往
    data/real_capture 写二进制、往 append-only trace 追加行。
    """
    token = _capture_token()
    if not token:
        if _is_loopback(request):
            return
        raise HTTPException(
            status_code=403,
            detail="服务绑定在非回环地址但未设置 SIGNAL_DESK_CAPTURE_TOKEN，已拒绝远端采集请求",
        )
    presented = (token_header or token_query or "").strip()
    if presented != token:
        raise HTTPException(status_code=401, detail="配对令牌无效，请重新扫描桌面端二维码")


@router.get("/api/capture/scripts")
def get_scripts(request: Request,
                token: str | None = Query(default=None),
                x_capture_token: str | None = Header(default=None)):
    _guard(request, x_capture_token, token)
    return capture.list_scripts()


@router.post("/api/capture/session")
def post_session(request: Request,
                 payload: dict = Body(default={}),
                 token: str | None = Query(default=None),
                 x_capture_token: str | None = Header(default=None)):
    _guard(request, x_capture_token, token)
    return capture.create_session(
        speaker_code=payload.get("speaker_code", "SPK-01"),
        script_id=payload.get("script_id", "p1"),
        declared_route=payload.get("declared_route", "unknown"),
        client_manifest=payload.get("client_manifest") or {},
        notes=payload.get("notes", ""),
    )


@router.post("/api/capture/session/{session_id}/chunk")
async def post_chunk(session_id: str,
                     request: Request,
                     seq: int = Query(...),
                     frames: int | None = Query(default=None),
                     token: str | None = Query(default=None),
                     x_capture_token: str | None = Header(default=None)):
    """原始 int16le 单声道 PCM 二进制体，不走 multipart，避免二次编码开销。"""
    _guard(request, x_capture_token, token)
    payload = await request.body()
    try:
        return capture.append_chunk(session_id, seq, payload, frames=frames)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/api/capture/session/{session_id}/finalize")
def post_finalize(session_id: str,
                  request: Request,
                  payload: dict = Body(default={}),
                  token: str | None = Query(default=None),
                  x_capture_token: str | None = Header(default=None)):
    _guard(request, x_capture_token, token)
    try:
        return capture.finalize_session(
            session_id,
            sample_rate=int(payload.get("sample_rate", 48000)),
            channel_count=int(payload.get("channel_count", 1)),
            client_manifest=payload.get("client_manifest") or {},
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/api/capture/sessions")
def get_sessions(request: Request,
                 limit: int = 50,
                 token: str | None = Query(default=None),
                 x_capture_token: str | None = Header(default=None)):
    _guard(request, x_capture_token, token)
    return capture.list_sessions(limit=limit)


@router.get("/api/capture/summary")
def get_summary(request: Request,
                token: str | None = Query(default=None),
                x_capture_token: str | None = Header(default=None)):
    _guard(request, x_capture_token, token)
    return capture.summary()


@router.get("/api/capture/session/{session_id}")
def get_session(session_id: str,
                request: Request,
                token: str | None = Query(default=None),
                x_capture_token: str | None = Header(default=None)):
    _guard(request, x_capture_token, token)
    try:
        return capture.load_session(session_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/api/capture/audio/{session_id}")
def get_audio(session_id: str,
              request: Request,
              token: str | None = Query(default=None),
              x_capture_token: str | None = Header(default=None)):
    _guard(request, x_capture_token, token)
    try:
        path = capture.wav_path(session_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not path:
        raise HTTPException(status_code=404, detail="file not found")
    return FileResponse(path, media_type="audio/wav")


@router.post("/api/capture/validity")
def post_validity(request: Request,
                  payload: dict = Body(default={}),
                  token: str | None = Query(default=None),
                  x_capture_token: str | None = Header(default=None)):
    """生态效度校验：合成基准的 ΔPQ 方向 vs 真机语料的 ΔPQ 方向。"""
    _guard(request, x_capture_token, token)
    return capture.validity_compare(payload.get("synthetic_delta") or {},
                                    payload.get("real_delta") or {})


@router.post("/api/capture/tier-gate")
def post_tier_gate(request: Request,
                   payload: dict = Body(default={}),
                   token: str | None = Query(default=None),
                   x_capture_token: str | None = Header(default=None)):
    _guard(request, x_capture_token, token)
    return capture.cross_tier_gate(payload.get("sources") or [])
