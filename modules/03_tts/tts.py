# -*- coding: utf-8 -*-
"""03 TTS 合成 —— 第三块蛋糕。

职责：按音色把文本合成 exam wav。默认走 MiniMax 商用 API（系统音色），
统一引擎契约预留本地 TTS 模型插槽（plan B）。

key 保护铁律：key 只从本机 .env 读取，永不写死、不打印、不出前端、不上 git。
"""

import base64
import datetime
import json
import re
import time
from pathlib import Path

import requests

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_SESSION = requests.Session()

MINIMAX_T2A_URL = "https://api.minimaxi.com/v1/t2a_v2"
MINIMAX_GET_VOICE_URL = "https://api.minimaxi.com/v1/get_voice"
MINIMAX_MODEL = "speech-2.8-turbo"

# 兜底音色：仅当动态拉取音色失败时使用，避免 TTS 页空白。
_FALLBACK_VOICES = [
    {"voice_id": "Chinese (Mandarin)_Warm_Bestie", "name": "温暖闺蜜", "kind": "system", "description": ""},
    {"voice_id": "Chinese (Mandarin)_Male_Announcer", "name": "播报男声", "kind": "system", "description": ""},
    {"voice_id": "Chinese (Mandarin)_Pure-hearted_Boy", "name": "清澈邻家弟弟", "kind": "system", "description": ""},
    {"voice_id": "Chinese (Mandarin)_Soft_Girl", "name": "软软女孩", "kind": "system", "description": ""},
]

_VOICES_CACHE = {"data": None, "ts": 0.0}
_VOICES_CACHE_TTL = 300  # 秒，音色清单不常变


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
        return _FALLBACK_VOICES

    now = time.time()
    if _VOICES_CACHE["data"] is not None and now - _VOICES_CACHE["ts"] < _VOICES_CACHE_TTL:
        return _VOICES_CACHE["data"]

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
        return voices
    except Exception:
        return _FALLBACK_VOICES


def list_voices():
    """返回可用音色清单（不含任何密钥）。"""
    return _fetch_voices()


def synthesize(text, voice_id, output_dir=None):
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
            data = resp.json()
            if data.get("base_resp", {}).get("status_code") != 0:
                raise RuntimeError(json.dumps(data, ensure_ascii=False))
            raw = data["data"]["audio"]
            sample = raw[:80]
            if all(c in "0123456789abcdefABCDEF" for c in sample) and len(sample) % 2 == 0:
                wav = bytes.fromhex(raw)  # MiniMax 返回 hex，不是 base64
            else:
                wav = base64.b64decode(raw)
            voice_name = next((v["name"] for v in list_voices() if v["voice_id"] == voice_id), "voice")
            safe = re.sub(r'[\\/:*?"<>|]', "_", voice_name)
            fname = f"{safe}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.wav"
            (out_dir / fname).write_bytes(wav)
            return {
                "status": "ok",
                "file": str(out_dir / fname),
                "filename": fname,
                "bytes": len(wav),
            }
        except Exception as exc:
            last_error = exc
            if attempt < 5:
                wait = 2 * (2 ** (attempt - 1))
                if "rate limit" in str(exc).lower() or "1002" in str(exc):
                    wait += 5
                time.sleep(wait)
    return {"status": "error", "message": str(last_error)}
