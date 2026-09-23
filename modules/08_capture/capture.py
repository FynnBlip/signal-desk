# -*- coding: utf-8 -*-
"""08 真机采集（Real Capture）

把「手机 / 蓝牙麦克风的真实人声」变成一条可追溯、可门禁的语料来源。

设计约束（延伸自 README 的数据红线）：
1. 原始 PCM 是唯一来源。`raw/mic.pcm` 落盘后不可改；WAV 只是同一份数据的无损封装。
2. 浏览器自带的 AEC / NS / AGC 若无法关闭，必须如实记录并降级 capture_grade，
   不允许把「被浏览器处理过」的信号当作干净输入。缺测就写缺测。
3. 真机语料 tier 与合成语料 tier 不可混入同一轮晋级比较；cross_tier_gate 负责拦截。
   真机语料的价值定位是「生态效度校验证据层」，不是又一把可以随便换的尺子。

只依赖标准库，保证 tests/ 在没装 fastapi 的环境里也能直接跑。
"""

from __future__ import annotations

import array
import csv
import datetime
import hashlib
import json
import math
import os
import re
import uuid
import wave
from pathlib import Path

SCHEMA_VERSION = 1
MODULE_ID = "08_capture"

PROJECT_ROOT = Path(os.environ.get("SIGNAL_DESK_ROOT") or Path(__file__).resolve().parents[2])
DATA_ROOT = PROJECT_ROOT / "data" / "real_capture"
SESSIONS_ROOT = DATA_ROOT / "sessions"
TRACE_PATH = DATA_ROOT / "capture_runs_v1.csv"

# 用 fullmatch 而不是 match + $：Python 的 $ 会放过尾随换行，那会造出名字带 \n 的目录。
SESSION_ID_RE = re.compile(r"rc-\d{8}-\d{6}-[0-9a-f]{6}")

# 数据来源分层：Loop 的晋级结论默认只在同一 tier 内成立。
TIER_SYNTHETIC = "synthetic_tts"
TIER_REAL = "real_device"

# 输入路径必须显式声明：蓝牙 HFP 是窄带，和手机内置麦不是同一把尺子。
INPUT_ROUTES = (
    "phone_internal",
    "wired_headset",
    "bluetooth_hfp",
    "bluetooth_le",
    "usb_mic",
    "unknown",
)

# 每条采集会话必读的脚本。anchor 用于跨会话电平标定，fricative / silence 专抓降噪器伪影。
SCRIPTS = [
    {
        "id": "anchor",
        "kind": "anchor",
        "text": "一二三四五六七八九十，信号台电平校准。",
        "reps": 3,
        "expect_s": 4.0,
        "note": "每次都读同一句，用于跨会话电平与带宽指纹对齐；重复 3 次可用于 test-retest 稳定性自检。",
    },
    {
        "id": "p1",
        "kind": "speech",
        "text": "喂，你好，我现在在路边等你，车有点多，你听我声音清楚吗？",
        "reps": 1,
        "expect_s": 5.0,
        "note": "常规通话语速与句长。",
    },
    {
        "id": "p2",
        "kind": "speech",
        "text": "麻烦你把刚才那个地址再发我一遍，我这会儿在地下车库，信号可能不太好。",
        "reps": 1,
        "expect_s": 7.0,
        "note": "长句 + 弱音尾，检验降噪后的可懂度保持。",
    },
    {
        "id": "p3",
        "kind": "fricative",
        "text": "滋——斯——夫——是——诗——",
        "reps": 1,
        "expect_s": 5.0,
        "note": "擦音 / 齿音探针。降噪器最容易在这里吃掉高频，听起来发闷。",
    },
    {
        "id": "p4",
        "kind": "silence",
        "text": "（保持安静 5 秒，不要说话）",
        "reps": 1,
        "expect_s": 5.0,
        "note": "静音探针。用于看本底噪声被压成什么样，以及是否引入 musical noise。",
    },
]

