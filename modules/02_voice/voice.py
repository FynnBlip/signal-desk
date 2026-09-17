# -*- coding: utf-8 -*-
"""02 音色聚类 —— 第二块蛋糕。

职责：把音色样本按声线特征聚类，产出簇摘要 + 覆盖矩阵（F0 五档 × F1 三档），
并用肘部法 + 轮廓系数给出建议簇数 K。

特征两层：可解释层（F0 基频 + F1/F2/F3 共振峰）+ 音色层（13 维 MFCC）。
复用旧项目 analyze_voices.py 的特征逻辑，新增肘部法建议 K 与客观命名。

可独立运行：python modules/02_voice/voice.py --dir <音色目录>
"""

import argparse
import csv
import datetime
import json
import shutil
import uuid
from pathlib import Path

import joblib
import librosa
import numpy as np
import parselmouth
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import StandardScaler

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# 覆盖矩阵分档（F0 五档 × F1 三档）
F0_BINS = [0, 120, 150, 200, 280, np.inf]
F0_LABELS = ["<120", "120-150", "150-200", "200-280", ">280"]
F0_NAMES = ["低基频", "中低基频", "中高基频", "高基频", "超高基频"]
F1_BINS = [0, 400, 700, np.inf]
F1_LABELS = ["<400", "400-700", ">700"]
F1_NAMES = ["低 F1", "中 F1", "高 F1"]

FEATURE_ORDER = [
    "f0_mean", "f0_median", "f0_std", "f0_p05", "f0_p95",
    "f1_mean", "f2_mean", "f3_mean",
] + [f"mfcc_{i}" for i in range(13)]


def extract_features(filepath):
    """从单个 wav 提取声线特征（复用旧实现）。"""
    path = Path(filepath)
    snd = parselmouth.Sound(str(path))
    duration = snd.get_total_duration()
    sample_rate = snd.sampling_frequency

    pitch = snd.to_pitch()
    f0_all = pitch.selected_array["frequency"]
    f0_voiced = f0_all[np.isfinite(f0_all) & (f0_all > 0)]
    if len(f0_voiced) == 0:
        raise ValueError("no voiced frames")

    f0_mean = float(np.mean(f0_voiced))
    f0_median = float(np.median(f0_voiced))
    f0_std = float(np.std(f0_voiced))
    f0_p05 = float(np.percentile(f0_voiced, 5))
    f0_p95 = float(np.percentile(f0_voiced, 95))

    max_formant_hz = 5000 if f0_median < 160 else 5500
    formant = snd.to_formant_burg(maximum_formant=max_formant_hz)
    f1_list, f2_list, f3_list = [], [], []
    for i in range(1, formant.get_number_of_frames() + 1):
        t = formant.get_time_from_frame_number(i)
        v1 = formant.get_value_at_time(1, t)
        v2 = formant.get_value_at_time(2, t)
        v3 = formant.get_value_at_time(3, t)
        if v1 > 0:
            f1_list.append(v1)
        if v2 > 0:
            f2_list.append(v2)
        if v3 > 0:
            f3_list.append(v3)
    if len(f1_list) == 0:
        raise ValueError("no formant frames")

    y, sr = librosa.load(str(path), sr=None, mono=True)
    mfcc = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=13)
    mfcc_mean = mfcc.mean(axis=1)

    return {
        "file": path.name,
        "duration_s": round(duration, 2),
        "sample_rate": int(sample_rate),
        "f0_mean": round(f0_mean, 2),
        "f0_median": round(f0_median, 2),
        "f0_std": round(f0_std, 2),
        "f0_p05": round(f0_p05, 2),
        "f0_p95": round(f0_p95, 2),
        "f1_mean": round(float(np.mean(f1_list)), 2),
        "f2_mean": round(float(np.mean(f2_list)), 2),
        "f3_mean": round(float(np.mean(f3_list)), 2),
        "mfcc": [round(float(v), 4) for v in mfcc_mean],
    }


