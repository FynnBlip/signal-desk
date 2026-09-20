# -*- coding: utf-8 -*-
"""05 降噪 DUT —— GTCRN / DeepFilterNet3 降噪闭环（第一版）。

复用旧项目 src/denoise_lab.py 的 ONNX 推理实现，去掉命令行入口，
按 通话评测实验室 模块化接口暴露 list_models / list_inputs / run。

数据红线：输入取 04 信道仿真 degraded wav（data/matrix/*.wav）；
输出按模型落 data/denoised/<model>/；每条 run 追加 denoise_runs.csv。
"""

import csv
import datetime
import hashlib
import importlib.metadata
import threading
import uuid
from pathlib import Path

import librosa
import numpy as np
import onnxruntime as ort
import soundfile as sf
import torch

try:
    import noisereduce
    HAS_NOISEREDUCE = True
except Exception:  # pragma: no cover - 环境缺包时降级为不可用
    noisereduce = None
    HAS_NOISEREDUCE = False

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
MODEL_DIR = PROJECT_ROOT / "data" / "models" / "denoise"
MATRIX_DIR = PROJECT_ROOT / "data" / "matrix"
DENOISED_DIR = PROJECT_ROOT / "data" / "denoised"
TRACE_SCHEMA_VERSION = 3
TRACE_FIELDS = [
    "schema_version", "run_id", "timestamp", "slot_id", "provider_id",
    "provider_version", "model_artifact", "model_artifact_sha256", "strength", "strength_mode",
    "input", "input_sha256", "output", "output_sha256", "input_sample_rate",
    "work_sample_rate", "duration_s",
]
_TRACE_LOCK = threading.Lock()

MODEL_FILES = {
    "gtcrn": "gtcrn_simple.onnx",
    "deepfilternet3": "denoiser_model_deepfilternet3.onnx",
}
MODEL_SAMPLE_RATES = {
    "gtcrn": 16000,
    "deepfilternet3": 48000,
    "noisereduce": None,
}
MODEL_LABELS = {
    "gtcrn": "GTCRN · 16kHz 通话流式",
    "deepfilternet3": "DeepFilterNet3 · 48kHz 全带",
    "noisereduce": "NoiseReduce · 谱门控（prop_decrease 强度旋钮）",
}


def _sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _provider_provenance(model):
    if model == "noisereduce":
        try:
            version = importlib.metadata.version("noisereduce")
        except importlib.metadata.PackageNotFoundError:
            version = "unknown"
        return {"provider_version": version, "model_artifact": "python:noisereduce", "model_artifact_sha256": ""}
    path = MODEL_DIR / MODEL_FILES[model]
    return {
        "provider_version": "onnx",
        "model_artifact": path.name,
        "model_artifact_sha256": _sha256_file(path) if path.is_file() else "",
    }


def _trace_path():
    """Choose a fixed-schema trace without rewriting legacy or malformed logs."""
    base = DENOISED_DIR / "denoise_runs_v3.csv"
    if not base.exists() or base.stat().st_size == 0:
        return base
    try:
        with base.open(encoding="utf-8-sig", newline="") as handle:
            header = next(csv.reader(handle), [])
    except OSError:
        header = []
    if header == TRACE_FIELDS:
        return base
    suffix = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    return DENOISED_DIR / f"denoise_runs_v3_{suffix}.csv"


def _append_trace(row):
    DENOISED_DIR.mkdir(parents=True, exist_ok=True)
    with _TRACE_LOCK:
        path = _trace_path()
        existed = path.exists() and path.stat().st_size > 0
        with path.open("a", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=TRACE_FIELDS, extrasaction="ignore")
            if not existed:
                writer.writeheader()
            writer.writerow({key: row.get(key, "") for key in TRACE_FIELDS})
    return path


def _stft(x, n_fft=512, hop=256, win=512):
    """和官方推理脚本一致的 STFT：hann 窗开方，返回 [帧数, 频点, 2]"""
    return torch.stft(
        x, n_fft, hop, win, torch.hann_window(win).pow(0.5), return_complex=False
    )


def _denoise_gtcrn(audio, session):
    """GTCRN 逐帧推理（16k 单声道 numpy float32）。"""
    x = torch.from_numpy(audio)
    x = _stft(x)[None]  # [1, 频点, 帧数, 2]

    conv_cache = np.zeros([2, 1, 16, 16, 33], dtype="float32")
    tra_cache = np.zeros([2, 3, 1, 1, 16], dtype="float32")
    inter_cache = np.zeros([2, 1, 33, 16], dtype="float32")

    inputs = x.numpy()
    outputs = []
    for i in range(inputs.shape[-2]):
        out_i, conv_cache, tra_cache, inter_cache = session.run(
            [],
            {
                "mix": inputs[..., i : i + 1, :],
                "conv_cache": conv_cache,
                "tra_cache": tra_cache,
                "inter_cache": inter_cache,
            },
        )
        outputs.append(out_i)

    outputs = np.concatenate(outputs, axis=2)
    spec = (outputs[..., 0] + 1j * outputs[..., 1])[0]
    enhanced = librosa.istft(
        spec,
        n_fft=512,
        hop_length=256,
        win_length=512,
        window=np.hanning(512) ** 0.5,
    )
    return enhanced.astype("float32")


