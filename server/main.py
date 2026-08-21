# -*- coding: utf-8 -*-
"""Signal Desk 本地服务（元框架）。

职责：把 modules/ 下的插件挂成 HTTP 接口，前端 app/ 负责交互。
启动：python server/main.py
打开：http://127.0.0.1:8090
"""

import datetime
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
loop = _load_module(PROJECT_ROOT / "modules" / "07_loop" / "loop.py")

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
    allowed = set(denoise.list_model_ids())
    if model not in allowed:
        return {"status": "error", "message": "unknown model"}
    safe = Path(filename).name
    f = PROJECT_ROOT / "data" / "denoised" / model / safe
    if not f.exists():
        return {"status": "error", "message": "file not found"}
    return FileResponse(f, media_type="audio/wav")


# 06 评测：后台线程 + 轮询
EVAL_JOB = {"state": "idle", "progress": 0, "total": 0, "message": "", "result": None}


@app.get("/api/evaluate/settings")
def evaluate_settings_get():
    """第六块：读取评测设置。"""
    return {"settings": evaluate.load_settings()}


@app.get("/api/evaluate/dirs")
def evaluate_dirs():
    """第六块：返回链路各阶段目录，供前端快捷选择。"""
    return {
        "dirs": {
            "clean": str(PROJECT_ROOT / "data" / "exam"),
            "degraded": str(PROJECT_ROOT / "data" / "matrix"),
            "gtcrn": str(PROJECT_ROOT / "data" / "denoised" / "gtcrn"),
            "deepfilternet3": str(PROJECT_ROOT / "data" / "denoised" / "deepfilternet3"),
        }
    }


@app.post("/api/evaluate/settings")
def evaluate_settings_post(payload: dict = Body(default={})):
    """第六块：保存评测设置。"""
    settings = payload.get("settings")
    if not isinstance(settings, dict):
        return {"status": "error", "message": "settings is required"}
    evaluate.save_settings(settings)
    return {"status": "ok", "settings": evaluate.load_settings()}


@app.post("/api/evaluate/run")
def evaluate_run(payload: dict = Body(default={})):
    """第六块：启动评测（comparison 链路对比 / directory 目录批量）。"""
    if EVAL_JOB.get("state") == "running":
        return {"status": "error", "message": "评测进行中"}
    mode = payload.get("mode", "comparison")
    folder = payload.get("folder")
    settings = payload.get("settings") or evaluate.load_settings()

    def _cb(done, total, message=""):
        percent = round(done / total * 100) if total else 0
        EVAL_JOB.update(state="running", progress=percent, total=total, message=message)

    def _worker():
        EVAL_JOB.update(state="running", progress=0, total=0, message="准备评测…", result=None)
        try:
            if mode == "directory":
                result = evaluate.run_directory(folder, settings, progress_cb=_cb)
            else:
                result = evaluate.run_comparison(settings, progress_cb=_cb)
            if isinstance(result, dict):
                result["settings"] = settings
            EVAL_JOB.update(state="done", progress=100, result=result, message="完成")
        except Exception as exc:
            EVAL_JOB.update(state="error", progress=0, message=str(exc), result=None)

    threading.Thread(target=_worker, daemon=True).start()
    return {"status": "ok"}


@app.get("/api/evaluate/status")
def evaluate_status():
    """第六块：返回评测任务状态。"""
    return EVAL_JOB


