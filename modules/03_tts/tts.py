# -*- coding: utf-8 -*-
"""03 TTS 合成 —— 第三块蛋糕。

职责：按音色把文本合成 exam wav。默认走 MiniMax 商用 API（系统音色），
统一引擎契约预留本地 TTS 模型插槽（plan B）。

key 保护铁律：key 只从本机 .env 读取，永不写死、不打印、不出前端、不上 git。
"""

import base64
import datetime
import hashlib
import json
import os
import random
import re
import time
import uuid
from pathlib import Path

import requests

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_SESSION = requests.Session()

MINIMAX_T2A_URL = "https://api.minimaxi.com/v1/t2a_v2"
MINIMAX_GET_VOICE_URL = "https://api.minimaxi.com/v1/get_voice"
MINIMAX_MODEL = "speech-2.8-turbo"

# 所有候选音色使用同一段探针，控制文本内容这个变量。目标实测时长 8–12 秒。
DEFAULT_VOICE_PROBE = (
    "喂，您好，我在车站等朋友，请把明天下午三点的会议改到六点半，再帮我确认新的房间号码，谢谢。"
)

# 兜底音色：仅当动态拉取音色失败时使用，避免 TTS 页空白。
_FALLBACK_VOICES = [
    {"voice_id": "Chinese (Mandarin)_Warm_Bestie", "name": "温暖闺蜜", "kind": "system", "description": ""},
    {"voice_id": "Chinese (Mandarin)_Male_Announcer", "name": "播报男声", "kind": "system", "description": ""},
    {"voice_id": "Chinese (Mandarin)_Pure-hearted_Boy", "name": "清澈邻家弟弟", "kind": "system", "description": ""},
    {"voice_id": "Chinese (Mandarin)_Soft_Girl", "name": "软软女孩", "kind": "system", "description": ""},
]

_VOICES_CACHE = {"data": None, "ts": 0.0}
_VOICES_CACHE_TTL = 300  # 秒，音色清单不常变
_VOICE_CATALOG_STATUS = {"source": "uninitialized", "fallback": False, "warning": ""}


class _PermanentTtsError(RuntimeError):
    pass


def _catalog_rows(rows, source, warning=""):
    global _VOICE_CATALOG_STATUS
    _VOICE_CATALOG_STATUS = {"source": source, "fallback": source == "fallback", "warning": warning}
    return [{**item, "catalog_source": source, "catalog_warning": warning} for item in rows]


def voice_catalog_status():
    return dict(_VOICE_CATALOG_STATUS)


def load_env():
    """从项目根目录 .env 读取键值，key 不写死在代码里。"""
    env = {}
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        return env
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def _fetch_voices():
    """动态拉取账号下全部可调用音色；失败时回退到本地兜底清单。"""
    env = load_env()
    api_key = env.get("MINIMAX_API_KEY")
    if not api_key:
        return _catalog_rows(_FALLBACK_VOICES, "fallback", "未配置 MiniMax API Key，当前仅展示 4 个本地兜底音色。")

    now = time.time()
    if _VOICES_CACHE["data"] is not None and now - _VOICES_CACHE["ts"] < _VOICES_CACHE_TTL:
        return _catalog_rows(_VOICES_CACHE["data"], "minimax_api")

    try:
        resp = _SESSION.post(
            MINIMAX_GET_VOICE_URL,
            json={"voice_type": "all"},
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            timeout=30,
        )
        data = resp.json()
        if data.get("base_resp", {}).get("status_code") != 0:
            raise RuntimeError(json.dumps(data, ensure_ascii=False))

        voices = []
        counters = {"voice_cloning": 0, "voice_generation": 0}
        kind_map = {"system_voice": "system", "voice_cloning": "cloning", "voice_generation": "generation"}
        for key in ("system_voice", "voice_cloning", "voice_generation"):
            for item in data.get(key) or []:
                voice_id = item.get("voice_id") or ""
                name = (item.get("voice_name") or "").strip()
                if not name:
                    counters[key] += 1
                    label = "克隆" if key == "voice_cloning" else "生成"
                    name = f"{label}音色 {counters[key]}"
                voices.append({
                    "voice_id": voice_id,
                    "name": name,
                    "kind": kind_map[key],
                    "description": " ".join(item.get("description") or []).strip(),
                })
        if not voices:
            raise RuntimeError("get_voice 返回空列表")

        _VOICES_CACHE["data"] = voices
        _VOICES_CACHE["ts"] = now
        return _catalog_rows(voices, "minimax_api")
    except Exception as exc:
        detail = str(exc).replace("\n", " ")[:300]
        return _catalog_rows(_FALLBACK_VOICES, "fallback", f"MiniMax 音色目录读取失败，已回退到 4 个兜底音色：{detail}")


