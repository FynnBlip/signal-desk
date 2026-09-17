"""Release audit regressions, isolated state only; no inference or API fees."""
import copy
import json
import tempfile
import unittest
import warnings
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from server import main
from server.contracts import LoopApplyRequest
from server.run_store import RunStore


class ReportTests(unittest.TestCase):
    def report(self, rows):
        with patch.object(main.loop, "build_version_summary", return_value={}):
            return main.loop.build_markdown({"rounds": [{"round": 1, "experiment_id": "e", "run_id": "r", "time": "test-time", "rows": rows}]})

    def test_each_sample_identity_and_markdown_escaping(self):
        rows = [{"scene_id": "OOFFICE", "voice_name": "同名|音色\n", "stem": stem, "baseline_pq": 5, "candidate_pq": 6} for stem in ["sample-a", "sample-b"]]
        text = self.report(rows)
        self.assertIn("实验：e · Run：r · 时间：test-time", text)
        self.assertIn("同名\\|音色 ", text)
        for stem in ["sample-a", "sample-b"]:
            self.assertIn(f"| {stem} |", text)
        self.assertEqual(sum(line.startswith("| OOFFICE") for line in text.splitlines()), 2)
        self.assertEqual(rows[0]["candidate_pq"], 6)

    def test_missing_zero_and_deltas(self):
        for baseline, candidate, verdict in [(None, 6, "无可比较数据"), (6, None, "无可比较数据"), (None, None, "无可比较数据"), (0, 0, "上行"), (0, 1, "上行"), (6, 5, "回退"), (float("nan"), 6, "无可比较数据")]:
            with self.subTest(baseline=baseline, candidate=candidate):
                line = next(line for line in self.report([{"scene_id": "OOFFICE", "baseline_pq": baseline, "candidate_pq": candidate}]).splitlines() if line.startswith("| OOFFICE"))
                self.assertTrue(line.endswith(f"| {verdict} |"), line)
                self.assertNotIn("nan", line)


class EvaluationRecoveryTests(unittest.TestCase):
    def test_newest_interrupted_run_keeps_identity_and_progress(self):
        with tempfile.TemporaryDirectory() as temp:
            store = RunStore(Path(temp))
            old = store.create("evaluate")
            store.update("evaluate", old["run_id"], state="done", created_at="2026-09-01", result={"status": "ok"})
            new = store.create("evaluate", request={"folder": "test-only"})
            store.update("evaluate", new["run_id"], state="running", created_at="2026-09-02", done=3, total=8)
            restored = store.recover_interrupted("evaluate")
            self.assertEqual(restored["run_id"], new["run_id"])
            self.assertEqual(restored["state"], "error")
            self.assertEqual(restored["error"]["type"], "InterruptedRun")
            self.assertEqual(restored["done"], 3)
            self.assertEqual(restored["request"]["folder"], "test-only")
            self.assertEqual(store.get("evaluate", old["run_id"])["state"], "done")
            again = store.recover_interrupted("evaluate")
            self.assertEqual(again, restored)
            with patch.object(main, "RUN_STORE", store), patch.object(main, "EVAL_JOB", {}):
                main.restore_evaluation_job()
                self.assertEqual(main.evaluate_status()["run_id"], new["run_id"])

    def test_queued_empty_and_persistence_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            store = RunStore(Path(temp))
            self.assertIsNone(store.recover_interrupted("evaluate"))
            new = store.create("evaluate")
            with patch.object(store, "_atomic_write", side_effect=PermissionError("fixture denied")), self.assertLogs("server.run_store", level="ERROR"):
                failed = store.recover_interrupted("evaluate")
            self.assertEqual(failed["error"]["type"], "PersistenceError")
            self.assertEqual(store.get("evaluate", new["run_id"])["state"], "queued")
            self.assertEqual(store.recover_interrupted("evaluate")["state"], "error")


