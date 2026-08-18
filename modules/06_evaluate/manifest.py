# -*- coding: utf-8 -*-
"""06 评测 —— 插件清单。"""

MANIFEST = {
    "id": "06_evaluate",
    "name": "评测",
    "version": "0.1.0",
    "status": "wip",
    "summary": "audiobox PQ/PC/CE/CU + 干净→退化→降噪 ΔPQ 对比",
    "routes": ["/api/evaluate/run", "/api/evaluate/status"],
    "tools": [],
}
