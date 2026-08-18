# -*- coding: utf-8 -*-
"""06 评测 —— audiobox-aesthetics PQ/PC/CE/CU + 三份对比 ΔPQ。

对比口径：同一条干净样本，评三份
    clean（data/exam）→ degraded（data/matrix）→ denoised（data/denoised/<model>）
算 ΔPQ = 降噪后 PQ - 降噪前 PQ，看降噪器把质量救回来多少。

数据红线：分数全部来自 audiobox-aesthetics 真实推理；模型路径从 .env 读。
"""

import csv
import datetime
import os
import warnings
from pathlib import Path

import soundfile as sf
import torch

warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=UserWarning)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
EVAL_DIR = PROJECT_ROOT / "data" / "eval"
MATRIX_DIR = PROJECT_ROOT / "data" / "matrix"
EXAM_DIR = PROJECT_ROOT / "data" / "exam"
DENOISED_DIR = PROJECT_ROOT / "data" / "denoised"

DIMS = ["pq", "pc", "ce", "cu"]


def _load_env_file():
    """从 signal-desk/.env 读取密钥/路径（不覆盖已有环境变量）。"""
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_env_file()


def get_checkpoint():
    """返回 audiobox checkpoint 路径，找不到返回 None。"""
    raw = os.environ.get("AUDIOBOX_CHECKPOINT")
    if raw and Path(raw).exists():
        return str(Path(raw))
    return None


def load_predictor(ckpt_path=None):
    """加载 audiobox-aesthetics 预测器（模型大，主流程只加载一次）。"""
    from audiobox_aesthetics.infer import initialize_predictor

    ckpt = ckpt_path or get_checkpoint()
    if not ckpt or not Path(ckpt).exists():
        raise RuntimeError("找不到 audiobox checkpoint，请在 .env 设置 AUDIOBOX_CHECKPOINT")
    return initialize_predictor(ckpt=str(ckpt))


def _load_wav(filepath):
    """读成模型需要的张量 [声道, 采样点]。"""
    data, sr = sf.read(str(filepath), always_2d=True)
    wav = torch.from_numpy(data.T).float()
    return wav, sr


def score_files(predictor, filepaths, batch_size=4, progress_cb=None):
    """批量打分，返回 {文件绝对路径: {pq,pc,ce,cu}}。"""
    files = [Path(p) for p in filepaths if Path(p).exists()]
    results = {}
    total = len(files)
    done = 0
    for i in range(0, total, batch_size):
        chunk = files[i : i + batch_size]
        inputs = []
        for fp in chunk:
            wav, sr = _load_wav(fp)
            inputs.append({"path": wav, "sample_rate": sr})
        outputs = predictor.forward(inputs)
        for fp, scores in zip(chunk, outputs):
            results[str(fp)] = {
                "pq": round(float(scores["PQ"]), 4),
                "pc": round(float(scores["PC"]), 4),
                "ce": round(float(scores["CE"]), 4),
                "cu": round(float(scores["CU"]), 4),
            }
        done += len(chunk)
        if progress_cb:
            progress_cb(done, total, "评测中…")
    return results


def list_models():
    """返回 data/denoised 下已落盘的模型目录名。"""
    if not DENOISED_DIR.exists():
        return []
    return sorted(p.name for p in DENOISED_DIR.iterdir() if p.is_dir())


