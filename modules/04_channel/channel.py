# -*- coding: utf-8 -*-
"""04 信道仿真 —— 噪声注入 + Opus 编解码闭环。

信号链：干净 wav → 加噪（场景 / SNR）→ Opus 编解码 → degraded wav。
噪声是"信道/环境"的一部分，落在 04；05 降噪只负责吃 degraded wav。

数据红线：所有数字来自真实产物；码率记「设定 + 实测」两列；seed 落 CSV。
"""

import csv
import datetime
import subprocess
from pathlib import Path

import librosa
import numpy as np
import soundfile as sf

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
MATRIX_DIR = PROJECT_ROOT / "data" / "matrix"
EXAM_DIR = PROJECT_ROOT / "data" / "exam"
NOISE_DIR = PROJECT_ROOT / "data" / "noise"
PREVIEW_DIR = NOISE_DIR / "preview"

BANDWIDTHS = {
    "narrowband": {"label": "窄带 8k", "sample_rate": 8000, "bitrate_min": 8, "bitrate_max": 12, "default_bitrate": 12},
    "wideband": {"label": "宽带 16k", "sample_rate": 16000, "bitrate_min": 16, "bitrate_max": 24, "default_bitrate": 16},
    "superwideband": {"label": "超宽带 24k", "sample_rate": 24000, "bitrate_min": 24, "bitrate_max": 32, "default_bitrate": 24},
    "fullband": {"label": "全频带 48k", "sample_rate": 48000, "bitrate_min": 32, "bitrate_max": 64, "default_bitrate": 32},
}
DEFAULT_BANDWIDTH = "wideband"
DEFAULT_BITRATE = 16
DEFAULT_SEED = 42

# 六个噪声场景（DEMAND），地铁用 90dB 实验室档
NOISE_SCENES = [
    {"id": "NPARK", "label": "安静 · 公园", "snr_db": 25, "level_db": 45, "dir": "demand/NPARK", "preview": "NPARK_20s.wav"},
    {"id": "OOFFICE", "label": "办公室", "snr_db": 15, "level_db": 55, "dir": "demand/OOFFICE", "preview": "OOFFICE_20s.wav"},
    {"id": "PCAFETER", "label": "咖啡厅", "snr_db": 10, "level_db": 70, "dir": "demand/PCAFETER", "preview": "PCAFETER_20s.wav"},
    {"id": "PRESTO", "label": "食堂", "snr_db": 5, "level_db": 72, "dir": "demand/PRESTO", "preview": "PRESTO_20s.wav"},
    {"id": "STRAFFIC", "label": "路口 · 交通", "snr_db": 0, "level_db": 75, "dir": "demand/STRAFFIC", "preview": "STRAFFIC_20s.wav"},
    {"id": "TMETRO", "label": "地铁 · 90dB", "snr_db": -10, "level_db": 90, "dir": "demand/TMETRO", "preview": "TMETRO_20s.wav"},
]


def _ffmpeg_exe():
    """从 imageio-ffmpeg 取本地 ffmpeg 二进制，不依赖系统 PATH。"""
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


def list_presets():
    """返回 Opus 带宽/码率预设，供前端渲染。"""
    return [
        {
            "id": key,
            "label": value["label"],
            "sample_rate": value["sample_rate"],
            "bitrate_min": value["bitrate_min"],
            "bitrate_max": value["bitrate_max"],
            "default_bitrate": value["default_bitrate"],
        }
        for key, value in BANDWIDTHS.items()
    ]


def list_inputs():
    """返回 data/exam/ 下可用干净 wav（03 产物）。"""
    if not EXAM_DIR.exists():
        return []
    return [{"name": p.name, "path": str(p)} for p in sorted(EXAM_DIR.glob("*.wav"))]


def list_noise_scenes():
    """返回六个噪声场景清单（含试听预览是否就绪）。"""
    scenes = []
    for s in NOISE_SCENES:
        item = dict(s)
        item["preview_ready"] = (PREVIEW_DIR / s["preview"]).exists()
        scenes.append(item)
    return scenes


def _run(cmd):
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    proc = subprocess.run(cmd, capture_output=True, text=True, creationflags=flags)
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout).strip()[-800:])
    return proc


