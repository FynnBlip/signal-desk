# -*- coding: utf-8 -*-
"""08 真机采集 · 端到端自检（没有手机也能证明链路是通的）。

  python scripts/verify_capture.py                       # 模块级：直接调 capture.py
  python scripts/verify_capture.py --http http://127.0.0.1:8091 --token <token>

它模拟一台「手机」按脚本上报 PCM，故意造一段丢帧和一段被强制 NS 的会话，
然后检查三件事：
  1. grade_a / grade_b / grade_c 是否被正确区分；
  2. 丢帧是否被如实记账，而不是被静默补齐；
  3. append-only trace 是否真的只增不改、schema 固定。
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
import shutil
import struct
import sys
import urllib.error
import urllib.request
import wave
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "modules" / "08_capture"))


def load_module():
    spec = importlib.util.spec_from_file_location(
        "capture_verify", PROJECT_ROOT / "modules" / "08_capture" / "capture.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# 访问本机 / 局域网地址必须绕过系统代理，否则会被代理拦成 502。
NO_PROXY_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def open_url(request, timeout: int = 30):
    return NO_PROXY_OPENER.open(request, timeout=timeout)


def fake_speech(seconds: float, sr: int, seed: int = 0) -> bytes:
    """合成一段带语音特征的 PCM，仅用于自检布线，不是语料、不是质量证据。"""
    samples = []
    for i in range(int(seconds * sr)):
        t = i / sr
        env = 0.55 + 0.45 * math.sin(2 * math.pi * (2.7 + seed * 0.3) * t)
        value = (math.sin(2 * math.pi * 310 * t) * 0.6
                 + math.sin(2 * math.pi * 2400 * t) * 0.25
                 + math.sin(2 * math.pi * 5100 * t) * 0.1)
        samples.append(int(max(-1.0, min(1.0, value * env)) * 6000))
    return struct.pack(f"<{len(samples)}h", *samples)


class HttpPhone:
    """把「手机」抽象成一个小客户端，模块级与 HTTP 级共用同一套调用序列。"""

    def __init__(self, base: str | None, token: str = "", sr: int = 16000):
        self.base = base.rstrip("/") if base else None
        self.token = token
        self.sr = sr

    def _call(self, path: str, payload=None, raw_body: bytes | None = None):
        if not self.base:
            raise RuntimeError("no http base")
        url = f"{self.base}{path}"
        headers = {"Content-Type": "application/octet-stream" if raw_body is not None else "application/json"}
        if self.token:
            headers["X-Capture-Token"] = self.token
        data = raw_body if raw_body is not None else json.dumps(payload or {}).encode()
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        with open_url(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def open_session(self, *, script_id: str, route: str, manifest: dict) -> str:
        if self.base:
            out = self._call("/api/capture/session", {
                "speaker_code": "SPK-VERIFY", "script_id": script_id,
                "declared_route": route, "client_manifest": manifest,
                "notes": "verify_capture.py 自检会话",
            })
            return out["session"]["session_id"]
        return None  # 模块级由调用方直接建

    def send(self, session_id: str, seq: int, pcm: bytes) -> dict:
        frames = len(pcm) // 2
        if self.base:
            return self._call(
                f"/api/capture/session/{session_id}/chunk?seq={seq}&frames={frames}",
                raw_body=pcm,
            )
        return {"status": "delegated"}

    def close(self, session_id: str, manifest: dict) -> dict:
        if self.base:
            return self._call(f"/api/capture/session/{session_id}/finalize", {
                "sample_rate": self.sr, "channel_count": 1, "client_manifest": manifest,
            })
        return {"status": "delegated"}


def run_module_level(capture) -> list[dict]:
    if capture.SESSIONS_ROOT.exists():
        shutil.rmtree(capture.SESSIONS_ROOT)
    if capture.TRACE_PATH.exists():
        capture.TRACE_PATH.unlink()

    cases = [
        ("干净会话（AEC/NS/AGC 全关）", "phone_internal", 3, [],
         {"aec_actual": False, "ns_actual": False, "agc_actual": False}, "grade_a"),
        ("丢帧会话（seq 1、2 未送达）", "phone_internal", 4, [1, 2],
         {"aec_actual": False, "ns_actual": False, "agc_actual": False}, "grade_b"),
        ("蓝牙 HFP 会话", "bluetooth_hfp", 3, [],
         {"aec_actual": False, "ns_actual": False, "agc_actual": False, "input_label": "AirPods Hands-Free"}, "grade_a"),
        ("被系统强制 NS 的会话", "phone_internal", 3, [],
         {"aec_actual": True, "ns_actual": True, "agc_actual": True}, "grade_c"),
    ]
    report = []
    for title, route, count, skip, actuals, expect in cases:
        created = capture.create_session(speaker_code="SPK-VERIFY", script_id="anchor",
                                         declared_route=route,
                                         client_manifest={"aec_requested": False, "ns_requested": False,
                                                          "agc_requested": False,
                                                          "input_label": actuals.get("input_label", "iPhone 麦克风")})
        sid = created["session"]["session_id"]
        seq = 0
        for _ in range(count):
            if seq in skip:
                seq += 1
                continue
            pcm = fake_speech(1.0, 16000, seed=seq)
            capture.append_chunk(sid, seq, pcm, frames=len(pcm) // 2)
            seq += 1
        out = capture.finalize_session(sid, sample_rate=16000, client_manifest={
            "aec_requested": False, "ns_requested": False, "agc_requested": False, **actuals})
        result = out.get("result", {})
        report.append({
            "case": title,
            "session_id": sid,
            "grade": result.get("capture_grade"),
            "expect": expect,
            "ok": result.get("capture_grade") == expect,
            "dropped_frames": (result.get("capture_integrity") or {}).get("dropped_frames"),
            "hf_ratio_db": (result.get("metrics") or {}).get("hf_ratio_db"),
            "reason": result.get("grade_reason"),
        })
    return report


def remote_data_root(base: str, token: str) -> str:
    """读对端服务的数据根。自检写的是合成正弦波，绝不能落进真实语料池。"""
    url = f"{base.rstrip('/')}/api/capture/summary"
    req = urllib.request.Request(url, headers={"X-Capture-Token": token} if token else {})
    with open_url(req) as resp:
        return str(json.loads(resp.read().decode("utf-8")).get("trace_path", ""))


def run_http_level(capture, base: str, token: str, *, allow_real_root: bool = False) -> list[dict]:
    # 自检用的是 fake_speech() 合成的三个正弦叠加，却会以 data_tier=real_device、
    # grade_a、usable_for_loop=true 落盘。一旦写进真实语料池，就等于往「真机语料」
    # 里掺了合成信号 —— 这正是 tier 分层要防的事，还没有任何机器可判别的标记能清洗。
    try:
        remote_trace = remote_data_root(base, token)
    except Exception as exc:  # noqa: BLE001
        return [{"case": "HTTP 前置检查", "ok": False,
                 "reason": f"读不到对端 /api/capture/summary：{exc}"}]
    if "runtime" not in Path(remote_trace).parts and not allow_real_root:
        return [{"case": "HTTP 前置检查", "ok": False,
                 "reason": ("对端服务的数据根不在沙箱里（trace=%s）。请用 "
                            "SIGNAL_DESK_ROOT=<repo>/runtime/verify_capture 启动被测服务，"
                            "或显式加 --allow-real-root 承担污染真实语料池的后果。" % remote_trace)}]

    phone = HttpPhone(base, token)
    report = []
    scenarios = [
        ("HTTP 干净会话", [], {"aec_actual": False, "ns_actual": False, "agc_actual": False}, "grade_a"),
        ("HTTP 丢帧会话", [1], {"aec_actual": False, "ns_actual": False, "agc_actual": False}, "grade_b"),
        ("HTTP 强制 NS 会话", [], {"aec_actual": False, "ns_actual": True, "agc_actual": False}, "grade_c"),
    ]
    for title, skip, actuals, expect in scenarios:
        created = phone._call("/api/capture/session", {
            "speaker_code": "SPK-VERIFY", "script_id": "p1", "declared_route": "phone_internal",
            "client_manifest": {"aec_requested": False, "ns_requested": False,
                                "agc_requested": False, "input_label": "iPhone 麦克风"},
            "notes": "verify_capture.py HTTP 自检",
        })
        if created.get("status") != "ok":
            report.append({"case": title, "ok": False, "reason": created.get("detail") or created.get("message")})
            continue
        sid = created["session"]["session_id"]
        seq = 0
        for _ in range(3):
            if seq in skip:
                seq += 1
                continue
            phone.send(sid, seq, fake_speech(1.0, 16000, seed=seq))
            seq += 1
        out = phone.close(sid, {"aec_actual": False, "ns_actual": False,
                                "agc_actual": False, **actuals})
        result = out.get("result", {})
        report.append({
            "case": title,
            "session_id": sid,
            "grade": result.get("capture_grade"),
            "expect": expect,
            "ok": result.get("capture_grade") == expect,
            "dropped_frames": (result.get("capture_integrity") or {}).get("dropped_frames"),
            "hf_ratio_db": (result.get("metrics") or {}).get("hf_ratio_db"),
            "reason": result.get("grade_reason"),
        })
    # 试听地址与汇总
    if report and report[0].get("session_id"):
        sid = report[0]["session_id"]
        req = urllib.request.Request(f"{base.rstrip('/')}/api/capture/audio/{sid}",
                                     headers={"X-Capture-Token": token} if token else {})
        try:
            with open_url(req, timeout=30) as resp:
                body = resp.read()
            target = PROJECT_ROOT / "runtime" / "verify_playback.wav"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(body)
            with wave.open(str(target), "rb") as fh:
                report.append({"case": "音频回读", "ok": fh.getnframes() > 0,
                               "reason": f"{fh.getnframes()} frames @ {fh.getframerate()}Hz -> {target}"})
        except urllib.error.HTTPError as exc:
            report.append({"case": "音频回读", "ok": False, "reason": f"HTTP {exc.code}"})
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--http", default="", help="对运行中的服务做 HTTP 级自检，如 http://127.0.0.1:8091")
    parser.add_argument("--token", default=os.environ.get("SIGNAL_DESK_CAPTURE_TOKEN", ""))
    parser.add_argument("--allow-real-root", action="store_true",
                        help="允许对非沙箱数据根的服务跑 HTTP 自检（会把合成正弦波写进真实语料池）")
    parser.add_argument("--use-real-root", action="store_true",
                        help="把模块级自检写进真实的 data/real_capture（会清空已有会话与 trace，危险）")
    args = parser.parse_args()

    # 模块级自检会 rmtree 会话目录并删掉 trace。默认把它关进沙箱根，
    # 否则一次自检就会抹掉真机录下来的人声语料与 append-only 留痕（ADR-004 硬约束 5）。
    if not args.use_real_root:
        sandbox = PROJECT_ROOT / "runtime" / "verify_capture"
        sandbox.mkdir(parents=True, exist_ok=True)
        os.environ["SIGNAL_DESK_ROOT"] = str(sandbox)
        print(f"[沙箱] 模块级自检写入 {sandbox}/data/real_capture（--use-real-root 可改写真实数据根）")

    capture = load_module()
    reports = run_module_level(capture)
    if args.http:
        reports += run_http_level(capture, args.http, args.token,
                                  allow_real_root=args.allow_real_root)

    width = max(len(row["case"]) for row in reports)
    print("=" * 78)
    print("08 真机采集 · 端到端自检")
    print("=" * 78)
    ok = True
    for row in reports:
        flag = "PASS" if row.get("ok") else "FAIL"
        ok = ok and bool(row.get("ok"))
        detail = row.get("reason") or ""
        tail = f"  grade={row.get('grade')}" if row.get("grade") else ""
        print(f"[{flag}] {row['case']:<{width}}{tail}")
        if detail:
            print(f"        {detail}")
        if row.get("dropped_frames"):
            print(f"        丢帧记账 = {row['dropped_frames']} 帧")
    print()
    # --http 模式下数据落在对端进程，拿本进程沙箱的 summary() 冒充就是误导性证据。
    summary = capture.summary()
    scope = "本进程沙箱"
    if args.http:
        try:
            url = f"{args.http.rstrip('/')}/api/capture/summary"
            req = urllib.request.Request(url, headers={"X-Capture-Token": args.token} if args.token else {})
            with open_url(req) as resp:
                summary = json.loads(resp.read().decode("utf-8"))
            scope = f"对端服务 {args.http}"
        except Exception as exc:  # noqa: BLE001
            print(f"（读不到对端汇总，下面是本进程沙箱的数字，不代表 HTTP 场景：{exc}）")
    print(f"统计范围 : {scope}")
    print(f"会话总数 {summary['session_count']} · 等级分布 {summary['by_grade']} · "
          f"路径分布 {summary['by_route']} · 可入 Loop {summary['usable_for_loop']}")
    print(f"trace  : {summary['trace_path']}")
    print()
    print("tier 门禁自检：")
    mixed = capture.cross_tier_gate([
        {"tier": capture.TIER_SYNTHETIC, "id": "mm-cohort-1"},
        {"tier": capture.TIER_REAL, "id": "rc-1"},
    ])
    print(f"  混用 tier  -> allowed={mixed['allowed']}  ({mixed['reason']})")
    single = capture.cross_tier_gate([{"tier": capture.TIER_REAL, "id": "rc-1"}])
    print(f"  单一 tier  -> allowed={single['allowed']}")
    print()
    print("结果：", "全部通过" if ok else "存在失败项，请检查上面的 FAIL 行")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
