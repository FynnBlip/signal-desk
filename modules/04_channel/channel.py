# -*- coding: utf-8 -*-
"""04 信道仿真 —— Opus 编解码闭环（第一版）。

第一版只做 Opus 编解码 + 仅编解码对照，覆盖 VoIP/OTT 通话。
噪声/增益、丢包/抖动/PLC 按 ADR-002 后续接入。

数据红线：所有数字来自真实产物；码率记「设定 + 实测」两列；seed 落 CSV。
"""

import csv
import datetime
import subprocess
from pathlib import Path

import soundfile as sf

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
MATRIX_DIR = PROJECT_ROOT / "data" / "matrix"
EXAM_DIR = PROJECT_ROOT / "data" / "exam"

BANDWIDTHS = {
    "narrowband": {"label": "窄带 8k", "sample_rate": 8000, "bitrate_min": 8, "bitrate_max": 12, "default_bitrate": 12},
    "wideband": {"label": "宽带 16k", "sample_rate": 16000, "bitrate_min": 16, "bitrate_max": 24, "default_bitrate": 16},
    "superwideband": {"label": "超宽带 24k", "sample_rate": 24000, "bitrate_min": 24, "bitrate_max": 32, "default_bitrate": 24},
    "fullband": {"label": "全频带 48k", "sample_rate": 48000, "bitrate_min": 32, "bitrate_max": 64, "default_bitrate": 32},
}
DEFAULT_BANDWIDTH = "wideband"
DEFAULT_BITRATE = 16
DEFAULT_SEED = 42


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


def _run(cmd):
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    proc = subprocess.run(cmd, capture_output=True, text=True, creationflags=flags)
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout).strip()[-800:])
    return proc


def encode_decode(input_wav, bandwidth=DEFAULT_BANDWIDTH, bitrate_kbps=DEFAULT_BITRATE, cbr=False, output_dir=None, seed=DEFAULT_SEED):
    """对单个干净 wav 做 Opus 编解码，返回 degraded（当前为 codec-only）产物与实测码率。"""
    input_wav = Path(input_wav)
    if not input_wav.exists():
        return {"status": "error", "message": f"输入 wav 不存在：{input_wav}"}

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
    tag = f"{input_wav.stem}__opus_{bandwidth}_{bitrate_kbps}k_{'cbr' if cbr else 'vbr'}_seed{seed}"
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
        "reference": str(input_wav),
        "degraded": str(wav_path),
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
        "mode": "codec_only",
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
        "reference": str(input_wav),
        "degraded": str(wav_path),
        "filename": wav_path.name,
        "opus_filename": opus_path.name,
        "bandwidth": bandwidth,
        "bandwidth_label": bw["label"],
        "bitrate_set_kbps": bitrate_kbps,
        "bitrate_measured_kbps": measured_bitrate,
        "vbr_cbr": "cbr" if cbr else "vbr",
        "seed": seed,
        "duration_s": round(duration, 3),
        "csv": str(csv_path),
    }
