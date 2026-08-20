# -*- coding: utf-8 -*-
"""07 闭环大脑 —— 降噪 DUT 迭代闭环（闭环一，人在环）。

流程：配置矩阵 → 跑一轮（归因 + 条件晋级判定）→ LLM/规则给建议 → 人在环确认 → 执行。
数据红线：分数全部来自 audiobox 真实推理；无解就写无解，不造晋级假象。
"""

import csv
import datetime
import json
import math
import os
import re
import warnings
from pathlib import Path

import numpy as np
from scipy import stats

warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=UserWarning)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"
LOOP_DIR = DATA_DIR / "loop"
LOOP_STATUS = LOOP_DIR / "loop_status.json"
MATRIX_DIR = DATA_DIR / "matrix"
EXAM_DIR = DATA_DIR / "exam"
DENOISED_DIR = DATA_DIR / "denoised"


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


def _load_module(path):
    import importlib.util

    spec = importlib.util.spec_from_file_location(path.stem, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


denoise = _load_module(PROJECT_ROOT / "modules" / "05_denoise" / "denoise.py")
evaluate = _load_module(PROJECT_ROOT / "modules" / "06_evaluate" / "evaluate.py")
channel = _load_module(PROJECT_ROOT / "modules" / "04_channel" / "channel.py")

DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-pro")
DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/anthropic")
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")

VERSION_CANDIDATES = [
    {"id": "v1", "model": "noisereduce", "strength": 1.0},
    {"id": "v2", "model": "noisereduce", "strength": 0.8},
    {"id": "v3", "model": "noisereduce", "strength": 0.6},
    {"id": "v4", "model": "noisereduce", "strength": 0.4},
]

DEFAULT_CONFIG = {
    "matrix": {"exam": None, "noise_scenes": []},
    "baseline": "v1",
    "candidate": "v2",
}


def list_exams():
    if not EXAM_DIR.exists():
        return []
    return [{"stem": p.stem, "name": p.name} for p in sorted(EXAM_DIR.glob("*.wav"))]


def list_scenes():
    return [{"id": s["id"], "label": s["label"], "snr_db": s["snr_db"]} for s in channel.NOISE_SCENES]


def list_versions():
    """返回版本候选（demo：NoiseReduce 按真实降噪比例 prop_decrease 分档）。"""
    return [
        {
            "id": v["id"],
            "model": v["model"],
            "strength": v["strength"],
            "label": f"{v['id']} · {v['model']} · 降噪比例 {v['strength']:g}",
        }
        for v in VERSION_CANDIDATES
    ]


def get_version(vid):
    for v in VERSION_CANDIDATES:
        if v["id"] == vid:
            return v
    return None


def _noise_scene_from_stem(stem):
    m = re.search(r"__([A-Z]+)_snr", stem)
    return m.group(1) if m else None


def collect_matrix(config):
    """按配置确定回归矩阵：固定 exam + 放开/固定的噪声场景。"""
    exam = (config.get("matrix") or {}).get("exam")
    scenes = (config.get("matrix") or {}).get("noise_scenes") or [s["id"] for s in channel.NOISE_SCENES]
    meta = evaluate.load_channel_meta()
    samples = []
    for degraded in sorted(MATRIX_DIR.glob("*.wav")):
        stem = degraded.stem
        scene = _noise_scene_from_stem(stem)
        if scene not in scenes:
            continue
        if exam and not stem.startswith(exam + "__"):
            continue
        clean = EXAM_DIR / f"{stem.split('__')[0]}.wav"
        if not clean.exists():
            continue
        m = meta.get(degraded.name, {})
        samples.append(
            {
                "scene_id": scene,
                "noise_label": m.get("noise_label", scene),
                "snr_db": m.get("snr_db", ""),
                "clean": str(clean),
                "degraded": str(degraded),
                "stem": stem,
            }
        )
    return samples


def _denoised_path(sample, version):
    model = version["model"]
    suffix = "" if version["strength"] >= 1.0 else f"__s{int(round(version['strength'] * 100))}"
    return DENOISED_DIR / model / f"{sample['stem']}__{model}{suffix}.wav"


def ensure_denoised(samples, version, progress_cb=None):
    """补齐某个版本在矩阵上的降噪产物（缺了就现跑）。"""
    missing = []
    for s in samples:
        out = _denoised_path(s, version)
        if not out.exists():
            missing.append(s)
    if not missing:
        return {"created": 0}
    if progress_cb:
        progress_cb(0, len(missing), f"降噪补齐（{version['id']}）…")
    for i, s in enumerate(missing, 1):
        denoise.run(s["degraded"], version["model"], strength=version["strength"])
        if progress_cb:
            progress_cb(i, len(missing), f"降噪补齐（{version['id']}）…")
    return {"created": len(missing)}


def judge(baseline_pqs, candidate_pqs, flags):
    """条件晋级判定：常规工况提升 + 极端档旁路。"""
    reg_base = [b for b, f in zip(baseline_pqs, flags) if f]
    reg_cand = [c for c, f in zip(candidate_pqs, flags) if f]
    ext_base = [b for b, f in zip(baseline_pqs, flags) if not f]
    ext_cand = [c for c, f in zip(candidate_pqs, flags) if not f]

    reg_delta = float(np.mean(np.array(reg_cand) - np.array(reg_base))) if reg_base else 0.0
    ext_delta = float(np.mean(np.array(ext_cand) - np.array(ext_base))) if ext_base else 0.0

    reg_p = None
    if len(reg_base) >= 2:
        try:
            _, reg_p = stats.ttest_rel(reg_cand, reg_base)
            reg_p = float(reg_p)
            if math.isnan(reg_p):
                reg_p = None
        except Exception:
            reg_p = None

    regular_pass = reg_delta > 0.05
    extreme_bypass = bool(ext_base) and ext_delta < -0.05
    reg_retreat = int(sum(1 for b, c, f in zip(baseline_pqs, candidate_pqs, flags) if f and c < b))

    if regular_pass:
        if extreme_bypass:
            verdict = "条件晋级"
        elif reg_retreat == 0:
            verdict = "全绿晋级"
        else:
            verdict = f"整体晋级（{reg_retreat} 场景回退）"
    else:
        verdict = "回滚"

    return {
        "n_regular": len(reg_base),
        "n_extreme": len(ext_base),
        "regular_retreat": reg_retreat,
        "promoted": regular_pass,
        "baseline_regular_pq": round(float(np.mean(reg_base)), 4) if reg_base else None,
        "candidate_regular_pq": round(float(np.mean(reg_cand)), 4) if reg_cand else None,
        "regular_delta": round(reg_delta, 4),
        "regular_p": round(reg_p, 6) if reg_p is not None else None,
        "extreme_delta": round(ext_delta, 4),
        "extreme_bypass": extreme_bypass,
        "verdict": verdict,
    }


def rule_decide(judge_report, config, evaluated):
    """规则兜底决策：新版本整体上行 → accept；回滚 → 迭代下一版 / 无解。"""
    candidate = config["candidate"]
    pool = [v["id"] for v in list_versions()]
    if judge_report.get("promoted"):
        return {
            "action": "accept",
            "version": candidate,
            "hypothesis": f"新版本 {candidate} 曲线整体上行（常规 Δ={judge_report['regular_delta']:+.3f}），验收晋级",
            "reason": judge_report["verdict"],
        }
    untried = [v for v in pool if v not in set(evaluated)]
    if untried:
        version = untried[0]
        return {
            "action": "iterate",
            "version": version,
            "hypothesis": f"新版本 {candidate} 曲线未整体上行，回滚；下一版 {version} 可针对薄弱场景定向调参",
            "reason": f"{candidate} 常规工况 Δ={judge_report['regular_delta']:+.3f}，未晋级，继续迭代",
        }
    return {
        "action": "no_solution",
        "version": None,
        "hypothesis": "已无可继续迭代的版本，诚实收口",
        "reason": "各版本均无整体正收益，保持已验收版本；本地不训练，如需继续需人工引入新模型/新训练版本",
    }


def llm_decide(context, config):
    """真 LLM 决策（DeepSeek anthropic 兼容接口）。失败则回退规则。"""
    if not DEEPSEEK_API_KEY:
        return None
    import requests

    prompt = (
        "你是通话降噪算法的「版本迭代」决策大脑（demo）。\n"
        "真实工作流：一个算法模型进来 → 迭代出新版本 → 看曲线是否整体上行 → 某场景还差就定向调参 → 出现「一个上、一个下」的权衡要诚实标注。\n"
        "只输出 JSON，不要任何多余文字。动作只能是：\n"
        "accept（新版本曲线整体上行，验收晋级）、iterate（未上行，回滚，准备下一版定向调参）、no_solution（无解，诚实收口）。\n"
        f"已验收版本 baseline={config['baseline']}，候选新版本 candidate={config['candidate']}\n"
        f"可用版本候选：{[{'id': v['id'], 'strength': v['strength']} for v in list_versions()]}\n"
        "数据：\n" + json.dumps(context, ensure_ascii=False, indent=2) + "\n"
        '输出格式：{"action": "...", "version": null, "hypothesis": "...", "reason": "..."}'
    )
    try:
        resp = requests.post(
            f"{DEEPSEEK_BASE_URL.rstrip('/')}/v1/messages",
            headers={
                "x-api-key": DEEPSEEK_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": DEEPSEEK_MODEL,
                "max_tokens": 800,
                "system": "你是严谨、诚实的通话降噪版本迭代决策者；不为了迭代而迭代，无解就诚实收口。",
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        text = "".join(b.get("text", "") for b in data.get("content", []))
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            return None
        decision = json.loads(m.group(0))
        decision["llm"] = True
        return decision
    except Exception:
        return None


def decide(judge_report, config, evaluated):
    """先试 LLM，再回退规则。"""
    ctx = {
        "judge": judge_report,
        "baseline": config["baseline"],
        "candidate": config["candidate"],
        "version_pool": [{"id": v["id"], "strength": v["strength"]} for v in list_versions()],
        "evaluated": evaluated,
    }
    decision = llm_decide(ctx, config)
    if decision is None:
        decision = rule_decide(judge_report, config, evaluated)
        decision["llm"] = False
    else:
        pool = [v["id"] for v in list_versions()]
        action = decision.get("action")
        if action == "iterate":
            untried = [v for v in pool if v not in set(evaluated)]
            if decision.get("version") not in untried:
                decision = rule_decide(judge_report, config, evaluated)
                decision["llm"] = False
        elif action not in ("accept", "no_solution"):
            decision = rule_decide(judge_report, config, evaluated)
            decision["llm"] = False
    return decision


def run_round(config, progress_cb=None):
    """跑一轮：补齐降噪 → 评测 → 归因 → 判定 → 决策建议。"""
    samples = collect_matrix(config)
    if not samples:
        return {"status": "error", "message": "矩阵里没有样本，请先在 04 生成对应退化 wav。"}
    baseline_v = get_version(config["baseline"])
    candidate_v = get_version(config["candidate"])
    if not baseline_v or not candidate_v:
        return {"status": "error", "message": "版本不存在，请检查 baseline / candidate。"}
    if baseline_v["id"] == candidate_v["id"]:
        return {"status": "error", "message": "候选新版本与已验收版本相同，请换一个版本。"}

    if progress_cb:
        progress_cb(0, 0, "加载 audiobox-aesthetics 模型…")
    predictor = evaluate.load_predictor()

    ensure_denoised(samples, baseline_v, progress_cb)
    ensure_denoised(samples, candidate_v, progress_cb)

    files = []
    for s in samples:
        files += [s["clean"], s["degraded"], str(_denoised_path(s, baseline_v)), str(_denoised_path(s, candidate_v))]
    unique = list(dict.fromkeys(files))
    if progress_cb:
        progress_cb(0, len(unique), "评测中…")
    scores = evaluate.score_files(predictor, unique, batch_size=4, progress_cb=progress_cb)

    rows = []
    base_pqs, cand_pqs, flags = [], [], []
    for s in samples:
        deg = scores.get(s["degraded"])
        base = scores.get(str(_denoised_path(s, baseline_v)))
        cand = scores.get(str(_denoised_path(s, candidate_v)))
        if not deg or not base or not cand:
            continue
        snr = float(s["snr_db"]) if s["snr_db"] not in ("", None) else 0.0
        is_regular = snr >= -5
        flags.append(is_regular)
        base_pqs.append(base["pq"])
        cand_pqs.append(cand["pq"])
        rows.append(
            {
                "scene_id": s["scene_id"],
                "noise_label": s["noise_label"],
                "snr_db": s["snr_db"],
                "degraded_pq": deg["pq"],
                "baseline_pq": base["pq"],
                "baseline_delta": round(base["pq"] - deg["pq"], 4),
                "candidate_pq": cand["pq"],
                "candidate_delta": round(cand["pq"] - deg["pq"], 4),
                "regular": is_regular,
                "stem": s["stem"],
                "clean_file": Path(s["clean"]).name,
                "degraded_file": Path(s["degraded"]).name,
                "baseline_file": _denoised_path(s, baseline_v).name,
                "candidate_file": _denoised_path(s, candidate_v).name,
                "baseline_model": baseline_v["model"],
                "candidate_model": candidate_v["model"],
            }
        )
    if not rows:
        return {"status": "error", "message": "没有可评分的配对样本。"}

    judge_report = judge(base_pqs, cand_pqs, flags)
    # 按 SNR 降序（安静在前）
    rows.sort(key=lambda r: (-(float(r["snr_db"]) if r["snr_db"] not in ("", None) else -999.0)))
    return {
        "status": "ok",
        "baseline": baseline_v["id"],
        "candidate": candidate_v["id"],
        "baseline_model": baseline_v["model"],
        "candidate_model": candidate_v["model"],
        "baseline_strength": baseline_v["strength"],
        "candidate_strength": candidate_v["strength"],
        "rows": rows,
        "judge": judge_report,
    }


def load_status():
    if LOOP_STATUS.exists():
        try:
            return json.loads(LOOP_STATUS.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {
        "config": json.loads(json.dumps(DEFAULT_CONFIG)),
        "evaluated_versions": ["v1"],
        "rounds": [],
        "changelog": [],
        "status": "idle",
        "baseline": "v1",
        "candidate": "v2",
        "last_judge": None,
        "last_decision": None,
        "conclusion": "",
    }


def save_status(state):
    LOOP_DIR.mkdir(parents=True, exist_ok=True)
    state["updated_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    LOOP_STATUS.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    return state


def build_markdown(state):
    cfg = state.get("config") or {}
    lines = ["# 闭环大脑 · 结论报告", ""]
    lines.append(f"- baseline：{state.get('baseline')}")
    lines.append(f"- candidate：{state.get('candidate')}")
    lines.append(f"- 状态：{state.get('status')}")
    if state.get("conclusion"):
        lines.append(f"- 结论：{state['conclusion']}")
    lines.append("")
    for r in state.get("rounds", []):
        j = r.get("judge") or {}
        d = r.get("decision") or {}
        lines.append(f"## 第 {r.get('round')} 轮 · {r.get('baseline')} vs {r.get('candidate')}")
        lines.append(f"- 判定：**{j.get('verdict')}**（常规 Δ={j.get('regular_delta')}，p={j.get('regular_p')}，极端 Δ={j.get('extreme_delta')}）")
        if d:
            lines.append(f"- 建议：{d.get('action')} {d.get('model') or ''} —— {d.get('hypothesis')}")
        lines.append("")
    return "\n".join(lines)
