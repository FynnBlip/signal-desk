# -*- coding: utf-8 -*-
"""Fast contract tests; no model inference and no external API calls."""

import csv
import base64
import concurrent.futures
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pydantic import ValidationError
from server import contracts
from server import main as server_main

ROOT = Path(__file__).resolve().parents[1]


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


evaluate = load_module("sd_evaluate_test", ROOT / "modules" / "06_evaluate" / "evaluate.py")
loop = load_module("sd_loop_test", ROOT / "modules" / "07_loop" / "loop.py")
denoise = load_module("sd_denoise_test", ROOT / "modules" / "05_denoise" / "denoise.py")
run_store = load_module("sd_run_store_test", ROOT / "server" / "run_store.py")
registry = load_module("sd_registry_test", ROOT / "server" / "provider_registry.py")
tts = load_module("sd_tts_test", ROOT / "modules" / "03_tts" / "tts.py")


class EvaluateSemanticsTests(unittest.TestCase):
    def test_missing_score_input_blocks_the_batch(self):
        with tempfile.TemporaryDirectory() as temp:
            missing = Path(temp) / "missing.wav"
            with self.assertRaisesRegex(FileNotFoundError, "评测输入不完整"):
                evaluate.score_files(object(), [missing])

    def test_empty_levels_are_ungraded_instead_of_crashing(self):
        self.assertEqual(evaluate.get_level(5.0, [])["label"], "未分级")

    def test_stats_disclose_metric_scope_and_source_breakdown(self):
        stats = evaluate.build_stats([
            {"filename": "clean.wav", "source": "干净", "pq": 8.0},
            {"filename": "degraded.wav", "source": "退化", "pq": 4.0},
        ])
        self.assertEqual(stats["metric"], "pq")
        self.assertEqual(stats["scope"], "all_sources")
        self.assertEqual(stats["by_source"]["干净"]["avg"], 8.0)
        self.assertEqual(stats["by_source"]["退化"]["avg"], 4.0)

    def test_default_has_no_overall_or_level(self):
        row = evaluate._annotate({"pq": 8.1, "pc": 7.2, "ce": 6.4, "cu": 5.9}, evaluate.DEFAULT_SETTINGS)
        self.assertIsNone(row["overall"])
        self.assertEqual(row["level"], "未分级")

    def test_old_average_settings_migrate_to_disabled(self):
        with tempfile.TemporaryDirectory() as temp:
            settings_path = Path(temp) / "settings.json"
            settings_path.write_text(json.dumps({"overall_mode": "average"}), encoding="utf-8")
            with patch.object(evaluate, "SETTINGS_FILE", settings_path):
                settings = evaluate.load_settings()
        self.assertEqual(settings["schema_version"], 3)
        self.assertEqual(settings["overall_mode"], "disabled")

    def test_old_level_defaults_migrate_to_ten_point_scale(self):
        with tempfile.TemporaryDirectory() as temp:
            settings_path = Path(temp) / "settings.json"
            settings_path.write_text(json.dumps({
                "schema_version": 2,
                "levels": [
                    {"min": 4, "label": "优秀"}, {"min": 3, "label": "良好"},
                    {"min": 2, "label": "一般"}, {"min": 0, "label": "较差"},
                ],
            }), encoding="utf-8")
            with patch.object(evaluate, "SETTINGS_FILE", settings_path):
                settings = evaluate.load_settings()
        self.assertEqual([item["min"] for item in settings["levels"]], [8.0, 6.0, 4.0, 0.0])


