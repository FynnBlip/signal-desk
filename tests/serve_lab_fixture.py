"""Loopback-only browser fixtures. No service imports, real APIs or disk writes.

GET /__test__/running starts a 30-second simulated task. Scores are test fixtures.
"""
import argparse
import ast
import copy
import io
import json
import math
import mimetypes
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs
import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parents[1]
SCENES = [("NPARK", "安静 · 公园", 25, 45), ("OOFFICE", "办公室", 15, 55), ("PCAFETER", "咖啡厅", 10, 70), ("PRESTO", "食堂", 5, 72), ("STRAFFIC", "路口 · 交通", 0, 75), ("TMETRO", "地铁 · 高噪", -10, 90)]
RESULT = {"status": "ok", "run_id": "fixture-run", "experiment_id": "fixture-experiment", "baseline": "v1", "candidate": "v2", "judge": {"baseline_regular_pq": 6, "candidate_regular_pq": 7, "regular_delta": 1}, "decision": {"action": "accept", "reason": "模拟测试数据，仅用于验证交互"}, "rows": [{"scene_id": "OOFFICE", "noise_label": "办公室", "snr_db": 15, "stem": "fixture-sample", "voice_name": "模拟音色", "baseline_pq": 6, "candidate_pq": 7}], "blind_pairs": [{"stem": "fixture-sample", "noise_label": "办公室"}]}


