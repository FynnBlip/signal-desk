# -*- coding: utf-8 -*-
"""05 降噪 DUT —— 插件清单。"""

MANIFEST = {
    "id": "05_denoise",
    "name": "降噪 DUT",
    "version": "0.1.0",
    "status": "wip",
    "summary": "GTCRN / DeepFilterNet3 降噪闭环，输入 04 degraded wav",
    "routes": ["/api/denoise/models", "/api/denoise/inputs", "/api/denoise/run"],
    "tools": [],
}