class PreviewRecoveryTests(unittest.TestCase):
    def preview(self):
        return {"state": "done", "run_id": "r", "result": {"status": "ok", "run_id": "r", "experiment_id": "e", "baseline": "v1", "candidate": "v2", "rows": [{"stem": "sample"}]}}

    def test_identity_and_consumption_control_restore(self):
        for experiment, processed, expected in [("e", None, "done"), ("other", None, "idle"), ("e", {"run_id": "r", "experiment_id": "e"}, "idle")]:
            with self.subTest(experiment=experiment, processed=processed), tempfile.TemporaryDirectory() as temp:
                path = Path(temp) / "preview.json"
                path.write_text(json.dumps(self.preview()), encoding="utf-8")
                state = {"workspace_mode": "experiment", "experiment_id": experiment, "baseline": "v1", "candidate": "v2", "processed_preview": processed}
                with patch.object(main, "LOOP_PREVIEW_SNAPSHOT", path), patch.object(main, "LOOP_JOB", {"state": "idle"}), patch.object(main, "LOOP_BLIND_ASSIGNMENTS", {}), patch.object(main.loop, "load_status", return_value=state), patch.object(main.loop, "build_blind_pairs", return_value=([], {})):
                    main._restore_loop_preview()
                    self.assertEqual(main.LOOP_JOB["state"], expected)

    def test_reject_is_durable_even_when_cleanup_fails(self):
        with tempfile.TemporaryDirectory() as temp, ExitStack() as stack:
            path = Path(temp) / "preview.json"
            preview = self.preview()
            path.write_text(json.dumps(preview), encoding="utf-8")
            state = {"workspace_mode": "experiment", "experiment_id": "e", "baseline": "v1", "candidate": "v2"}
            def save(value):
                state.clear(); state.update(copy.deepcopy(value)); return copy.deepcopy(state)
            stack.enter_context(patch.object(main, "LOOP_JOB", preview))
            stack.enter_context(patch.object(main, "LOOP_PREVIEW_SNAPSHOT", path))
            stack.enter_context(patch.object(main, "LOOP_BLIND_ASSIGNMENTS", {}))
            stack.enter_context(patch.object(main.loop, "load_status", side_effect=lambda: copy.deepcopy(state)))
            stack.enter_context(patch.object(main.loop, "save_status", side_effect=save))
            stack.enter_context(patch.object(main.loop, "list_versions", return_value=[{"id": "v1"}, {"id": "v2"}]))
            with patch.object(Path, "unlink", side_effect=PermissionError("fixture cleanup failure")):
                main.loop_apply(LoopApplyRequest(decision={"action": "reject"}))
            self.assertTrue(path.exists())
            self.assertEqual(state["processed_preview"]["run_id"], "r")
            main._restore_loop_preview()
            self.assertEqual(main.LOOP_JOB["state"], "idle")

    def test_save_failure_keeps_unprocessed_preview(self):
        preview = self.preview()
        with patch.object(main, "LOOP_JOB", preview), patch.object(main.loop, "load_status", return_value={"baseline": "v1", "candidate": "v2"}), patch.object(main.loop, "list_versions", return_value=[]), patch.object(main.loop, "save_status", side_effect=PermissionError("fixture state write failure")), patch.object(main, "_discard_loop_preview") as cleanup:
            with self.assertRaises(PermissionError):
                main.loop_apply(LoopApplyRequest(decision={"action": "reject"}))
            cleanup.assert_not_called()
            self.assertEqual(main.LOOP_JOB["result"]["run_id"], "r")

    def test_legacy_preview_is_retained_but_not_restored(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "preview.json"
            preview = self.preview()
            del preview["result"]["experiment_id"]
            path.write_text(json.dumps(preview), encoding="utf-8")
            with patch.object(main, "LOOP_PREVIEW_SNAPSHOT", path), patch.object(main, "LOOP_JOB", {"state": "idle"}), patch.object(main, "LOOP_BLIND_ASSIGNMENTS", {}), patch.object(main.loop, "load_status", return_value={"workspace_mode": "experiment", "experiment_id": "e", "baseline": "v1", "candidate": "v2"}), patch.object(main.loop, "build_blind_pairs", return_value=([], {})):
                main._restore_loop_preview()
                self.assertEqual(main.LOOP_JOB["state"], "idle")
                self.assertIn("缺少实验身份", main.LOOP_JOB["message"])
                self.assertTrue(path.exists())
                self.assertEqual(json.loads(path.read_text(encoding="utf-8")), preview)



class DiagnosticsTests(unittest.TestCase):
    def test_evaluation_imports_do_not_suppress_unrelated_warnings(self):
        for module in ["06_evaluate/evaluate.py", "07_loop/loop.py"]:
            with self.subTest(module=module), warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("default")
                main._load_module(main.PROJECT_ROOT / "modules" / module)
                warnings.warn("unrelated audit user warning", UserWarning)
                warnings.warn("unrelated audit future warning", FutureWarning)
                messages = [str(item.message) for item in caught]
                self.assertIn("unrelated audit user warning", messages)
                self.assertIn("unrelated audit future warning", messages)