def list_voices():
    """返回可用音色清单（不含任何密钥）。"""
    return _fetch_voices()


def _decode_wav_payload(raw):
    """Decode a complete hex/base64 payload and reject mislabeled non-WAV bytes."""
    if not isinstance(raw, str) or not raw:
        raise _PermanentTtsError("MiniMax 返回了空音频")
    try:
        if len(raw) % 2 == 0 and re.fullmatch(r"[0-9a-fA-F]+", raw):
            wav = bytes.fromhex(raw)
        else:
            wav = base64.b64decode(raw, validate=True)
    except (ValueError, base64.binascii.Error) as exc:
        raise _PermanentTtsError("MiniMax 音频既不是完整 hex，也不是合法 base64") from exc
    if len(wav) < 12 or wav[:4] != b"RIFF" or wav[8:12] != b"WAVE":
        raise _PermanentTtsError("MiniMax 返回内容不是有效 WAV（缺少 RIFF/WAVE 头）")
    return wav


def _is_transient_tts_error(exc):
    if isinstance(exc, (requests.Timeout, requests.ConnectionError)):
        return True
    text = str(exc).lower()
    return any(marker in text for marker in ("rate limit", "1002", "429", "timeout", "temporarily", "server error", "502", "503", "504"))


def synthesize(text, voice_id, output_dir=None, output_name=None):
    """合成一条语料为 wav，返回结构化结果。key 从 .env 读取，绝不外泄。"""
    env = load_env()
    api_key = env.get("MINIMAX_API_KEY")
    group_id = env.get("MINIMAX_GROUP_ID")
    if not api_key or not group_id:
        return {"status": "error", "message": ".env 缺少 MINIMAX_API_KEY 或 MINIMAX_GROUP_ID"}

    out_dir = Path(output_dir) if output_dir else PROJECT_ROOT / "data" / "exam"
    out_dir.mkdir(parents=True, exist_ok=True)

    payload = {
        "model": MINIMAX_MODEL,
        "text": text,
        "stream": False,
        "voice_setting": {"voice_id": voice_id, "speed": 1.0, "vol": 1.0, "pitch": 0},
        "audio_setting": {"sample_rate": 32000, "bitrate": 128000, "format": "wav", "channel": 1},
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    last_error = None
    for attempt in range(1, 6):
        try:
            resp = _SESSION.post(
                MINIMAX_T2A_URL, json=payload, headers=headers,
                params={"GroupId": group_id}, timeout=120,
            )
            if resp.status_code >= 500 or resp.status_code == 429:
                raise RuntimeError(f"MiniMax HTTP {resp.status_code}")
            if resp.status_code >= 400:
                raise _PermanentTtsError(f"MiniMax HTTP {resp.status_code}: {resp.text[:300]}")
            data = resp.json()
            if data.get("base_resp", {}).get("status_code") != 0:
                message = json.dumps(data, ensure_ascii=False)
                if _is_transient_tts_error(RuntimeError(message)):
                    raise RuntimeError(message)
                raise _PermanentTtsError(message)
            raw = data["data"]["audio"]
            wav = _decode_wav_payload(raw)
            voice_name = next((v["name"] for v in list_voices() if v["voice_id"] == voice_id), "voice")
            safe = re.sub(r'[\\/:*?"<>|]', "_", voice_name)
            fname = Path(output_name).name if output_name else f"{safe}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.wav"
            if not fname.lower().endswith(".wav"):
                fname += ".wav"
            (out_dir / fname).write_bytes(wav)
            return {
                "status": "ok",
                "file": str(out_dir / fname),
                "filename": fname,
                "bytes": len(wav),
            }
        except Exception as exc:
            last_error = exc
            if isinstance(exc, _PermanentTtsError) or not _is_transient_tts_error(exc):
                break
            if attempt < 5:
                wait = 2 * (2 ** (attempt - 1))
                if "rate limit" in str(exc).lower() or "1002" in str(exc):
                    wait += 5
                time.sleep(wait)
    return {"status": "error", "message": str(last_error)}


def plan_voice_cohort(count=50, seed=42, probe_text=None, kinds=None, language_scope="mandarin", version_label=""):
    """只做 Cohort 计划，不产生 TTS 费用。选择结果按 seed 可复现且 voice_id 去重。"""
    probe = (probe_text or DEFAULT_VOICE_PROBE).strip()
    requested = min(max(int(count), 2), 100)
    allowed_kinds = set(kinds or ["system"])
    unique = {}
    for item in list_voices():
        voice_id = (item.get("voice_id") or "").strip()
        is_mandarin = "chinese (mandarin)" in voice_id.lower()
        if voice_id and item.get("kind") in allowed_kinds and (language_scope != "mandarin" or is_mandarin):
            unique.setdefault(voice_id, item)
    available = list(unique.values())
    random.Random(int(seed)).shuffle(available)
    selected = available[:requested]
    chars = len(probe)
    plan = {
        "status": "ok" if len(selected) >= 2 else "error",
        "message": "" if len(selected) >= 2 else "可用的不同音色不足 2 个",
        "requested_count": requested,
        "selected_count": len(selected),
        "available_count": len(available),
        "seed": int(seed),
        "kinds": sorted(allowed_kinds),
        "language_scope": "mandarin" if language_scope == "mandarin" else "all",
        "version_label": (version_label or "").strip()[:80],
        "probe_text": probe,
        "probe_chars": chars,
        "estimated_seconds_per_voice": round(chars / 4.8, 1),
        "estimated_total_seconds": round(chars / 4.8 * len(selected), 1),
        "api_calls": len(selected),
        "voices": selected,
    }
    plan["request_fingerprint"] = cohort_fingerprint(plan)
    return plan


def cohort_fingerprint(plan):
    """相同实验输入得到稳定指纹，避免重复调用 TTS API。"""
    payload = {
        "voice_ids": sorted(item.get("voice_id") for item in plan.get("voices") or [] if item.get("voice_id")),
        "probe_text": (plan.get("probe_text") or "").strip(),
        "seed": int(plan.get("seed", 42)),
        "language_scope": plan.get("language_scope", "all"),
        "kinds": sorted(plan.get("kinds") or []),
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _file_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json_atomic(path, payload):
    """Publish manifests atomically so an interrupted write cannot trigger paid re-generation."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def _cohort_integrity(manifest, cohort_dir):
    """检查 Cohort 是否可以安全复用；老 manifest 无 hash 时只做文件存在性检查。"""
    audio_dir = Path(cohort_dir) / "audio"
    items = manifest.get("items") or []
    if not items or any(item.get("status") != "ok" for item in items):
        return False
    for item in items:
        audio = audio_dir / str(item.get("filename") or "")
        if not audio.is_file():
            return False
        expected = item.get("sha256")
        if expected and _file_sha256(audio) != expected:
            return False
    return True


def find_existing_cohort(plan):
    """返回同一请求的本地 Cohort；只读，不触发费用。"""
    root = PROJECT_ROOT / "data" / "voice" / "cohorts"
    if not root.exists():
        return None
    fingerprint = plan.get("request_fingerprint") or cohort_fingerprint(plan)
    for manifest_path in sorted(root.glob("*/manifest.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        existing = manifest.get("request_fingerprint")
        if not existing:
            existing_plan = {
                "voices": manifest.get("items") or [],
                "probe_text": manifest.get("probe_text") or "",
                "seed": manifest.get("seed", 42),
                "language_scope": manifest.get("language_scope", "all"),
                "kinds": sorted({item.get("kind") or "system" for item in manifest.get("items") or []}),
                "version_label": manifest.get("version_label") or "",
            }
            existing = cohort_fingerprint(existing_plan)
        if existing == fingerprint:
            status = manifest.get("status") or "partial"
            if status == "ready" and not _cohort_integrity(manifest, manifest_path.parent):
                status = "partial"
            return {
                "id": manifest.get("id") or manifest_path.parent.name,
                "status": status,
                "completed_count": manifest.get("completed_count", 0),
                "requested_count": manifest.get("requested_count", len(manifest.get("items") or [])),
            }
    return None


def generate_voice_cohort(plan, cohort_dir, progress_cb=None, cancel_event=None):
    """按计划逐条生成 Cohort；manifest 每条完成即落盘，支持同目录断点续跑。"""
    cohort_dir = Path(cohort_dir)
    audio_dir = cohort_dir / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = cohort_dir / "manifest.json"

    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    else:
        created_at = datetime.datetime.now().isoformat(timespec="seconds")
        manifest = {
            "schema_version": 1,
            "id": cohort_dir.name,
            "name": f"{plan.get('version_label') or '未命名版本'} · MiniMax {'普通话' if plan.get('language_scope') == 'mandarin' else '多语种'} · {created_at[:10]}",
            "provider": "minimax",
            "model": MINIMAX_MODEL,
            "created_at": created_at,
            "seed": plan["seed"],
            "language_scope": plan.get("language_scope", "all"),
            "version_label": (plan.get("version_label") or "").strip()[:80],
            "request_fingerprint": plan.get("request_fingerprint") or cohort_fingerprint(plan),
            "probe_text": plan["probe_text"],
            "probe_chars": plan["probe_chars"],
            "estimated_seconds_per_voice": plan["estimated_seconds_per_voice"],
            "requested_count": plan["selected_count"],
            "original_requested_count": plan["requested_count"],
            "items": [],
        }
        for index, voice_item in enumerate(plan["voices"], 1):
            manifest["items"].append({
                "index": index,
                "voice_id": voice_item["voice_id"],
                "voice_name": voice_item.get("name") or voice_item["voice_id"],
                "kind": voice_item.get("kind") or "system",
                "status": "pending",
                "filename": f"{index:03d}__voice.wav",
            })
        _write_json_atomic(manifest_path, manifest)

    items = manifest.get("items") or []
    # 生成过程中若文件被替换或损坏，回退到 pending，下一轮只补这一条。
    for item in items:
        if item.get("status") == "ok" and item.get("sha256"):
            audio = audio_dir / str(item.get("filename") or "")
            if not audio.is_file() or _file_sha256(audio) != item["sha256"]:
                item["status"] = "pending"
                item.pop("sha256", None)
    total = len(items)
    completed = sum(1 for item in items if item.get("status") == "ok" and (audio_dir / item["filename"]).exists())
    if progress_cb:
        progress_cb(completed, total, "读取计划，跳过已完成样本")

    for item in items:
        if cancel_event is not None and cancel_event.is_set():
            manifest["completed_count"] = completed
            manifest["failed_count"] = sum(1 for row in items if row.get("status") == "error")
            manifest["status"] = "partial"
            manifest["updated_at"] = datetime.datetime.now().isoformat(timespec="seconds")
            _write_json_atomic(manifest_path, manifest)
            return {"status": "cancelled", "message": "已暂停，可从本地 Cohort 继续", "manifest": manifest, "path": str(cohort_dir)}
        output = audio_dir / item["filename"]
        if item.get("status") == "ok" and output.exists():
            continue
        item["status"] = "running"
        item.pop("error", None)
        _write_json_atomic(manifest_path, manifest)
        if progress_cb:
            progress_cb(completed, total, f"生成 {item['index']:03d} · {item['voice_name']}")
        result = synthesize(
            manifest.get("probe_text") or plan["probe_text"],
            item["voice_id"], output_dir=audio_dir, output_name=item["filename"]
        )
        if result.get("status") == "ok":
            item.update(
                status="ok",
                bytes=result.get("bytes", 0),
                sha256=_file_sha256(output),
                completed_at=datetime.datetime.now().isoformat(timespec="seconds"),
            )
            completed += 1
        else:
            item.update(status="error", error=result.get("message") or "合成失败")
        _write_json_atomic(manifest_path, manifest)
        if progress_cb:
            progress_cb(completed, total, f"已完成 {completed}/{total}")

    manifest["completed_count"] = completed
    manifest["failed_count"] = sum(1 for item in items if item.get("status") == "error")
    manifest["status"] = "ready" if completed == total else "partial"
    manifest["updated_at"] = datetime.datetime.now().isoformat(timespec="seconds")
    _write_json_atomic(manifest_path, manifest)
    result_status = "ok" if completed == total and total else ("partial" if completed else "error")
    message = "" if result_status == "ok" else f"仅完成 {completed}/{total}，已保留本地文件供断点续跑"
    return {"status": result_status, "message": message, "manifest": manifest, "path": str(cohort_dir)}
