# -*- coding: utf-8 -*-
"""06 评测 —— audiobox-aesthetics PQ/PC/CE/CU + 可选派生分 / ΔPQ 对比。

两种模式：
    directory   —— 评一个目录里的 wav（对齐 First-CC 批量评测工具）
    comparison  —— 评「干净→退化→降噪」三份，算 ΔPQ（agent loop 数据底座）

数据红线：分数全部来自 audiobox-aesthetics 真实推理；模型路径从 .env 读。
"""

import csv
import datetime
import json
import math
import os
from pathlib import Path

import soundfile as sf
import torch

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
EVAL_DIR = PROJECT_ROOT / "data" / "eval"
MATRIX_DIR = PROJECT_ROOT / "data" / "matrix"
EXAM_DIR = PROJECT_ROOT / "data" / "exam"
DENOISED_DIR = PROJECT_ROOT / "data" / "denoised"
SETTINGS_FILE = EVAL_DIR / "settings.json"

METRIC_NAMES = {
    "PQ": "制作质量",
    "PC": "制作复杂度",
    "CE": "内容愉悦度",
    "CU": "内容实用性",
}
METRIC_DESCRIPTIONS = {
    "PQ": "Production Quality — 技术制作品质：清晰度、保真度、动态、频响与空间感",
    "PC": "Production Complexity — 音频场景复杂程度（声部/成分数量），不是伪影或降噪指标",
    "CE": "Content Enjoyment — 主观愉悦度：情感共鸣、艺术表达与整体听感体验",
    "CU": "Content Usefulness — 作为内容创作素材的可用性与再利用价值",
}
DEFAULT_LEVELS = [
    {"min": 8.0, "label": "优秀", "color": "#34D399"},
    {"min": 6.0, "label": "良好", "color": "#60A5FA"},
    {"min": 4.0, "label": "一般", "color": "#FBBF24"},
    {"min": 0.0, "label": "较差", "color": "#F87171"},
]
DEFAULT_SETTINGS = {
    "schema_version": 3,
    "batch_size": 4,
    # PC 是 Production Complexity，不是“越高越好”的质量轴。默认不把四轴
    # 平均成一个看似权威的总分；项目方明确给出判据后才允许启用派生分。
    "overall_mode": "disabled",
    "weights": {"PQ": 1.0, "PC": 1.0, "CE": 1.0, "CU": 1.0},
    "custom_formula": "(PQ + PC + CE + CU) / 4",
    "level_enabled": False,
    "level_metric": "PQ",
    "levels": DEFAULT_LEVELS,
}


def _load_env_file():
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
    raw = os.environ.get("AUDIOBOX_CHECKPOINT")
    if raw and Path(raw).exists():
        return str(Path(raw))
    return None


def load_predictor(ckpt_path=None):
    from audiobox_aesthetics.infer import initialize_predictor

    ckpt = ckpt_path or get_checkpoint()
    if not ckpt or not Path(ckpt).exists():
        raise RuntimeError("找不到 audiobox checkpoint，请在 .env 设置 AUDIOBOX_CHECKPOINT")
    return initialize_predictor(ckpt=str(ckpt))


def _load_wav(filepath):
    data, sr = sf.read(str(filepath), always_2d=True)
    wav = torch.from_numpy(data.T).float()
    return wav, sr


def score_files(predictor, filepaths, batch_size=4, progress_cb=None):
    requested = [Path(p) for p in filepaths]
    missing = [str(path) for path in requested if not path.is_file()]
    if missing:
        preview = "、".join(missing[:3])
        suffix = f"（另有 {len(missing) - 3} 个）" if len(missing) > 3 else ""
        raise FileNotFoundError(f"评测输入不完整，缺少：{preview}{suffix}")
    files = requested
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
    if not DENOISED_DIR.exists():
        return []
    return sorted(p.name for p in DENOISED_DIR.iterdir() if p.is_dir())