@app.get("/api/evaluate/export")
def evaluate_export():
    """第六块：把最近一次结果导出 Excel。"""
    result = EVAL_JOB.get("result")
    if not result or not result.get("files"):
        return {"status": "error", "message": "暂无评测结果"}
    out = PROJECT_ROOT / "data" / "eval" / "audiobox_results.xlsx"
    evaluate.export_excel(result.get("files"), out, result.get("settings"))
    return FileResponse(
        out,
        filename="audiobox_results.xlsx",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


# 07 闭环大脑：后台跑轮 + 人在环
LOOP_JOB = {"state": "idle", "progress": 0, "total": 0, "message": "", "result": None}


@app.get("/api/loop/status")
def loop_status():
    """第七块：返回闭环状态（含配置/轮次/判定/建议）。"""
    return loop.load_status()


@app.get("/api/loop/job")
def loop_job():
    """第七块：返回当前跑轮任务进度。"""
    return LOOP_JOB


@app.get("/api/loop/options")
def loop_options():
    """第七块：矩阵配置选项。"""
    return {
        "exams": loop.list_exams(),
        "scenes": loop.list_scenes(),
        "versions": loop.list_versions(),
    }


@app.post("/api/loop/config")
def loop_config(payload: dict = Body(default={})):
    """第七块：保存矩阵配置 + baseline/candidate。"""
    state = loop.load_status()
    if isinstance(payload.get("config"), dict):
        state["config"] = payload["config"]
    if payload.get("baseline"):
        state["baseline"] = payload["baseline"]
    if payload.get("candidate"):
        state["candidate"] = payload["candidate"]
    version_ids = [v["id"] for v in loop.list_versions()]
    if state.get("baseline") not in version_ids:
        state["baseline"] = version_ids[0]
    if state.get("candidate") not in version_ids:
        state["candidate"] = version_ids[1] if len(version_ids) > 1 else version_ids[0]
    return loop.save_status(state)


@app.post("/api/loop/run")
def loop_run(payload: dict = Body(default={})):
    """第七块：后台跑一轮（归因 + 条件晋级判定 + 建议）。"""
    if LOOP_JOB.get("state") == "running":
        return {"status": "error", "message": "闭环运行中"}
    state = loop.load_status()
    config = state.get("config") or loop.DEFAULT_CONFIG
    baseline = state.get("baseline") or config.get("baseline")
    candidate = state.get("candidate")
    if not candidate:
        return {"status": "error", "message": "没有候选版本，请先在矩阵配置里设 candidate"}
    run_config = {**config, "baseline": baseline, "candidate": candidate}

    def _cb(done, total, message=""):
        percent = round(done / total * 100) if total else 0
        LOOP_JOB.update(state="running", progress=percent, total=total, message=message)

    def _worker():
        LOOP_JOB.update(state="running", progress=0, total=0, message="准备跑轮…", result=None)
        try:
            result = loop.run_round(run_config, progress_cb=_cb)
            if result.get("status") == "ok":
                st = loop.load_status()
                evaluated = list(dict.fromkeys(st.get("evaluated_versions", []) + [baseline, candidate]))
                decision = loop.decide(result["judge"], run_config, evaluated, result["rows"])
                st["last_judge"] = result["judge"]
                st["last_decision"] = decision
                st["evaluated_versions"] = evaluated
                st["rounds"] = st.get("rounds", []) + [
                    {
                        "round": len(st.get("rounds", [])) + 1,
                        "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "baseline": baseline,
                        "candidate": candidate,
                        "judge": result["judge"],
                        "decision": decision,
                        "rows": result["rows"],
                    }
                ]
                st["status"] = "pending_decision"
                loop.save_status(st)
                result["decision"] = decision
            LOOP_JOB.update(state="done", progress=100, result=result, message="完成")
        except Exception as exc:
            LOOP_JOB.update(state="error", progress=0, message=str(exc), result=None)

    threading.Thread(target=_worker, daemon=True).start()
    return {"status": "ok"}


@app.post("/api/loop/apply")
def loop_apply(payload: dict = Body(default={})):
    """第七块：人在环确认建议（accept / switch_model / no_solution / reject）。"""
    decision = payload.get("decision")
    if not isinstance(decision, dict):
        return {"status": "error", "message": "decision required"}
    state = loop.load_status()
    action = decision.get("action")
    baseline = state.get("baseline")
    candidate = state.get("candidate")
    evaluated = state.setdefault("evaluated_versions", [])
    if candidate and candidate not in evaluated:
        evaluated.append(candidate)
    pool = [v["id"] for v in loop.list_versions()]
    round_no = len(state.get("rounds", []))

    if action == "accept":
        state["baseline"] = candidate
        state["changelog"] = state.get("changelog", []) + [f"第{round_no}轮：新版本 {candidate} 曲线整体上行，验收晋级为 baseline"]
        untried = [v for v in pool if v != candidate and v not in evaluated]
        if untried:
            state["candidate"] = untried[0]
            state["status"] = "running"
        else:
            state["candidate"] = None
            state["status"] = "converged"
            state["conclusion"] = f"已无可继续迭代的版本，收敛于 {candidate}"
    elif action == "iterate":
        new = decision.get("version")
        if new:
            state["candidate"] = new
            state["status"] = "running"
            state["changelog"] = state.get("changelog", []) + [f"第{round_no}轮：{candidate} 曲线未整体上行，回滚，下一版 {new}"]
    elif action == "no_solution":
        state["status"] = "no_solution"
        state["conclusion"] = decision.get("reason") or "无解，保持 baseline"
        state["candidate"] = None
        state["changelog"] = state.get("changelog", []) + [f"第{round_no}轮：{candidate} 未整体上行，无可迭代版本，诚实收口"]
    elif action == "reject":
        state["status"] = "running"
        state["changelog"] = state.get("changelog", []) + [f"第{round_no}轮：人工驳回建议，回到配置"]
    state["last_decision"] = None
    state["last_judge"] = None
    state["evaluated_versions"] = evaluated
    return loop.save_status(state)


@app.get("/api/loop/report")
def loop_report():
    """第七块：返回人可读 Markdown 结论报告。"""
    state = loop.load_status()
    return {"markdown": loop.build_markdown(state)}


app.mount("/", StaticFiles(directory=str(PROJECT_ROOT / "app"), html=True), name="app")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8090)
