# -*- coding: utf-8 -*-
"""01 语料生成 —— 插件清单。"""

MANIFEST = {
    "id": "01_corpus",
    "name": "语料生成",
    "version": "0.2.0",
    "status": "ready",
    "summary": "中文通话考试语料 + 易混音对覆盖自检",
    "routes": ["/api/corpus/templates", "/api/corpus/generate"],
    "providers": [
        {"id": "builtin-zh-call-corpus", "name": "内置中文通话语料", "kind": "local", "default": True, "capabilities": ["templates", "coverage_labels", "wav_render"]},
    ],
    "tools": ["plan", "generate"],
}
