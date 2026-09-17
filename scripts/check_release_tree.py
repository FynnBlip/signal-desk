# -*- coding: utf-8 -*-
"""Inspect the working tree that would be published. Does not commit or push."""

from __future__ import annotations

import argparse
import compileall
import py_compile
import re
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

REQUIRED = [
    ".env.example",
    ".gitignore",
    "LICENSE",
    "README.md",
    "requirements.txt",
    "design.md",
    "tokens.css",
    "tokens.json",
    "启动.bat",
    "app/index.html",
    "app/lab.html",
    "app/lab.js",
    "app/lab.css",
    "app/insights.css",
    "app/insights.js",
    "app/scenes.css",
    "app/setup.html",
    "app/workbench.css",
    "app/workbench.js",
    "data/README.md",
    "models/README.md",
    "modules/README.md",
    "modules/01_corpus/corpus.py",
    "modules/01_corpus/manifest.py",
    "modules/02_voice/voice.py",
    "modules/02_voice/manifest.py",
    "modules/03_tts/tts.py",
    "modules/03_tts/manifest.py",
    "modules/04_channel/channel.py",
    "modules/04_channel/wiring.py",
    "modules/04_channel/manifest.py",
    "modules/05_denoise/denoise.py",
    "modules/05_denoise/manifest.py",
    "modules/06_evaluate/evaluate.py",
    "modules/06_evaluate/manifest.py",
    "modules/07_loop/loop.py",
    "modules/07_loop/manifest.py",
    "server/main.py",
    "server/contracts.py",
    "server/provider_registry.py",
    "server/run_store.py",
    "scripts/bootstrap_demo.py",
    "scripts/smoke_test.py",
    "scripts/check_release_tree.py",
    "tests/test_core.py",
    "tests/test_first_run.py",
    "tests/test_observability.py",
    "tests/test_release_tree.py",
    "tests/test_insights.cjs",
    "tests/test_ui_audit.cjs",
    "tests/test_workbench.cjs",
    "tests/test_lab_workflow.py",
    "tests/lab_workflow.test.cjs",
    "tests/lab_acceptance.test.cjs",
    "tests/lab_incremental.test.cjs",
    "tests/lab_prepare.test.cjs",
    "tests/test_incremental_fixes.py",
    "tests/serve_lab_fixture.py",
    "docs/README.md",
    "docs/发布前检查.md",
    "docs/发布文件清单.md",
    "docs/验收清单.md",
    "docs/asset_manifest.example.json",
    "docs/ADR-001-插件化架构.md",
    "docs/ADR-002-信道仿真.md",
    "docs/ADR-003-闭环大脑.md",
]

OPTIONAL = [
    "docs/交接.md",
    "docs/依据-声线分类.md",
    "docs/design-system.md",
    "docs/design-tokens.md",
    "docs/design-tokens-preview.html",
]

