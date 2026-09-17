"""Job progress must be truthful, recoverable and cooperatively cancellable."""
import unittest
from unittest.mock import patch
from server import main


class ObservabilityTests(unittest.TestCase):
    def test_polling_does_not_invent_new_events(self):
        job = {"state": "running", "events": []}
        main._observe_loop_job(job, message="降噪 DUT", done=1, total=4)
        main._observe_loop_job(job, message="降噪 DUT", done=2, total=4)
        self.assertEqual(len(job["events"]), 1)
        self.assertEqual(job["events"][0]["done"], 2)
        main._observe_loop_job(job, message="评测中", done=0, total=4)
        self.assertEqual([e["stage"] for e in job["events"]], ["dut", "evaluate"])
        main._observe_loop_job(job, state="done", message="等待人工确认")
        self.assertEqual(job["stage"], "review")
        self.assertIsNotNone(job["finished_at"])

    def test_cancel_waits_for_work_boundary_and_does_not_publish_result(self):
        job = {"state": "running", "events": [], "result": None}
        with patch.object(main, "LOOP_JOB", job):
            main.loop_cancel()
            self.assertEqual(job["state"], "running")
            with self.assertRaises(main.LoopCancelled):
                main._observe_loop_job(job, message="评测中", done=1, total=4)
            main._observe_loop_job(job, state="cancelled", message="已停止", result=None)
        self.assertIsNone(job["result"])
        self.assertIsNotNone(job["finished_at"])

    def test_retry_resets_timing_and_cancel_flag(self):
        job = {"state": "cancelled", "cancel_requested": True, "events": [{"stage": "dut"}]}
        with patch.object(main, "LOOP_JOB", job), patch.object(main, "LOOP_BENCHMARK_JOB", {"state":"idle"}):
            self.assertTrue(main._claim_loop_job(job, "准备运行"))
        self.assertFalse(job["cancel_requested"])
        self.assertEqual(len(job["events"]), 1)
        self.assertEqual(job["stage"], "prepare")
        self.assertIsNone(job["finished_at"])


if __name__ == '__main__':
    unittest.main()
