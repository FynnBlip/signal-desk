# -*- coding: utf-8 -*-
"""07 闭环大脑 —— 插件清单。"""

MANIFEST = {
    "id": "07_loop",
    "name": "闭环大脑",
    "version": "0.1.0",
    "status": "wip",
    "summary": "闭环一：归因→条件晋级判定→LLM/规则建议→人在环执行",
    "routes": ["/api/loop/status", "/api/loop/run", "/api/loop/apply"],
    "tools": [],
}
