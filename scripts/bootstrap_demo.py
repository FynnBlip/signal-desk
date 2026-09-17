# -*- coding: utf-8 -*-
"""Generate deterministic, synthetic smoke fixtures for a fresh clone.

These files only exercise the seven-slot wiring. They are not speech, not a benchmark,
and must never be used as evidence for audio quality.
"""

from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path


def _load_wiring():
    spec = importlib.util.spec_from_file_location(
        "channel_wiring",
        Path(__file__).resolve().parents[1] / "modules" / "04_channel" / "wiring.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_wav(path: Path, audio, sample_rate: int, force: bool, wiring) -> None:
    if path.exists() and not force:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(wiring.wav_bytes(audio, sample_rate))


def build(root: Path, force: bool = False) -> list[Path]:
    root = Path(root)
    wiring = _load_wiring()
    created = []
    exam = root / "data" / "exam" / "demo_synthetic_probe.wav"
    write_wav(exam, wiring.probe_audio(), wiring.SAMPLE_RATE, force, wiring)
    created.append(exam)

    for index, scene in enumerate(wiring.SCENES):
        noise = wiring.scene_noise_audio(index)
        source = root / "data" / "noise" / "demand" / scene / "demo_synthetic_noise.wav"
        preview = root / "data" / "noise" / "preview" / f"{scene}_20s.wav"
        write_wav(source, noise, wiring.SAMPLE_RATE, force, wiring)
        write_wav(preview, noise, wiring.SAMPLE_RATE, force, wiring)
        created.extend([source, preview])
    notice = root / "data" / "DEMO_SYNTHETIC_ONLY.txt"
    notice.parent.mkdir(parents=True, exist_ok=True)
    notice.write_text(
        "Synthetic smoke fixtures only. Not speech, not a benchmark, not scientific evidence.\n",
        encoding="utf-8",
    )
    created.append(notice)
    return created


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    files = build(args.root.resolve(), args.force)
    print(f"Generated or verified {len(files)} synthetic smoke fixtures under {args.root.resolve()}")
