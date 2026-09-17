"""First-run guards: no network calls, inference, or user data writes."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import soundfile as sf

from server import main


def _write_valid_wav(path, seed=1, frames=16000, samplerate=16000):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)
    audio = rng.normal(0.0, 0.04, frames).astype(np.float32)
    sf.write(path, audio, samplerate)
    return path


def _fill_scenes(noise_root, writer):
    for scene in main.channel.NOISE_SCENES:
        writer(Path(noise_root) / scene["dir"] / "clip.wav", scene)


class FirstRunTests(unittest.TestCase):
    def test_missing_and_empty_noise_cannot_be_ready(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(main.channel, "NOISE_DIR", Path(temp)):
            blockers = main.channel.benchmark_noise_blockers()
            self.assertEqual(len(blockers), 6)
            self.assertTrue(all("缺少正式噪声素材" in item for item in blockers))
            for scene in main.channel.NOISE_SCENES:
                folder = Path(temp) / scene["dir"]
                folder.mkdir(parents=True)
                (folder / "recording.wav").touch()
            empty_blockers = main.channel.benchmark_noise_blockers()
            self.assertEqual(len(empty_blockers), 6)
            self.assertTrue(all("噪声不可用" in item for item in empty_blockers))

    def test_mixed_synthetic_filename_cannot_be_ready(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(main.channel, "NOISE_DIR", Path(temp)):
            _fill_scenes(temp, lambda path, scene: _write_valid_wav(path, seed=100 + abs(hash(scene["id"])) % 50))
            self.assertEqual(main.channel.benchmark_noise_blockers(), [])
            folder = Path(temp) / main.channel.NOISE_SCENES[0]["dir"]
            (folder / "demo_synthetic_noise.wav").touch()
            self.assertIn("合成布线素材", main.channel.benchmark_noise_blockers()[0])

    def test_renamed_wiring_fixture_is_still_blocked_by_hash(self):
        wiring = main.channel.wiring
        with tempfile.TemporaryDirectory() as temp, patch.object(main.channel, "NOISE_DIR", Path(temp)):
            for index, scene in enumerate(main.channel.NOISE_SCENES):
                dest = Path(temp) / scene["dir"] / "office_field.wav"
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(wiring.wav_bytes(wiring.scene_noise_audio(index)))
            report = main.channel.inspect_benchmark_noise()
            self.assertFalse(report["ok"])
            self.assertEqual(report["provenance"], "wiring")
            self.assertTrue(all("合成布线素材" in item for item in report["blockers"]))
            renamed = Path(temp) / main.channel.NOISE_SCENES[0]["dir"] / "office_field.wav"
            self.assertEqual(wiring.inspect_wav(renamed)["purpose"], "wiring")

    def test_undeclared_valid_wav_is_detected_not_certified(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(main.channel, "NOISE_DIR", Path(temp)):
            _fill_scenes(temp, lambda path, scene: _write_valid_wav(path, seed=30 + abs(hash(scene["id"])) % 80))
            report = main.channel.inspect_benchmark_noise()
            self.assertTrue(report["ok"])
            self.assertEqual(report["provenance"], "undeclared")
            self.assertIn("来源未声明", report["provenance_note"])
            self.assertIn("不当作已认证", report["provenance_note"])
            self.assertTrue(all(item["status"] == "undeclared" for item in report["scenes"]))

    def test_declared_manifest_changes_provenance_not_certification(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(main.channel, "NOISE_DIR", Path(temp)):
            _fill_scenes(temp, lambda path, scene: _write_valid_wav(path, seed=9))
            manifest = {
                "schema_version": 1,
                "scenes": {scene["id"]: {"source": "local recording", "purpose": "formal-benchmark"} for scene in main.channel.NOISE_SCENES},
            }
            (Path(temp) / "asset_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            report = main.channel.inspect_benchmark_noise()
            self.assertTrue(report["ok"])
            self.assertEqual(report["provenance"], "declared")
            self.assertIn("声明", report["provenance_note"])
            self.assertNotIn("已认证", report["provenance_note"])

    def test_checkpoint_presence_is_not_inference_verified(self):
        voices = [{"voice_id": f"v{index}", "cluster_id": index % 4 + 1} for index in range(26)]
        with tempfile.TemporaryDirectory() as temp:
            noise = Path(temp) / "noise"
            _fill_scenes(noise, lambda path, scene: _write_valid_wav(path, seed=11))
            status_path = Path(temp) / "loop_status.json"
            status_path.write_text(json.dumps({"baseline": None, "candidate": None, "rounds": []}), encoding="utf-8")
            with patch.object(main.channel, "NOISE_DIR", noise), \
                 patch.object(main.loop, "_load_active_cohort", return_value={"voices": voices}), \
                 patch.object(main.denoise, "list_models", return_value=[{"id": "noisereduce", "ready": True}]), \
                 patch.object(main.evaluate, "get_checkpoint", return_value=Path(temp) / "checkpoint.pt"), \
                 patch.object(main.loop, "LOOP_STATUS", status_path), \
                 patch.object(main.loop, "BENCHMARK_ROOT", Path(temp) / "benchmarks"):
                report = main._golden_benchmark_readiness()
        self.assertTrue(report["assets_detected"])
        self.assertTrue(report["ready"])
        self.assertFalse(report["inference_verified"])
        self.assertEqual(report["noise_provenance"], "undeclared")

    def test_legacy_homepage_separates_assets_and_inference_copy(self):
        html = (Path(__file__).resolve().parents[1] / "app" / "index.html").read_text(encoding="utf-8")
        setup = (Path(__file__).resolve().parents[1] / "app" / "setup.html").read_text(encoding="utf-8")
        self.assertIn("真实推理", html)
        self.assertIn("来源未声明", html)
        self.assertIn("检测到文件不等于已经跑通 AudioBox", html)
        self.assertIn("文件内容哈希", setup)
        self.assertIn("资产已检测到", setup)
        self.assertIn('data-loop-stage="prepare"', html)
        self.assertIn("这是一套算法迭代 Loop", html)
        self.assertIn("function goLoopStage", html)
        self.assertNotIn('id="experimentRail"', html)
        self.assertIn('data-home-mode', html)

    def test_current_homepage_uses_lab_entry_and_preparation_contract(self):
        response = main.workbench_home()
        self.assertEqual(Path(response.path).name, "lab.html")
        html = Path(response.path).read_text(encoding="utf-8")
        source = Path(response.path).with_name("lab.js").read_text(encoding="utf-8")
        self.assertIn('/lab.js', html)
        self.assertIn('/lab.css', html)
        self.assertNotIn('/workbench.js', html)
        self.assertIn('benchmark?.readiness', source)
        self.assertIn('ready&&!ready.ready', source)
        self.assertIn('检查音频缓存与测试集', source)

    def test_insufficient_reference_voices_never_start_generation(self):
        with patch.object(main.tts, "plan_voice_cohort", return_value={"status": "ok", "selected_count": 25}), \
             patch.object(main.tts, "find_existing_cohort") as find_existing:
            payload = {"benchmark": True, "count": 26, "version_label": "first-run"}
            self.assertEqual(main.voice_cohort_plan(payload)["status"], "error")
            self.assertEqual(main.voice_cohort_run(payload)["status"], "error")
            find_existing.assert_not_called()

    def test_independent_voice_analysis_keeps_other_counts(self):
        plan = {"status": "ok", "selected_count": 50}
        with patch.object(main.tts, "plan_voice_cohort", return_value=plan):
            self.assertEqual(main.voice_cohort_plan({"count": 50, "version_label": "independent"}), plan)

    def test_direct_matrix_generation_rejects_wiring_fixtures(self):
        with patch.object(main.loop.channel, "benchmark_noise_blockers", return_value=["合成布线素材"]), \
             patch.object(main.loop, "_golden_benchmark_context") as context:
            with self.assertRaisesRegex(RuntimeError, "合成布线素材"):
                main.loop.prepare_golden_matrix()
            context.assert_not_called()

    def test_bootstrap_bytes_match_canonical_wiring_hashes(self):
        import importlib.util
        wiring = main.channel.wiring
        bootstrap_path = Path(__file__).resolve().parents[1] / "scripts" / "bootstrap_demo.py"
        spec = importlib.util.spec_from_file_location("bootstrap_demo_test", bootstrap_path)
        bootstrap = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(bootstrap)
        with tempfile.TemporaryDirectory() as temp:
            bootstrap.build(Path(temp), force=True)
            original = Path(temp) / "data" / "noise" / "demand" / "TMETRO" / "demo_synthetic_noise.wav"
            renamed = Path(temp) / "data" / "noise" / "demand" / "TMETRO" / "copied.wav"
            renamed.write_bytes(original.read_bytes())
            self.assertIn(wiring.sha256_file(renamed), wiring.canonical_wiring_hashes())
            self.assertEqual(wiring.inspect_wav(renamed)["purpose"], "wiring")


if __name__ == "__main__":
    unittest.main()