# append-only trace 固定 schema。加字段必须升 schema 版本，不改历史列。
TRACE_FIELDS = [
    "schema_version",
    "session_id",
    "created_at",
    "finalized_at",
    "speaker_code",
    "script_id",
    "declared_route",
    "detected_label",
    "input_device_id",
    "sample_rate",
    "channel_count",
    "aec_requested",
    "aec_actual",
    "ns_requested",
    "ns_actual",
    "agc_requested",
    "agc_actual",
    "chunk_count",
    "chunk_gap_count",
    "dropped_frames",
    "duration_s",
    "rms_dbfs",
    "peak_dbfs",
    "clip_ratio",
    "dc_offset",
    "voiced_ratio",
    "hf_ratio_db",
    "wav_sha256",
    "pcm_sha256",
    "capture_grade",
    "usable_for_loop",
    "notes",
]


# --------------------------------------------------------------------------- #
# 基础工具
# --------------------------------------------------------------------------- #

def _now() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def _safe_id(value: str) -> str:
    """只允许规范形态的 session_id，挡住 ../ 之类的路径穿越。"""
    text = str(value or "").strip()
    if not SESSION_ID_RE.fullmatch(text):
        raise ValueError(f"非法 session_id: {value!r}")
    return text


def _session_dir(session_id: str) -> Path:
    return SESSIONS_ROOT / _safe_id(session_id)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _read_json(path: Path, default=None):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


# --------------------------------------------------------------------------- #
# 会话生命周期
# --------------------------------------------------------------------------- #

def create_session(
    *,
    speaker_code: str = "SPK-01",
    script_id: str = "p1",
    declared_route: str = "unknown",
    client_manifest: dict | None = None,
    notes: str = "",
) -> dict:
    """建立一次采集会话。返回的 session_id 是后续所有追加的唯一句柄。"""
    route = str(declared_route or "unknown").strip()
    if route not in INPUT_ROUTES:
        return {"status": "error", "message": f"declared_route 必须是 {INPUT_ROUTES} 之一"}
    script_ids = {item["id"] for item in SCRIPTS}
    if script_id not in script_ids:
        return {"status": "error", "message": f"未知脚本 {script_id!r}"}

    session_id = f"rc-{datetime.datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
    folder = SESSIONS_ROOT / session_id
    (folder / "raw").mkdir(parents=True, exist_ok=True)

    manifest = dict(client_manifest or {})
    session = {
        "schema_version": SCHEMA_VERSION,
        "module": MODULE_ID,
        "session_id": session_id,
        "created_at": _now(),
        "speaker_code": str(speaker_code or "SPK-01")[:32],
        "script_id": script_id,
        "declared_route": route,
        "data_tier": TIER_REAL,
        "status": "recording",
        "notes": str(notes or "")[:500],
        "client_manifest": manifest,
        # 真人录音属于个人信息：默认不入库、不公开，权属声明随会话一起留痕。
        "consent": {
            "speaker_informed": bool(manifest.get("consent_speaker_informed", True)),
            "allow_local_keep": True,
            "allow_public_share": bool(manifest.get("consent_allow_public_share", False)),
        },
    }
    _write_json(folder / "session.json", session)
    _write_json(folder / "capture_state.json", {
        "session_id": session_id,
        "received_chunks": 0,
        "next_seq": 0,
        "gap_seqs": [],
        "dropped_frames": 0,
        "bytes": 0,
        "updated_at": _now(),
    })
    return {"status": "ok", "session": session, "session_dir": str(folder)}


def _state(session_id: str) -> dict:
    state = _read_json(_session_dir(session_id) / "capture_state.json")
    if not state:
        raise ValueError("会话不存在或状态文件丢失")
    return state


