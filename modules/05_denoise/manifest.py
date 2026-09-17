# -*- coding: utf-8 -*-
"""05 降噪 DUT —— 插件清单。"""

MANIFEST = {
    "id": "05_denoise",
    "name": "降噪 DUT",
    "version": "0.2.0",
    "status": "wip",
    "summary": "GTCRN / DeepFilterNet3 降噪闭环，输入 04 degraded wav",
    "routes": ["/api/denoise/models", "/api/denoise/inputs", "/api/denoise/run"],
    "providers": [
        {"id": "gtcrn", "name": "GTCRN ONNX", "kind": "local-cpu", "default": False, "requires": ["gtcrn_simple.onnx"], "capabilities": ["denoise"]},
        {"id": "deepfilternet3", "name": "DeepFilterNet3 ONNX", "kind": "local-cpu", "default": False, "requires": ["denoiser_model_deepfilternet3.onnx"], "capabilities": ["denoise"]},
        {"id": "noisereduce", "name": "NoiseReduce", "kind": "local-cpu", "default": True, "capabilities": ["denoise", "strength"]},
    ],
    "tools": ["list_models", "run"],
}