def _feature_vector(feat):
    return [feat[name] for name in FEATURE_ORDER[:8]] + list(feat["mfcc"])


def cluster_voices(features, n_clusters):
    X = np.array([_feature_vector(f) for f in features])
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)
    model = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
    labels = model.fit_predict(X_scaled)
    distances = np.linalg.norm(X_scaled - model.cluster_centers_[labels], axis=1)
    for feat, dist in zip(features, distances):
        feat["_distance"] = float(dist)
    return labels, scaler, model


def _stable_labels(features, raw_labels):
    """按簇的 F0 中位数从低到高稳定编号，避免 KMeans 的 C1/C2 每次随机换名。"""
    raw_ids = sorted(set(int(v) for v in raw_labels))
    ordered = sorted(
        raw_ids,
        key=lambda cid: float(np.median([
            feat["f0_median"] for feat, label in zip(features, raw_labels) if int(label) == cid
        ])),
    )
    mapping = {raw: stable for stable, raw in enumerate(ordered)}
    return np.array([mapping[int(v)] for v in raw_labels], dtype=int), mapping


def build_coverage_matrix(features):
    matrix = np.zeros((len(F0_LABELS), len(F1_LABELS)), dtype=int)
    for feat in features:
        row = min(max(int(np.digitize(feat["f0_mean"], F0_BINS)) - 1, 0), len(F0_LABELS) - 1)
        col = min(max(int(np.digitize(feat["f1_mean"], F1_BINS)) - 1, 0), len(F1_LABELS) - 1)
        matrix[row, col] += 1
    return matrix


def _find_elbow(values):
    """最大垂直距离法找肘部拐点（Kneed 的简化版）。"""
    n = len(values)
    if n < 3:
        return 2
    v = np.array(values, dtype=float)
    vn = (v - v.min()) / (v.max() - v.min() + 1e-12)
    line = np.linspace(vn[0], vn[-1], n)
    dist = line - vn
    return int(np.argmax(dist)) + 2


def suggest_k(features, max_k=8):
    """肘部法 + 轮廓系数，给出建议 K 与整条曲线数据（供前端画）。"""
    X = np.array([_feature_vector(f) for f in features])
    Xs = StandardScaler().fit_transform(X)
    n = len(Xs)
    max_k = max(2, min(max_k, n - 1))
    inertias, sil = [], []
    for k in range(2, max_k + 1):
        m = KMeans(n_clusters=k, random_state=42, n_init=10).fit(Xs)
        inertias.append(m.inertia_)
        s = silhouette_score(Xs, m.labels_) if 2 <= k <= n - 1 else 0.0
        sil.append(s)
    curve = [
        {"k": k, "inertia": round(iner, 2), "silhouette": round(s, 4)}
        for k, (iner, s) in zip(range(2, max_k + 1), zip(inertias, sil))
    ]
    return {
        "k_elbow": _find_elbow(inertias),
        "k_silhouette": int(np.argmax(sil)) + 2,
        "curve": curve,
    }


def _f0_name(f0_mean):
    idx = min(max(int(np.digitize(f0_mean, F0_BINS)) - 1, 0), len(F0_NAMES) - 1)
    return F0_NAMES[idx], F0_LABELS[idx]


def _f1_name(f1_mean):
    idx = min(max(int(np.digitize(f1_mean, F1_BINS)) - 1, 0), len(F1_NAMES) - 1)
    return F1_NAMES[idx], F1_LABELS[idx]


