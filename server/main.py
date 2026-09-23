# -*- coding: utf-8 -*-
"""通话评测实验室 本地服务（元框架）。

职责：把 modules/ 下的插件挂成 HTTP 接口，前端 app/ 负责交互。
启动：python server/main.py
打开：http://127.0.0.1:8090
"""

import datetime
import importlib.util
import json
import os
import statistics
import threading
import uuid
from pathlib import Path

from fastapi import Body, FastAPI
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

try:
    from capture_routes import router as capture_router
    from contracts import ChannelRunRequest, EvaluateRunRequest, LoopApplyRequest, LoopListenRequest, LoopRunRequest, VoiceRegressionRequest
    from provider_registry import ProviderRegistry
    from run_store import RunStore
except ImportError:  # package-style imports used by tests/tooling
    from server.capture_routes import router as capture_router
    from server.contracts import ChannelRunRequest, EvaluateRunRequest, LoopApplyRequest, LoopListenRequest, LoopRunRequest, VoiceRegressionRequest
    from server.provider_registry import ProviderRegistry
    from server.run_store import RunStore

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

app = FastAPI(title="通话评测实验室")
RUN_STORE = RunStore(PROJECT_ROOT / "data" / "runs")
PROVIDERS = ProviderRegistry(PROJECT_ROOT / "modules")
JOB_LOCK = threading.RLock()


def _claim_single_job(job, message, **fields):
    """Atomically reserve one asynchronous job before any paid or destructive work."""
    with JOB_LOCK:
        if job.get("state") == "running":
            return False
        job.clear()
        initial = {"state": "running", "progress": 0, "done": 0, "total": 0, "message": message, "result": None}
        initial.update(fields)
        job.update(initial)
        return True


def _payload_dict(payload):
    if isinstance(payload, dict):
        return payload
    if hasattr(payload, "model_dump"):
        return payload.model_dump()
    if hasattr(payload, "dict"):
        return payload.dict()
    return {}


def _runtime_readiness():
    denoise_ready = {item["id"]: bool(item.get("ready")) for item in denoise.list_models()}
    tts_env = tts.load_env()
    return {
        "01_corpus": {"builtin-zh-call-corpus": True},
        "02_voice": {"praat-mfcc-kmeans": True},
        "03_tts": {"minimax-speech-2.8-turbo": bool(tts_env.get("MINIMAX_API_KEY") and tts_env.get("MINIMAX_GROUP_ID"))},
        "04_channel": {"demand-opus": any(item.get("preview_ready") for item in channel.list_noise_scenes())},
        "05_denoise": denoise_ready,
        "06_evaluate": {
            "audiobox-aesthetics": bool(evaluate.get_checkpoint()),
            "audio-judge": False,
        },
        "07_loop": {
            "deterministic-gate-v2": True,
            "deepseek-advisor": bool(getattr(loop, "DEEPSEEK_API_KEY", "")),
            "human-blind-ab": True,
        },
    }


def _has_real_inference_record():
    """True only when this machine already stored real scores. File presence is not inference."""
    try:
        state = loop.load_status()
        for item in state.get("rounds") or []:
            if item.get("rows"):
                return True
    except Exception:
        pass
    try:
        root = loop.BENCHMARK_ROOT
        if root.exists() and any(root.glob("golden-v1-*/tournament_result.json")):
            return True
    except Exception:
        pass
    return False


def _golden_benchmark_readiness():
    """Compute readiness from real local assets; never claim a fresh clone is experiment-ready."""
    blockers = []
    details = {"voice": False, "noise": False, "dut": False, "evaluator": False}
    try:
        cohort = loop._load_active_cohort()
        details["voice"] = len(cohort.get("voices") or []) == 26
    except Exception as exc:
        blockers.append(str(exc))
    noise_report = channel.inspect_benchmark_noise()
    details["noise"] = bool(noise_report.get("ok"))
    blockers.extend(noise_report.get("blockers") or [])
    model_rows = {item.get("id"): item for item in denoise.list_models()}
    details["dut"] = all(bool(model_rows.get(spec["model"], {}).get("ready")) for spec in loop.VERSION_CANDIDATES)
    if not details["dut"]:
        blockers.append("降噪 Provider 尚未就绪")
    details["evaluator"] = bool(evaluate.get_checkpoint())
    if not details["evaluator"]:
        blockers.append("AudioBox 评测模型尚未就绪")
    assets_detected = all(details.values())
    inference_verified = _has_real_inference_record()
    return {
        **loop.GOLDEN_BENCHMARK,
        "ready": assets_detected,
        "readiness": details,
        "assets_detected": assets_detected,
        "inference_verified": inference_verified,
        "noise_provenance": noise_report.get("provenance"),
        "noise_note": noise_report.get("provenance_note"),
        "blockers": blockers,
    }


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
    readiness = _runtime_readiness()
    return {
        "status": "ok",
        "schema_version": 2,
        "service": "signal-desk",
        "providers": readiness,
        "ready_count": sum(1 for slot in readiness.values() for value in slot.values() if value),
        "provider_count": sum(len(slot) for slot in readiness.values()),
    }


@app.get("/api/modules")
def get_modules():
    return {"modules": PROVIDERS.modules()}


@app.get("/api/providers")
def get_providers():
    readiness = _runtime_readiness()
    rows = PROVIDERS.providers()
    for row in rows:
        row["ready"] = bool(readiness.get(row["slot_id"], {}).get(row["id"], row.get("configured", True)))
    return {"schema_version": 1, "providers": rows}


@app.get("/api/providers/{slot_id}")
def get_slot_providers(slot_id: str):
    slot = PROVIDERS.slot(slot_id)
    if not slot:
        return {"status": "error", "message": "unknown slot"}
    readiness = _runtime_readiness().get(slot_id, {})
    rows = PROVIDERS.providers(slot_id)
    for row in rows:
        row["ready"] = bool(readiness.get(row["id"], row.get("configured", True)))
    return {"status": "ok", "slot": slot, "providers": rows}


@app.get("/api/runs/{kind}")
def list_runs(kind: str, limit: int = 20):
    return {"status": "ok", "kind": kind, "runs": RUN_STORE.list(kind, min(max(limit, 1), 100))}


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


@app.get("/api/voice/clusters")
def voice_clusters():
    """第二块：只读读取落盘的聚类结果，供总览 loop canvas 复用。"""
    return {"clusters": voice.load_clusters()}


@app.get("/api/voice/distribution")
def voice_distribution():
    return voice.load_distribution()


