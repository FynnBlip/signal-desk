# -*- coding: utf-8 -*-
"""01 语料生成 —— 插件清单。"""

MANIFEST = {
    "id": "01_corpus",
    "name": "语料生成",
    "version": "0.1.0",
    "status": "ready",
    "summary": "中文通话考试语料 + 易混音对覆盖自检",
    "routes": ["/api/corpus/templates", "/api/corpus/generate"],
    "tools": [],
}