SKIP_DIR_NAMES = {".git", "__pycache__", ".pytest_cache", ".hallmark", ".venv", "venv", "node_modules"}
WEIGHT_SUFFIXES = {".pt", ".pth", ".ckpt", ".onnx", ".bin"}
SECRET_PATTERNS = [
    ("pem-private-key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("aws-access-key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("generic-sk-token", re.compile(r"(?<![A-Za-z0-9])sk-[A-Za-z0-9]{20,}")),
    ("assigned-minimax-key", re.compile(r"MINIMAX_API_KEY\s*=\s*\S+")),
    ("assigned-deepseek-key", re.compile(r"DEEPSEEK_API_KEY\s*=\s*\S+")),
]
TEXT_SUFFIXES = {
    ".py", ".md", ".html", ".css", ".js", ".cjs", ".json", ".txt", ".bat",
    ".example", ".gitignore", ".yml", ".yaml", ".toml",
}


def posix(path: Path) -> str:
    return path.as_posix()


def is_text_candidate(path: Path) -> bool:
    if path.name in {".gitignore", ".env.example"}:
        return True
    return path.suffix.lower() in TEXT_SUFFIXES


def iter_release_files(root: Path) -> list[Path]:
    files = []
    for rel in REQUIRED + OPTIONAL:
        path = root / rel
        if path.is_file():
            files.append(path)
    return files


def missing_required(root: Path) -> list[str]:
    return [rel for rel in REQUIRED if not (root / rel).is_file()]


def forbidden_hits(root: Path) -> list[str]:
    hits = []
    env = root / ".env"
    if env.exists():
        hits.append(".env exists locally and must stay untracked")
    data = root / "data"
    if data.is_dir():
        for path in data.rglob("*"):
            if path.is_file() and path.name != "README.md":
                rel = posix(path.relative_to(root))
                hits.append(f"local data file not for git: {rel}")
    models = root / "models"
    if models.is_dir():
        for path in models.rglob("*"):
            if path.is_file() and path.suffix.lower() in WEIGHT_SUFFIXES:
                hits.append(f"model weight not for git: {posix(path.relative_to(root))}")
    return hits


def scan_secrets(root: Path) -> list[str]:
    findings = []
    for path in iter_release_files(root):
        if not is_text_candidate(path):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        rel = posix(path.relative_to(root))
        skip_assigned = path.name == ".env.example" or path.suffix.lower() in {".py", ".js", ".cjs"}
        for name, pattern in SECRET_PATTERNS:
            if skip_assigned and name.startswith("assigned-"):
                continue
            if pattern.search(text):
                findings.append(f"{rel}: matched {name}")
    return findings


def compile_release_copy(root: Path) -> list[str]:
    errors = []
    with tempfile.TemporaryDirectory() as temp:
        dest = Path(temp) / "signal-desk-release"
        for rel in REQUIRED + OPTIONAL:
            src = root / rel
            if not src.is_file():
                continue
            target = dest / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, target)
        for path in dest.rglob("*.py"):
            try:
                py_compile.compile(str(path), doraise=True)
            except py_compile.PyCompileError as exc:
                errors.append(str(exc))
        if not compileall.compile_dir(str(dest), quiet=1, maxlevels=10):
            errors.append("compileall reported a failure")
    return errors


def inspect(root: Path, compile_copy: bool = True) -> dict:
    root = Path(root)
    report = {
        "root": str(root),
        "missing_required": missing_required(root),
        "forbidden_local_only": forbidden_hits(root),
        "secret_hits": scan_secrets(root),
        "compile_errors": compile_release_copy(root) if compile_copy else [],
        "note": (
            "forbidden_local_only lists files that must not be committed; "
            "their presence on this machine is expected. "
            "Independent Py 3.12 venv + torch install is not performed by this script."
        ),
    }
    report["ok_to_stage"] = not report["missing_required"] and not report["secret_hits"] and not report["compile_errors"]
    return report


def format_report(report: dict) -> str:
    lines = [
        f"root: {report['root']}",
        f"ok_to_stage (files+secrets+syntax): {report['ok_to_stage']}",
        f"missing_required: {len(report['missing_required'])}",
        *([f"  - {item}" for item in report["missing_required"]] or ["  (none)"]),
        f"secret_hits: {len(report['secret_hits'])}",
        *([f"  - {item}" for item in report["secret_hits"]] or ["  (none)"]),
        f"compile_errors: {len(report['compile_errors'])}",
        *([f"  - {item}" for item in report["compile_errors"]] or ["  (none)"]),
        "local-only files (must stay gitignored, not a staging blocker):",
        *([f"  - {item}" for item in report["forbidden_local_only"][:20]] or ["  (none)"]),
    ]
    if len(report["forbidden_local_only"]) > 20:
        lines.append(f"  … {len(report['forbidden_local_only']) - 20} more")
    lines.append(report["note"])
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--skip-compile", action="store_true")
    args = parser.parse_args(argv)
    report = inspect(args.root, compile_copy=not args.skip_compile)
    print(format_report(report))
    return 0 if report["ok_to_stage"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
