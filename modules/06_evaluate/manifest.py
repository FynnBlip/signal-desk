# -*- coding: utf-8 -*-
"""06 评测 —— 插件清单。"""

MANIFEST = {
    "id": "06_evaluate",
    "name": "评测",
    "version": "0.2.0",
    "status": "wip",
    "summary": "audiobox PQ/PC/CE/CU + 干净→退化→降噪 ΔPQ 对比",
    "routes": ["/api/evaluate/run", "/api/evaluate/status"],
    "providers": [
        {"id": "audiobox-aesthetics", "name": "Meta AudioBox Aesthetics", "kind": "local-cpu", "default": True, "requires": ["AUDIOBOX_CHECKPOINT"], "capabilities": ["PQ", "PC", "CE", "CU"]},
        {"id": "audio-judge", "name": "Audio Judge（待接入）", "kind": "pluggable", "default": False, "configured": False, "capabilities": ["audio_reasoning", "evidence_text"]},
    ],
    "tools": ["score_directory", "compare", "export"],
}
