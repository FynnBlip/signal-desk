# -*- coding: utf-8 -*-
"""03 TTS 合成 —— 插件清单。"""

MANIFEST = {
    "id": "03_tts",
    "name": "TTS 合成",
    "version": "0.2.0",
    "status": "wip",
    "summary": "MiniMax 系统音色合成 exam wav（预留本地引擎插槽）",
    "routes": ["/api/tts/voices", "/api/tts/synthesize"],
    "providers": [
        {"id": "minimax-speech-2.8-turbo", "name": "MiniMax Speech 2.8 Turbo", "kind": "remote-api", "default": True, "requires": ["MINIMAX_API_KEY"], "capabilities": ["voices", "synthesize", "cohort"]},
    ],
    "tools": ["list_voices", "synthesize", "generate_cohort"],
}