@app.get("/api/voice/cohorts/{cohort_id}/distribution")
def voice_cohort_distribution(cohort_id: str):
    return voice.load_distribution(cohort_id)


VOICE_COHORT_JOB = {
    "state": "idle", "progress": 0, "done": 0, "total": 0,
    "message": "", "cohort_id": None, "result": None,
}
VOICE_COHORT_CANCEL = threading.Event()


@app.get("/api/voice/cohorts")
def voice_cohorts():
    return {"cohorts": voice.list_cohorts()}


@app.get("/api/voice/regression")
def voice_regression():
    return voice.build_regression_ledger()


@app.post("/api/voice/cohorts/plan")
def voice_cohort_plan(payload: dict = Body(default={})):
    """只预览调用量和采样，不产生 TTS 费用。"""
    if not str(payload.get("version_label") or "").strip():
        return {"status": "error", "message": "请先填写唯一、可读的版本标签；它不会影响复用指纹"}
    plan = tts.plan_voice_cohort(
        count=payload.get("count", 50),
        seed=payload.get("seed", 42),
        probe_text=payload.get("probe_text"),
        kinds=payload.get("kinds") or ["system"],
        language_scope=payload.get("language_scope", "mandarin"),
        version_label=payload.get("version_label", ""),
    )

    if payload.get("benchmark") and plan.get("status") == "ok" and plan.get("selected_count") != 26:
        return {"status": "error", "message": "固定基准必须有 26 个不同音色；当前目录不足或请求数量不符，未启动生成。"}
    return plan


@app.post("/api/voice/cohorts/run")
def voice_cohort_run(payload: dict = Body(default={})):
    """后台生成不同 voice_id 的固定探针 Cohort；同一任务运行时拒绝重复启动。"""
    cohort_id = payload.get("cohort_id")
    if not cohort_id and not str(payload.get("version_label") or "").strip():
        return {"status": "error", "message": "请先填写唯一、可读的版本标签"}
    plan = tts.plan_voice_cohort(
        count=payload.get("count", 50),
        seed=payload.get("seed", 42),
        probe_text=payload.get("probe_text"),
        kinds=payload.get("kinds") or ["system"],
        language_scope=payload.get("language_scope", "mandarin"),
        version_label=payload.get("version_label", ""),
    )
    if plan.get("status") != "ok":
        return plan
    if payload.get("benchmark") and plan.get("selected_count") != 26:
        return {"status": "error", "message": "固定基准必须有 26 个不同音色；当前目录不足或请求数量不符，未启动生成。"}
    existing = tts.find_existing_cohort(plan)
    if existing and existing.get("status") == "ready":
        return {
            "status": "reused",
            "message": "已复用本地 Cohort，未产生新的 API 调用",
            "cohort_id": existing["id"],
            "reused": True,
        }
    if cohort_id:
        cohort_id = Path(str(cohort_id)).name
    elif existing:
        cohort_id = existing["id"]
    else:
        cohort_id = f"mm-{datetime.datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
    if not _claim_single_job(
        VOICE_COHORT_JOB, "准备生成固定探针", cohort_id=cohort_id, total=plan["selected_count"]
    ):
        return {"status": "error", "message": "已有 Cohort 正在生成"}
    cohort_dir = PROJECT_ROOT / "data" / "voice" / "cohorts" / cohort_id
    VOICE_COHORT_CANCEL.clear()

    def _cb(done, total, message=""):
        percent = round(done / total * 100) if total else 0
        VOICE_COHORT_JOB.update(
            state="running", progress=percent, done=done, total=total,
            message=message, cohort_id=cohort_id,
        )

    def _worker():
        try:
            result = tts.generate_voice_cohort(plan, cohort_dir, progress_cb=_cb, cancel_event=VOICE_COHORT_CANCEL)
            status = result.get("status")
            state = "done" if status == "ok" else ("cancelled" if status == "cancelled" else ("partial" if status == "partial" else "error"))
            VOICE_COHORT_JOB.update(
                state=state, progress=100 if state == "done" else VOICE_COHORT_JOB.get("progress", 0),
                message=("Cohort 已就绪，可开始聚类" if state == "done" else result.get("message", "生成失败")),
                result=result,
            )
        except Exception as exc:
            VOICE_COHORT_JOB.update(state="error", message=str(exc), result=None)

    threading.Thread(target=_worker, daemon=True).start()
    return {"status": "ok", "cohort_id": cohort_id, "plan": plan}


@app.post("/api/voice/cohorts/cancel")
def voice_cohort_cancel():
    """协作式暂停：当前 HTTP 调用完成后，在下一个样本边界停下并保留 partial Cohort。"""
    if VOICE_COHORT_JOB.get("state") != "running":
        return {"status": "error", "message": "当前没有正在生成的 Cohort"}
    VOICE_COHORT_CANCEL.set()
    VOICE_COHORT_JOB["message"] = "正在收尾，当前音色完成后暂停…"
    return {"status": "ok", "message": "已请求暂停"}


@app.get("/api/voice/cohorts/job")
def voice_cohort_job():
    return VOICE_COHORT_JOB


@app.get("/api/voice/cohorts/{cohort_id}/result")
def voice_cohort_result(cohort_id: str):
    return voice.load_cohort_result(cohort_id)


@app.post("/api/voice/cohorts/{cohort_id}/analyze")
def voice_cohort_analyze(cohort_id: str, payload: dict = Body(default={})):
    k = payload.get("k")
    return voice.analyze_cohort(cohort_id, n_clusters=k, use_anchor=bool(payload.get("use_anchor", True)))


@app.post("/api/voice/cohorts/{cohort_id}/activate")
def voice_cohort_activate(cohort_id: str):
    return voice.activate_cohort(cohort_id)


@app.post("/api/voice/cohorts/{cohort_id}/clusters/{cluster}/export")
def voice_cohort_cluster_export(cohort_id: str, cluster: int):
    return voice.export_cohort_cluster(cohort_id, cluster)


VOICE_REGRESSION_JOB = {
    "state": "idle", "progress": 0, "done": 0, "total": 0,
    "message": "", "result": None,
}


def _voice_metric_summary(files):
    metrics = {}
    for key in ("pq", "pc", "ce", "cu", "overall"):
        values = [float(item[key]) for item in files if item.get(key) is not None]
        metrics[key] = {
            "n": len(values),
            "avg": round(statistics.mean(values), 4) if values else None,
            "median": round(statistics.median(values), 4) if values else None,
            "std": round(statistics.pstdev(values), 4) if len(values) > 1 else 0.0 if values else None,
            "min": round(min(values), 4) if values else None,
            "max": round(max(values), 4) if values else None,
        }
    return metrics