def _summarize_clusters(features, labels):
    summaries = []
    for cid in sorted(set(labels)):
        members = [f for f, lab in zip(features, labels) if lab == cid]
        f0_vals = [m["f0_mean"] for m in members]
        rep = min(members, key=lambda m: m["_distance"])
        f0_name, f0_label = _f0_name(float(np.median(f0_vals)))
        f1_name, f1_label = _f1_name(float(np.mean([m["f1_mean"] for m in members])))
        summaries.append({
            "cluster": int(cid),
            "count": len(members),
            "f0_min": round(min(f0_vals), 1),
            "f0_max": round(max(f0_vals), 1),
            "f0_label": f0_label,
            "f0_name": f0_name,
            "f1_name": f1_name,
            "name": f"C{int(cid) + 1} · {f0_name} · {f1_name}",
            "subjective": "",  # 待峰哥盲听后贴听感标签
            "representative": rep["file"],
            "files": [m["file"] for m in members],
        })
    return summaries


def load_clusters(csv_path=None):
    """只读：从落盘的 voice_clusters.csv 读簇摘要，供总览 loop canvas 复用。

    不重新提特征，只读 CSV，保证轻量且数据诚实（数字来自落盘，不写死）。
    """
    if csv_path is None:
        pointer = PROJECT_ROOT / "data" / "voice" / "active_cohort.json"
        if pointer.exists():
            try:
                cohort_id = json.loads(pointer.read_text(encoding="utf-8")).get("cohort_id")
                result_file = PROJECT_ROOT / "data" / "voice" / "cohorts" / str(cohort_id) / "cluster_result.json"
                if result_file.exists():
                    return json.loads(result_file.read_text(encoding="utf-8")).get("clusters") or []
            except (OSError, ValueError, TypeError):
                pass
    csv_path = Path(csv_path) if csv_path else PROJECT_ROOT / "data" / "voice" / "voice_clusters.csv"
    if not csv_path.exists():
        return []

    rows = []
    with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            try:
                rows.append({
                    "file": r["file"],
                    "cluster": int(r["cluster"]),
                    "f0_mean": float(r["f0_mean"]),
                    "f0_median": float(r["f0_median"]),
                    "f1_mean": float(r["f1_mean"]),
                })
            except (KeyError, ValueError):
                continue

    clusters = []
    for cid in sorted({r["cluster"] for r in rows}):
        members = [r for r in rows if r["cluster"] == cid]
        f0_med = float(np.median([m["f0_median"] for m in members]))
        f0_name, _ = _f0_name(float(np.median([m["f0_mean"] for m in members])))
        f1_name, _ = _f1_name(float(np.mean([m["f1_mean"] for m in members])))
        # 代表样本：f0_median 最接近簇中位数的那个
        rep = min(members, key=lambda m: abs(m["f0_median"] - f0_med))["file"]
        clusters.append({
            "id": f"c{cid}",
            "cluster": int(cid),
            "count": len(members),
            "name": f"C{int(cid) + 1} · {f0_name} · {f1_name}",
            "f0_name": f0_name,
            "f1_name": f1_name,
            "f0_min": round(min(m["f0_mean"] for m in members), 1),
            "f0_max": round(max(m["f0_mean"] for m in members), 1),
            "representative": rep,
            "files": [m["file"] for m in members],
            "subjective": "",
        })
    return clusters


def load_distribution():
    """Read cached acoustic measurements without generating or analysing audio."""
    root = PROJECT_ROOT / "data" / "voice"
    pointer = root / "active_cohort.json"
    cohort = None
    if pointer.exists():
        cohort = json.loads(pointer.read_text(encoding="utf-8")).get("cohort_id")
        if not cohort or Path(cohort).name != cohort:
            return {"points": [], "cohort_id": None}
        root = root / "cohorts" / cohort
    source = root / "voice_clusters.csv"
    points = []
    if source.exists():
        with source.open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                try:
                    x, y = float(row["f0_mean"]), float(row["f1_mean"])
                    if not np.isfinite(x) or not np.isfinite(y):
                        continue
                    filename = Path(row["file"]).name
                    audio = root / "audio" / filename if cohort else PROJECT_ROOT / "data" / "exam" / filename
                    points.append({"file": filename, "name": row.get("voice_name") or filename,
                                   "cluster": int(row["cluster"]), "x": x, "y": y,
                                   "audio_available": audio.is_file()})
                except (KeyError, ValueError):
                    continue
    return {"points": points, "cohort_id": cohort}