def load_channel_meta():
    meta = {}
    # Legacy rows stay readable; schema-v2 rows win for the same degraded file.
    for csv_path in (MATRIX_DIR / "channel_runs.csv", MATRIX_DIR / "channel_runs_v2.csv", MATRIX_DIR / "channel_runs_v3.csv"):
        if not csv_path.exists():
            continue
        with csv_path.open(encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                degraded = Path(row.get("degraded", "")).name
                if degraded:
                    meta[degraded] = {
                        "noise_label": row.get("noise_label", ""),
                        "snr_db": row.get("snr_set_db") or row.get("snr_db", ""),
                        "snr_measured_db": row.get("snr_measured_db", ""),
                        "level_db": row.get("level_db", ""),
                        "bandwidth_label": row.get("bandwidth_label", ""),
                    }
    return meta


def collect_samples():
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


def scan_folder(folder):
    folder = Path(folder)
    if not folder.is_dir():
        return []
    return [str(p) for p in sorted(folder.glob("*.wav"))]


# ---------------------------------------------------------------------------
# 设置 / 评分逻辑
# ---------------------------------------------------------------------------

def load_settings():
    settings = json.loads(json.dumps(DEFAULT_SETTINGS))
    if SETTINGS_FILE.is_file():
        try:
            data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            # v1 默认把 PQ/PC/CE/CU 等权平均。这个语义不成立，所以旧设置
            # 不自动继承 average；用户保存过 v2 之后才按显式选择恢复。
            if int(data.get("schema_version", 1)) < 2:
                data["overall_mode"] = "disabled"
                data["level_enabled"] = False
            # v2 曾错误沿用 1–5 分制的 4/3/2 示例；AudioBox 四轴实际按
            # 0–10 展示。只迁移这一组精确的旧默认值，不触碰用户自定义阈值。
            legacy_levels = [4.0, 3.0, 2.0, 0.0]
            loaded_levels = data.get("levels") or []
            loaded_mins = [float(item.get("min", 0)) for item in loaded_levels]
            if int(data.get("schema_version", 1)) < 3 and loaded_mins == legacy_levels:
                data["levels"] = json.loads(json.dumps(DEFAULT_LEVELS))
            for key in (
                "schema_version", "batch_size", "overall_mode", "weights",
                "custom_formula", "level_enabled", "level_metric", "levels",
            ):
                if key in data:
                    settings[key] = data[key]
        except Exception:
            pass
    settings["schema_version"] = 3
    if settings.get("overall_mode") not in {"disabled", "weighted", "custom"}:
        settings["overall_mode"] = "disabled"
    return settings


def save_settings(settings):
    EVAL_DIR.mkdir(parents=True, exist_ok=True)
    normalized = json.loads(json.dumps(DEFAULT_SETTINGS))
    if isinstance(settings, dict):
        for key in normalized:
            if key in settings:
                normalized[key] = settings[key]
    normalized["schema_version"] = 3
    if normalized.get("overall_mode") not in {"disabled", "weighted", "custom"}:
        normalized["overall_mode"] = "disabled"
    SETTINGS_FILE.write_text(
        json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def eval_custom_formula(expr, pq, pc, ce, cu):
    formula = (expr or "").strip()
    if not formula:
        raise ValueError("自定义公式不能为空")
    scope = {
        "PQ": pq, "PC": pc, "CE": ce, "CU": cu,
        "pq": pq, "pc": pc, "ce": ce, "cu": cu,
        "min": min, "max": max, "abs": abs, "round": round, "sqrt": math.sqrt, "pow": pow,
    }
    try:
        return float(eval(formula, {"__builtins__": {}}, scope))
    except Exception as exc:
        raise ValueError(f"公式无效：{exc}") from exc


def compute_overall(pq, pc, ce, cu, settings):
    mode = settings.get("overall_mode", "disabled")
    if mode == "disabled":
        return None
    if mode == "custom":
        return eval_custom_formula(settings.get("custom_formula", ""), pq, pc, ce, cu)
    if mode == "weighted":
        w = settings.get("weights", {})
        total = float(w.get("PQ", 1.0)) + float(w.get("PC", 1.0)) + float(w.get("CE", 1.0)) + float(w.get("CU", 1.0))
        if total <= 0:
            return (pq + pc + ce + cu) / 4.0
        return (pq * float(w.get("PQ", 1.0)) + pc * float(w.get("PC", 1.0)) + ce * float(w.get("CE", 1.0)) + cu * float(w.get("CU", 1.0))) / total
    return None


def get_level(score, levels):
    if not levels:
        return {"label": "未分级", "color": "#746F65"}
    ordered = sorted(levels, key=lambda x: -float(x.get("min", 0.0)))
    for lv in ordered:
        if score >= float(lv.get("min", 0.0)):
            return {"label": lv.get("label", ""), "color": lv.get("color", "#94A3B8")}
    return {"label": ordered[-1].get("label", ""), "color": ordered[-1].get("color", "#94A3B8")}


def _annotate(scores, settings):
    pq = scores["pq"]
    pc = scores["pc"]
    ce = scores["ce"]
    cu = scores["cu"]
    raw_overall = compute_overall(pq, pc, ce, cu, settings)
    overall = round(raw_overall, 4) if raw_overall is not None else None
    level = {"label": "未分级", "color": "#746F65"}
    if settings.get("level_enabled"):
        metric = str(settings.get("level_metric", "PQ")).upper()
        metric_value = {"PQ": pq, "PC": pc, "CE": ce, "CU": cu, "OVERALL": overall}.get(metric)
        if metric_value is not None:
            level = get_level(metric_value, settings.get("levels", DEFAULT_LEVELS))
    return {
        "pq": pq, "pc": pc, "ce": ce, "cu": cu,
        "overall": overall,
        "level": level["label"],
        "level_color": level["color"],
    }


def build_stats(files):
    def summarize(rows, scope):
        if not rows:
            return {"metric": "pq", "scope": scope, "n": 0, "avg": None, "max": None, "min": None, "std": None}
        values = [item["pq"] for item in rows]
        avg = sum(values) / len(values)
        std = math.sqrt(sum((score - avg) ** 2 for score in values) / len(values)) if len(values) > 1 else 0.0
        max_f = max(rows, key=lambda item: item["pq"])
        min_f = min(rows, key=lambda item: item["pq"])
        return {
            "metric": "pq", "scope": scope, "n": len(rows), "avg": round(avg, 4),
            "max": round(max_f["pq"], 4), "max_file": max_f["filename"],
            "min": round(min_f["pq"], 4), "min_file": min_f["filename"],
            "std": round(std, 4),
        }

    result = summarize(files, "all_sources")
    result["by_source"] = {
        source: summarize(
            [item for item in files if str(item.get("source") or "未标注") == source],
            "source",
        )
        for source in sorted({str(item.get("source") or "未标注") for item in files})
    }
    return result


# ---------------------------------------------------------------------------
# 运行
# ---------------------------------------------------------------------------

def run_directory(folder, settings, progress_cb=None):
    paths = scan_folder(folder)
    if not paths:
        return {"status": "error", "message": f"目录里没有 wav：{folder}"}
    batch = max(1, int(settings.get("batch_size", 4)))
    if progress_cb:
        progress_cb(0, 0, "加载 audiobox-aesthetics 模型…")
    predictor = load_predictor()
    scores = score_files(predictor, paths, batch_size=batch, progress_cb=progress_cb)
    files = []
    for p in paths:
        sc = scores.get(p)
        if not sc:
            continue
        ann = _annotate(sc, settings)
        files.append({"filename": Path(p).name, "source": "目录", "filepath": p, **ann})
    return {
        "status": "ok",
        "mode": "directory",
        "folder": str(folder),
        "files": files,
        "stats": build_stats(files),
    }


def run_comparison(settings, progress_cb=None):
    samples = collect_samples()
    if not samples:
        return {"status": "error", "message": "没有可对比的降噪产物，请先在 05 降噪 DUT 生成 denoised wav。"}
    batch = max(1, int(settings.get("batch_size", 4)))
    if progress_cb:
        progress_cb(0, 0, "加载 audiobox-aesthetics 模型…")
    predictor = load_predictor()

    order = []
    for stem in samples:
        s = samples[stem]
        order.append(s["clean"])
        order.append(s["degraded"])
        order.extend(s["models"].values())
    unique = list(dict.fromkeys(order))
    scores = score_files(predictor, unique, batch_size=batch, progress_cb=progress_cb)

    meta = load_channel_meta()
    models = sorted({m for s in samples.values() for m in s["models"].keys()})
    incomplete = []
    for stem, sample in samples.items():
        missing_models = [model for model in models if model not in sample["models"]]
        if missing_models:
            incomplete.append(f"{stem} 缺少模型 {', '.join(missing_models)}")
    if incomplete:
        preview = "；".join(incomplete[:5])
        suffix = f"（另有 {len(incomplete) - 5} 条）" if len(incomplete) > 5 else ""
        raise RuntimeError(f"对比矩阵不完整：{preview}{suffix}")

    files = []
    rows = []
    seen_clean = set()
    for stem, s in samples.items():
        clean_sc = scores.get(s["clean"])
        deg_sc = scores.get(s["degraded"])
        if clean_sc is None or deg_sc is None:
            raise RuntimeError(f"对比矩阵评分缺失：{stem} 的干净或退化音频没有评分")
        m = meta.get(f"{stem}.wav", {})
        clean_ann = _annotate(clean_sc, settings)
        deg_ann = _annotate(deg_sc, settings)
        if s["clean"] not in seen_clean:
            seen_clean.add(s["clean"])
            files.append({"filename": Path(s["clean"]).name, "source": "干净", "sample": stem, "filepath": s["clean"], **clean_ann})
        files.append({"filename": Path(s["degraded"]).name, "source": "退化", "sample": stem, "filepath": s["degraded"], **deg_ann})

        row = {
            "sample": stem,
            "noise_label": m.get("noise_label", ""),
            "snr_db": m.get("snr_db", ""),
            "bandwidth_label": m.get("bandwidth_label", ""),
            "clean_pq": clean_sc["pq"],
            "degraded_pq": deg_sc["pq"],
        }
        for model in models:
            model_sc = scores.get(s["models"].get(model))
            if model_sc is None:
                raise RuntimeError(f"对比矩阵评分缺失：{stem} · {model}")
            model_ann = _annotate(model_sc, settings)
            files.append({"filename": Path(s["models"][model]).name, "source": model, "sample": stem, "filepath": s["models"][model], **model_ann})
            row[f"{model}_pq"] = model_sc["pq"]
            row[f"{model}_delta"] = round(model_sc["pq"] - deg_sc["pq"], 4)
        rows.append(row)

    def _snr(r):
        try:
            return float(r["snr_db"])
        except (TypeError, ValueError):
            return -999.0

    rows.sort(key=lambda r: (-_snr(r), r["sample"]))
    summary = build_comparison_summary(rows, models)

    csv_path = EVAL_DIR / f"eval_comparison_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    EVAL_DIR.mkdir(parents=True, exist_ok=True)
    fieldnames = ["sample", "noise_label", "snr_db", "bandwidth_label", "clean_pq", "degraded_pq"]
    for model in models:
        fieldnames += [f"{model}_pq", f"{model}_delta"]
    with csv_path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in rows:
            writer.writerow({k: r.get(k, "") for k in fieldnames})

    return {
        "status": "ok",
        "mode": "comparison",
        "files": files,
        "stats": build_stats(files),
        "comparison": {
            "models": models,
            "rows": rows,
            "summary": summary,
            "csv": str(csv_path),
        },
    }


def build_comparison_summary(rows, models):
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


def export_excel(files, out_path, settings=None):
    """按 First-CC 口径导出 Excel（评估结果 + 维度说明两张表）。"""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = "评估结果"
    headers = ["文件名", "PQ 制作质量", "PC 制作复杂度", "CE 内容愉悦度", "CU 内容实用性", "综合评分", "等级"]
    header_fill = PatternFill("solid", fgColor="A855F7")
    header_font = Font(bold=True, color="FFFFFF", size=11)
    thin = Side(style="thin", color="D4D4D8")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    for col, title in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=title)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = border
    ws.row_dimensions[1].height = 24
    stripe_a = PatternFill("solid", fgColor="FAFAFA")
    stripe_b = PatternFill("solid", fgColor="FFFFFF")
    for idx, r in enumerate(files, 2):
        level = {
            "label": r.get("level") or "未分级",
            "color": r.get("level_color") or "#746F65",
        }
        stripe = stripe_a if idx % 2 == 0 else stripe_b
        vals = [r.get("filename", ""), r.get("pq", 0), r.get("pc", 0), r.get("ce", 0), r.get("cu", 0), r.get("overall"), level["label"]]
        for col, value in enumerate(vals, 1):
            cell = ws.cell(row=idx, column=col, value=value)
            cell.border = border
            if col == 1:
                cell.alignment = Alignment(horizontal="left", vertical="center")
                cell.fill = stripe
            elif col == 7:
                cell.alignment = Alignment(horizontal="center", vertical="center")
                cell.fill = PatternFill("solid", fgColor=level["color"].lstrip("#"))
                cell.font = Font(bold=True, color="FFFFFF")
            else:
                cell.number_format = "0.000"
                cell.alignment = Alignment(horizontal="center", vertical="center")
                cell.fill = stripe
    name_w = max((len(r.get("filename", "")) for r in files), default=10)
    ws.column_dimensions["A"].width = min(max(name_w + 2, 28), 72)
    for col, width in enumerate([14, 14, 14, 14, 12, 10], 2):
        ws.column_dimensions[get_column_letter(col)].width = width
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:G{len(files) + 1}"

    info = wb.create_sheet("维度说明")
    info.column_dimensions["A"].width = 10
    info.column_dimensions["B"].width = 18
    info.column_dimensions["C"].width = 56
    info_rows = [("代号", "中文名", "含义")]
    for k in ("PQ", "PC", "CE", "CU"):
        info_rows.append((k, METRIC_NAMES[k], METRIC_DESCRIPTIONS[k]))
    for r_idx, row in enumerate(info_rows, 1):
        for c_idx, value in enumerate(row, 1):
            cell = info.cell(row=r_idx, column=c_idx, value=value)
            cell.border = border
            if r_idx == 1:
                cell.fill = header_fill
                cell.font = header_font
            cell.alignment = Alignment(horizontal="center" if c_idx <= 2 else "left", vertical="center", wrap_text=c_idx == 3)
    wb.save(out_path)
    return str(out_path)
