# -*- coding: utf-8 -*-
"""启动手机可访问的真机采集服务：本地自签证书 + 配对令牌 + 终端二维码。

  python scripts/serve.py                 # https://<局域网IP>:8443 （自签证书）
  python scripts/serve.py --port 8091 --no-tls   # 只在本机试页面
  python scripts/serve.py --tailscale-hint       # 打印 Tailscale Serve 推荐做法

不用自签证书的更省心做法（真证书、零信任折腾、还能远程）：
  tailscale serve https / http://127.0.0.1:8090
"""

from __future__ import annotations

import argparse
import os
import secrets
import shutil
import socket
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _load_sibling(name: str):
    """scripts/ 不是包，按文件路径加载同目录脚本（与 server/main.py 的做法一致）。"""
    import importlib.util
    spec = importlib.util.spec_from_file_location(name, Path(__file__).resolve().parent / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


find_openssl = _load_sibling("capture_doctor").find_openssl
RUNTIME = PROJECT_ROOT / "runtime"
CERT = RUNTIME / "capture-cert.pem"
KEY = RUNTIME / "capture-key.pem"


def lan_ips() -> list[str]:
    ips: set[str] = set()
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("8.8.8.8", 80))
        ips.add(sock.getsockname()[0])
        sock.close()
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except OSError:
        pass
    if sys.platform == "darwin":
        for iface in ("en0", "en1"):
            try:
                out = subprocess.run(["ipconfig", "getifaddr", iface], capture_output=True,
                                     text=True, timeout=3).stdout.strip()
                if out:
                    ips.add(out)
            except (OSError, subprocess.SubprocessError):
                pass
    return sorted(ip for ip in ips if not ip.startswith("127."))


def ensure_cert(ips: list[str]) -> tuple[Path, Path]:
    """生成带 IP SAN 的自签证书。手机需要装一次根证书并开启完全信任。"""
    RUNTIME.mkdir(parents=True, exist_ok=True)
    if CERT.exists() and KEY.exists():
        return CERT, KEY
    openssl = find_openssl()
    if not openssl:
        # 以前这里直接抛异常。但 Windows 自带没有 openssl，而本项目恰恰是 Windows 优先的，
        # 等于在作者的主力平台上把这条路判死。现在改成指路：还有三条路不需要证书。
        raise RuntimeError(
            "找不到 openssl，无法生成自签证书。不必卡在这里，另有三条路：\n"
            "  1) Android：adb reverse tcp:<port> tcp:<port>，手机开 http://localhost:<port> —— 零证书\n"
            "  2) iOS：tailscale serve https / http://127.0.0.1:<port> —— 真证书\n"
            "  3) 桌面回环自测：python server/main.py 后开 http://127.0.0.1:<port>/capture.html\n"
            "跑 python scripts/capture_doctor.py 看这台机器现在能走哪条。\n"
            "（Windows 上装了 Git for Windows 通常就自带 openssl，本脚本已自动扫描常见安装位）"
        )
    sans = ",".join(
        [f"IP:127.0.0.1", f"DNS:localhost", f"DNS:{socket.gethostname()}"]
        + [f"IP:{ip}" for ip in ips]
    )
    subprocess.run([
        openssl, "req", "-x509", "-newkey", "rsa:2048", "-sha256", "-days", "825", "-nodes",
        "-keyout", str(KEY), "-out", str(CERT),
        "-subj", "/CN=signal-desk-capture",
        "-addext", f"subjectAltName={sans}",
        "-addext", "basicConstraints=critical,CA:TRUE",
        "-addext", "keyUsage=digitalSignature,keyEncipherment,keyCertSign",
    ], check=True, capture_output=True)
    os.chmod(KEY, 0o600)
    return CERT, KEY


def print_qr(url: str) -> None:
    try:
        import qrcode
    except ImportError:
        print(f"（未安装 qrcode，跳过二维码。URL：{url}）")
        return
    qr = qrcode.QRCode(border=1)
    qr.add_data(url)
    qr.make(fit=True)
    qr.print_ascii(invert=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--adb", action="store_true",
                        help="Android 零证书路径：自动 adb reverse，把本端口映射到手机的 localhost")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8443)
    parser.add_argument("--no-tls", action="store_true", help="仅本机验证页面用，手机端无法授权麦克风")
    parser.add_argument("--tailscale-hint", action="store_true")
    args = parser.parse_args()

    ips = lan_ips()
    token = os.environ.get("SIGNAL_DESK_CAPTURE_TOKEN") or secrets.token_urlsafe(9)
    os.environ["SIGNAL_DESK_CAPTURE_TOKEN"] = token

    scheme = "http" if args.no_tls else "https"
    primary = ips[0] if ips else "127.0.0.1"
    url = f"{scheme}://{primary}:{args.port}/capture.html?t={token}"

    print("=" * 64)
    print("Signal Desk · 真机采集")
    print("=" * 64)
    print(f"配对令牌 : {token}")
    print(f"采集页   : {url}")
    for ip in ips[1:]:
        print(f"备用地址 : {scheme}://{ip}:{args.port}/capture.html?t={token}")
    print(f"本机验证 : {scheme}://127.0.0.1:{args.port}/capture.html?t={token}")
    print()
    if args.tailscale_hint:
        print("更省心的做法（真证书，无需在手机装根证书，且支持跨网络）：")
        print("  1) 手机上安装 Tailscale 并登录同一 tailnet")
        print("  2) 桌面端：tailscale serve https / http://127.0.0.1:8091")
        print("  3) 手机打开 tailscale 给出的 https://<机器名>.<tailnet>.ts.net/capture.html?t=<令牌>")
        print()
    if not args.no_tls:
        print("自签证书需要手机端信任：")
        print(f"  - 把 {CERT} 传到手机安装（iOS 还需在「关于本机→证书信任设置」开启完全信任）")
        print("  - 若嫌麻烦，直接用 Tailscale Serve，或用手机自带录音 App 走导入路径")
        print()
    print("按 Ctrl+C 结束服务。")
    print("=" * 64)

    print_qr(url)
    print()

    if args.adb:
        adb = shutil.which("adb")
        if not adb:
            print("！未找到 adb，跳过反向端口。装 Android Platform Tools 后重试。")
        else:
            code = subprocess.run([adb, "reverse", f"tcp:{args.port}", f"tcp:{args.port}"],
                                  capture_output=True, text=True)
            if code.returncode == 0:
                print(f"√ adb reverse 已建立：手机浏览器打开 http://localhost:{args.port}/capture.html?t={token}")
                print("  localhost 即安全上下文，麦克风直接可用，不需要任何证书。")
            else:
                print(f"！adb reverse 失败：{(code.stderr or code.stdout).strip()}")
        print()

    os.environ.setdefault("CAPTURE_PORT", str(args.port))
    sys.path.insert(0, str(PROJECT_ROOT / "server"))
    import uvicorn  # noqa: E402

    from capture_app import app  # noqa: E402

    kwargs = {"host": args.host, "port": args.port}
    if not args.no_tls:
        cert, key = ensure_cert(ips)
        kwargs.update(ssl_certfile=str(cert), ssl_keyfile=str(key))
    uvicorn.run(app, **kwargs)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