def _denoise_deepfilternet3(audio, session, atten_lim_db=0.0):
    """DeepFilterNet3 逐帧推理（48k 单声道 numpy float32）。"""
    hop_size = 480
    fft_size = 960

    input_audio = torch.from_numpy(audio).float()
    orig_len = input_audio.shape[0]

    hop_pad = (hop_size - orig_len % hop_size) % hop_size
    orig_len += hop_pad
    input_audio = torch.nn.functional.pad(input_audio, (0, fft_size + hop_pad))
    chunked_audio = torch.split(input_audio, hop_size)

    state = np.zeros(45304, dtype="float32")
    atten = np.zeros(1, dtype="float32")
    atten[0] = atten_lim_db

    enhanced = []
    for frame in chunked_audio:
        out = session.run(
            None,
            input_feed={
                "input_frame": frame.numpy(),
                "states": state,
                "atten_lim_db": atten,
            },
        )
        enhanced.append(torch.tensor(out[0]))
        state = out[1]

    enhanced_audio = torch.cat(enhanced).unsqueeze(0)  # [1, t]
    d = fft_size - hop_size
    enhanced_audio = enhanced_audio[:, d : orig_len + d]
    return enhanced_audio.squeeze(0).numpy().astype("float32")


def _denoise_noisereduce(audio, sr, prop_decrease=1.0):
    """NoiseReduce 谱门控降噪：prop_decrease 是真实、可引用的强度旋钮。

    1.0 = 100% 降噪，0.0 = 不降噪。非平稳模式，按输入采样率直接工作，
    不依赖 GPU；论文：Sainburg et al. 2020（PLoS Comp Bio），DOI 10.5281/zenodo.3243139。
    """
    if not HAS_NOISEREDUCE:
        raise RuntimeError("noisereduce 未安装，请先 pip install noisereduce")
    n_fft = 512 if sr <= 16000 else 1024
    enhanced = noisereduce.reduce_noise(
        y=audio,
        sr=sr,
        stationary=False,
        prop_decrease=prop_decrease,
        n_fft=n_fft,
    )
    enhanced = np.asarray(enhanced, dtype="float32")
    n = min(len(audio), len(enhanced))
    enhanced = enhanced[:n]
    if n < len(audio):
        enhanced = np.pad(enhanced, (0, len(audio) - n))
    return enhanced


def list_model_ids():
    """返回全部可用模型 id（ONNX 模型 + NoiseReduce 算法）。"""
    ids = list(MODEL_FILES.keys())
    if HAS_NOISEREDUCE:
        ids.append("noisereduce")
    return ids


def load_model(model_name):
    """加载 onnxruntime 会话，返回 (session, work_sr)。"""
    if model_name not in MODEL_FILES:
        raise ValueError(f"未知模型：{model_name}，可选 {list(MODEL_FILES.keys())}")
    model_path = MODEL_DIR / MODEL_FILES[model_name]
    if not model_path.exists():
        raise FileNotFoundError(f"模型文件不存在：{model_path}")
    session = ort.InferenceSession(str(model_path), providers=["CPUExecutionProvider"])
    return session, MODEL_SAMPLE_RATES[model_name]