def load_channel_meta():
    """读 04 的 channel_runs.csv，建 degraded 文件名 -> 场景/SNR 元信息。"""
    meta = {}
    csv_path = MATRIX_DIR / "channel_runs.csv"
    if not csv_path.exists():
        return meta
    with csv_path.open(encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            degraded = Path(row.get("degraded", "")).name
            if degraded:
                meta[degraded] = {
                    "noise_label": row.get("noise_label", ""),
                    "snr_db": row.get("snr_db", ""),
                    "level_db": row.get("level_db", ""),
                    "bandwidth_label": row.get("bandwidth_label", ""),
                }
    return meta


def collect_samples():
    """把 data/denoised/<model>/ 的产物映射回 degraded + clean，按 degraded stem 分组。"""
    samples = {}
    if not DENOISED_DIR.exists():
        return samples
    for model_dir in DENOISED_DIR.iterdir():
        if not model_dir.is_dir():
            continue
        model = model_dir.name
        for f in model_dir.glob("*.wav"):
            suffix = f"__{model}.wav"
            if not f.name.endswith(suffix):
                continue
            degraded_stem = f.name[: -len(suffix)]
            degraded = MATRIX_DIR / f"{degraded_stem}.wav"
            clean_stem = degraded_stem.split("__")[0]
            clean = EXAM_DIR / f"{clean_stem}.wav"
            if not degraded.exists() or not clean.exists():
                continue
            s = samples.setdefault(
                degraded_stem,
                {"clean": str(clean), "degraded": str(degraded), "models": {}},
            )
            s["models"][model] = str(f)
    return samples


def compare(progress_cb=None, batch_size=4):
    """跑「干净→退化→降噪」对比，落 CSV 并返回行/摘要。"""
    samples = collect_samples()
    if not samples:
        return {"status": "error", "message": "没有可对比的降噪产物，请先在 05 降噪 DUT 生成 denoised wav。"}

    if progress_cb:
        progress_cb(0, 0, "加载 audiobox-aesthetics 模型…")
    predictor = load_predictor()

    # 去重收集要打分的文件
    file_order = []
    for stem in samples:
        s = samples[stem]
        file_order.append(s["clean"])
        file_order.append(s["degraded"])
        file_order.extend(s["models"].values())
    unique_files = list(dict.fromkeys(file_order))

    if progress_cb:
        progress_cb(0, len(unique_files), "评测中…")
    scores = score_files(predictor, unique_files, batch_size=batch_size, progress_cb=progress_cb)

    meta = load_channel_meta()
    models = sorted({m for s in samples.values() for m in s["models"].keys()})

    rows = []
    for stem, s in samples.items():
        clean_sc = scores.get(s["clean"])
        deg_sc = scores.get(s["degraded"])
        if clean_sc is None or deg_sc is None:
            continue
        m = meta.get(f"{stem}.wav", {})
        row = {
            "degraded_stem": stem,
            "noise_label": m.get("noise_label", ""),
            "snr_db": m.get("snr_db", ""),
            "bandwidth_label": m.get("bandwidth_label", ""),
            "clean_pq": clean_sc["pq"],
            "degraded_pq": deg_sc["pq"],
        }
        for model in models:
            model_sc = scores.get(s["models"].get(model))
            if model_sc is None:
                continue
            row[f"{model}_pq"] = model_sc["pq"]
            row[f"{model}_delta"] = round(model_sc["pq"] - deg_sc["pq"], 4)
        rows.append(row)

    # 排序：按 SNR 降序（安静在前），缺省按 stem
    def _snr(r):
        try:
            return float(r["snr_db"])
        except (TypeError, ValueError):
            return -999.0

    rows.sort(key=lambda r: (-_snr(r), r["degraded_stem"]))

    summary = _build_summary(rows, models)

    csv_path = EVAL_DIR / f"eval_comparison_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    EVAL_DIR.mkdir(parents=True, exist_ok=True)
    fieldnames = ["degraded_stem", "noise_label", "snr_db", "bandwidth_label", "clean_pq", "degraded_pq"]
    for model in models:
        fieldnames += [f"{model}_pq", f"{model}_delta"]
    with csv_path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in rows:
            writer.writerow({k: r.get(k, "") for k in fieldnames})

    return {
        "status": "ok",
        "models": models,
        "rows": rows,
        "summary": summary,
        "csv": str(csv_path),
        "n": len(rows),
    }


def _build_summary(rows, models):
    """算平均 PQ / 平均 ΔPQ，供前端统计卡用。"""
    def avg(key):
        vals = [r[key] for r in rows if r.get(key) is not None]
        return round(sum(vals) / len(vals), 4) if vals else None

    summary = {
        "n": len(rows),
        "clean_pq_avg": avg("clean_pq"),
        "degraded_pq_avg": avg("degraded_pq"),
    }
    for model in models:
        summary[f"{model}_pq_avg"] = avg(f"{model}_pq")
        summary[f"{model}_delta_avg"] = avg(f"{model}_delta")
    return summary