def append_chunk(session_id: str, seq: int, payload: bytes, *, frames: int | None = None) -> dict:
    """追加一段 int16le 单声道 PCM。

    seq 必须严格递增。出现断档不静默补齐：记进 gap_seqs，最终降级 capture_grade。
    这就是「记录实测、不假装干净」在采集层的具体兑现。
    """
    folder = _session_dir(session_id)
    session = _read_json(folder / "session.json")
    if not session:
        raise ValueError("会话不存在")
    if session.get("status") != "recording":
        return {"status": "error", "message": f"会话已 {session.get('status')}，不再接受数据"}
    if not isinstance(payload, (bytes, bytearray)) or len(payload) == 0:
        return {"status": "error", "message": "空 chunk 被拒绝"}
    if len(payload) % 2 != 0:
        return {"status": "error", "message": "int16 载荷长度必须是偶数"}

    try:
        seq = int(seq)
    except (TypeError, ValueError):
        return {"status": "error", "message": "seq 必须是整数"}
    if seq < 0:
        return {"status": "error", "message": "seq 必须非负"}

    state = _state(session_id)
    if seq < state["received_chunks"]:
        return {"status": "replayed", "state": state, "message": "重复 chunk，已幂等丢弃"}

    read_frames = len(payload) // 2
    frame_count = int(frames) if frames is not None else read_frames
    if seq > state["next_seq"]:
        state["gap_seqs"].extend(range(state["next_seq"], seq))
        state["dropped_frames"] += (seq - state["next_seq"]) * frame_count

    with open(folder / "raw" / "mic.pcm", "ab") as fh:
        fh.write(payload)

    state.update(
        received_chunks=seq + 1,
        next_seq=seq + 1,
        bytes=state["bytes"] + len(payload),
        updated_at=_now(),
    )
    _write_json(folder / "capture_state.json", state)
    return {"status": "ok", "received_chunks": state["received_chunks"], "gap_count": len(state["gap_seqs"])}


def finalize_session(
    session_id: str,
    *,
    sample_rate: int = 48000,
    channel_count: int = 1,
    client_manifest: dict | None = None,
) -> dict:
    """封存会话：PCM → WAV、算电平/带宽指纹、定 capture_grade、写 append-only trace。"""
    folder = _session_dir(session_id)
    session = _read_json(folder / "session.json")
    if not session:
        return {"status": "error", "message": "会话不存在"}
    result_path = folder / "session_result.json"
    if result_path.exists():
        return {"status": "error", "message": "会话已封存，历史不可重写；请新建会话"}

    sample_rate = int(sample_rate)
    channel_count = max(1, int(channel_count))
    pcm_path = folder / "raw" / "mic.pcm"
    if not pcm_path.exists() or pcm_path.stat().st_size == 0:
        return {"status": "error", "message": "没有任何音频数据，不予封存"}

    with wave.open(str(folder / "raw" / "audio.wav"), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm_path.read_bytes())

    metrics = analyze_pcm(pcm_path, sample_rate=sample_rate)
    manifest = {**session.get("client_manifest", {}), **(client_manifest or {})}
    state = _state(session_id)

    graded = {
        "duration_s": metrics["duration_s"],
        "rms_dbfs": metrics["rms_dbfs"],
        "peak_dbfs": metrics["peak_dbfs"],
        "clip_ratio": metrics["clip_ratio"],
        "dc_offset": metrics["dc_offset"],
        "voiced_ratio": metrics["voiced_ratio"],
        "hf_ratio_db": metrics["hf_ratio_db"],
        "chunk_count": state["received_chunks"],
        "chunk_gap_count": len(state["gap_seqs"]),
        "dropped_frames": state["dropped_frames"],
        "aec_requested": manifest.get("aec_requested"),
        "aec_actual": manifest.get("aec_actual"),
        "ns_requested": manifest.get("ns_requested"),
        "ns_actual": manifest.get("ns_actual"),
        "agc_requested": manifest.get("agc_requested"),
        "agc_actual": manifest.get("agc_actual"),
    }
    grade, grade_reason = grade_of(graded)

    result = {
        "schema_version": SCHEMA_VERSION,
        "session_id": session_id,
        "finalized_at": _now(),
        "sample_rate": sample_rate,
        "channel_count": channel_count,
        "client_manifest": manifest,
        "metrics": metrics,
        # 采集完整性单独成块：这是「这把尺子准不准」的证据，不是音频质量分。
        "capture_integrity": {
            "chunk_count": graded["chunk_count"],
            "chunk_gap_count": graded["chunk_gap_count"],
            "gap_seqs": state["gap_seqs"][:100],
            "dropped_frames": graded["dropped_frames"],
            "aec_requested": graded["aec_requested"], "aec_actual": graded["aec_actual"],
            "ns_requested": graded["ns_requested"], "ns_actual": graded["ns_actual"],
            "agc_requested": graded["agc_requested"], "agc_actual": graded["agc_actual"],
        },
        "capture_grade": grade,
        "grade_reason": grade_reason,
        "usable_for_loop": grade == "grade_a",
        "data_tier": TIER_REAL,
        "raw": {
            "pcm": f"raw/mic.pcm",
            "wav": f"raw/audio.wav",
            "pcm_sha256": _sha256_file(pcm_path),
            "wav_sha256": _sha256_file(folder / "raw" / "audio.wav"),
        },
    }
    _write_json(result_path, result)

    session["status"] = "finalized"
    session["finalized_at"] = result["finalized_at"]
    _write_json(folder / "session.json", session)

    row = {
        "schema_version": SCHEMA_VERSION,
        "session_id": session_id,
        "created_at": session["created_at"],
        "finalized_at": result["finalized_at"],
        "speaker_code": session["speaker_code"],
        "script_id": session["script_id"],
        "declared_route": session["declared_route"],
        "detected_label": manifest.get("input_label") or "",
        "input_device_id": manifest.get("input_device_id") or "",
        "sample_rate": sample_rate,
        "channel_count": channel_count,
        **{k: ("" if graded[k] is None else graded[k]) for k in (
            "aec_requested", "aec_actual", "ns_requested", "ns_actual",
            "agc_requested", "agc_actual", "chunk_count", "chunk_gap_count",
            "dropped_frames", "duration_s", "rms_dbfs", "peak_dbfs",
            "clip_ratio", "dc_offset", "voiced_ratio", "hf_ratio_db",
        )},
        "wav_sha256": result["raw"]["wav_sha256"],
        "pcm_sha256": result["raw"]["pcm_sha256"],
        "capture_grade": grade,
        "usable_for_loop": grade == "grade_a",
        "notes": session.get("notes", ""),
    }
    append_trace(row)
    return {"status": "ok", "result": result}


