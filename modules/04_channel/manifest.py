# -*- coding: utf-8 -*-
"""04 信道仿真 —— 插件清单。"""

MANIFEST = {
    "id": "04_channel",
    "name": "信道仿真",
    "version": "0.2.0",
    "status": "wip",
    "summary": "Opus 编解码闭环（VoIP/OTT），噪声/丢包后续接入",
    "routes": ["/api/channel/presets", "/api/channel/inputs", "/api/channel/run"],
    "providers": [
        {"id": "demand-opus", "name": "DEMAND + Opus", "kind": "local-cpu", "default": True, "capabilities": ["noise_mix", "codec_roundtrip", "snr_measure"]},
    ],
    "tools": ["list_scenes", "run_matrix"],
}