def _score_voice_cluster(folder, cohort_id, cluster, settings, predictor, progress_cb):
    paths = evaluate.scan_folder(folder)
    if not paths:
        raise RuntimeError(f"簇目录里没有 wav：{folder}")
    scores = evaluate.score_files(
        predictor, paths, batch_size=max(1, int(settings.get("batch_size", 4))), progress_cb=progress_cb
    )
    result = voice.load_cohort_result(cohort_id)
    metadata = {
        Path(str(item.get("file") or "")).name: item
        for item in result.get("files") or []
        if int(item.get("cluster", -1)) == int(cluster)
    }
    files = []
    for path in paths:
        scores_for_file = scores.get(path)
        if not scores_for_file:
            continue
        item = metadata.get(Path(path).name, {})
        files.append({
            "filename": Path(path).name,
            "voice_id": item.get("voice_id"),
            "voice_name": item.get("voice_name"),
            **evaluate._annotate(scores_for_file, settings),
        })
    return {
        "cohort_id": cohort_id,
        "cluster": int(cluster),
        "folder": str(folder),
        "n": len(files),
        "files": files,
        "metrics": _voice_metric_summary(files),
    }


@app.post("/api/voice/regression/evaluate")
def voice_regression_evaluate(payload: VoiceRegressionRequest):
    """启动同一固定簇的 baseline / candidate AudioBox 客观回归。"""
    payload = _payload_dict(payload)
    candidate_id = Path(str(payload.get("candidate_cohort_id") or "")).name
    if not candidate_id or candidate_id == ".":
        return {"status": "error", "message": "candidate_cohort_id 必填"}
    baseline_id = Path(str(payload.get("baseline_cohort_id") or "")).name
    if not baseline_id or baseline_id == ".":
        baseline_id = voice.build_regression_ledger().get("baseline_id") or ""
    if not baseline_id or baseline_id == candidate_id:
        return {"status": "error", "message": "baseline 与 candidate 必须是不同 Cohort"}
    try:
        cluster = int(payload.get("cluster"))
    except (TypeError, ValueError):
        return {"status": "error", "message": "cluster 必须是整数"}
    if not _claim_single_job(VOICE_REGRESSION_JOB, "准备簇级回归评测"):
        return {"status": "error", "message": "已有簇级回归评测正在运行"}
    try:
        baseline_export = voice.export_cohort_cluster(baseline_id, cluster)
        candidate_export = voice.export_cohort_cluster(candidate_id, cluster)
    except Exception as exc:
        VOICE_REGRESSION_JOB.update(state="error", progress=0, message=str(exc), result=None)
        return {"status": "error", "message": str(exc)}
    if baseline_export.get("status") != "ok":
        VOICE_REGRESSION_JOB.update(state="error", message=baseline_export.get("message", "基准簇导出失败"))
        return baseline_export
    if candidate_export.get("status") != "ok":
        VOICE_REGRESSION_JOB.update(state="error", message=candidate_export.get("message", "候选簇导出失败"))
        return candidate_export
    settings = evaluate.load_settings()
    try:
        record = RUN_STORE.create("voice-regression", request=payload, message="准备簇级回归评测")
    except Exception as exc:
        VOICE_REGRESSION_JOB.update(state="error", progress=0, message=str(exc), result=None)
        return {"status": "error", "message": str(exc)}
    run_id = record["run_id"]
    with JOB_LOCK:
        VOICE_REGRESSION_JOB.update(record)
        VOICE_REGRESSION_JOB.update(state="running", result=None)

    def _cb(done, total, message=""):
        changes = dict(
            state="running", progress=round(done / total * 100) if total else 0,
            done=done, total=total, message=message,
        )
        VOICE_REGRESSION_JOB.update(**changes)
        RUN_STORE.update("voice-regression", run_id, **changes)

    def _worker():
        RUN_STORE.update("voice-regression", run_id, state="running", message="加载 audiobox-aesthetics 模型…")
        try:
            predictor = evaluate.load_predictor()
            baseline = _score_voice_cluster(baseline_export["folder"], baseline_id, cluster, settings, predictor, _cb)
            candidate = _score_voice_cluster(candidate_export["folder"], candidate_id, cluster, settings, predictor, _cb)
            metrics = []
            metric_keys = ["pq", "pc", "ce", "cu"]
            if settings.get("overall_mode") != "disabled":
                metric_keys.append("overall")
            for key in metric_keys:
                b = baseline["metrics"][key]
                c = candidate["metrics"][key]
                metrics.append({
                    "metric": key,
                    "baseline": b,
                    "candidate": c,
                    "delta": round(c["avg"] - b["avg"], 4) if c["avg"] is not None and b["avg"] is not None else None,
                })
            result = {
                "status": "ok",
                "run_id": run_id,
                "mode": "voice_cluster_regression",
                "cluster": cluster,
                "baseline": baseline,
                "candidate": candidate,
                "metrics": metrics,
                "settings": settings,
                "created_at": datetime.datetime.now().isoformat(timespec="seconds"),
            }
            out_dir = PROJECT_ROOT / "data" / "eval" / "voice_regression" / "results"
            out_dir.mkdir(parents=True, exist_ok=True)
            result_path = out_dir / f"{run_id}.json"
            result["result_path"] = str(result_path)
            result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            changes = dict(state="done", progress=100, done=baseline["n"] + candidate["n"], total=baseline["n"] + candidate["n"], message="簇级回归评测完成", result=result, error=None)
            VOICE_REGRESSION_JOB.update(**changes)
            RUN_STORE.update("voice-regression", run_id, **changes)
        except Exception as exc:
            changes = dict(state="error", progress=0, message=str(exc), result=None, error={"type": type(exc).__name__, "message": str(exc)})
            VOICE_REGRESSION_JOB.update(**changes)
            RUN_STORE.update("voice-regression", run_id, **changes)

    threading.Thread(target=_worker, daemon=True).start()
    return {
        "status": "ok",
        "run_id": run_id,
        "cluster": cluster,
        "baseline": baseline_export,
        "candidate": candidate_export,
    }


@app.get("/api/voice/regression/evaluate/status")
def voice_regression_evaluate_status():
    return VOICE_REGRESSION_JOB


