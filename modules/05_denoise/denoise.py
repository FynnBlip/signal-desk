# -*- coding: utf-8 -*-
"""05 降噪 DUT —— GTCRN / DeepFilterNet3 降噪闭环（第一版）。

复用旧项目 src/denoise_lab.py 的 ONNX 推理实现，去掉命令行入口，
按 Signal Desk 模块化接口暴露 list_models / list_inputs / run。

数据红线：输入取 04 信道仿真 degraded wav（data/matrix/*.wav）；
输出按模型落 data/denoised/<model>/；每条 run 追加 denoise_runs.csv。
"""

import csv
import datetime
from pathlib import Path

import librosa
import numpy as np
import onnxruntime as ort
import soundfile as sf
import torch

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
MODEL_DIR = PROJECT_ROOT / "data" / "models" / "denoise"
MATRIX_DIR = PROJECT_ROOT / "data" / "matrix"
DENOISED_DIR = PROJECT_ROOT / "data" / "denoised"

MODEL_FILES = {
    "gtcrn": "gtcrn_simple.onnx",
    "deepfilternet3": "denoiser_model_deepfilternet3.onnx",
}
MODEL_SAMPLE_RATES = {
    "gtcrn": 16000,
    "deepfilternet3": 48000,
}
MODEL_LABELS = {
    "gtcrn": "GTCRN · 16kHz 通话流式",
    "deepfilternet3": "DeepFilterNet3 · 48kHz 全带",
}


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

    if session is None:
        session, work_sr = load_model(model_name)
    else:
        work_sr = MODEL_SAMPLE_RATES[model_name]

    audio, in_sr = sf.read(str(input_wav), dtype="float32")
    if audio.ndim > 1:
        audio = audio.mean(axis=1)

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
            }
        )
    return models


def list_inputs():
    """返回 data/matrix/ 下可用的 degraded wav（04 产物）。"""
    if not MATRIX_DIR.exists():
        return []
    return [{"name": p.name, "path": str(p)} for p in sorted(MATRIX_DIR.glob("*.wav"))]


def run(input_wav, model="gtcrn"):
    """对一条 degraded wav 跑降噪，落盘并按模型追加 CSV。"""
    input_wav = Path(input_wav)
    if not input_wav.exists():
        return {"status": "error", "message": f"输入 wav 不存在：{input_wav}"}
    if model not in MODEL_FILES:
        return {
            "status": "error",
            "message": f"未知模型：{model}，可选 {list(MODEL_FILES.keys())}",
        }

    out_dir = DENOISED_DIR / model
    output_wav = out_dir / f"{input_wav.stem}__{model}.wav"

    try:
        result = process(str(input_wav), str(output_wav), {"model": model})
    except Exception as exc:
        return {"status": "error", "message": str(exc)}

    if result.get("status") != "ok":
        return result

    row = {
        "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "model": model,
        "model_name": MODEL_LABELS.get(model, model),
        "input": str(input_wav),
        "output": str(output_wav),
        "input_sample_rate": result.get("input_sample_rate"),
        "work_sample_rate": result.get("work_sample_rate"),
        "duration_s": result.get("duration_s"),
    }
    csv_path = DENOISED_DIR / "denoise_runs.csv"
    existed = csv_path.exists()
    with csv_path.open("a", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(row.keys()))
        if not existed:
            writer.writeheader()
        writer.writerow(row)

    return {
        "status": "ok",
        "model": model,
        "model_name": MODEL_LABELS.get(model, model),
        "input": str(input_wav),
        "output": str(output_wav),
        "filename": output_wav.name,
        "input_sample_rate": result.get("input_sample_rate"),
        "work_sample_rate": result.get("work_sample_rate"),
        "duration_s": result.get("duration_s"),
        "csv": str(csv_path),
    }