def append_trace(row: dict) -> None:
    """append-only：新数据写新行，历史行不改。"""
    TRACE_PATH.parent.mkdir(parents=True, exist_ok=True)
    exists = TRACE_PATH.exists()
    with open(TRACE_PATH, "a", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=TRACE_FIELDS)
        if not exists:
            writer.writeheader()
        writer.writerow({key: row.get(key, "") for key in TRACE_FIELDS})


def load_session(session_id: str) -> dict:
    folder = _session_dir(session_id)
    session = _read_json(folder / "session.json")
    if not session:
        return {"status": "error", "message": "会话不存在"}
    return {
        "status": "ok",
        "session": session,
        "state": _read_json(folder / "capture_state.json"),
        "result": _read_json(folder / "session_result.json"),
    }


def list_sessions(limit: int = 50) -> dict:
    rows = []
    if SESSIONS_ROOT.exists():
        for folder in sorted(SESSIONS_ROOT.iterdir(), reverse=True):
            if not folder.is_dir() or not SESSION_ID_RE.match(folder.name):
                continue
            session = _read_json(folder / "session.json") or {}
            result = _read_json(folder / "session_result.json") or {}
            rows.append({
                "session_id": folder.name,
                "created_at": session.get("created_at"),
                "status": session.get("status"),
                "speaker_code": session.get("speaker_code"),
                "script_id": session.get("script_id"),
                "declared_route": session.get("declared_route"),
                "capture_grade": result.get("capture_grade"),
                "duration_s": (result.get("metrics") or {}).get("duration_s"),
                "hf_ratio_db": (result.get("metrics") or {}).get("hf_ratio_db"),
                "has_audio": (folder / "raw" / "audio.wav").exists(),
            })
            if len(rows) >= max(1, int(limit)):
                break
    return {"status": "ok", "sessions": rows, "tier": TIER_REAL}


def wav_path(session_id: str) -> Path | None:
    path = _session_dir(session_id) / "raw" / "audio.wav"
    return path if path.exists() else None


# --------------------------------------------------------------------------- #
# 音频度量（纯 stdlib，可单测）
# --------------------------------------------------------------------------- #

