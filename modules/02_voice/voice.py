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
import json
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
F0_NAMES = ["男低音", "男声常域", "女声常域", "女高音", "童声/特殊"]
F1_BINS = [0, 400, 700, np.inf]
F1_LABELS = ["<400", "400-700", ">700"]
F1_NAMES = ["粗厚声道", "中等声道", "细薄声道"]

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

    labels, scaler, model = cluster_voices(features, n_clusters)
    for feat, label in zip(features, labels):
        feat["cluster"] = int(label)

    cluster_csv = out_dir / "voice_clusters.csv"
    matrix = build_coverage_matrix(features)
    matrix_csv = out_dir / "coverage_matrix.csv"
    model_file = out_dir / "voice_model.pkl"

    _write_cluster_csv(cluster_csv, features)
    _write_matrix_csv(matrix_csv, matrix)
    joblib.dump({"scaler": scaler, "kmeans": model, "feature_order": FEATURE_ORDER}, model_file)

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


def _write_cluster_csv(csv_path, features):
    header = ["file", "cluster", "duration_s", "f0_mean", "f0_median", "f0_std",
              "f0_p05", "f0_p95", "f1_mean", "f2_mean", "f3_mean"] + [f"mfcc_{i}" for i in range(13)]
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(header)
        for feat in features:
            w.writerow([feat["file"], feat["cluster"], feat["duration_s"],
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