def process(input_wav, output_wav, version_spec=None, session=None):
    """统一入口：输入一条 wav，输出降噪后的 wav。"""
    spec = dict(version_spec or {})
    model_name = spec.get("model", "gtcrn")
    atten_lim_db = float(spec.get("atten_lim_db", 0.0))
    strength = float(spec.get("strength", 1.0))

    audio, in_sr = sf.read(str(input_wav), dtype="float32")
    if audio.ndim > 1:
        audio = audio.mean(axis=1)

    if model_name == "noisereduce":
        # NoiseReduce 用自己的强度旋钮 prop_decrease，按输入采样率直接工作，不重采样。
        enhanced = _denoise_noisereduce(audio, in_sr, prop_decrease=strength)
        work_sr = in_sr
        strength_mode = "native_prop_decrease"
    else:
        if session is None:
            session, work_sr = load_model(model_name)
        else:
            work_sr = MODEL_SAMPLE_RATES[model_name]

        if in_sr != work_sr:
            audio_work = librosa.resample(audio, orig_sr=in_sr, target_sr=work_sr)
        else:
            audio_work = audio

        if model_name == "gtcrn":
            enhanced_work = _denoise_gtcrn(audio_work, session)
        else:
            enhanced_work = _denoise_deepfilternet3(audio_work, session, atten_lim_db)

        if in_sr != work_sr:
            enhanced = librosa.resample(enhanced_work, orig_sr=work_sr, target_sr=in_sr)
        else:
            enhanced = enhanced_work

        # ONNX 模型没有原生强度旋钮，暂用湿/干混合演示；NoiseReduce 走 prop_decrease。
        if strength < 1.0:
            n = min(len(audio), len(enhanced))
            enhanced = enhanced[:n] * strength + audio[:n] * (1.0 - strength)
        strength_mode = "wet_dry_demo"

    out_path = Path(output_wav)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(out_path), enhanced, in_sr)

    return {
        "status": "ok",
        "model": model_name,
        "input": str(input_wav),
        "output": str(out_path),
        "input_sample_rate": int(in_sr),
        "work_sample_rate": int(work_sr),
        "duration_s": round(len(audio) / in_sr, 2),
        "strength_mode": strength_mode,
        "version_spec": spec,
    }


def list_models():
    """返回可用的降噪模型清单（含是否就绪）。"""
    models = []
    for model_id, filename in MODEL_FILES.items():
        path = MODEL_DIR / filename
        models.append(
            {
                "id": model_id,
                "name": MODEL_LABELS.get(model_id, model_id),
                "file": filename,
                "work_sample_rate": MODEL_SAMPLE_RATES[model_id],
                "bytes": path.stat().st_size if path.exists() else 0,
                "ready": path.exists(),
                "strength_mode": "wet_dry_demo",
            }
        )
    models.append(
        {
            "id": "noisereduce",
            "name": MODEL_LABELS.get("noisereduce", "noisereduce"),
            "file": "noisereduce (pip)",
            "work_sample_rate": MODEL_SAMPLE_RATES["noisereduce"],
            "bytes": 0,
            "ready": HAS_NOISEREDUCE,
            "strength_mode": "native_prop_decrease",
        }
    )
    return models


def list_inputs():
    """返回 data/matrix/ 下可用的 degraded wav（04 产物）。"""
    if not MATRIX_DIR.exists():
        return []
    return [{"name": p.name, "path": str(p)} for p in sorted(MATRIX_DIR.glob("*.wav"))]


def run(input_wav, model="gtcrn", strength=1.0):
    """对一条 degraded wav 跑降噪，落盘并按模型追加 CSV。"""
    strength = float(strength)
    input_wav = Path(input_wav)
    if not input_wav.exists():
        return {"status": "error", "message": f"输入 wav 不存在：{input_wav}"}
    if model not in list_model_ids():
        return {
            "status": "error",
            "message": f"未知模型：{model}，可选 {list_model_ids()}",
        }

    out_dir = DENOISED_DIR / model
    suffix = "" if strength >= 1.0 else f"__s{int(round(strength * 100))}"
    output_wav = out_dir / f"{input_wav.stem}__{model}{suffix}.wav"

    try:
        result = process(str(input_wav), str(output_wav), {"model": model, "strength": strength})
    except Exception as exc:
        return {"status": "error", "message": str(exc)}

    if result.get("status") != "ok":
        return result

    provenance = _provider_provenance(model)
    row = {
        "schema_version": TRACE_SCHEMA_VERSION,
        "run_id": f"dn-{datetime.datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}",
        "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
        "slot_id": "05_denoise",
        "provider_id": model,
        **provenance,
        "strength": strength,
        "strength_mode": result.get("strength_mode"),
        "input": str(input_wav),
        "input_sha256": _sha256_file(input_wav),
        "output": str(output_wav),
        "output_sha256": _sha256_file(output_wav),
        "input_sample_rate": result.get("input_sample_rate"),
        "work_sample_rate": result.get("work_sample_rate"),
        "duration_s": result.get("duration_s"),
    }
    csv_path = _append_trace(row)

    return {
        "status": "ok",
        "model": model,
        "strength": strength,
        "model_name": MODEL_LABELS.get(model, model),
        "input": str(input_wav),
        "output": str(output_wav),
        "filename": output_wav.name,
        "input_sample_rate": result.get("input_sample_rate"),
        "work_sample_rate": result.get("work_sample_rate"),
        "duration_s": result.get("duration_s"),
        "csv": str(csv_path),
        "run_id": row["run_id"],
        "trace_schema_version": TRACE_SCHEMA_VERSION,
        "strength_mode": result.get("strength_mode"),
        "input_sha256": row["input_sha256"],
        "output_sha256": row["output_sha256"],
    }