def analyze_voices(voices_dir, n_clusters=None, output_dir=None):
    """主流程：扫描 -> 提特征 -> 建议 K -> 聚类 -> 落盘 -> 返回摘要。"""
    voice_dir = Path(voices_dir)
    out_dir = Path(output_dir) if output_dir else PROJECT_ROOT / "data" / "voice"
    out_dir.mkdir(parents=True, exist_ok=True)

    files = sorted(voice_dir.glob("*.wav"))
    if not files:
        return {"status": "error", "message": f"no wav files in {voice_dir}"}

    features, errors = [], []
    for fp in files:
        try:
            features.append(extract_features(fp))
        except Exception as exc:
            errors.append({"file": fp.name, "error": str(exc)})

    if len(features) < 2:
        return {"status": "error", "message": "valid samples < 2, cannot cluster", "errors": errors}

    suggestion = suggest_k(features)
    if n_clusters is None:
        n_clusters = suggestion["k_silhouette"]
    n_clusters = int(n_clusters)
    n_clusters = min(max(n_clusters, 2), len(features) - 1)

    raw_labels, scaler, model = cluster_voices(features, n_clusters)
    labels, raw_to_stable = _stable_labels(features, raw_labels)
    for feat, label in zip(features, labels):
        feat["cluster"] = int(label)

    cluster_csv = out_dir / "voice_clusters.csv"
    matrix = build_coverage_matrix(features)
    matrix_csv = out_dir / "coverage_matrix.csv"
    model_file = out_dir / "voice_model.pkl"

    _write_cluster_csv(cluster_csv, features)
    _write_matrix_csv(matrix_csv, matrix)
    joblib.dump({
        "scaler": scaler,
        "kmeans": model,
        "feature_order": FEATURE_ORDER,
        "raw_to_stable": raw_to_stable,
    }, model_file)

    return {
        "status": "ok",
        "n_files": len(files),
        "n_valid": len(features),
        "n_clusters": n_clusters,
        "suggestion": suggestion,
        "f0_bins": {"labels": F0_LABELS, "names": F0_NAMES},
        "f1_bins": {"labels": F1_LABELS, "names": F1_NAMES},
        "coverage_matrix": matrix.tolist(),
        "clusters": _summarize_clusters(features, labels),
        "files": [{"file": f["file"], "cluster": f["cluster"]} for f in features],
        "cluster_csv": str(cluster_csv),
        "coverage_csv": str(matrix_csv),
        "errors": errors,
    }


def _cohorts_root():
    return PROJECT_ROOT / "data" / "voice" / "cohorts"