class LoopGateTests(unittest.TestCase):
    def test_history_archive_keeps_recent_current_month_and_writes_old_rounds(self):
        now = __import__("datetime").datetime(2026, 9, 7, 12, 0, 0)
        rounds = [
            {"round": 1, "time": "2026-08-24 23:20:37", "baseline": "v1", "candidate": "v2"},
            {"round": 2, "time": "2026-09-07 00:49:07", "baseline": "v1", "candidate": "v3"},
        ]
        with tempfile.TemporaryDirectory() as temp:
            archive_dir = Path(temp) / "archive"
            archive_file = archive_dir / "loop_history.json"
            with patch.object(loop, "HISTORY_ARCHIVE_DIR", archive_dir), patch.object(loop, "HISTORY_ARCHIVE_FILE", archive_file):
                meta = loop.prepare_history_archive({"rounds": rounds}, now=now)
                self.assertEqual(meta["visible_rounds"], [2])
                self.assertEqual(meta["archived_count"], 1)
                self.assertEqual(meta["newly_archived"], 1)
                self.assertTrue(archive_file.is_file())
                self.assertEqual(loop.load_history_archive()["rounds"][0]["round"], 1)

    def test_extreme_retreat_is_conditional_not_promoted(self):
        report = loop.judge(
            [5.0, 5.0, 5.0, 5.0, 5.0, 5.0],
            [5.2, 5.2, 5.2, 5.2, 5.2, 4.5],
            [True, True, True, True, True, False],
        )
        self.assertFalse(report["promoted"])
        self.assertTrue(report["conditional"])
        self.assertEqual(report["gate_status"], "conditional")
        self.assertEqual(loop.allowed_actions(report, ["v1", "v2"])["actions"], ["accept_conditional"])

    def test_public_blind_pairs_hide_identity_and_keep_server_assignment(self):
        rows = [{
            "stem": "sample", "noise_label": "办公室", "snr_db": 15,
            "baseline_model": "base-model", "baseline_file": "base.wav", "baseline_path": "D:/data/base.wav",
            "candidate_model": "cand-model", "candidate_file": "cand.wav", "candidate_path": "D:/data/cand.wav",
        }]
        public, assignments = loop.build_blind_pairs("run-1", rows, include_assignments=True)
        encoded = json.dumps(public, ensure_ascii=False)
        self.assertNotIn("baseline", encoded)
        self.assertNotIn("candidate", encoded)
        self.assertNotIn("base.wav", encoded)
        self.assertNotIn("cand.wav", encoded)
        self.assertEqual({assignments["sample"]["A"]["role"], assignments["sample"]["B"]["role"]}, {"baseline", "candidate"})

    def test_corrupt_status_is_never_silently_replaced(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "loop_status.json"
            path.write_text("{broken", encoding="utf-8")
            with patch.object(loop, "LOOP_STATUS", path):
                with self.assertRaisesRegex(RuntimeError, "已阻止"):
                    loop.load_status()
            self.assertEqual(path.read_text(encoding="utf-8"), "{broken")

    def test_cache_rejects_audio_rewritten_during_scoring(self):
        with tempfile.TemporaryDirectory() as temp:
            audio = Path(temp) / "sample.wav"
            cache = Path(temp) / "scores.json"
            audio.write_bytes(b"before")

            def rewrite_while_scoring(_predictor, paths, **_kwargs):
                audio.write_bytes(b"after-a-different-size")
                return {str(Path(paths[0])): {"pq": 5.0, "pc": 5.0, "ce": 5.0, "cu": 5.0}}

            with patch.object(loop.evaluate, "load_predictor", return_value=object()), \
                 patch.object(loop.evaluate, "score_files", side_effect=rewrite_while_scoring):
                with self.assertRaisesRegex(RuntimeError, "评分期间音频被改写"):
                    loop._score_files_cached([audio], cache)
            self.assertFalse(cache.exists())

    def test_invalid_snr_blocks_round_instead_of_becoming_regular(self):
        sample = {
            "scene_id": "BROKEN", "noise_label": "坏数据", "snr_db": "unknown",
            "clean": "clean.wav", "degraded": "degraded.wav", "stem": "broken",
        }
        baseline = loop.get_version("v1")
        candidate = loop.get_version("v2")
        paths = [
            sample["clean"], sample["degraded"],
            str(loop._denoised_path(sample, baseline)), str(loop._denoised_path(sample, candidate)),
        ]
        scores = {path: {"pq": 5.0, "pc": 5.0, "ce": 5.0, "cu": 5.0} for path in paths}
        with patch.object(loop, "collect_matrix", return_value=[sample]), \
             patch.object(loop, "ensure_denoised"), \
             patch.object(loop.evaluate, "load_predictor", return_value=object()), \
             patch.object(loop.evaluate, "score_files", return_value=scores):
            with self.assertRaisesRegex(RuntimeError, "SNR 无效"):
                loop.run_round({"baseline": "v1", "candidate": "v2", "matrix": {"source": "legacy"}})

    def test_same_filename_in_different_cohorts_does_not_merge(self):
        common = {
            "degraded_file": "same.wav", "clean_file": "voice.wav", "voice_id": "voice-1",
            "scene_id": "NPARK", "noise_label": "公园", "snr_db": 25, "regular": True,
        }
        state = {"rounds": [
            {"baseline": "v1", "candidate": "v2", "rows": [{**common, "cohort_id": "A", "baseline_pq": 5.0, "candidate_pq": 5.1}]},
            {"baseline": "v2", "candidate": "v3", "rows": [{**common, "cohort_id": "A", "baseline_pq": 5.1, "candidate_pq": 5.2}]},
            {"baseline": "v2", "candidate": "v4", "rows": [{**common, "cohort_id": "A", "baseline_pq": 5.1, "candidate_pq": 5.3}]},
            {"baseline": "v1", "candidate": "v2", "rows": [{**common, "cohort_id": "B", "baseline_pq": 4.0, "candidate_pq": 4.1}]},
        ]}
        summary = loop.build_version_summary(state)
        self.assertEqual(summary["status"], "insufficient")
        self.assertEqual(summary["shared_samples"], 1)

    def test_golden_context_fingerprint_is_stable_and_scene_sensitive(self):
        cohort = {
            "cohort_id": "fixed-26",
            "cohort_dir": "D:/fixed-26",
            "voices": [{
                "file": f"{index:03d}__voice.wav", "path": f"D:/fixed-26/{index}.wav",
                "voice_id": f"voice-{index}", "voice_name": f"Voice {index}",
                "cluster_id": index % 4 + 1, "sha256": f"hash-{index}",
            } for index in range(26)],
        }
        with tempfile.TemporaryDirectory() as temp, \
             patch.object(loop, "_load_active_cohort", return_value=cohort), \
             patch.object(loop, "BENCHMARK_ROOT", Path(temp)):
            first = loop._golden_benchmark_context({"matrix": {"noise_scenes": ["NPARK"]}})
            again = loop._golden_benchmark_context({"matrix": {"noise_scenes": ["NPARK"]}})
            changed = loop._golden_benchmark_context({"matrix": {"noise_scenes": ["OFFICE"]}})
        self.assertEqual(first["fingerprint"], again["fingerprint"])
        self.assertNotEqual(first["fingerprint"], changed["fingerprint"])

    def test_golden_matrix_reuses_existing_audio(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            voice_file = root / "voice.wav"
            voice_file.write_bytes(b"wav")
            voice = {
                "file": voice_file.name, "path": str(voice_file), "voice_id": "voice-1",
                "voice_name": "Voice 1", "cluster_id": 1, "sha256": "hash",
            }
            scene = {"id": "NPARK", "label": "安静 · 公园", "snr_db": 25}
            context = {
                "cohort_id": "fixed-26", "voices": [voice], "scenes": [scene],
                "fingerprint": "stable", "root": root / "benchmark", "payload": {},
            }
            target = context["root"] / "matrix" / loop._golden_matrix_filename(voice, scene)
            target.parent.mkdir(parents=True)
            target.write_bytes(b"cached")
            with patch.object(loop, "_golden_benchmark_context", return_value=context), \
                 patch.object(loop.channel, "benchmark_noise_blockers", return_value=[]), \
                 patch.object(loop.channel, "run") as channel_run:
                samples, _ = loop.prepare_golden_matrix({"matrix": {"source": "golden"}})
            channel_run.assert_not_called()
            self.assertEqual(samples[0]["cluster_id"], 1)
            self.assertEqual(Path(samples[0]["degraded"]), target)

    def _fixed_cohort(self, root, count=26):
        root = Path(root)
        root.mkdir(parents=True, exist_ok=True)
        voices = []
        for index in range(count):
            audio = root / f"{index:03d}__voice.wav"
            audio.write_bytes(f"voice-{index}".encode())
            voices.append({
                "file": audio.name, "path": str(audio), "voice_id": f"voice-{index}",
                "voice_name": f"Voice {index}", "cluster_id": index % 4 + 1, "sha256": f"hash-{index}",
            })
        return {
            "cohort_id": "fixed-26",
            "cohort_dir": str(root),
            "voices": voices,
        }

    def _write_scene_noise(self, noise_root, scene_id, content, name="clip.wav"):
        folder = Path(noise_root) / "demand" / scene_id
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / name
        path.write_bytes(content)
        return path

    def test_same_noise_content_keeps_fingerprint_and_reuses_matrix(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            noise_root = root / "noise"
            self._write_scene_noise(noise_root, "NPARK", b"noise-a")
            cohort = self._fixed_cohort(root / "voices", count=1)
            config = {"matrix": {"noise_scenes": ["NPARK"]}}
            with patch.object(loop, "_load_active_cohort", return_value=cohort), \
                 patch.object(loop, "BENCHMARK_ROOT", root / "benchmarks"), \
                 patch.object(loop.channel, "NOISE_DIR", noise_root), \
                 patch.object(loop.channel, "benchmark_noise_blockers", return_value=[]):
                first = loop._golden_benchmark_context(config)
                again = loop._golden_benchmark_context(config)
                self.assertEqual(first["fingerprint"], again["fingerprint"])
                self.assertEqual(first["payload"]["schema_version"], 2)
                target = first["root"] / "matrix" / loop._golden_matrix_filename(cohort["voices"][0], first["scenes"][0])
                target.parent.mkdir(parents=True)
                target.write_bytes(b"cached-matrix")
                with patch.object(loop.channel, "run") as channel_run:
                    samples, context = loop.prepare_golden_matrix(config)
                channel_run.assert_not_called()
                self.assertEqual(context["fingerprint"], first["fingerprint"])
                self.assertEqual(Path(samples[0]["degraded"]).read_bytes(), b"cached-matrix")

    def test_renamed_same_noise_filename_with_new_bytes_opens_new_namespace(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            noise_root = root / "noise"
            clip = self._write_scene_noise(noise_root, "NPARK", b"noise-a")
            cohort = self._fixed_cohort(root / "voices", count=1)
            config = {"matrix": {"noise_scenes": ["NPARK"]}}
            with patch.object(loop, "_load_active_cohort", return_value=cohort), \
                 patch.object(loop, "BENCHMARK_ROOT", root / "benchmarks"), \
                 patch.object(loop.channel, "NOISE_DIR", noise_root):
                before = loop._golden_benchmark_context(config)
                old_root = before["root"]
                old_root.mkdir(parents=True)
                (old_root / "tournament_result.json").write_text("{}", encoding="utf-8")
                clip.write_bytes(b"noise-b-different")
                after = loop._golden_benchmark_context(config)
                self.assertNotEqual(before["fingerprint"], after["fingerprint"])
                self.assertTrue((old_root / "tournament_result.json").is_file())
                self.assertNotEqual(old_root, after["root"])

    def test_dut_weight_or_impl_change_does_not_reuse_denoised(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            degraded = root / "in.wav"
            degraded.write_bytes(b"degraded")
            sample = {"stem": "sample", "degraded": str(degraded), "denoised_root": str(root / "out")}
            version = {"id": "gtcrn", "model": "gtcrn", "strength": 1.0}
            model_dir = root / "models"
            model_dir.mkdir()
            weights = model_dir / "gtcrn_simple.onnx"
            weights.write_bytes(b"weights-a")
            created = []

            def fake_process(_input, output, _spec):
                Path(output).write_bytes(f"out-{len(created)}".encode())
                created.append(Path(output))
                return {"status": "ok"}

            with patch.object(loop.denoise, "MODEL_DIR", model_dir), \
                 patch.object(loop.denoise, "process", side_effect=fake_process):
                first = loop.ensure_denoised([sample], version)
                first_path = loop._denoised_path(sample, version)
                self.assertEqual(first["created"], 1)
                second = loop.ensure_denoised([sample], version)
                self.assertEqual(second["created"], 0)
                self.assertEqual(first_path.read_bytes(), b"out-0")

                weights.write_bytes(b"weights-b")
                third = loop.ensure_denoised([sample], version)
                second_path = loop._denoised_path(sample, version)
                self.assertEqual(third["created"], 1)
                self.assertNotEqual(first_path, second_path)
                self.assertTrue(first_path.is_file())
                self.assertEqual(second_path.read_bytes(), b"out-1")

                with patch.object(loop, "DENOISE_IMPL_VERSION", "05-process-v2"):
                    fourth = loop.ensure_denoised([sample], version)
                    third_path = loop._denoised_path(sample, version)
                self.assertEqual(fourth["created"], 1)
                self.assertNotEqual(second_path, third_path)
                self.assertTrue(second_path.is_file())

    def test_score_cache_hits_fake_evaluator_and_misses_after_checkpoint_swap(self):
        with tempfile.TemporaryDirectory() as temp:
            audio = Path(temp) / "sample.wav"
            cache = Path(temp) / "scores.json"
            ckpt = Path(temp) / "ckpt.pt"
            audio.write_bytes(b"audio-bytes")
            ckpt.write_bytes(b"A" * 64)
            calls = []

            def fake_score(_predictor, paths, **_kwargs):
                calls.append([str(Path(path)) for path in paths])
                return {str(Path(path)): {"pq": 4.2, "pc": 1.0, "ce": 1.0, "cu": 1.0} for path in paths}

            with patch.object(loop.evaluate, "get_checkpoint", return_value=str(ckpt)), \
                 patch.object(loop.evaluate, "load_predictor", return_value=object()), \
                 patch.object(loop.evaluate, "score_files", side_effect=fake_score):
                first, missed = loop._score_files_cached([audio], cache)
                self.assertEqual(missed, 1)
                self.assertEqual(first[str(audio)]["pq"], 4.2)
                again, missed_again = loop._score_files_cached([audio], cache)
                self.assertEqual(missed_again, 0)
                self.assertEqual(again[str(audio)]["pq"], 4.2)
                self.assertEqual(len(calls), 1)

                stat = ckpt.stat()
                ckpt.write_bytes(b"B" * 64)
                os.utime(ckpt, ns=(stat.st_atime_ns, stat.st_mtime_ns))
                swapped, missed_swap = loop._score_files_cached([audio], cache)
                self.assertEqual(missed_swap, 1)
                self.assertEqual(swapped[str(audio)]["pq"], 4.2)
                self.assertEqual(len(calls), 2)
                stored = json.loads(cache.read_text(encoding="utf-8"))
                self.assertEqual(len(stored[str(audio)]["versions"]), 2)

    def test_fresh_workspace_requires_explicit_baseline(self):
        with tempfile.TemporaryDirectory() as temp:
            original = loop.LOOP_STATUS
            try:
                loop.LOOP_STATUS = Path(temp) / "loop_status.json"
                state = loop.load_status()
            finally:
                loop.LOOP_STATUS = original
        self.assertIsNone(state["baseline"])
        self.assertIsNone(state["candidate"])
        self.assertFalse(state["benchmark"]["ready"])
        self.assertEqual(state["benchmark"]["id"], "golden-v1")

    def test_existing_promoted_baseline_gets_traceable_origin(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "loop_status.json"
            path.write_text(json.dumps({
                "baseline": "v2",
                "candidate": "v3",
                "rounds": [{
                    "round": 1,
                    "time": "2026-08-24 12:00:00",
                    "baseline": "v1",
                    "candidate": "v2",
                    "decision": {"action": "accept"},
                }],
            }), encoding="utf-8")
            original = loop.LOOP_STATUS
            try:
                loop.LOOP_STATUS = path
                state = loop.load_status()
            finally:
                loop.LOOP_STATUS = original
        self.assertEqual(state["baseline_origin"]["type"], "promoted")
        self.assertEqual(state["baseline_origin"]["from_version"], "v1")
        self.assertIn("第 1 轮", state["baseline_origin"]["label"])

    def test_new_experiment_clears_draft_but_keeps_history(self):
        state = {
            "baseline": "v2", "candidate": "v4", "status": "no_solution",
            "last_judge": {"verdict": "回滚"}, "last_decision": {"action": "stop"},
            "conclusion": "旧结论", "rounds": [{"round": 1}], "changelog": ["旧记录"],
            "evaluated_versions": ["v1", "v2", "v4"],
        }
        fresh = loop.start_new_experiment(state)
        self.assertIsNone(fresh["baseline"])
        self.assertIsNone(fresh["candidate"])
        self.assertEqual(fresh["status"], "idle")
        self.assertEqual(fresh["rounds"], state["rounds"])
        self.assertEqual(fresh["changelog"], state["changelog"])
        self.assertEqual(fresh["evaluated_versions"], [])
        self.assertTrue(fresh["experiment_id"].startswith("exp-"))

    def test_version_summary_uses_only_shared_samples_and_recommends_safest(self):
        rows = []
        for name, regular in (("regular.wav", True), ("extreme.wav", False)):
            rows.append({
                "degraded_file": name, "clean_file": "未知音色_20260824_120000.wav",
                "noise_label": name, "snr_db": 10 if regular else -10, "regular": regular,
                "baseline_pq": 5.0, "candidate_pq": 5.2 if regular else 6.0,
            })
        state = {"rounds": [
            {"baseline": "v1", "candidate": "v2", "rows": rows},
            {"baseline": "v2", "candidate": "v3", "rows": [
                {**row, "baseline_pq": row["candidate_pq"], "candidate_pq": 5.1}
                for row in rows
            ]},
            {"baseline": "v2", "candidate": "v4", "rows": [
                {**row, "baseline_pq": row["candidate_pq"], "candidate_pq": 4.9}
                for row in rows
            ]},
        ]}
        summary = loop.build_version_summary(state)
        self.assertEqual(summary["shared_samples"], 2)
        self.assertEqual(summary["recommendation"]["version"], "v2")
        self.assertEqual([item["version"] for item in summary["versions"]], ["v1", "v2", "v3", "v4"])

    def test_version_summary_uses_locked_scene_weights(self):
        scene_rows = []
        for index, scene_id in enumerate(loop.SCENE_WEIGHTS):
            scene_rows.append({
                "cohort_id": "cohort", "voice_id": "voice-1", "voice_name": "音色一",
                "cluster_id": 1, "scene_id": scene_id, "noise_label": scene_id,
                "snr_db": 20-index*5, "degraded_file": f"{scene_id}.wav",
                "stem": scene_id, "regular": True,
            })
        rounds = []
        deltas = {"v2": 0.2, "v3": 0.1, "v4": -0.1}
        for candidate, delta in deltas.items():
            rounds.append({
                "baseline": "v1", "candidate": candidate,
                "rows": [{**row, "baseline_pq": 5.0, "candidate_pq": 5.0+delta} for row in scene_rows],
            })
        summary = loop.build_version_summary({"baseline": "v1", "rounds": rounds})
        weights = {item["scene_id"]: item["effective_weight"] for item in summary["scene_weights"]}
        self.assertEqual(weights, loop.SCENE_WEIGHTS)
        self.assertAlmostEqual(next(item["delta"] for item in summary["weighted_versions"] if item["version"] == "v2"), 0.2)
        self.assertEqual(len(summary["scene_cluster_charts"]), 6)

    def test_version_summary_renormalizes_disabled_scenes_and_naturally_weights_clusters(self):
        cluster_sizes = {1: 10, 2: 7, 3: 5, 4: 4}
        base_rows = []
        voice_number = 0
        for cluster, count in cluster_sizes.items():
            for _ in range(count):
                voice_number += 1
                for scene_id in ("NPARK", "PCAFETER"):
                    base_rows.append({
                        "cohort_id": "cohort", "voice_id": f"voice-{voice_number}",
                        "voice_name": f"音色{voice_number}", "cluster_id": cluster,
                        "scene_id": scene_id, "noise_label": scene_id, "snr_db": 20,
                        "degraded_file": f"voice-{voice_number}-{scene_id}.wav",
                        "stem": f"voice-{voice_number}-{scene_id}", "regular": True,
                    })
        rounds = []
        for candidate, delta in (("v2", 0.2), ("v3", 0.1), ("v4", -0.1)):
            rows = []
            for row in base_rows:
                gain = 1.0 if candidate == "v2" and row["scene_id"] == "NPARK" else delta
                rows.append({**row, "baseline_pq": 5.0, "candidate_pq": 5.0+gain})
            rounds.append({"baseline": "v1", "candidate": candidate, "rows": rows})
        summary = loop.build_version_summary({"baseline": "v1", "rounds": rounds})
        weights = {item["scene_id"]: item["effective_weight"] for item in summary["scene_weights"]}
        self.assertAlmostEqual(weights["NPARK"], 0.25 / 0.45, places=6)
        self.assertAlmostEqual(weights["PCAFETER"], 0.20 / 0.45, places=6)
        self.assertEqual(
            [(item["cluster"], item["voice_count"]) for item in summary["cluster_weights"]],
            [("C1", 10), ("C2", 7), ("C3", 5), ("C4", 4)],
        )
        self.assertAlmostEqual(sum(item["weight"] for item in summary["cluster_weights"]), 1.0, places=5)

    def test_mean_gain_cannot_hide_majority_retreat(self):
        baseline = [5.0] * 5
        candidate = [6.5, 5.8, 4.9, 4.9, 4.9]  # mean rises, 3/5 retreat
        report = loop.judge(baseline, candidate, [True] * 5)
        self.assertGreater(report["regular_delta"], 0.05)
        self.assertFalse(report["promoted"])
        self.assertIn("常规场景回退比例", report["gate_reasons"])

    def test_clean_gain_passes_all_gates(self):
        report = loop.judge(
            [4.8, 4.9, 5.0, 5.1, 5.2],
            [5.0, 5.1, 5.2, 5.3, 5.4],
            [True] * 5,
        )
        self.assertTrue(report["promoted"])
        self.assertEqual(loop.allowed_actions(report, ["v1", "v2"])["actions"], ["accept"])

    def test_confirmed_round_report_keeps_scene_evidence_table(self):
        markdown = loop.build_markdown({
            "baseline": "v2",
            "candidate": "v3",
            "status": "running",
            "rounds": [{
                "round": 1,
                "baseline": "v1",
                "candidate": "v2",
                "judge": {"verdict": "整体晋级"},
                "decision": {"action": "accept", "hypothesis": "测试"},
                "rows": [{
                    "noise_label": "办公室", "snr_db": 15,
                    "baseline_pq": 5.2, "candidate_pq": 5.4,
                }],
            }],
        })
        self.assertIn("| 场景 | 音色 | 样本 ID | SNR | 当前版本 PQ | 待验证版本 PQ | 新版−当前 ΔPQ | 判读 |", markdown)
        self.assertIn("| 办公室 | 音色未记录 | 样本 ID 未记录 | 15 dB | 5.2 | 5.4 | +0.2 | 上行 |", markdown)


class TraceAndStoreTests(unittest.TestCase):
    def test_file_hash_changes_after_same_path_is_rewritten(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "artifact.bin"
            path.write_bytes(b"first")
            first = denoise._sha256_file(path)
            path.write_bytes(b"other")
            self.assertNotEqual(first, denoise._sha256_file(path))

    def test_ensure_denoised_publishes_atomically(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            degraded = root / "in.wav"
            degraded.write_bytes(b"input")
            sample = {"stem": "sample", "degraded": str(degraded), "denoised_root": str(root / "out")}
            version = loop.get_version("v1")

            def fake_process(_input, output, _spec):
                Path(output).write_bytes(b"complete")
                self.assertNotEqual(Path(output), loop._denoised_path(sample, version))
                return {"status": "ok"}

            with patch.object(loop.denoise, "process", side_effect=fake_process):
                loop.ensure_denoised([sample], version)
            target = loop._denoised_path(sample, version)
            self.assertEqual(target.read_bytes(), b"complete")
            self.assertTrue(loop._denoise_identity_sidecar(target).is_file())
            self.assertEqual(list(target.parent.glob("*.tmp.wav")), [])

    def test_denoise_trace_uses_fixed_schema(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(denoise, "DENOISED_DIR", Path(temp)):
                path = denoise._append_trace({"schema_version": 2, "run_id": "test-run", "provider_id": "noisereduce"})
                with path.open(encoding="utf-8-sig", newline="") as handle:
                    reader = csv.DictReader(handle)
                    row = next(reader)
                    self.assertEqual(reader.fieldnames, denoise.TRACE_FIELDS)
                    self.assertEqual(row["run_id"], "test-run")

    def test_run_store_survives_new_instance(self):
        with tempfile.TemporaryDirectory() as temp:
            store = run_store.RunStore(Path(temp))
            record = store.create("evaluate", request={"mode": "directory"})
            store.update("evaluate", record["run_id"], state="done", result={"n": 2})
            restored = run_store.RunStore(Path(temp)).latest("evaluate", states=("done",))
            self.assertEqual(restored["result"]["n"], 2)


class ProviderRegistryTests(unittest.TestCase):
    def test_seven_slots_and_provider_contract(self):
        items = registry.ProviderRegistry(ROOT / "modules").modules()
        self.assertEqual(len(items), 7)
        self.assertTrue(all(item.get("providers") for item in items))


class HttpContractTests(unittest.TestCase):
    def test_single_job_claim_is_atomic(self):
        job = {"state": "idle"}
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            claimed = list(pool.map(lambda _: server_main._claim_single_job(job, "test"), range(16)))
        self.assertEqual(sum(claimed), 1)
        self.assertEqual(job["state"], "running")

    def test_public_loop_job_cannot_reveal_blind_assignment_paths(self):
        original = dict(server_main.LOOP_JOB)
        try:
            server_main.LOOP_JOB.clear()
            server_main.LOOP_JOB.update({
                "state": "done",
                "result": {"rows": [{
                    "stem": "opaque", "baseline_model": "v1", "candidate_model": "v2",
                    "baseline_file": "a.wav", "candidate_file": "b.wav",
                    "baseline_path": "D:/a.wav", "candidate_path": "D:/b.wav",
                    "baseline_pq": 5.0, "candidate_pq": 5.2,
                }]},
            })
            row = server_main.loop_job()["result"]["rows"][0]
            self.assertEqual(row["baseline_pq"], 5.0)
            self.assertFalse(any("path" in key or "file" in key or "model" in key for key in row))
        finally:
            server_main.LOOP_JOB.clear(); server_main.LOOP_JOB.update(original)

    def test_blank_workspace_does_not_restore_mismatched_preview(self):
        original_job = dict(server_main.LOOP_JOB)
        with tempfile.TemporaryDirectory() as temp:
            snapshot = Path(temp) / "last_preview.json"
            snapshot.write_text(json.dumps({
                "state": "done",
                "result": {
                    "status": "ok", "run_id": "old-run",
                    "baseline": "v1", "candidate": "v2",
                    "rows": [{
                        "stem": "old", "baseline_path": "old-a.wav",
                        "candidate_path": "old-b.wav",
                    }],
                },
            }), encoding="utf-8")
            try:
                server_main.LOOP_JOB.clear()
                server_main.LOOP_JOB.update(state="idle", result=None)
                with patch.object(server_main, "LOOP_PREVIEW_SNAPSHOT", snapshot), \
                     patch.object(server_main.loop, "load_status", return_value={
                         "workspace_mode": "blank", "baseline": None, "candidate": None,
                     }):
                    server_main._restore_loop_preview()
                self.assertEqual(server_main.LOOP_JOB["state"], "idle")
                self.assertTrue(snapshot.exists())  # Unknown legacy identity is retained for inspection.
            finally:
                server_main.LOOP_JOB.clear(); server_main.LOOP_JOB.update(original_job)

    def test_new_experiment_cannot_reset_a_running_worker(self):
        original_round = dict(server_main.LOOP_JOB)
        original_benchmark = dict(server_main.LOOP_BENCHMARK_JOB)
        try:
            server_main.LOOP_JOB.update(state="running", run_id="still-running")
            server_main.LOOP_BENCHMARK_JOB.update(state="idle")
            result = server_main.loop_new_experiment()
            self.assertEqual(result["status"], "error")
            self.assertEqual(server_main.LOOP_JOB.get("run_id"), "still-running")
        finally:
            server_main.LOOP_JOB.clear(); server_main.LOOP_JOB.update(original_round)
            server_main.LOOP_BENCHMARK_JOB.clear(); server_main.LOOP_BENCHMARK_JOB.update(original_benchmark)

    def test_blank_loop_status_does_not_surface_old_tournament(self):
        blank = {
            "workspace_mode": "blank", "baseline": None, "candidate": None,
            "rounds": [], "config": {},
        }
        with patch.object(server_main.loop, "load_status", return_value=blank), \
             patch.object(server_main.loop, "load_version_tournament") as load_tournament:
            result = server_main.loop_status()
        load_tournament.assert_not_called()
        self.assertIsNone(result["benchmark_run"])
        self.assertEqual(result["version_summary"]["status"], "insufficient")

    def test_blank_loop_report_does_not_surface_old_tournament(self):
        blank = {
            "workspace_mode": "blank", "baseline": None, "candidate": None,
            "rounds": [], "config": {}, "changelog": [],
        }
        with patch.object(server_main.loop, "load_status", return_value=blank), \
             patch.object(server_main.loop, "load_version_tournament") as load_tournament, \
             patch.object(server_main.loop, "build_markdown", return_value="# 空白实验"):
            result = server_main.loop_report()
        load_tournament.assert_not_called()
        self.assertEqual(result["markdown"], "# 空白实验")

    def test_loop_runs_are_blocked_until_golden_benchmark_is_ready(self):
        blocked = {"ready": False, "blockers": ["缺少 26 音色基线"]}
        with patch.object(server_main, "_golden_benchmark_readiness", return_value=blocked), \
             patch.object(server_main, "_claim_loop_job") as claim:
            benchmark = server_main.loop_benchmark_run()
            round_run = server_main.loop_run(contracts.LoopRunRequest())
        claim.assert_not_called()
        self.assertEqual(benchmark["status"], "error")
        self.assertEqual(round_run["status"], "error")
        self.assertIn("缺少 26 音色基线", benchmark["message"])

    def test_round_and_benchmark_share_one_atomic_job_slot(self):
        original_round = dict(server_main.LOOP_JOB)
        original_benchmark = dict(server_main.LOOP_BENCHMARK_JOB)
        try:
            server_main.LOOP_JOB.update(state="idle")
            server_main.LOOP_BENCHMARK_JOB.update(state="idle")
            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
                claimed = list(pool.map(
                    lambda _: server_main._claim_loop_job(server_main.LOOP_JOB, "test"),
                    range(16),
                ))
            self.assertEqual(sum(claimed), 1)
            self.assertFalse(server_main._claim_loop_job(server_main.LOOP_BENCHMARK_JOB, "benchmark"))
        finally:
            server_main.LOOP_JOB.clear(); server_main.LOOP_JOB.update(original_round)
            server_main.LOOP_BENCHMARK_JOB.clear(); server_main.LOOP_BENCHMARK_JOB.update(original_benchmark)

    def test_tts_payload_decoder_validates_complete_wav(self):
        wav = b"RIFF" + (4).to_bytes(4, "little") + b"WAVE" + b"data"
        self.assertEqual(tts._decode_wav_payload(wav.hex()), wav)
        self.assertEqual(tts._decode_wav_payload(base64.b64encode(wav).decode()), wav)
        with self.assertRaisesRegex(RuntimeError, "不是有效 WAV"):
            tts._decode_wav_payload(base64.b64encode(b"not-wave-data").decode())

    def test_tts_does_not_retry_deterministic_client_error(self):
        class Response:
            status_code = 400
            text = "invalid voice_id"

        with tempfile.TemporaryDirectory() as temp, \
             patch.object(tts, "load_env", return_value={"MINIMAX_API_KEY": "key", "MINIMAX_GROUP_ID": "group"}), \
             patch.object(tts._SESSION, "post", return_value=Response()) as post, \
             patch.object(tts.time, "sleep") as sleep:
            result = tts.synthesize("测试", "missing", output_dir=temp)
        self.assertEqual(result["status"], "error")
        self.assertEqual(post.call_count, 1)
        sleep.assert_not_called()

    def test_voice_fallback_is_explicit(self):
        with patch.object(tts, "load_env", return_value={}):
            voices = tts.list_voices()
        self.assertTrue(voices)
        self.assertTrue(all(item["catalog_source"] == "fallback" for item in voices))
        self.assertTrue(tts.voice_catalog_status()["warning"])

    def test_channel_rejects_non_numeric_bitrate_before_execution(self):
        with self.assertRaises(ValidationError):
            contracts.ChannelRunRequest(input_wav="sample.wav", bitrate_kbps="oops")

    def test_legacy_file_open_has_local_service_redirect_guard(self):
        html = (ROOT / "app" / "index.html").read_text(encoding="utf-8")
        self.assertIn('if (location.protocol === "file:")', html)
        self.assertIn('http://127.0.0.1:8090/', html)
        self.assertIn("function cancelVoiceCohort()", html)
        self.assertIn("版本 × 固定簇变化", html)
        self.assertIn("正在聚类本地目录", html)
        self.assertIn("result.scrollIntoView", html)
        self.assertIn("history-evidence", html)
        self.assertIn("查看 C1–C4 回归", html)
        self.assertIn("固定输入不可临时替换", html)
        self.assertIn("至少保留一个噪声场景", html)
        self.assertIn("function aggregateLoopRows", html)
        self.assertIn("function representativeLoopRows", html)
        self.assertIn("不会生成新音频，也不会重新运行评测", html)
        self.assertIn('/insights.js', html)
        self.assertIn("查看原始证据", html)
        self.assertIn('versionRawRows.length', html)
        self.assertLess(html.index('id="loopVersionReview"'), html.index('id="loopPreviewSection"'))
        self.assertLess(html.index('id="loopChartCard"'), html.index('id="loopDecisionCard"'))
        self.assertIn('#view-loop.result-ready:not([hidden])', html)
        self.assertIn("V1–V4 参数赛马", html)
        self.assertIn("不是本轮结论", html)
        self.assertNotIn('id="experimentRail"', html)
        self.assertNotIn("确认版本", html)
        self.assertIn('进入空白专家工作台', html)
        self.assertIn("function goLoopStage", html)
        self.assertIn('class="eval-result-context"', html)
        self.assertIn('aria-label="盲听音频 A"', html)

    def test_cohort_fingerprint_is_stable_and_probe_sensitive(self):
        plan = {
            "voices": [{"voice_id": "voice-a"}, {"voice_id": "voice-b"}],
            "probe_text": "固定探针文本",
            "seed": 42,
            "language_scope": "mandarin",
            "kinds": ["system"],
            "version_label": "v1",
        }
        self.assertEqual(tts.cohort_fingerprint(plan), tts.cohort_fingerprint(dict(plan)))
        relabeled = dict(plan)
        relabeled["version_label"] = "同一音频的显示标签"
        self.assertEqual(tts.cohort_fingerprint(plan), tts.cohort_fingerprint(relabeled))
        changed = dict(plan)
        changed["probe_text"] = "另一段固定探针文本"
        self.assertNotEqual(tts.cohort_fingerprint(plan), tts.cohort_fingerprint(changed))

    def test_default_probe_is_in_eight_to_twelve_second_range(self):
        estimated = len(tts.DEFAULT_VOICE_PROBE) / 4.8
        self.assertGreaterEqual(estimated, 8)
        self.assertLessEqual(estimated, 12)

    def test_cancelled_cohort_writes_partial_manifest_without_api_call(self):
        with tempfile.TemporaryDirectory() as temp:
            plan = {
                "seed": 42,
                "language_scope": "mandarin",
                "version_label": "test",
                "probe_text": tts.DEFAULT_VOICE_PROBE,
                "probe_chars": len(tts.DEFAULT_VOICE_PROBE),
                "estimated_seconds_per_voice": 6.0,
                "selected_count": 2,
                "requested_count": 2,
                "voices": [
                    {"voice_id": "voice-a", "name": "A", "kind": "system"},
                    {"voice_id": "voice-b", "name": "B", "kind": "system"},
                ],
            }
            cancel = __import__("threading").Event()
            cancel.set()
            with patch.object(tts, "synthesize") as synthesize:
                result = tts.generate_voice_cohort(plan, Path(temp) / "cohort", cancel_event=cancel)
            self.assertEqual(result["status"], "cancelled")
            self.assertFalse(synthesize.called)
            manifest = json.loads((Path(temp) / "cohort" / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["status"], "partial")

    def test_existing_ready_cohort_is_found_by_request_fingerprint(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "data" / "voice" / "cohorts" / "existing"
            root.mkdir(parents=True)
            plan = {
                "voices": [{"voice_id": "voice-a"}],
                "probe_text": "固定探针",
                "seed": 7,
                "language_scope": "mandarin",
                "kinds": ["system"],
                "version_label": "v1",
            }
            (root / "audio").mkdir()
            (root / "audio" / "a.wav").write_bytes(b"a")
            (root / "manifest.json").write_text(json.dumps({
                "id": "existing", "status": "ready",
                "request_fingerprint": tts.cohort_fingerprint(plan),
                "items": [{**plan["voices"][0], "status": "ok", "filename": "a.wav"}], "requested_count": 1,
            }), encoding="utf-8")
            with patch.object(tts, "PROJECT_ROOT", Path(temp) / "data" / ".."):
                found = tts.find_existing_cohort(plan)
            self.assertEqual(found["id"], "existing")
            self.assertEqual(found["status"], "ready")

    def test_ready_cohort_hash_is_written_and_corruption_downgrades_to_partial(self):
        with tempfile.TemporaryDirectory() as temp:
            plan = {
                "seed": 42,
                "language_scope": "mandarin",
                "version_label": "v1",
                "probe_text": tts.DEFAULT_VOICE_PROBE,
                "probe_chars": len(tts.DEFAULT_VOICE_PROBE),
                "estimated_seconds_per_voice": 6.0,
                "selected_count": 2,
                "requested_count": 2,
                "voices": [
                    {"voice_id": "voice-a", "name": "A", "kind": "system"},
                    {"voice_id": "voice-b", "name": "B", "kind": "system"},
                ],
            }
            def fake_synthesize(text, voice_id, output_dir=None, output_name=None):
                target = Path(output_dir) / output_name
                target.write_bytes((voice_id + text).encode("utf-8"))
                return {"status": "ok", "bytes": target.stat().st_size}

            cohort_dir = Path(temp) / "data" / "voice" / "cohorts" / "hashed"
            with patch.object(tts, "synthesize", side_effect=fake_synthesize):
                result = tts.generate_voice_cohort(plan, cohort_dir)
            self.assertEqual(result["status"], "ok")
            manifest = result["manifest"]
            self.assertTrue(all(item.get("sha256") for item in manifest["items"]))
            with patch.object(tts, "PROJECT_ROOT", Path(temp)):
                self.assertEqual(tts.find_existing_cohort(plan)["status"], "ready")
                (cohort_dir / "audio" / manifest["items"][0]["filename"]).write_bytes(b"corrupt")
                self.assertEqual(tts.find_existing_cohort(plan)["status"], "partial")


if __name__ == "__main__":
    unittest.main()