def _biquad_highpass(f0: float, fs: float, q: float = 0.707):
    """RBJ 高通系数，用于估高频能量占比。"""
    w0 = 2.0 * math.pi * f0 / fs
    cos_w0, sin_w0 = math.cos(w0), math.sin(w0)
    alpha = sin_w0 / (2.0 * q)
    b0 = (1 + cos_w0) / 2
    b1 = -(1 + cos_w0)
    b2 = (1 + cos_w0) / 2
    a0 = 1 + alpha
    a1 = -2 * cos_w0
    a2 = 1 - alpha
    return b0 / a0, b1 / a0, b2 / a0, a1 / a0, a2 / a0


def analyze_pcm(pcm_path: Path, *, sample_rate: int = 48000, channels: int = 1,
                frame_ms: float = 20.0, voiced_floor_dbfs: float = -45.0) -> dict:
    """电平 / 削波 / 静音占比 / 高频能量占比。

    这些是**输入侧可观测量**，不是质量分。名字里不带 quality，避免被当成 PQ 用。
    """
    raw = pcm_path.read_bytes()
    frames = array.array("h")
    frames.frombytes(raw[: len(raw) - (len(raw) % 2)])
    total = len(frames)
    if total == 0:
        return {
            "duration_s": 0.0, "samples": 0, "rms_dbfs": None, "peak_dbfs": None,
            "clip_ratio": None, "dc_offset": None, "voiced_ratio": None,
            "hf_ratio_db": None, "silence_ratio": None,
        }

    peak = 0
    sq_sum = 0.0
    dc_sum = 0
    clipped = 0
    hp_energy = 0.0
    total_energy = 0.0
    b0, b1, b2, a1, a2 = _biquad_highpass(4000.0, float(sample_rate))
    x1 = x2 = y1 = y2 = 0.0

    for value in frames:
        sq_sum += float(value) * value
        dc_sum += value
        av = abs(value)
        if av > peak:
            peak = av
        if av >= 32760:
            clipped += 1
        y = b0 * value + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2
        x2, x1 = x1, value
        y2, y1 = y1, y
        hp_energy += y * y
        total_energy += float(value) * value

    rms = math.sqrt(sq_sum / total)
    frame_len = max(1, int(sample_rate * frame_ms / 1000.0))
    voiced = 0
    n_frames = 0
    for start in range(0, total - frame_len + 1, frame_len):
        chunk = frames[start:start + frame_len]
        frame_rms = math.sqrt(sum(float(v) * v for v in chunk) / frame_len)
        if frame_rms <= 0:
            continue
        n_frames += 1
        if 20.0 * math.log10(frame_rms / 32768.0) > voiced_floor_dbfs:
            voiced += 1

    def db(value):
        return round(20.0 * math.log10(value / 32768.0), 2) if value > 0 else None

    return {
        "duration_s": round(total / float(sample_rate), 3),
        "samples": total,
        "rms_dbfs": db(rms),
        "peak_dbfs": db(float(peak)),
        "clip_ratio": round(clipped / total, 6),
        "dc_offset": round(dc_sum / total / 32768.0, 6),
        "voiced_ratio": round(voiced / n_frames, 4) if n_frames else None,
        "silence_ratio": round(1.0 - voiced / n_frames, 4) if n_frames else None,
        "hf_ratio_db": (round(10.0 * math.log10(hp_energy / total_energy), 2)
                        if total_energy > 0 else None),
    }


def grade_of(metrics: dict) -> tuple[str, str]:
    """采集等级。grade_c 的数据连探索都不该用，只保留取证。

    关键取舍：**未知不等于干净**。浏览器没有回报 AEC/NS/AGC 实际状态时，
    按 grade_b 处理，而不是默认为通过。这与「缺测明确为空、不用占位数据」是同一条原则。
    """
    actuals = {name: metrics.get(f"{name}_actual") for name in ("aec", "ns", "agc")}
    forced = [name for name in ("ns", "agc", "aec") if actuals[name] is True]
    labels = [name.upper() for name in forced]
    unknown = [name.upper() for name in ("aec", "ns", "agc") if actuals[name] is None]
    gaps = int(metrics.get("chunk_gap_count") or 0)
    dropped = int(metrics.get("dropped_frames") or 0)
    clip = float(metrics.get("clip_ratio") or 0.0)
    duration = float(metrics.get("duration_s") or 0.0)

    if any(name in forced for name in ("ns", "agc")):
        return "grade_c", f"本机强制开启 {' / '.join(labels)}，信号已被处理，禁止用于任何比较"
    if duration < 1.0:
        return "grade_c", "有效时长不足 1 秒"
    reasons = []
    if unknown:
        reasons.append(f"{' / '.join(unknown)} 实际状态未知（浏览器未回报），不能视为已关闭")
    if "aec" in forced:
        reasons.append("无法关闭 AEC")
    if gaps or dropped:
        reasons.append(f"丢帧 {dropped}（序号断档 {gaps} 段）")
    if clip > 0.001:
        reasons.append(f"削波比例 {clip}")
    if reasons:
        return "grade_b", "；".join(reasons)
    return "grade_a", "AEC/NS/AGC 全部实际关闭，无丢帧，无削波"


