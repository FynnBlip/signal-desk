# -*- coding: utf-8 -*-
"""Canonical synthetic smoke fixtures. Wiring only — never scientific evidence."""

from __future__ import annotations

import functools
import hashlib
import io
from pathlib import Path

import numpy as np
import soundfile as sf

SCENES = ["NPARK", "OOFFICE", "PCAFETER", "PRESTO", "STRAFFIC", "TMETRO"]
SAMPLE_RATE = 16000
DURATION_S = 10.0
MIN_DURATION_S = 0.25
MIN_SAMPLE_RATE = 8000
MAX_SAMPLE_RATE = 48000
_INSPECT_MEMO: dict[tuple, dict] = {}


def _timeline(sample_rate: int = SAMPLE_RATE, duration: float = DURATION_S):
    return np.arange(int(sample_rate * duration), dtype=np.float32) / sample_rate


def probe_audio(sample_rate: int = SAMPLE_RATE, duration: float = DURATION_S):
    t = _timeline(sample_rate, duration)
    envelope = np.minimum(1.0, np.minimum(t / 0.08, (duration - t) / 0.12))
    return envelope * (0.12 * np.sin(2 * np.pi * 160 * t) + 0.05 * np.sin(2 * np.pi * 730 * t))


def scene_noise_audio(index: int, sample_rate: int = SAMPLE_RATE, duration: float = DURATION_S):
    t = _timeline(sample_rate, duration)
    rng = np.random.default_rng(4200 + index)
    return rng.normal(0.0, 0.06 + index * 0.008, len(t)).astype(np.float32)


def wav_bytes(audio, sample_rate: int = SAMPLE_RATE) -> bytes:
    buffer = io.BytesIO()
    sf.write(buffer, np.asarray(audio, dtype=np.float32), sample_rate, format="WAV")
    return buffer.getvalue()


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@functools.lru_cache(maxsize=1)
def canonical_wiring_hashes() -> frozenset[str]:
    hashes = {sha256_bytes(wav_bytes(probe_audio()))}
    for index, _scene in enumerate(SCENES):
        hashes.add(sha256_bytes(wav_bytes(scene_noise_audio(index))))
    return frozenset(hashes)


def _mark_wiring(report: dict) -> dict:
    report.update(ok=False, purpose="wiring", reason="合成布线素材，不能进入正式基准")
    return report


def inspect_wav(path: Path) -> dict:
    path = Path(path)
    report = {
        "name": path.name,
        "path": str(path),
        "ok": False,
        "purpose": "invalid",
        "reason": "",
        "sha256": "",
        "duration_s": 0.0,
        "samplerate": 0,
    }
    try:
        stat = path.stat()
    except OSError as exc:
        report["reason"] = f"无法读取：{exc}"
        return report
    key = (str(path.resolve()), stat.st_size, stat.st_mtime_ns)
    cached = _INSPECT_MEMO.get(key)
    if cached is not None:
        return dict(cached)

    wiring_name = path.name.lower().startswith("demo_synthetic_")
    if stat.st_size < 64:
        result = _mark_wiring(report) if wiring_name else {**report, "reason": "空文件或过短，不能当作噪声源"}
        _INSPECT_MEMO[key] = dict(result)
        return dict(result)
    try:
        info = sf.info(str(path))
        digest = sha256_file(path)
    except Exception as exc:
        result = _mark_wiring(report) if wiring_name else {**report, "reason": f"无法解码为 WAV：{exc}"}
        _INSPECT_MEMO[key] = dict(result)
        return dict(result)
    duration = float(info.frames) / float(info.samplerate or 1)
    report.update(sha256=digest, duration_s=round(duration, 4), samplerate=int(info.samplerate))
    if digest in canonical_wiring_hashes() or wiring_name:
        result = _mark_wiring(report)
        _INSPECT_MEMO[key] = dict(result)
        return dict(result)
    if info.frames <= 0 or duration < MIN_DURATION_S:
        report["reason"] = "音频时长无效"
        _INSPECT_MEMO[key] = dict(report)
        return dict(report)
    if info.samplerate < MIN_SAMPLE_RATE or info.samplerate > MAX_SAMPLE_RATE:
        report["reason"] = f"采样率无效：{info.samplerate}"
        _INSPECT_MEMO[key] = dict(report)
        return dict(report)
    report.update(ok=True, purpose="undeclared", reason="可解码，来源未声明，不当作已认证录音")
    _INSPECT_MEMO[key] = dict(report)
    return dict(report)