def _mix_noise(clean_path, scene, out_path, seed):
    """把场景噪声按 SNR 混入干净 wav，写到 out_path（保持输入采样率）。"""
    audio, sr = sf.read(str(clean_path), dtype="float32")
    if audio.ndim > 1:
        audio = audio.mean(axis=1)

    noise_dir = NOISE_DIR / scene["dir"]
    segments = []
    for seg_file in sorted(noise_dir.glob("*.wav")):
        seg, seg_sr = sf.read(str(seg_file), dtype="float32")
        if seg.ndim > 1:
            seg = seg.mean(axis=1)
        if seg_sr != sr:
            seg = librosa.resample(seg, orig_sr=seg_sr, target_sr=sr)
        segments.append(seg)
    if not segments:
        raise ValueError(f"噪声目录没有 wav：{noise_dir}")

    # 逐段 RMS 归一化：DEMAND 各段功率差异大，不归一化会让设定 SNR 失真
    rms = [float(np.sqrt(np.mean(s**2))) or 1e-12 for s in segments]
    target_rms = float(np.median(rms))
    segments = [s * (target_rms / r) for s, r in zip(segments, rms)]
    noise = np.concatenate(segments)

    n = len(audio)
    if len(noise) < n:
        noise = np.tile(noise, int(np.ceil(n / len(noise))))[:n]
    else:
        rng = np.random.default_rng(seed)
        start = int(rng.integers(0, len(noise) - n + 1))
        noise = noise[start : start + n]

    signal_power = float(np.mean(audio**2)) or 1e-12
    noise_power = signal_power / (10 ** (scene["snr_db"] / 10))
    noise_data_power = float(np.mean(noise**2)) or 1e-12
    scale = np.sqrt(noise_power / noise_data_power)
    noisy = audio + noise * scale

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(out_path), noisy, sr)
    return sr


def encode_decode(input_wav, bandwidth=DEFAULT_BANDWIDTH, bitrate_kbps=DEFAULT_BITRATE, cbr=False, output_dir=None, seed=DEFAULT_SEED, noise_meta=None, reference=None):
    """对单个 wav 做 Opus 编解码，返回 degraded（codec-only 或 noise+codec）产物与实测码率。"""
    input_wav = Path(input_wav)
    if not input_wav.exists():
        return {"status": "error", "message": f"输入 wav 不存在：{input_wav}"}
    ref_path = Path(reference) if reference else input_wav

    bw = BANDWIDTHS.get(bandwidth)
    if not bw:
        return {"status": "error", "message": f"未知带宽档：{bandwidth}"}
    if not (bw["bitrate_min"] <= bitrate_kbps <= bw["bitrate_max"]):
        return {
            "status": "error",
            "message": f"码率 {bitrate_kbps}kbps 超出「{bw['label']}」建议范围 {bw['bitrate_min']}~{bw['bitrate_max']} kbps",
        }

    out_dir = Path(output_dir) if output_dir else MATRIX_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        info = sf.info(str(input_wav))
        input_sr = info.samplerate
        duration = info.duration
    except Exception as exc:
        return {"status": "error", "message": f"读取输入 wav 失败：{exc}"}

    ff = _ffmpeg_exe()
    noise_tag = ""
    if noise_meta:
        noise_tag = f"{noise_meta['id']}_snr{noise_meta['snr_db']}dB_"
    tag = f"{input_wav.stem}__{noise_tag}opus_{bandwidth}_{bitrate_kbps}k_{'cbr' if cbr else 'vbr'}_seed{seed}"
    opus_path = out_dir / f"{tag}.opus"
    wav_path = out_dir / f"{tag}.wav"

    enc = [
        ff, "-y", "-i", str(input_wav),
        "-c:a", "libopus", "-b:a", f"{bitrate_kbps}k",
        "-ar", str(bw["sample_rate"]), "-application", "voip",
    ]
    if cbr:
        enc += ["-vbr", "off"]
    enc += [str(opus_path)]

    dec = [
        ff, "-y", "-i", str(opus_path),
        "-c:a", "pcm_s16le", "-ar", str(input_sr), str(wav_path),
    ]

    try:
        _run(enc)
        _run(dec)
    except Exception as exc:
        return {"status": "error", "message": str(exc)}

    opus_bytes = opus_path.stat().st_size
    measured_bitrate = round(opus_bytes * 8 / duration / 1000, 1) if duration > 0 else 0.0

    row = {
        "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "reference": str(ref_path),
        "degraded": str(wav_path),
        "noise_scene": noise_meta["id"] if noise_meta else "",
        "noise_label": noise_meta["label"] if noise_meta else "无噪声",
        "snr_db": noise_meta["snr_db"] if noise_meta else "",
        "level_db": noise_meta["level_db"] if noise_meta else "",
        "codec": "opus",
        "bandwidth": bandwidth,
        "bandwidth_label": bw["label"],
        "bitrate_set_kbps": bitrate_kbps,
        "bitrate_measured_kbps": measured_bitrate,
        "vbr_cbr": "cbr" if cbr else "vbr",
        "seed": seed,
        "input_sr": input_sr,
        "opus_sr": bw["sample_rate"],
        "duration_s": round(duration, 3),
        "opus_bytes": opus_bytes,
        "mode": "noise_codec" if noise_meta else "codec_only",
    }

    csv_path = out_dir / "channel_runs.csv"
    existed = csv_path.exists()
    with csv_path.open("a", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(row.keys()))
        if not existed:
            writer.writeheader()
        writer.writerow(row)

    return {
        "status": "ok",
        "reference": str(ref_path),
        "degraded": str(wav_path),
        "filename": wav_path.name,
        "opus_filename": opus_path.name,
        "noise_scene": noise_meta["id"] if noise_meta else "",
        "noise_label": noise_meta["label"] if noise_meta else "无噪声",
        "snr_db": noise_meta["snr_db"] if noise_meta else None,
        "level_db": noise_meta["level_db"] if noise_meta else None,
        "bandwidth": bandwidth,
        "bandwidth_label": bw["label"],
        "bitrate_set_kbps": bitrate_kbps,
        "bitrate_measured_kbps": measured_bitrate,
        "vbr_cbr": "cbr" if cbr else "vbr",
        "seed": seed,
        "duration_s": round(duration, 3),
        "csv": str(csv_path),
    }


