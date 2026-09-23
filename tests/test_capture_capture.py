# -*- coding: utf-8 -*-
"""08 真机采集 · 模块验收测试（纯标准库，不需要 fastapi / 模型权重）。

  python -m unittest discover -s tests -v
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

TMP_ROOT = Path(tempfile.mkdtemp(prefix="sd-capture-tests-"))
os.environ["SIGNAL_DESK_ROOT"] = str(TMP_ROOT)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "modules" / "08_capture"))

_spec = importlib.util.spec_from_file_location(
    "capture_under_test", PROJECT_ROOT / "modules" / "08_capture" / "capture.py"
)
capture = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(capture)

SR = 16000
CHUNK_FRAMES = SR  # 每段 1 秒


def speech_like_pcm(seconds: float, *, amplitude: int = 6000, sr: int = SR,
                    silence_tail: float = 0.0) -> bytes:
    """造一段有语音特征的 int16：300Hz 基频 + 2.5kHz 泛音 + 包络起伏，可选尾部静音。"""
    import math
    import struct

    total = int(seconds * sr)
    tail = int(silence_tail * sr)
    samples = []
    for i in range(total):
        t = i / sr
        env = 0.55 + 0.45 * math.sin(2 * math.pi * 3.0 * t)
        value = (math.sin(2 * math.pi * 300 * t) * 0.6
                 + math.sin(2 * math.pi * 2500 * t) * 0.25)
        samples.append(int(max(-1.0, min(1.0, value * env)) * amplitude))
    samples.extend([0] * tail)
    return struct.pack(f"<{len(samples)}h", *samples)


def framed(pcm: bytes) -> int:
    return len(pcm) // 2


class CaptureTestCase(unittest.TestCase):
    def setUp(self):
        if capture.SESSIONS_ROOT.exists():
            shutil.rmtree(capture.SESSIONS_ROOT)
        if capture.TRACE_PATH.exists():
            capture.TRACE_PATH.unlink()

    # ------------------------------------------------------------------ #
    def test_happy_path_is_grade_a(self):
        created = capture.create_session(speaker_code="SPK-09", script_id="anchor",
                                        declared_route="phone_internal")
        self.assertEqual(created["status"], "ok")
        sid = created["session"]["session_id"]

        pcm = speech_like_pcm(1.0)
        for seq in range(3):
            out = capture.append_chunk(sid, seq, pcm, frames=framed(pcm))
            self.assertEqual(out["status"], "ok")

        result = capture.finalize_session(sid, sample_rate=SR, channel_count=1, client_manifest={
            "aec_requested": False, "aec_actual": False,
            "ns_requested": False, "ns_actual": False,
            "agc_requested": False, "agc_actual": False,
            "input_label": "iPhone 麦克风",
        })
        self.assertEqual(result["status"], "ok")
        metrics = result["result"]["metrics"]
        self.assertAlmostEqual(metrics["duration_s"], 3.0, places=2)
        self.assertEqual(result["result"]["capture_grade"], "grade_a")
        self.assertTrue(result["result"]["usable_for_loop"])

        wav = capture.wav_path(sid)
        self.assertIsNotNone(wav)
        import wave
        with wave.open(str(wav), "rb") as fh:
            self.assertEqual(fh.getnchannels(), 1)
            self.assertEqual(fh.getframerate(), SR)
            self.assertEqual(fh.getnframes(), 3 * SR)

        with open(capture.TRACE_PATH, newline="", encoding="utf-8") as fh:
            import csv as _csv
            reader = _csv.DictReader(fh)
            self.assertEqual(reader.fieldnames, capture.TRACE_FIELDS)
            rows = list(reader)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["session_id"], sid)
        self.assertEqual(rows[0]["capture_grade"], "grade_a")
        self.assertEqual(rows[0]["usable_for_loop"], "True")

        reloaded = capture.load_session(sid)
        self.assertEqual(reloaded["session"]["status"], "finalized")
        self.assertEqual(reloaded["result"]["raw"]["wav_sha256"],
                         result["result"]["raw"]["wav_sha256"])

    def test_same_input_gives_same_hash(self):
        """同版本重复采集的哈希稳定性（test-retest 的最底层前提）。"""
        pcm = speech_like_pcm(1.0)
        hashes = []
        for _ in range(2):
            sid = capture.create_session()["session"]["session_id"]
            capture.append_chunk(sid, 0, pcm, frames=framed(pcm))
            out = capture.finalize_session(sid, sample_rate=SR)
            hashes.append(out["result"]["raw"]["wav_sha256"])
        self.assertEqual(hashes[0], hashes[1])

    def test_seq_gap_degrades_to_grade_b(self):
        sid = capture.create_session()["session"]["session_id"]
        pcm = speech_like_pcm(1.0)
        capture.append_chunk(sid, 0, pcm, frames=framed(pcm))
        gap = capture.append_chunk(sid, 3, pcm, frames=framed(pcm))
        self.assertEqual(gap["gap_count"], 2)
        out = capture.finalize_session(sid, sample_rate=SR)["result"]
        self.assertEqual(out["capture_grade"], "grade_b")
        self.assertFalse(out["usable_for_loop"])
        self.assertEqual(out["capture_integrity"]["dropped_frames"], 2 * framed(pcm))
        self.assertEqual(out["capture_integrity"]["chunk_gap_count"], 2)

    def test_forced_ns_is_grade_c(self):
        sid = capture.create_session()["session"]["session_id"]
        pcm = speech_like_pcm(2.0)
        capture.append_chunk(sid, 0, pcm, frames=framed(pcm))
        out = capture.finalize_session(sid, sample_rate=SR, client_manifest={
            "ns_requested": False, "ns_actual": True,
        })["result"]
        self.assertEqual(out["capture_grade"], "grade_c")
        self.assertIn("NS", out["grade_reason"])

    def test_unknown_processing_state_is_not_treated_as_clean(self):
        """浏览器没回报 AEC/NS/AGC 状态时，按 grade_b 处理，不能默认干净。"""
        sid = capture.create_session()["session"]["session_id"]
        pcm = speech_like_pcm(2.0)
        capture.append_chunk(sid, 0, pcm, frames=framed(pcm))
        out = capture.finalize_session(sid, sample_rate=SR, client_manifest={
            "input_label": "某浏览器",  # 完全没有 aec/ns/agc 回报
        })["result"]
        self.assertEqual(out["capture_grade"], "grade_b")
        self.assertIn("未知", out["grade_reason"])
        self.assertFalse(out["usable_for_loop"])

    def test_too_short_is_grade_c(self):
        sid = capture.create_session()["session"]["session_id"]
        pcm = speech_like_pcm(0.2)
        capture.append_chunk(sid, 0, pcm, frames=framed(pcm))
        out = capture.finalize_session(sid, sample_rate=SR)["result"]
        self.assertEqual(out["capture_grade"], "grade_c")

    def test_double_finalize_is_rejected(self):
        sid = capture.create_session()["session"]["session_id"]
        pcm = speech_like_pcm(1.0)
        capture.append_chunk(sid, 0, pcm, frames=framed(pcm))
        self.assertEqual(capture.finalize_session(sid, sample_rate=SR)["status"], "ok")
        second = capture.finalize_session(sid, sample_rate=SR)
        self.assertEqual(second["status"], "error")
        self.assertIn("不可重写", second["message"])

    def test_append_after_finalize_is_rejected(self):
        sid = capture.create_session()["session"]["session_id"]
        pcm = speech_like_pcm(1.0)
        capture.append_chunk(sid, 0, pcm, frames=framed(pcm))
        capture.finalize_session(sid, sample_rate=SR)
        out = capture.append_chunk(sid, 1, pcm, frames=framed(pcm))
        self.assertEqual(out["status"], "error")

    def test_replayed_chunk_is_idempotent(self):
        sid = capture.create_session()["session"]["session_id"]
        pcm = speech_like_pcm(1.0)
        capture.append_chunk(sid, 0, pcm, frames=framed(pcm))
        again = capture.append_chunk(sid, 0, pcm, frames=framed(pcm))
        self.assertEqual(again["status"], "replayed")
        self.assertEqual(again["state"]["received_chunks"], 1)

    # ------------------------------------------------------------------ #
    def test_path_traversal_and_bad_ids_are_rejected(self):
        for bad in ["../../etc/passwd", "rc-20260101-000000-aaaaaa/../../x", "", None]:
            with self.assertRaises(ValueError):
                capture.load_session(bad)
        with self.assertRaises(ValueError):
            capture.append_chunk("../x", 0, b"\x00\x00")

    def test_garbage_chunks_are_rejected(self):
        sid = capture.create_session()["session"]["session_id"]
        self.assertEqual(capture.append_chunk(sid, 0, b"")["status"], "error")
        self.assertEqual(capture.append_chunk(sid, 0, b"\x00")["status"], "error")
        self.assertEqual(capture.append_chunk(sid, -1, b"\x00\x00")["status"], "error")
        self.assertEqual(capture.append_chunk(sid, "x", b"\x00\x00")["status"], "error")
        self.assertEqual(capture.finalize_session(sid)["status"], "error")

    def test_invalid_route_and_script_are_rejected(self):
        self.assertEqual(capture.create_session(declared_route="magic")["status"], "error")
        self.assertEqual(capture.create_session(script_id="nope")["status"], "error")

    def test_trace_is_append_only(self):
        pcm = speech_like_pcm(1.0)
        for _ in range(2):
            sid = capture.create_session()["session"]["session_id"]
            capture.append_chunk(sid, 0, pcm, frames=framed(pcm))
            capture.finalize_session(sid, sample_rate=SR)
        with open(capture.TRACE_PATH, newline="", encoding="utf-8") as fh:
            lines = [line for line in fh.read().splitlines() if line.strip()]
        self.assertEqual(len(lines), 3)  # 1 表头 + 2 行
        self.assertEqual(lines[0].split(","), capture.TRACE_FIELDS)

    # ------------------------------------------------------------------ #
    def test_cross_tier_gate(self):
        mixed = capture.cross_tier_gate([
            {"tier": capture.TIER_SYNTHETIC, "id": "mm-1"},
            {"tier": capture.TIER_REAL, "id": "rc-1"},
        ])
        self.assertFalse(mixed["allowed"])
        self.assertIn("生态效度", mixed["reason"])

        single = capture.cross_tier_gate([{"tier": capture.TIER_SYNTHETIC, "id": "mm-1"}])
        self.assertTrue(single["allowed"])
        self.assertFalse(capture.cross_tier_gate([])["allowed"])

    def test_validity_compare(self):
        agree = capture.validity_compare({"pq": 0.31, "ce": 0.04}, {"pq": 0.12, "ce": 0.02})
        self.assertTrue(agree["status"] == "ok" and agree["agree"])

        disagree = capture.validity_compare({"pq": 0.31}, {"pq": -0.18})
        self.assertFalse(disagree["agree"])
        self.assertEqual(disagree["agree_ratio"], 0.0)

        self.assertEqual(capture.validity_compare({"pq": None}, {"ce": 1})["status"], "no_shared_metric")

    def test_analyze_pcm_edges(self):
        silent = TMP_ROOT / "silent.pcm"
        silent.write_bytes(b"\x00\x00" * SR)
        metrics = capture.analyze_pcm(silent, sample_rate=SR)
        self.assertEqual(metrics["duration_s"], 1.0)
        self.assertIsNone(metrics["rms_dbfs"])
        self.assertEqual(metrics["clip_ratio"], 0.0)

        loud = TMP_ROOT / "loud.pcm"
        loud.write_bytes(b"\xff\x7f" * SR)
        clipped = capture.analyze_pcm(loud, sample_rate=SR)
        self.assertEqual(clipped["clip_ratio"], 1.0)
        # assertTrue(x, "grade_b") 的第二参是失败消息不是期望值，写成那样这条断言恒过。
        # 另外必须显式给三项 _actual=False，否则会因「状态未知」走到 grade_b，
        # 测不出 clip_ratio 那条规则本身。
        grade, reason = capture.grade_of({
            "clip_ratio": 1.0, "duration_s": 3.0, "chunk_gap_count": 0, "dropped_frames": 0,
            "aec_actual": False, "ns_actual": False, "agc_actual": False,
        })
        self.assertEqual(grade, "grade_b")
        self.assertIn("削波", reason)

        empty = TMP_ROOT / "empty.pcm"
        empty.write_bytes(b"")
        self.assertIsNone(capture.analyze_pcm(empty, sample_rate=SR)["rms_dbfs"])

    def test_bandwidth_fingerprint_separates_narrowband(self):
        """窄带（截掉 4kHz 以上）的 hf_ratio_db 应显著低于宽带，用于识别蓝牙 HFP 路径。"""
        import math
        import struct
        sr = 16000
        wide = []
        narrow = []
        for i in range(sr):
            t = i / sr
            wide.append(int(sum(math.sin(2 * math.pi * f * t) for f in [200, 900, 2500, 5200, 6800]) / 5 * 6000))
            narrow.append(int(sum(math.sin(2 * math.pi * f * t) for f in [200, 900, 2500]) / 3 * 6000))
        wide_p = TMP_ROOT / "wide.pcm"
        narrow_p = TMP_ROOT / "narrow.pcm"
        wide_p.write_bytes(struct.pack(f"<{len(wide)}h", *wide))
        narrow_p.write_bytes(struct.pack(f"<{len(narrow)}h", *narrow))
        w = capture.analyze_pcm(wide_p, sample_rate=sr)["hf_ratio_db"]
        n = capture.analyze_pcm(narrow_p, sample_rate=sr)["hf_ratio_db"]
        self.assertLess(n, w - 10)

    # ------------------------------------------------------------------ #
    def test_summary_and_scripts(self):
        pcm = speech_like_pcm(1.0)
        sid = capture.create_session(declared_route="bluetooth_hfp")["session"]["session_id"]
        capture.append_chunk(sid, 0, pcm, frames=framed(pcm))
        capture.finalize_session(sid, sample_rate=SR)
        summary = capture.summary()
        self.assertEqual(summary["tier"], capture.TIER_REAL)
        self.assertEqual(summary["session_count"], 1)
        self.assertEqual(summary["by_route"]["bluetooth_hfp"], 1)
        scripts = capture.list_scripts()
        self.assertEqual(scripts["scripts"][0]["id"], "anchor")
        self.assertIn("bluetooth_hfp", scripts["routes"])

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(TMP_ROOT, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
