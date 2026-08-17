# -*- coding: utf-8 -*-
"""02 音色聚类 —— 插件清单（元框架自动发现用）。"""

MANIFEST = {
    "id": "02_voice",
    "name": "音色聚类",
    "version": "0.1.0",
    "status": "wip",           # ready 可用 / wip 施工中 / disabled 停用
    "summary": "声线特征提取 + KMeans 聚类 + 覆盖矩阵",
    "routes": ["/api/voice/analyze"],
    "tools": [],
}
