# -*- coding: utf-8 -*-
"""08 真机采集 —— 插件清单（ADR-001 自动发现）。"""

MANIFEST = {
    "id": "08_capture",
    "name": "真机采集",
    "version": "0.1.0",
    "status": "wip",
    "summary": "手机 / 蓝牙麦克风真实人声采集，落盘为 real_device tier 语料，受 tier 门禁约束",
    "routes": [
        "/api/capture/scripts",
        "/api/capture/session",
        "/api/capture/session/{session_id}/chunk",
        "/api/capture/session/{session_id}/finalize",
        "/api/capture/sessions",
        "/api/capture/summary",
    ],
    "providers": [
        {
            "id": "browser-pcm-upload",
            "name": "手机浏览器原始 PCM 上传",
            "kind": "lan-https",
            "default": True,
            "capabilities": ["capture", "device_manifest", "seq_integrity"],
        },
        {
            "id": "phone-internal-mic",
            "name": "手机内置麦克风",
            "kind": "device-route",
            "default": True,
            "capabilities": ["capture"],
        },
        {
            "id": "bluetooth-hfp-mic",
            "name": "蓝牙耳机 HFP 麦克风",
            "kind": "device-route",
            "default": False,
            "capabilities": ["capture", "narrowband"],
        },
    ],
    "tools": ["create_session", "append_chunk", "finalize_session", "list_sessions", "validity_compare"],
    "notes": "真机语料 tier=real_device，不参与合成基准的晋级判定，只输出生态效度校验报告。",
}
