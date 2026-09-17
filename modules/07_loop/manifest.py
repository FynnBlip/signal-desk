# -*- coding: utf-8 -*-
"""07 闭环大脑 —— 插件清单。"""

MANIFEST = {
    "id": "07_loop",
    "name": "闭环大脑",
    "version": "0.2.0",
    "status": "wip",
    "summary": "闭环一：归因→条件晋级判定→LLM/规则建议→人在环执行",
    "routes": ["/api/loop/status", "/api/loop/run", "/api/loop/apply"],
    "providers": [
        {"id": "deterministic-gate-v2", "name": "确定性工程 Gate v2", "kind": "local", "default": True, "capabilities": ["guardrail", "allowed_actions"]},
        {"id": "deepseek-advisor", "name": "DeepSeek 决策建议器", "kind": "remote-api", "default": False, "requires": ["DEEPSEEK_API_KEY"], "capabilities": ["attribution", "recommendation"]},
        {"id": "human-blind-ab", "name": "人工盲听 A/B", "kind": "human", "default": False, "capabilities": ["listen", "record"]},
    ],
    "tools": ["run_preview", "record_listening", "apply_decision"],
}
