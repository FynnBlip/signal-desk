# -*- coding: utf-8 -*-
"""Read-only HTTP smoke test for a running local Signal Desk service."""

import json
import sys
import urllib.request


BASE = "http://127.0.0.1:8090"


def get(path):
    with urllib.request.urlopen(BASE + path, timeout=10) as response:
        return json.load(response)


def main():
    health = get("/api/health")
    providers = get("/api/providers")
    modules = get("/api/modules")
    evaluate = get("/api/evaluate/status")
    assert health.get("status") == "ok"
    assert len(modules.get("modules", [])) == 7
    assert providers.get("providers")
    assert "state" in evaluate
    print(f"OK · {len(modules['modules'])} slots · {len(providers['providers'])} providers · eval={evaluate['state']}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"FAIL · {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1)
