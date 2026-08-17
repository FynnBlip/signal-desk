# -*- coding: utf-8 -*-
"""Signal Desk 本地服务（元框架）。

职责：把 modules/ 下的插件挂成 HTTP 接口，前端 app/ 负责交互。
启动：python server/main.py
打开：http://127.0.0.1:8090
"""

import importlib.util
from pathlib import Path

from fastapi import Body, FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _load_module(file_path: Path):
    """目录名以编号开头（01_corpus）不能直接 import，按文件路径加载。"""
    spec = importlib.util.spec_from_file_location(file_path.stem, file_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


corpus = _load_module(PROJECT_ROOT / "modules" / "01_corpus" / "corpus.py")
voice = _load_module(PROJECT_ROOT / "modules" / "02_voice" / "voice.py")
tts = _load_module(PROJECT_ROOT / "modules" / "03_tts" / "tts.py")

app = FastAPI(title="Signal Desk")


def _scan_modules():
    """扫描 modules/*/manifest.py，返回插件清单（ADR-001：模块自动发现）。"""
    manifests = []
    for manifest_file in sorted((PROJECT_ROOT / "modules").glob("*/manifest.py")):
        mod = _load_module(manifest_file)
        m = getattr(mod, "MANIFEST", {})
        if m:
            manifests.append(m)
    return manifests


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/modules")
def get_modules():
    return {"modules": _scan_modules()}


@app.get("/api/corpus/templates")
def get_templates():
    return {"templates": corpus.get_templates()}


@app.post("/api/corpus/generate")
def generate_corpus(payload: dict = Body(default={})):
    items = payload.get("items") if isinstance(payload, dict) else None
    return corpus.generate_corpus(items=items, output_dir=PROJECT_ROOT / "data" / "corpus")


@app.post("/api/voice/analyze")
def analyze_voice(payload: dict = Body(default={})):
    """第二块：按目录聚类音色，k 为 None 时走肘部/轮廓自动建议。"""
    folder = payload.get("folder")
    k = payload.get("k")
    if not folder:
        return {"status": "error", "message": "folder is required"}
    return voice.analyze_voices(folder, n_clusters=k, output_dir=PROJECT_ROOT / "data" / "voice")


@app.get("/api/tts/voices")
def tts_voices():
    """第三块：可用音色清单（不含密钥）。"""
    return {"voices": tts.list_voices()}


@app.post("/api/tts/synthesize")
def tts_synthesize(payload: dict = Body(default={})):
    """第三块：按音色合成一条语料。key 由后端从 .env 读，前端不传。"""
    text = payload.get("text")
    voice_id = payload.get("voice_id")
    if not text or not voice_id:
        return {"status": "error", "message": "text 和 voice_id 必填"}
    return tts.synthesize(text, voice_id, output_dir=PROJECT_ROOT / "data" / "tts")


@app.get("/api/tts/audio/{filename}")
def tts_audio(filename: str):
    """返回合成出的 wav，供前端试听。文件名只取 basename，防路径穿越。"""
    safe = Path(filename).name
    f = PROJECT_ROOT / "data" / "tts" / safe
    if not f.exists():
        return {"status": "error", "message": "file not found"}
    return FileResponse(f, media_type="audio/wav")


app.mount("/", StaticFiles(directory=str(PROJECT_ROOT / "app"), html=True), name="app")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8090)