@app.get("/api/voice/regression/evaluate/history")
def voice_regression_evaluate_history():
    root = PROJECT_ROOT / "data" / "eval" / "voice_regression" / "results"
    rows = []
    for path in sorted(root.glob("*.json"), reverse=True):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        rows.append({
            "run_id": data.get("run_id") or path.stem,
            "cluster": data.get("cluster"),
            "baseline_cohort_id": (data.get("baseline") or {}).get("cohort_id"),
            "candidate_cohort_id": (data.get("candidate") or {}).get("cohort_id"),
            "metrics": data.get("metrics") or [],
            "created_at": data.get("created_at"),
            "path": str(path),
        })
    return {"status": "ok", "rows": rows}


@app.get("/api/voice/cohorts/{cohort_id}/audio/{filename}")
def voice_cohort_audio(cohort_id: str, filename: str):
    safe_id = Path(cohort_id).name
    safe_file = Path(filename).name
    f = PROJECT_ROOT / "data" / "voice" / "cohorts" / safe_id / "audio" / safe_file
    if not f.exists():
        return {"status": "error", "message": "file not found"}
    return FileResponse(f, media_type="audio/wav")


@app.get("/api/tts/voices")
def tts_voices():
    """第三块：可用音色清单（不含密钥）。"""
    voices = tts.list_voices()
    return {"voices": voices, "catalog": tts.voice_catalog_status()}


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
def channel_run(payload: ChannelRunRequest):
    """第四块：对干净 wav 施加噪声 + Opus 编解码。"""
    payload = _payload_dict(payload)
    input_wav = payload.get("input_wav")
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


# 06 评测：后台线程 + 轮询 + 重启恢复
_latest_eval = RUN_STORE.latest("evaluate")
EVAL_JOB = _latest_eval or {
    "state": "idle", "progress": 0, "done": 0, "total": 0,
    "message": "", "result": None, "run_id": None,
}


@app.on_event("startup")
def restore_evaluation_job():
    """No worker survives startup; do not silently hide its newest record."""
    restored = RUN_STORE.recover_interrupted("evaluate")
    if restored:
        EVAL_JOB.clear()
        EVAL_JOB.update(restored)


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
def evaluate_run(payload: EvaluateRunRequest):
    """第六块：启动评测（comparison 链路对比 / directory 目录批量）。"""
    payload = _payload_dict(payload)
    mode = payload.get("mode", "comparison")
    folder = payload.get("folder")
    if mode == "directory":
        folder = (folder or "").strip()
        if not folder:
            return {"status": "error", "message": "请选择或输入包含 wav 的目录"}
    settings = payload.get("settings") or evaluate.load_settings()
    if not _claim_single_job(EVAL_JOB, "准备评测"):
        return {"status": "error", "message": "评测进行中"}
    try:
        record = RUN_STORE.create("evaluate", request={"mode": mode, "folder": folder, "settings": settings}, message="准备评测")
    except Exception as exc:
        EVAL_JOB.update(state="error", progress=0, message=str(exc), result=None)
        return {"status": "error", "message": str(exc)}
    run_id = record["run_id"]
    with JOB_LOCK:
        EVAL_JOB.clear()
        EVAL_JOB.update(record)
        EVAL_JOB.update(state="running", result=None)
        RUN_STORE.update("evaluate", run_id, state="running", message="准备评测")

    def _cb(done, total, message=""):
        percent = round(done / total * 100) if total else 0
        changes = dict(state="running", progress=percent, done=done, total=total, message=message)
        EVAL_JOB.update(**changes)
        RUN_STORE.update("evaluate", run_id, **changes)

    def _worker():
        try:
            if mode == "directory":
                result = evaluate.run_directory(folder, settings, progress_cb=_cb)
            else:
                result = evaluate.run_comparison(settings, progress_cb=_cb)
            if isinstance(result, dict):
                result["settings"] = settings
                result["run_id"] = run_id
                result["run_context"] = {
                    "mode": mode,
                    "folder": folder,
                    "provider": "audiobox-aesthetics",
                    "completed_at": datetime.datetime.now().isoformat(timespec="seconds"),
                }
            if not isinstance(result, dict) or result.get("status") != "ok":
                message = result.get("message", "评测未产生有效结果") if isinstance(result, dict) else "评测未产生有效结果"
                changes = dict(
                    state="error", progress=0, result=result, message=message,
                    error={"type": "EvaluationError", "message": message},
                )
                EVAL_JOB.update(**changes)
                RUN_STORE.update("evaluate", run_id, **changes)
                return
            changes = dict(state="done", progress=100, result=result, message="完成", error=None)
            EVAL_JOB.update(**changes)
            RUN_STORE.update("evaluate", run_id, **changes)
        except Exception as exc:
            changes = dict(state="error", progress=0, message=str(exc), result=None, error={"type": type(exc).__name__, "message": str(exc)})
            EVAL_JOB.update(**changes)
            RUN_STORE.update("evaluate", run_id, **changes)

    threading.Thread(target=_worker, daemon=True).start()
    return {"status": "ok", "run_id": run_id, "state": "running"}


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
LOOP_JOB = {"state": "idle", "progress": 0, "done": 0, "total": 0, "message": "", "result": None}
LOOP_BENCHMARK_JOB = {"state": "idle", "progress": 0, "done": 0, "total": 0, "message": "", "result": None}
LOOP_BLIND_ASSIGNMENTS = {}
LOOP_PREVIEW_SNAPSHOT = PROJECT_ROOT / "data" / "loop" / "last_preview.json"