def run(input_wav, noise_scenes=None, bandwidth=DEFAULT_BANDWIDTH, bitrate_kbps=DEFAULT_BITRATE, cbr=False, seed=DEFAULT_SEED):
    """按选中的噪声场景批量施加「噪声 + 编解码」，每个场景一条 degraded wav。"""
    input_wav = Path(input_wav)
    if not input_wav.exists():
        return {"status": "error", "message": f"输入 wav 不存在：{input_wav}"}

    bw = BANDWIDTHS.get(bandwidth)
    if not bw:
        return {"status": "error", "message": f"未知带宽档：{bandwidth}"}

    scenes = []
    for sid in (noise_scenes or []):
        scene = next((s for s in NOISE_SCENES if s["id"] == sid), None)
        if scene:
            scenes.append(scene)
    if not scenes:
        scenes = [None]

    tmp_dir = MATRIX_DIR / ".tmp_noisy"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    runs = []
    for scene in scenes:
        codec_in = input_wav
        noise_meta = None
        tmp_file = None
        if scene:
            tmp_file = tmp_dir / f"{input_wav.stem}.wav"
            try:
                _mix_noise(input_wav, scene, tmp_file, seed)
            except Exception as exc:
                runs.append({"status": "error", "noise_scene": scene["id"], "message": str(exc)})
                continue
            codec_in = tmp_file
            noise_meta = scene

        res = encode_decode(codec_in, bandwidth=bandwidth, bitrate_kbps=bitrate_kbps, cbr=cbr, seed=seed, noise_meta=noise_meta, reference=str(input_wav))
        runs.append(res)

        if tmp_file and tmp_file.exists():
            try:
                tmp_file.unlink()
            except Exception:
                pass

    return {
        "status": "ok",
        "input": str(input_wav),
        "bandwidth": bandwidth,
        "bandwidth_label": bw["label"],
        "bitrate_set_kbps": bitrate_kbps,
        "cbr": cbr,
        "seed": seed,
        "n_runs": len(runs),
        "runs": runs,
    }