# --------------------------------------------------------------------------- #
# Tier 门禁 + 生态效度
# --------------------------------------------------------------------------- #

def cross_tier_gate(sources: list[dict]) -> dict:
    """一轮晋级比较的 tier 门禁。

    sources: [{"tier": "synthetic_tts"|"real_device", "id": "..."}]
    规则：晋级结论只允许在同一 tier 内成立；真机语料单独出生态效度报告。
    """
    tiers = []
    for item in sources or []:
        tier = str((item or {}).get("tier") or "").strip()
        if tier and tier not in tiers:
            tiers.append(tier)
    if not tiers:
        return {"allowed": False, "tier_set": [], "reason": "没有可判定的数据来源 tier"}
    if len(tiers) > 1:
        return {
            "allowed": False,
            "tier_set": tiers,
            "reason": (
                "同一轮晋级比较混用了 " + " + ".join(tiers) +
                "；真机语料只能作为生态效度校验证据层，不能与合成基准一起决定晋级"
            ),
        }
    return {"allowed": True, "tier_set": tiers, "reason": f"单一来源 tier：{tiers[0]}"}


def validity_compare(synthetic_delta: dict, real_delta: dict, *, tolerance: float = 0.0) -> dict:
    """对比「合成基准上的 ΔPQ 方向」与「真机语料上的 ΔPQ 方向」是否一致。

    不一致不代表哪个是错的，代表基准的生态效度存疑，需要人来看。
    """
    shared = [k for k in synthetic_delta if k in real_delta
              and synthetic_delta[k] is not None and real_delta[k] is not None]
    if not shared:
        return {"status": "no_shared_metric", "agree": None, "rows": []}
    rows = []
    agree = 0
    for key in shared:
        s = float(synthetic_delta[key])
        r = float(real_delta[key])
        s_dir = 1 if s > tolerance else (-1 if s < -tolerance else 0)
        r_dir = 1 if r > tolerance else (-1 if r < -tolerance else 0)
        same = s_dir == r_dir
        agree += 1 if same else 0
        rows.append({
            "metric": key,
            "synthetic_delta": round(s, 4),
            "real_delta": round(r, 4),
            "synthetic_dir": s_dir,
            "real_dir": r_dir,
            "agree": same,
        })
    ratio = round(agree / len(shared), 3)
    return {
        "status": "ok",
        "agree_ratio": ratio,
        "agree": ratio >= 1.0,
        "verdict": "方向一致：真机语料支持合成基准的结论" if ratio >= 1.0
        else "方向不一致：合成基准的生态效度存疑，需人工判定",
        "rows": rows,
    }


def list_scripts() -> dict:
    return {"status": "ok", "scripts": SCRIPTS, "routes": list(INPUT_ROUTES)}


def summary() -> dict:
    rows = list_sessions(limit=1000)["sessions"]
    by_grade: dict[str, int] = {}
    by_route: dict[str, int] = {}
    for row in rows:
        by_grade[str(row.get("capture_grade"))] = by_grade.get(str(row.get("capture_grade")), 0) + 1
        by_route[str(row.get("declared_route"))] = by_route.get(str(row.get("declared_route")), 0) + 1
    return {
        "status": "ok",
        "tier": TIER_REAL,
        "session_count": len(rows),
        "by_grade": by_grade,
        "by_route": by_route,
        "usable_for_loop": sum(1 for row in rows if row.get("capture_grade") == "grade_a"),
        "trace_path": str(TRACE_PATH),
    }