def _save_loop_preview(job):
    """Persist the latest completed preview so a service restart is not a rerun."""
    result = (job or {}).get("result")
    if (job or {}).get("state") != "done" or not isinstance(result, dict) or result.get("status") != "ok":
        return
    LOOP_PREVIEW_SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
    tmp = LOOP_PREVIEW_SNAPSHOT.with_name(f".{LOOP_PREVIEW_SNAPSHOT.name}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, LOOP_PREVIEW_SNAPSHOT)
    finally:
        if tmp.exists():
            tmp.unlink()


def _discard_loop_preview():
    """Clear the transient preview without touching confirmed history or benchmark assets."""
    try:
        LOOP_PREVIEW_SNAPSHOT.unlink(missing_ok=True)
    except OSError:
        # A stale optional snapshot must not block an explicit new experiment.
        pass


def _restore_loop_preview():
    """Restore preview data and rebuild private blind assignments from row paths."""
    if not LOOP_PREVIEW_SNAPSHOT.exists():
        return
    try:
        saved = json.loads(LOOP_PREVIEW_SNAPSHOT.read_text(encoding="utf-8"))
        result = saved.get("result") or {}
        run_id = result.get("run_id") or saved.get("run_id")
        rows = result.get("rows") or []
        if saved.get("state") != "done" or result.get("status") != "ok" or not run_id or not rows:
            return
        if not result.get("experiment_id"):
            LOOP_JOB["message"] = "旧待审预览缺少实验身份，未自动恢复；原文件保留，请重新运行当前比较"
            return
        state = loop.load_status()
        processed = state.get("processed_preview") or {}
        if processed.get("run_id") == run_id:
            return
        same_experiment = (
            state.get("workspace_mode") != "blank"
            and result.get("baseline") == state.get("baseline")
            and result.get("candidate") == state.get("candidate")
            and result.get("experiment_id") == state.get("experiment_id")
        )
        if not same_experiment:
            # Unknown legacy identity was retained above; reject known foreign identities.
            if state.get("workspace_mode") == "blank" or (result.get("experiment_id") and result.get("experiment_id") != state.get("experiment_id")):
                _discard_loop_preview()
            return
        public_pairs, assignments = loop.build_blind_pairs(run_id, rows, include_assignments=True)
        result["blind_pairs"] = public_pairs
        saved["result"] = result
        LOOP_BLIND_ASSIGNMENTS[run_id] = assignments
        LOOP_JOB.clear()
        LOOP_JOB.update(saved)
    except Exception:
        # A bad optional snapshot must never prevent the service from starting.
        return


_restore_loop_preview()


def _claim_loop_job(target, message):
    """Atomically reserve the single benchmark/round execution slot."""
    with JOB_LOCK:
        if LOOP_JOB.get("state") == "running" or LOOP_BENCHMARK_JOB.get("state") == "running":
            return False
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        target.update(state="running", progress=0, done=0, total=0, message=message, result=None,
                      started_at=now, updated_at=now, finished_at=None, events=[], stage="prepare",
                      cancel_requested=False)
        _observe_loop_job(target, message=message, done=0, total=0)
        return True


class LoopCancelled(Exception):
    """Stop between units of work; never interrupt an audio file write."""


def _observe_loop_job(target, **fields):
    with JOB_LOCK:
        if target.get("cancel_requested") and fields.get("state", "running") == "running":
            raise LoopCancelled()
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        message = fields.get("message", target.get("message", ""))
        stage = target.get("stage", "prepare")
        if "降噪" in message or "DUT" in message:
            stage = "dut"
        elif "AudioBox" in message or "audiobox" in message or "评测" in message:
            stage = "evaluate"
        elif "判定" in message or "建议" in message:
            stage = "decision"
        if fields.get("state") == "done":
            stage = "review"
        target.update(**fields, updated_at=now, stage=stage)
        if fields.get("state") in ("done", "error", "cancelled"):
            target["finished_at"] = now
        entry = {"stage": stage, "time": now, "message": message,
                 "done": target.get("done", 0), "total": target.get("total", 0)}
        events = target.setdefault("events", [])
        if events and events[-1]["stage"] == stage:
            events[-1] = entry
        else:
            events.append(entry)


@app.post("/api/loop/cancel")
def loop_cancel():
    with JOB_LOCK:
        if LOOP_JOB.get("state") != "running":
            return {"status": "ok", "state": LOOP_JOB.get("state")}
        LOOP_JOB["cancel_requested"] = True
        return {"status": "ok", "state": "cancelling"}


@app.get("/api/loop/status")
def loop_status():
    """第七块：返回闭环状态（含配置/轮次/判定/建议）。"""
    state = loop.load_status()
    state["history_archive"] = loop.prepare_history_archive(state)
    state["benchmark"] = _golden_benchmark_readiness()
    is_blank = state.get("workspace_mode") == "blank" and not state.get("baseline") and not state.get("candidate")
    tournament = None if is_blank else loop.load_version_tournament(state.get("config"))
    summary_state = {**state, "rounds": []} if is_blank else state
    state["version_summary"] = tournament["version_summary"] if tournament else loop.build_version_summary(summary_state)
    state["benchmark_run"] = ({
        key: tournament.get(key)
        for key in ("benchmark_id", "cohort_id", "voices", "scenes", "samples", "versions", "completed_at", "result_path")
    } if tournament else None)
    return state


@app.get("/api/loop/archive")
def loop_archive():
    """按需读取本地历史归档；默认页面只展示近七天的当前月记录。"""
    state = loop.load_status()
    policy = loop.prepare_history_archive(state)
    archive = loop.load_history_archive()
    return {
        "status": "ok",
        "policy": policy,
        "updated_at": archive.get("updated_at"),
        "rounds": archive.get("rounds") or [],
    }


@app.get("/api/loop/job")
def loop_job():
    """Return the current job without fields that can reveal blind A/B assignments."""
    public = json.loads(json.dumps(LOOP_JOB))
    result = public.get("result") or {}
    for row in result.get("rows") or []:
        for key in (
            "baseline_model", "candidate_model", "baseline_file", "candidate_file",
            "baseline_path", "candidate_path",
        ):
            row.pop(key, None)
    return public


@app.get("/api/loop/benchmark/job")
def loop_benchmark_job():
    """返回固定 26 音色 × 场景 × V1-V4 赛马进度。"""
    return LOOP_BENCHMARK_JOB


@app.post("/api/loop/benchmark/run")
def loop_benchmark_run():
    """后台生成/复用 Golden Benchmark，并完成 V1-V4 同条件评测。"""
    readiness = _golden_benchmark_readiness()
    if not readiness.get("ready"):
        blockers = readiness.get("blockers") or ["固定测试矩阵尚未就绪"]
        return {"status": "error", "message": "；".join(blockers), "benchmark": readiness}
    config = (loop.load_status().get("config") or loop.DEFAULT_CONFIG)
    if not _claim_loop_job(LOOP_BENCHMARK_JOB, "准备固定 26 音色基准…"):
        return {"status": "error", "message": "已有闭环任务正在运行"}

    stage_windows = {
        "v1": (25, 10), "v2": (35, 10), "v3": (45, 10), "v4": (55, 10),
    }

    def _cb(done, total, message=""):
        ratio = (done / total) if total else 0
        if message.startswith("准备固定测试矩阵"):
            percent = round(ratio * 25)
        elif "降噪补齐" in message:
            version = next((vid for vid in stage_windows if vid in message.lower()), "v1")
            base, width = stage_windows[version]
            percent = base + round(ratio * width)
        elif "AudioBox" in message or "评测" in message:
            percent = 65 + round(ratio * 34)
        else:
            percent = LOOP_BENCHMARK_JOB.get("progress", 0)
        LOOP_BENCHMARK_JOB.update(
            state="running", progress=max(LOOP_BENCHMARK_JOB.get("progress", 0), min(99, percent)),
            done=done, total=total, message=message,
        )

    def _worker():
        try:
            result = loop.run_version_tournament(config, progress_cb=_cb)
            LOOP_BENCHMARK_JOB.update(
                state="done", progress=100, done=result.get("samples", 0), total=result.get("samples", 0),
                message="固定基准赛马完成", result={
                    key: result.get(key)
                    for key in ("status", "benchmark_id", "cohort_id", "voices", "scenes", "samples", "scored_now", "versions", "completed_at")
                },
            )
        except Exception as exc:
            LOOP_BENCHMARK_JOB.update(state="error", progress=0, message=str(exc), result=None)

    threading.Thread(target=_worker, daemon=True).start()
    return {"status": "ok", "state": "running"}


@app.get("/api/loop/options")
def loop_options():
    """第七块：矩阵配置选项。"""
    return {
        "exams": loop.list_exams(),
        "scenes": loop.list_scenes(),
        "versions": loop.list_versions(),
    }


@app.post("/api/loop/config")
@loop.serialized_status_write
def loop_config(payload: dict = Body(default={})):
    """第七块：保存矩阵配置 + baseline/candidate。"""
    state = loop.load_status()
    if isinstance(payload.get("config"), dict):
        state["config"] = payload["config"]
    if "baseline" in payload:
        requested_baseline = payload.get("baseline") or None
        established = state.get("baseline") and (state.get("rounds") or state.get("baseline_origin"))
        if established and requested_baseline != state.get("baseline"):
            return {"status": "error", "message": "当前基准已有追溯历史，不能通过普通配置改写；请新建实验或按 Gate 晋级"}
        state["baseline"] = requested_baseline
    if "candidate" in payload:
        state["candidate"] = payload.get("candidate") or None
    version_ids = [v["id"] for v in loop.list_versions()]
    if state.get("baseline") and state["baseline"] not in version_ids:
        return {"status": "error", "message": "当前基准版本不存在"}
    if state.get("candidate") and state["candidate"] not in version_ids:
        return {"status": "error", "message": "待验证版本不存在"}
    if state.get("baseline") and state.get("candidate") == state.get("baseline"):
        return {"status": "error", "message": "待验证版本不能与当前基准版本相同"}
    return loop.save_status(state)


@app.post("/api/loop/baseline")
@loop.serialized_status_write
def loop_establish_baseline(payload: dict = Body(default={})):
    """首次建立比较起点；不会伪造一轮对比结果。"""
    version = str(payload.get("version") or "").strip()
    version_ids = [v["id"] for v in loop.list_versions()]
    if version not in version_ids:
        return {"status": "error", "message": "请选择一个已配置的 DUT 版本"}
    state = loop.load_status()
    if state.get("rounds") and state.get("baseline") != version and state.get("workspace_mode") != "blank":
        return {"status": "error", "message": "已有正式轮次，不能绕过历史改写当前基准"}
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    mode = "demo" if payload.get("mode") == "demo" else "project"
    state["baseline"] = version
    state["candidate"] = None
    state["status"] = "ready_for_candidate"
    state["baseline_origin"] = {
        "type": "demo" if mode == "demo" else "first_setup",
        "label": "项目内置示范基准" if mode == "demo" else "首次建立的比较起点",
        "established_at": now,
        "benchmark_id": (state.get("benchmark") or loop.GOLDEN_BENCHMARK)["id"],
    }
    state["workspace_mode"] = "experiment" if state.get("workspace_mode") == "blank" else mode
    state["conclusion"] = ""
    return loop.save_status(state)


@app.post("/api/loop/new")
@loop.serialized_status_write
def loop_new_experiment():
    """Start with a blank draft while preserving local assets and confirmed history."""
    with JOB_LOCK:
        if LOOP_JOB.get("state") == "running" or LOOP_BENCHMARK_JOB.get("state") == "running":
            return {"status": "error", "message": "当前任务仍在运行，完成后才能新建实验"}
        state = loop.start_new_experiment(loop.load_status())
        LOOP_JOB.clear()
        LOOP_JOB.update(state="idle", progress=0, done=0, total=0, message="", result=None)
        LOOP_BENCHMARK_JOB.clear()
        LOOP_BENCHMARK_JOB.update(state="idle", progress=0, done=0, total=0, message="", result=None)
        LOOP_BLIND_ASSIGNMENTS.clear()
        _discard_loop_preview()
    return loop.save_status(state)


@app.post("/api/loop/run")
def loop_run(payload: LoopRunRequest):
    """第七块：后台跑一轮（归因 + 条件晋级判定 + 建议）。"""
    readiness = _golden_benchmark_readiness()
    if not readiness.get("ready"):
        blockers = readiness.get("blockers") or ["固定测试矩阵尚未就绪"]
        return {"status": "error", "message": "；".join(blockers), "benchmark": readiness}
    state = loop.load_status()
    config = state.get("config") or loop.DEFAULT_CONFIG
    baseline = state.get("baseline") or config.get("baseline")
    candidate = state.get("candidate")
    if not baseline:
        return {"status": "error", "message": "还没有当前基准版本，请先建立比较起点"}
    if not candidate:
        return {"status": "error", "message": "还没有待验证版本，请先选择本轮要验证的新版本"}
    run_config = {**config, "baseline": baseline, "candidate": candidate}
    run_id = f"loop-{datetime.datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
    if not _claim_loop_job(LOOP_JOB, "准备跑轮…"):
        return {"status": "error", "message": "已有闭环任务正在运行"}
    with JOB_LOCK:
        LOOP_JOB["run_id"] = run_id

    def _cb(done, total, message=""):
        percent = round(done / total * 100) if total else 0
        _observe_loop_job(LOOP_JOB, state="running", progress=percent, done=done, total=total, message=message)

    def _worker():
        try:
            result = loop.run_round(run_config, progress_cb=_cb)
            if result.get("status") == "ok":
                st = loop.load_status()
                evaluated = list(dict.fromkeys(st.get("evaluated_versions", []) + [baseline, candidate]))
                _observe_loop_job(LOOP_JOB, state="running", progress=100, message="生成判定建议…")
                decision = loop.decide(result["judge"], run_config, evaluated, result["rows"])
                _observe_loop_job(LOOP_JOB, message="判定建议已生成")
                result["decision"] = decision
                result["run_id"] = run_id
                result["experiment_id"] = state.get("experiment_id")
                public_pairs, assignments = loop.build_blind_pairs(run_id, result.get("rows") or [], include_assignments=True)
                result["blind_pairs"] = public_pairs
                with JOB_LOCK:
                    LOOP_BLIND_ASSIGNMENTS.clear()
                    LOOP_BLIND_ASSIGNMENTS[run_id] = assignments
                result["preview_created_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                tournament = loop.load_version_tournament(run_config)
                result["version_summary"] = (
                    tournament["version_summary"] if tournament else loop.build_version_summary(st, result)
                )
            if result.get("status") != "ok":
                raise RuntimeError(result.get("message", "运行未生成有效结果"))
            _observe_loop_job(LOOP_JOB, state="done", progress=100, result=result, message="完成，等待人工确认")
            _save_loop_preview(LOOP_JOB)
        except LoopCancelled:
            _observe_loop_job(LOOP_JOB, state="cancelled", result=None, message="本轮已安全停止，未写入正式历史")
        except Exception as exc:
            _observe_loop_job(LOOP_JOB, state="error", progress=0, message=str(exc), result=None)

    threading.Thread(target=_worker, daemon=True).start()
    return {"status": "ok", "run_id": run_id, "state": "running"}


@app.get("/api/loop/blind/audio/{run_id}/{stem}/{side}")
def loop_blind_audio(run_id: str, stem: str, side: str):
    """Resolve a blind clip without exposing its role, model, filename, or path."""
    if side not in {"A", "B"} or stem != Path(stem).name or run_id != Path(run_id).name:
        return {"status": "error", "message": "invalid blind clip"}
    with JOB_LOCK:
        assignment = ((LOOP_BLIND_ASSIGNMENTS.get(run_id) or {}).get(stem) or {}).get(side)
    path = Path(str((assignment or {}).get("path") or ""))
    if not assignment or not path.is_file():
        return {"status": "error", "message": "blind clip not found"}
    resolved = path.resolve()
    data_root = (PROJECT_ROOT / "data").resolve()
    try:
        resolved.relative_to(data_root)
    except ValueError:
        return {"status": "error", "message": "blind clip outside data root"}
    return FileResponse(resolved, media_type="audio/wav")


@app.get("/api/loop/benchmark/audio/{kind}/{stem}")
def loop_benchmark_audio(kind: str, stem: str):
    """Serve traceable clean/degraded/V1-V4 evidence from the saved benchmark."""
    allowed = {"clean", "degraded", "v1", "v2", "v3", "v4"}
    if kind not in allowed or stem != Path(stem).name:
        return {"status": "error", "message": "invalid benchmark clip"}
    state = loop.load_status()
    tournament = loop.load_version_tournament(state.get("config"))
    if not tournament:
        return {"status": "error", "message": "benchmark not found"}
    row = next((item for item in tournament.get("rows") or [] if item.get("stem") == stem), None)
    if not row:
        return {"status": "error", "message": "benchmark sample not found"}
    benchmark_root = Path(tournament["result_path"]).parent
    if kind == "clean":
        path = PROJECT_ROOT / "data" / "voice" / "cohorts" / Path(str(row["cohort_id"])).name / "audio" / Path(str(row["clean_file"])).name
    elif kind == "degraded":
        path = benchmark_root / "matrix" / Path(str(row["degraded_file"])).name
    else:
        path = loop._denoised_path(
            {"stem": stem, "denoised_root": str(benchmark_root / "denoised")},
            loop.get_version(kind),
        )
    resolved = path.resolve()
    data_root = (PROJECT_ROOT / "data").resolve()
    try:
        resolved.relative_to(data_root)
    except ValueError:
        return {"status": "error", "message": "benchmark clip outside data root"}
    if not resolved.is_file():
        return {"status": "error", "message": "benchmark clip not found"}
    return FileResponse(resolved, media_type="audio/wav")


@app.post("/api/loop/listen")
def loop_listen(payload: LoopListenRequest):
    """Record one blinded A/B judgement for the current in-memory preview."""
    data = _payload_dict(payload)
    preview = LOOP_JOB.get("result")
    if not isinstance(preview, dict) or preview.get("status") != "ok":
        return {"status": "error", "message": "没有可听审的临时运行"}
    if data.get("run_id") != preview.get("run_id"):
        return {"status": "error", "message": "临时运行已被替换，请重新选择"}
    public_pair = next((item for item in preview.get("blind_pairs") or [] if item.get("stem") == data.get("stem")), None)
    with JOB_LOCK:
        assignment = ((LOOP_BLIND_ASSIGNMENTS.get(data["run_id"]) or {}).get(data.get("stem")))
    if not public_pair or not assignment:
        return {"status": "error", "message": "场景不属于当前运行"}
    pair = {**public_pair, "A": assignment["A"], "B": assignment["B"]}
    saved = loop.record_listening(data["run_id"], pair, data["pick"], data.get("note", ""))
    return {"status": "ok", "listening": {key: saved[key] for key in ("listening_id", "run_id", "stem", "pick", "selected_role", "timestamp")}}


@app.post("/api/loop/apply")
@loop.serialized_status_write
def loop_apply(payload: LoopApplyRequest):
    """第七块：人在环确认建议（accept / switch_model / no_solution / reject）。"""
    payload = _payload_dict(payload)
    decision = payload.get("decision")
    if not isinstance(decision, dict):
        return {"status": "error", "message": "decision required"}
    state = loop.load_status()
    action = decision.get("action")
    preview = LOOP_JOB.get("result")
    baseline = state.get("baseline")
    candidate = state.get("candidate")
    evaluated = state.setdefault("evaluated_versions", [])
    pool = [v["id"] for v in loop.list_versions()]

    if action != "reject":
        if not isinstance(preview, dict) or preview.get("status") != "ok":
            return {"status": "error", "message": "没有待确认的临时运行，请先跑一轮"}
        if preview.get("baseline") != baseline or preview.get("candidate") != candidate:
            return {"status": "error", "message": "当前版本已变化，请重新运行后再确认"}
        suggested = preview.get("decision") or {}
        if suggested.get("action") != action:
            return {"status": "error", "message": "确认动作与本轮建议不一致"}
        allowed = suggested.get("allowed_actions") or loop.allowed_actions(preview.get("judge") or {}, evaluated)
        if action not in allowed.get("actions", []):
            return {"status": "error", "message": "确认动作未通过本轮工程 gate"}
        if action == "accept" and not (preview.get("judge") or {}).get("promoted"):
            return {"status": "error", "message": "工程 gate 未通过，禁止晋级"}
        if action == "accept_conditional" and not (preview.get("judge") or {}).get("conditional"):
            return {"status": "error", "message": "本轮不是条件晋级，拒绝条件确认"}
        if baseline and baseline not in evaluated:
            evaluated.append(baseline)
        if candidate and candidate not in evaluated:
            evaluated.append(candidate)
        round_no = len(state.get("rounds", [])) + 1
        state["rounds"] = state.get("rounds", []) + [
            {
                "round": round_no,
                "experiment_id": state.get("experiment_id"),
                "run_id": preview.get("run_id"),
                "time": preview.get("preview_created_at") or datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "baseline": baseline,
                "candidate": candidate,
                "judge": preview.get("judge"),
                "decision": suggested,
                "rows": preview.get("rows") or [],
            }
        ]
        decision = suggested
    else:
        round_no = len(state.get("rounds", []))

    if action in {"accept", "accept_conditional"}:
        state["baseline"] = candidate
        state["baseline_origin"] = {
            "type": "conditional_promoted" if action == "accept_conditional" else "promoted",
            "label": f"第 {round_no} 轮确认条件晋级（极端回退已知）" if action == "accept_conditional" else f"第 {round_no} 轮确认晋级",
            "round": round_no,
            "from_version": baseline,
            "established_at": preview.get("preview_created_at") or datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "benchmark_id": (state.get("benchmark") or loop.GOLDEN_BENCHMARK)["id"],
        }
        change = (
            f"第{round_no}轮：新版本 {candidate} 常规曲线上行、极端噪声回退，经人工明确确认后条件晋级为 baseline"
            if action == "accept_conditional"
            else f"第{round_no}轮：新版本 {candidate} 曲线整体上行，验收晋级为 baseline"
        )
        state["changelog"] = state.get("changelog", []) + [change]
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
    state["last_decision"] = None
    state["last_judge"] = None
    state["evaluated_versions"] = evaluated
    if isinstance(preview, dict) and preview.get("run_id"):
        state["processed_preview"] = {"experiment_id": preview.get("experiment_id") or state.get("experiment_id"), "run_id": preview["run_id"]}
    saved = loop.save_status(state)
    LOOP_JOB.update(state="idle", progress=0, done=0, total=0, message="", result=None)
    with JOB_LOCK:
        LOOP_BLIND_ASSIGNMENTS.clear()
        _discard_loop_preview()
    return saved


@app.get("/api/loop/report")
def loop_report():
    """第七块：返回网页摘要数据，并保留 Markdown 归档文本。"""
    state = loop.load_status()
    is_blank = state.get("workspace_mode") == "blank" and not state.get("baseline") and not state.get("candidate")
    tournament = None if is_blank else loop.load_version_tournament(state.get("config"))
    if tournament:
        state["version_summary"] = tournament.get("version_summary")
    summary = state.get("version_summary") or loop.build_version_summary(state)
    return {
        "summary": {
            "benchmark": (state.get("benchmark") or loop.GOLDEN_BENCHMARK).get("label"),
            "baseline": state.get("baseline"),
            "candidate": state.get("candidate"),
            "status": state.get("status"),
            "conclusion": state.get("conclusion"),
            "recommendation": summary.get("recommendation") or {},
            "shared_samples": summary.get("shared_samples"),
        },
        "rounds": state.get("rounds") or [],
        "markdown": loop.build_markdown(state),
    }


@app.get("/api/loop/report.md")
def loop_report_markdown():
    """Download the durable experiment report as Markdown."""
    state = loop.load_status()
    return PlainTextResponse(
        loop.build_markdown(state),
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="audio-call-lab-report.md"'},
    )


@app.get("/api/loop/report.xlsx")
def loop_report_excel():
    """Download conclusions and full per-sample evidence as an Excel workbook."""
    state = loop.load_status()
    is_blank = state.get("workspace_mode") == "blank" and not state.get("baseline") and not state.get("candidate")
    tournament = None if is_blank else loop.load_version_tournament(state.get("config"))
    if tournament:
        state["version_summary"] = tournament.get("version_summary")
    out = loop.LOOP_DIR / "audio_call_lab_report.xlsx"
    loop.export_report_excel(state, out)
    return FileResponse(
        out,
        filename="audio_call_lab_report.xlsx",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@app.get("/tokens.css", include_in_schema=False)
def design_tokens_css():
    return FileResponse(PROJECT_ROOT / "tokens.css", media_type="text/css")


@app.get("/architecture.html", include_in_schema=False)
def runtime_architecture():
    """Open the explorable runtime diagram without duplicating the generated artifact."""
    return FileResponse(PROJECT_ROOT / "docs" / "signal-desk-runtime.html", media_type="text/html")


@app.get("/", include_in_schema=False)
@app.get("/index.html", include_in_schema=False)
def workbench_home():
    """A single UI entry; legacy query links are resolved by the new shell."""
    return FileResponse(PROJECT_ROOT / "app" / "lab.html", media_type="text/html")


# 08 真机采集：路由必须先于根静态挂载注册，否则 /api/capture/* 会被 StaticFiles 吞掉。
# 手机端页面走现有根挂载（/capture.html），因此 capture.js 里的 /capture-worklet.js 无需改路径。
app.include_router(capture_router)

app.mount("/", StaticFiles(directory=str(PROJECT_ROOT / "app"), html=True), name="app")


if __name__ == "__main__":
    import uvicorn

    # 默认只绑回环。手机直连请显式 SIGNAL_DESK_HOST=0.0.0.0，且必须同时设置配对令牌，
    # 否则同一局域网内任何人都能往 /api/capture/* 上传音频（ADR-004 网络接入章节）。
    host = os.environ.get("SIGNAL_DESK_HOST", "127.0.0.1").strip() or "127.0.0.1"
    port = int(os.environ.get("SIGNAL_DESK_PORT", "8090"))
    if host not in ("127.0.0.1", "localhost", "::1") and not os.environ.get("SIGNAL_DESK_CAPTURE_TOKEN", "").strip():
        raise SystemExit(
            "拒绝在非回环地址上无令牌启动：请先设置 SIGNAL_DESK_CAPTURE_TOKEN，"
            "或改用 scripts/serve.py / Tailscale Serve 暴露服务。"
        )
    uvicorn.run(app, host=host, port=port)