def serve(app_root, port):
    state = {"deadline": None, "calls": [], "candidate": "v2", "cohorts": [], "voice_job": {"state": "idle"}, "voice_deadline": None, "resource_mode": "empty"}
    def cohort(status="ready", clustered=False):
        return {"id": "fixture-cohort", "name": "模拟普通话音色", "version_label": "模拟资源", "provider": "minimax", "model": "mock", "seed": 42, "language_scope": "mandarin", "probe_text": "模拟固定探针", "requested_count": 26, "completed_count": 26 if status == "ready" else 3, "status": status, "clustered": clustered, "n_clusters": 4 if clustered else 0, "can_activate": clustered, "active": False}
    buffer = io.BytesIO()
    sf.write(buffer, np.zeros(16000), 16000, format="WAV")
    audio = buffer.getvalue()
    class Handler(BaseHTTPRequestHandler):
        def send(self, body, mime="application/json", code=200):
            if isinstance(body, dict):
                body = json.dumps(body, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", mime)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers(); self.wfile.write(body)

        def do_GET(self):
            path = urlparse(self.path).path
            deadline = state["deadline"]
            running = deadline is not None and time.monotonic() < deadline
            if path == "/__test__/running":
                state["deadline"] = time.monotonic() + 30
                return self.send({"fixture": True, "state": "running"})
            if path == "/__test__/calls":
                return self.send({"fixture": True, "calls": state["calls"]})
            if path == "/__test__/resources":
                mode = parse_qs(urlparse(self.path).query).get("mode", ["empty"])[0]
                state.update(resource_mode=mode, voice_job={"state": "idle"}, voice_deadline=None, calls=[], cohorts=[cohort("partial")] if mode == "partial" else ([cohort(clustered=True)] if mode in {"ready", "activate-fail"} else ([cohort()] if mode == "analyze-fail" else [])))
                return self.send({"fixture": True, "mode": mode})
            if path == "/api/providers":
                return self.send({"providers": [{"id": "minimax-speech-2.8-turbo", "name": "MiniMax · 模拟 Provider", "ready": state["resource_mode"] != "offline"}]})
            if path == "/api/voice/cohorts/job":
                if state["voice_deadline"] and time.monotonic() >= state["voice_deadline"]:
                    state["voice_deadline"] = None
                    state["voice_job"] = {"state": "done", "done": 26, "total": 26, "cohort_id": "fixture-cohort", "message": "模拟音色就绪"}
                    state["cohorts"] = [cohort()]
                return self.send(state["voice_job"])
            if path == "/api/loop/status":
                return self.send({"experiment_id": "fixture-experiment", "workspace_mode": "experiment", "baseline": "v1", "candidate": state["candidate"], "config": {}, "rounds": [], "benchmark": {"ready": True, "readiness": {"voice": True, "noise": True, "dut": True, "evaluator": True}}})
            if path == "/api/loop/job":
                return self.send({"state": "running" if running else "done" if deadline else "idle", "run_id": "fixture-run", "result": None if running or not deadline else copy.deepcopy(RESULT), "done": 0 if running else 1, "total": 1, "message": "模拟测试任务，仅用于验证交互", "events": []})
            if path == "/api/loop/options":
                return self.send({"versions": [{"id": v, "label": f"{v} · 测试版本"} for v in ["v1", "v2", "v3"]]})
            if path == "/api/voice/distribution":
                return self.send({"cohort_id": "fixture-cohort", "points": [{"file": "fixture.wav", "name": "模拟音色", "cluster": 1, "x": 150, "y": 700, "audio_available": True}]})
            if path == "/api/voice/cohorts":
                return self.send({"cohorts": state["cohorts"]})
            if path in {"/api/voice/cohorts/fixture-cohort/distribution", "/api/voice/distribution"}:
                return self.send({"cohort_id": "fixture-cohort", "embedding": {"method": "PCA", "source_dimensions": 21, "dimensions": 3, "axes": ["PC1", "PC2", "PC3"], "explained_variance": [.42, .23, .11]}, "points": [{"file": f"{i}.wav", "name": f"模拟音色{i}", "cluster": i % 4, "x": i/8-1.5, "y": (i%7)/3-1, "z": (i%5)/2-1, "f0_mean": 100+i*4, "f1_mean": 300+i*10, "f2_mean": 1200+i*12, "audio_available": True} for i in range(26)]})
            if path == "/api/voice/cohorts/fixture-cohort/result":
                return self.send({"status": "ok", "n_clusters": 4, "files": [{"file": f"{i}.wav", "voice_name": f"模拟音色{i}", "cluster": i % 4, "f0_mean": 100+i*4, "f1_mean": 300+i*10, "f2_mean": 1200+i*12} for i in range(26)]})
            if path == "/api/corpus/templates":
                return self.send({"templates": []})
            if path == "/api/channel/noise/scenes":
                return self.send({"scenes": [{"id": i, "label": n, "snr_db": snr, "level_db": level, "preview_ready": True, "preview": "fixture.wav"} for i, n, snr, level in SCENES]})
            if path == "/api/loop/archive":
                return self.send({"rounds": []})
            if path == "/api/loop/report":
                source = ROOT / "modules/07_loop/loop.py"
                function = next(n for n in ast.parse(source.read_text(encoding="utf-8")).body if isinstance(n, ast.FunctionDef) and n.name == "build_markdown")
                ns = {"math": math, "GOLDEN_BENCHMARK": {"label": "模拟测试矩阵"}, "build_version_summary": lambda s: {}}
                exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), "exec"), ns)
                round_item = {**RESULT, "round": 1, "time": "fixture-time"}
                return self.send({"summary": {"baseline": "v1", "candidate": "v2", "status": "review", "recommendation": {}}, "rounds": [round_item], "markdown": ns["build_markdown"]({"rounds": [round_item]})})
            if path.startswith("/api/") and ("/audio/" in path or "/preview/" in path):
                return self.send(audio, "audio/wav")
            if path.startswith("/api/"):
                return self.send({"status": "error", "message": "Undefined fixture; real API forwarding forbidden"}, code=404)
            file = app_root / ("lab.html" if path in {"/", "/index.html"} else path.lstrip("/"))
            if file.resolve().is_relative_to(app_root.resolve()) and file.is_file():
                return self.send(file.read_bytes(), mimetypes.guess_type(file.name)[0] or "application/octet-stream")
            self.send(b"Not found", "text/plain", 404)

        def do_POST(self):
            path = urlparse(self.path).path
            payload = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            state["calls"].append({"path": path, "payload": payload})
            if path == "/api/voice/cohorts/plan":
                count = 10 if state["resource_mode"] == "short" else 26
                return self.send({"status": "ok", "selected_count": count, "api_calls": count, "version_label": payload.get("version_label"), "probe_text": payload.get("probe_text") or "模拟固定探针", "voices": [{"voice_id": f"mock-{i}", "name": f"模拟音色{i}"} for i in range(count)]})
            if path == "/api/voice/cohorts/run":
                if state["cohorts"] and state["cohorts"][0]["status"] == "ready":
                    return self.send({"status": "reused", "cohort_id": "fixture-cohort", "message": "模拟缓存复用，未生成"})
                state["voice_deadline"] = time.monotonic() + 8
                state["cohorts"] = [cohort("partial")]
                state["voice_job"] = {"state": "running", "done": 3, "total": 26, "cohort_id": "fixture-cohort", "message": "模拟生成，保留已有缓存"}
                return self.send({"status": "ok", "cohort_id": "fixture-cohort"})
            if path == "/api/voice/cohorts/cancel":
                state.update(voice_deadline=None, voice_job={"state": "cancelled", "done": 3, "total": 26, "message": "模拟暂停，缓存保留"})
                return self.send({"status": "ok", "message": "已请求暂停"})
            if path == "/api/voice/cohorts/fixture-cohort/analyze":
                if state["resource_mode"] == "analyze-fail": return self.send({"status": "error", "message": "模拟聚类失败"})
                state["cohorts"] = [cohort(clustered=True)]
                return self.send({"status": "ok"})
            if path == "/api/voice/cohorts/fixture-cohort/activate":
                if state["resource_mode"] == "activate-fail": return self.send({"status": "error", "message": "模拟激活失败"})
                state["cohorts"][0]["active"] = True
                return self.send({"status": "ok", "cohort_id": "fixture-cohort"})
            if path == "/api/loop/config":
                state["candidate"] = payload.get("candidate", "v2")
                time.sleep(2)
                return self.send({"status": "ok"})
            if path == "/api/loop/run":
                state["deadline"] = time.monotonic() + 12
                return self.send({"status": "ok", "state": "running", "run_id": "fixture-run"})
            if path == "/api/loop/listen":
                return self.send({"status": "ok"})
            return self.send({"status": "error", "message": "Undefined fixture write; no real API forwarding"}, code=400)
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--app-root", type=Path, default=ROOT / "app")
    parser.add_argument("--port", type=int, default=8091)
    args = parser.parse_args()
    serve(args.app_root.resolve(), args.port)
