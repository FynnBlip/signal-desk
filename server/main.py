# -*- coding: utf-8 -*-
"""Signal Desk 本地服务（元框架）。

职责：把 modules/ 下的插件挂成 HTTP 接口，前端 app/ 负责交互。
启动：python server/main.py
打开：http://127.0.0.1:8090
"""

import importlib.util
import threading
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
channel = _load_module(PROJECT_ROOT / "modules" / "04_channel" / "channel.py")
denoise = _load_module(PROJECT_ROOT / "modules" / "05_denoise" / "denoise.py")
evaluate = _load_module(PROJECT_ROOT / "modules" / "06_evaluate" / "evaluate.py")

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
    return tts.synthesize(text, voice_id, output_dir=PROJECT_ROOT / "data" / "exam")


@app.get("/api/tts/audio/{filename}")
def tts_audio(filename: str):
    """返回合成出的 wav，供前端试听。文件名只取 basename，防路径穿越。"""
    safe = Path(filename).name
    f = PROJECT_ROOT / "data" / "exam" / safe
    if not f.exists():
        return {"status": "error", "message": "file not found"}
    return FileResponse(f, media_type="audio/wav")


@app.get("/api/channel/presets")
def channel_presets():
    """第四块：Opus 带宽/码率预设。"""
    return {"presets": channel.list_presets()}


@app.get("/api/channel/inputs")
def channel_inputs():
    """第四块：data/exam/ 下可施加信道的干净 wav。"""
    return {"inputs": channel.list_inputs()}


@app.get("/api/channel/noise/scenes")
def channel_noise_scenes():
    """第四块：六个噪声场景清单（含预览）。"""
    return {"scenes": channel.list_noise_scenes()}


@app.get("/api/channel/noise/preview/{filename}")
def channel_noise_preview(filename: str):
    """返回噪声场景试听预览（data/noise/preview）。"""
    safe = Path(filename).name
    f = PROJECT_ROOT / "data" / "noise" / "preview" / safe
    if not f.exists():
        return {"status": "error", "message": "file not found"}
    return FileResponse(f, media_type="audio/wav")


@app.post("/api/channel/run")
def channel_run(payload: dict = Body(default={})):
    """第四块：对干净 wav 施加噪声 + Opus 编解码。"""
    input_wav = payload.get("input_wav")
    if not input_wav:
        return {"status": "error", "message": "input_wav is required"}
    return channel.run(
        input_wav,
        noise_scenes=payload.get("noise_scenes"),
        bandwidth=payload.get("bandwidth", "wideband"),
        bitrate_kbps=int(payload.get("bitrate_kbps", 16)),
        cbr=bool(payload.get("cbr", False)),
        seed=int(payload.get("seed", 42)),
    )


@app.get("/api/channel/audio/{filename}")
def channel_audio(filename: str):
    """返回信道仿真产物 wav（data/matrix），供前端试听。"""
    safe = Path(filename).name
    f = PROJECT_ROOT / "data" / "matrix" / safe
    if not f.exists():
        return {"status": "error", "message": "file not found"}
    return FileResponse(f, media_type="audio/wav")


@app.get("/api/denoise/models")
def denoise_models():
    """第五块：可用降噪模型清单。"""
    return {"models": denoise.list_models()}


@app.get("/api/denoise/inputs")
def denoise_inputs():
    """第五块：data/matrix/ 下可降噪的 degraded wav。"""
    return {"inputs": denoise.list_inputs()}


@app.post("/api/denoise/run")
def denoise_run(payload: dict = Body(default={})):
    """第五块：对 degraded wav 跑指定降噪模型。"""
    input_wav = payload.get("input_wav")
    if not input_wav:
        return {"status": "error", "message": "input_wav is required"}
    return denoise.run(input_wav, model=payload.get("model", "gtcrn"))


@app.get("/api/denoise/audio/{model}/{filename}")
def denoise_audio(model: str, filename: str):
    """返回降噪产物 wav（data/denoised/<model>），供前端试听。"""
    allowed = set(denoise.MODEL_FILES.keys())
    if model not in allowed:
        return {"status": "error", "message": "unknown model"}
    safe = Path(filename).name
    f = PROJECT_ROOT / "data" / "denoised" / model / safe
    if not f.exists():
        return {"status": "error", "message": "file not found"}
    return FileResponse(f, media_type="audio/wav")


# 06 评测：后台线程 + 轮询
EVAL_JOB = {"state": "idle", "progress": 0, "total": 0, "message": "", "result": None}


@app.post("/api/evaluate/run")
def evaluate_run(payload: dict = Body(default={})):
    """第六块：启动「干净→退化→降噪」对比评测（后台跑）。"""
    if EVAL_JOB.get("state") == "running":
        return {"status": "error", "message": "评测进行中"}

    def _cb(done, total, message=""):
        percent = round(done / total * 100) if total else 0
        EVAL_JOB.update(state="running", progress=percent, total=total, message=message)

    def _worker():
        EVAL_JOB.update(state="running", progress=0, total=0, message="准备评测…", result=None)
        try:
            result = evaluate.compare(progress_cb=_cb, batch_size=int(payload.get("batch_size", 4)))
            EVAL_JOB.update(state="done", progress=100, result=result, message="完成")
        except Exception as exc:
            EVAL_JOB.update(state="error", progress=0, message=str(exc), result=None)

    threading.Thread(target=_worker, daemon=True).start()
    return {"status": "ok"}


@app.get("/api/evaluate/status")
def evaluate_status():
    """第六块：返回评测任务状态。"""
    return EVAL_JOB


app.mount("/", StaticFiles(directory=str(PROJECT_ROOT / "app"), html=True), name="app")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8090)