def list_cohorts():
    """列出本地 Cohort 与聚类/基线状态，不触发计算。"""
    root = _cohorts_root()
    root.mkdir(parents=True, exist_ok=True)
    active_id = None
    pointer = PROJECT_ROOT / "data" / "voice" / "active_cohort.json"
    if pointer.exists():
        try:
            active_id = json.loads(pointer.read_text(encoding="utf-8")).get("cohort_id")
        except (OSError, ValueError):
            pass
    rows = []
    for manifest_file in sorted(root.glob("*/manifest.json"), reverse=True):
        try:
            manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        result_file = manifest_file.parent / "cluster_result.json"
        result = {}
        if result_file.exists():
            try:
                result = json.loads(result_file.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                pass
        items = manifest.get("items") or []
        rows.append({
            "id": manifest.get("id") or manifest_file.parent.name,
            "name": manifest.get("name") or manifest_file.parent.name,
            "version_label": manifest.get("version_label") or "",
            "created_at": manifest.get("created_at"),
            "provider": manifest.get("provider"),
            "model": manifest.get("model"),
            "requested_count": manifest.get("requested_count") or len(items),
            "seed": manifest.get("seed", 42),
            "language_scope": manifest.get("language_scope", "all"),
            "probe_text": manifest.get("probe_text") or "",
            "completed_count": sum(1 for item in items if item.get("status") == "ok"),
            "failed_count": sum(1 for item in items if item.get("status") == "error"),
            "status": manifest.get("status") or "running",
            "clustered": bool(result),
            "n_clusters": result.get("n_clusters"),
            "can_activate": (manifest_file.parent / "voice_model.pkl").exists(),
            "active": (manifest.get("id") or manifest_file.parent.name) == active_id,
        })
    return rows


def load_cohort_result(cohort_id):
    safe_id = Path(str(cohort_id)).name
    result_file = _cohorts_root() / safe_id / "cluster_result.json"
    if not result_file.exists():
        return {"status": "error", "message": "该 Cohort 尚未聚类"}
    try:
        return json.loads(result_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"status": "error", "message": "聚类结果无法读取"}


def analyze_cohort(cohort_id, n_clusters=None, use_anchor=True):
    """一条 voice_id 对应一个固定探针样本；首次拟合，后续 Cohort 可映射到已锁基线。"""
    safe_id = Path(str(cohort_id)).name
    cohort_dir = _cohorts_root() / safe_id
    manifest_file = cohort_dir / "manifest.json"
    if not manifest_file.exists():
        return {"status": "error", "message": "Cohort 不存在"}
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    audio_dir = cohort_dir / "audio"
    features, errors = [], []
    for item in manifest.get("items") or []:
        if item.get("status") != "ok":
            continue
        fp = audio_dir / Path(item.get("filename") or "").name
        if not fp.exists():
            continue
        try:
            feat = extract_features(fp)
            feat["voice_id"] = item.get("voice_id") or ""
            feat["voice_name"] = item.get("voice_name") or feat["voice_id"]
            features.append(feat)
        except Exception as exc:
            errors.append({"file": fp.name, "error": str(exc)})
    if len(features) < 3:
        return {"status": "error", "message": "有效的不同音色不足 3 个，无法稳定计算轮廓系数", "errors": errors}

    suggestion = suggest_k(features)
    pointer = PROJECT_ROOT / "data" / "voice" / "active_cohort.json"
    active_id = None
    if pointer.exists():
        try:
            active_id = json.loads(pointer.read_text(encoding="utf-8")).get("cohort_id")
        except (OSError, ValueError):
            pass
    anchor_model_file = _cohorts_root() / str(active_id) / "voice_model.pkl" if active_id else None
    anchored = bool(use_anchor and active_id and active_id != safe_id and anchor_model_file and anchor_model_file.exists())

    if anchored:
        bundle = joblib.load(anchor_model_file)
        X = np.array([_feature_vector(f) for f in features])
        X_scaled = bundle["scaler"].transform(X)
        raw_labels = bundle["kmeans"].predict(X_scaled)
        raw_to_stable = {int(k): int(v) for k, v in (bundle.get("raw_to_stable") or {}).items()}
        labels = np.array([raw_to_stable.get(int(v), int(v)) for v in raw_labels], dtype=int)
        distances = np.linalg.norm(X_scaled - bundle["kmeans"].cluster_centers_[raw_labels], axis=1)
        for feat, distance in zip(features, distances):
            feat["_distance"] = float(distance)
        scaler, model = bundle["scaler"], bundle["kmeans"]
        n_clusters = len(set(raw_to_stable.values())) or len(model.cluster_centers_)
        mode = "anchored"
    else:
        if n_clusters is None:
            n_clusters = suggestion["k_silhouette"]
        n_clusters = min(max(int(n_clusters), 2), len(features) - 1)
        raw_labels, scaler, model = cluster_voices(features, n_clusters)
        labels, raw_to_stable = _stable_labels(features, raw_labels)
        mode = "fitted"

    for feat, label in zip(features, labels):
        feat["cluster"] = int(label)
    matrix = build_coverage_matrix(features)
    cluster_csv = cohort_dir / "voice_clusters.csv"
    matrix_csv = cohort_dir / "coverage_matrix.csv"
    model_file = cohort_dir / "voice_model.pkl"
    _write_cluster_csv(cluster_csv, features)
    _write_matrix_csv(matrix_csv, matrix)
    if not anchored:
        joblib.dump({
            "scaler": scaler,
            "kmeans": model,
            "feature_order": FEATURE_ORDER,
            "raw_to_stable": raw_to_stable,
        }, model_file)

    result = {
        "status": "ok",
        "cohort_id": safe_id,
        "mode": mode,
        "anchor_cohort_id": active_id if anchored else None,
        "n_files": len(manifest.get("items") or []),
        "n_valid": len(features),
        "duration_summary": {
            "min": round(min(f["duration_s"] for f in features), 2),
            "median": round(float(np.median([f["duration_s"] for f in features])), 2),
            "max": round(max(f["duration_s"] for f in features), 2),
        },
        "n_clusters": int(n_clusters),
        "suggestion": suggestion,
        "f0_bins": {"labels": F0_LABELS, "names": F0_NAMES},
        "f1_bins": {"labels": F1_LABELS, "names": F1_NAMES},
        "coverage_matrix": matrix.tolist(),
        "clusters": _summarize_clusters(features, labels),
        "files": [{
            "file": f["file"], "voice_id": f.get("voice_id"), "voice_name": f.get("voice_name"),
            "cluster": f["cluster"], "duration_s": f["duration_s"],
            "f0_mean": f["f0_mean"], "f0_median": f["f0_median"],
            "f1_mean": f["f1_mean"], "f2_mean": f["f2_mean"], "f3_mean": f["f3_mean"],
        } for f in features],
        "cluster_csv": str(cluster_csv),
        "coverage_csv": str(matrix_csv),
        "errors": errors,
        "analyzed_at": datetime.datetime.now().isoformat(timespec="seconds"),
    }
    (cohort_dir / "cluster_result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return result


def _regression_cluster_stats(result, n_clusters):
    """把一轮聚类结果压成可比较的 C1–Ck 统计；旧结果缺字段时保留空值。"""
    files = result.get("files") or []
    stats = []
    total = max(int(result.get("n_valid") or len(files) or 0), 1)
    for cid in range(int(n_clusters)):
        members = [f for f in files if int(f.get("cluster", -1)) == cid]

        def avg(key):
            values = [float(f[key]) for f in members if f.get(key) is not None]
            return round(float(np.mean(values)), 2) if values else None

        stats.append({
            "cluster": cid,
            "count": len(members),
            "share_pct": round(len(members) / total * 100, 1),
            "f0_mean": avg("f0_mean"),
            "f1_mean": avg("f1_mean"),
            "duration_mean": avg("duration_s"),
        })
    return stats


def build_regression_ledger():
    """返回以当前 active Cohort 为锚的版本回归账本，不重新计算音频特征。"""
    pointer = PROJECT_ROOT / "data" / "voice" / "active_cohort.json"
    if not pointer.exists():
        return {"status": "empty", "message": "尚未锁定声线基线", "rows": []}
    try:
        active_id = Path(str(json.loads(pointer.read_text(encoding="utf-8")).get("cohort_id"))).name
    except (OSError, ValueError, TypeError):
        return {"status": "error", "message": "声线基线指针无法读取", "rows": []}

    root = _cohorts_root()
    baseline_result = load_cohort_result(active_id)
    if baseline_result.get("status") != "ok":
        return {"status": "error", "message": "声线基线结果无法读取", "rows": []}
    n_clusters = int(baseline_result.get("n_clusters") or 0)
    if n_clusters < 2:
        return {"status": "error", "message": "声线基线缺少有效簇数", "rows": []}

    baseline_stats = _regression_cluster_stats(baseline_result, n_clusters)
    baseline_clusters = baseline_result.get("clusters") or []
    cluster_meta = []
    for cid in range(n_clusters):
        item = next((c for c in baseline_clusters if int(c.get("cluster", -1)) == cid), {})
        cluster_meta.append({"cluster": cid, "name": item.get("name") or f"C{cid + 1}", "baseline_count": baseline_stats[cid]["count"]})

    rows = []
    for manifest_file in sorted(root.glob("*/manifest.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        cid = manifest.get("id") or manifest_file.parent.name
        result_file = manifest_file.parent / "cluster_result.json"
        if not result_file.exists():
            continue
        try:
            result = json.loads(result_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if result.get("status") != "ok":
            continue
        comparable = cid == active_id or (
            result.get("mode") == "anchored" and result.get("anchor_cohort_id") == active_id
        )
        row_n = int(result.get("n_clusters") or n_clusters)
        stats = _regression_cluster_stats(result, n_clusters)
        deltas = []
        for stat, base in zip(stats, baseline_stats):
            f0_delta = round(stat["f0_mean"] - base["f0_mean"], 2) if stat["f0_mean"] is not None and base["f0_mean"] is not None else None
            share_delta = round(stat["share_pct"] - base["share_pct"], 1)
            count_delta = stat["count"] - base["count"]
            reasons = []
            if f0_delta is not None and abs(f0_delta) >= 5:
                reasons.append(f"平均 F0 {f0_delta:+.2f} Hz")
            if abs(share_delta) >= 5:
                reasons.append(f"占比 {share_delta:+.1f} 个百分点")
            if abs(count_delta) >= 2:
                reasons.append(f"样本数 {count_delta:+d}")
            deltas.append({
                **stat,
                "f0_delta": f0_delta,
                "f1_delta": round(stat["f1_mean"] - base["f1_mean"], 2) if stat["f1_mean"] is not None and base["f1_mean"] is not None else None,
                "share_delta_pct": share_delta,
                "count_delta": count_delta,
                "attention": bool(comparable and reasons),
                "attention_reason": "；".join(reasons),
            })
        rows.append({
            "id": cid,
            "version_label": manifest.get("version_label") or "",
            "name": manifest.get("name") or cid,
            "role": "baseline" if cid == active_id else ("anchored" if comparable else "unanchored"),
            "mode": result.get("mode") or "unknown",
            "comparable": comparable,
            "n_valid": int(result.get("n_valid") or 0),
            "analyzed_at": result.get("analyzed_at"),
            "clusters": deltas,
            "note": "同一基线映射，可比较" if comparable else "独立拟合，仅作参考，未纳入变化判断",
        })
    rows.sort(key=lambda row: (row["role"] != "baseline", row.get("analyzed_at") or row["id"]))
    return {
        "status": "ok",
        "baseline_id": active_id,
        "baseline_version": next((r["version_label"] for r in rows if r["id"] == active_id), "") or "baseline",
        "cluster_count": n_clusters,
        "clusters": cluster_meta,
        "rows": rows,
        "message": "后续版本需使用锚定基线聚类，才会进入可比较账本。",
    }


def export_cohort_cluster(cohort_id, cluster):
    """把一个固定簇导出为评测模块可直接读取的 wav 目录。"""
    safe_id = Path(str(cohort_id)).name
    try:
        cluster_id = int(cluster)
    except (TypeError, ValueError):
        return {"status": "error", "message": "簇编号无效"}
    result = load_cohort_result(safe_id)
    if result.get("status") != "ok":
        return result
    files = [f for f in result.get("files") or [] if int(f.get("cluster", -1)) == cluster_id]
    if not files:
        return {"status": "error", "message": f"C{cluster_id + 1} 没有可评测音频"}
    source_dir = _cohorts_root() / safe_id / "audio"
    target_dir = PROJECT_ROOT / "data" / "eval" / "voice_regression" / safe_id / f"C{cluster_id + 1}"
    target_dir.mkdir(parents=True, exist_ok=True)
    for old in target_dir.glob("*.wav"):
        old.unlink()
    selected = []
    for item in files:
        source = source_dir / Path(str(item.get("file") or "")).name
        if not source.exists():
            continue
        target = target_dir / source.name
        shutil.copy2(source, target)
        selected.append(target.name)
    if not selected:
        return {"status": "error", "message": "簇内音频文件不存在"}
    (target_dir / "selection.json").write_text(json.dumps({
        "cohort_id": safe_id,
        "cluster": cluster_id,
        "source_result": str(_cohorts_root() / safe_id / "cluster_result.json"),
        "files": selected,
        "exported_at": datetime.datetime.now().isoformat(timespec="seconds"),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "status": "ok",
        "cohort_id": safe_id,
        "cluster": cluster_id,
        "folder": str(target_dir),
        "count": len(selected),
    }


def activate_cohort(cohort_id):
    """把已拟合的 Cohort 锁为声线基线；后续版本只映射，不重排 C1/C2/C3。"""
    safe_id = Path(str(cohort_id)).name
    cohort_dir = _cohorts_root() / safe_id
    result_file = cohort_dir / "cluster_result.json"
    model_file = cohort_dir / "voice_model.pkl"
    manifest_file = cohort_dir / "manifest.json"
    if not result_file.exists() or not model_file.exists() or not manifest_file.exists():
        return {"status": "error", "message": "请先对该 Cohort 完成一次基线聚类"}
    try:
        result = json.loads(result_file.read_text(encoding="utf-8"))
        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"status": "error", "message": "Cohort 元数据损坏，不能激活为 Golden Benchmark"}
    files = result.get("files") or []
    voice_ids = [str(item.get("voice_id") or "").strip() for item in files]
    clusters = {int(item.get("cluster", -1)) for item in files}
    if manifest.get("status") != "ready" or len(files) != 26 or len(set(voice_ids)) != 26 or "" in voice_ids:
        return {"status": "error", "message": "Golden Benchmark 必须由 26 个完整且不同的 voice_id 组成"}
    if int(result.get("n_clusters") or 0) != 4 or clusters != {0, 1, 2, 3}:
        return {"status": "error", "message": "Golden Benchmark 必须使用固定 C1–C4 四个簇"}
    pointer = PROJECT_ROOT / "data" / "voice" / "active_cohort.json"
    pointer.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "cohort_id": safe_id,
        "activated_at": datetime.datetime.now().isoformat(timespec="seconds"),
    }
    temp = pointer.with_name(f".{pointer.name}.{uuid.uuid4().hex}.tmp")
    try:
        temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(pointer)
    finally:
        temp.unlink(missing_ok=True)
    return {"status": "ok", "cohort_id": safe_id, "clusters": load_clusters()}


def _write_cluster_csv(csv_path, features):
    header = ["file", "voice_id", "voice_name", "cluster", "duration_s", "f0_mean", "f0_median", "f0_std",
              "f0_p05", "f0_p95", "f1_mean", "f2_mean", "f3_mean"] + [f"mfcc_{i}" for i in range(13)]
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(header)
        for feat in features:
            w.writerow([feat["file"], feat.get("voice_id", ""), feat.get("voice_name", ""), feat["cluster"], feat["duration_s"],
                        feat["f0_mean"], feat["f0_median"], feat["f0_std"],
                        feat["f0_p05"], feat["f0_p95"], feat["f1_mean"],
                        feat["f2_mean"], feat["f3_mean"], *feat["mfcc"]])


def _write_matrix_csv(csv_path, matrix):
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["F0\\F1"] + F1_LABELS)
        for i, label in enumerate(F0_LABELS):
            w.writerow([label] + list(matrix[i]))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="音色聚类")
    p.add_argument("--dir", default=r"C:\Users\Administrator\Desktop\音源")
    p.add_argument("--k", type=int, default=None)
    args = p.parse_args()
    res = analyze_voices(args.dir, n_clusters=args.k)
    print(json.dumps(res, ensure_ascii=False, indent=2))
