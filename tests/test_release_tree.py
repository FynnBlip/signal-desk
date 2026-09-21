"""Release-tree inspector: no network, no commit."""
import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "check_release_tree_test",
    ROOT / "scripts" / "check_release_tree.py",
)
checker = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(checker)


class ReleaseTreeTests(unittest.TestCase):
    def test_each_current_entry_asset_is_required(self):
        for missing in ("app/lab.html", "app/lab.js", "app/lab.css",
                        "app/assets/runtime-architecture.webm", "app/assets/runtime-architecture.webp",
                        "docs/signal-desk-runtime.html", "docs/signal-desk-runtime.architecture.json"):
            with self.subTest(missing=missing), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                for name in checker.REQUIRED:
                    if name != missing:
                        path = root / name
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.touch()
                report = checker.inspect(root, compile_copy=False)
                self.assertIn(missing, report["missing_required"])
                self.assertFalse(report["ok_to_stage"])

    def test_empty_directory_reports_missing_required_files(self):
        with tempfile.TemporaryDirectory() as temp:
            report = checker.inspect(Path(temp), compile_copy=False)
        self.assertFalse(report["ok_to_stage"])
        self.assertIn("LICENSE", report["missing_required"])
        self.assertIn("server/contracts.py", report["missing_required"])
        self.assertIn("app/workbench.js", report["missing_required"])

    def test_scan_includes_new_files_outside_fixed_manifest(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            added = root / "new-doc.md"
            added.write_text("sk-" + "x" * 24, encoding="utf-8")
            self.assertIn("new-doc.md: matched generic-sk-token", checker.scan_secrets(root))

    def test_current_tree_has_required_source_files(self):
        report = checker.inspect(checker.ROOT, compile_copy=True)
        self.assertEqual(report["missing_required"], [])
        self.assertEqual(report["secret_hits"], [])
        self.assertEqual(report["compile_errors"], [])
        self.assertTrue(report["ok_to_stage"])


if __name__ == "__main__":
    unittest.main()
