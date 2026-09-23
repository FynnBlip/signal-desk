# -*- coding: utf-8 -*-
"""08 真机采集 · 跨平台接入体检（纯标准库，Windows / macOS / Linux 通用）。

  python scripts/capture_doctor.py

浏览器只在**安全上下文**下开放麦克风，这是这个模块唯一的接入门槛。
本脚本不替你做决定，只回答一个问题：**这台机器现在能走哪几条路。**

关键事实（很多方案绕远路就是因为不知道这条）：
    http://localhost 与 http://127.0.0.1 本身就是安全上下文。
    所以只要让手机把桌面端「看成」 localhost，就完全不需要证书。
    Android 的 `adb reverse` 正是干这个的，且 Windows / macOS 命令完全一致。
"""

from __future__ import annotations

import os
import platform
import shutil
import socket
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PORT = int(os.environ.get("SIGNAL_DESK_PORT", "8090"))

OK, WARN, BAD = "可用", "待装", "不可用"


def _run(cmd: list[str], timeout: int = 6) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except Exception as exc:  # noqa: BLE001
        return 1, str(exc)


def find_openssl() -> str | None:
    """跨平台找 openssl。

    Windows 自带没有 openssl，但 Git for Windows 捆绑了一个，开发机上几乎必有。
    只查 PATH 会在作者的主力平台上直接判死刑，所以这里把常见安装位一并扫掉。
    """
    found = shutil.which("openssl")
    if found:
        return found
    if os.name != "nt":
        return None
    candidates = [
        r"C:\Program Files\Git\usr\bin\openssl.exe",
        r"C:\Program Files\Git\mingw64\bin\openssl.exe",
        r"C:\Program Files (x86)\Git\usr\bin\openssl.exe",
        r"C:\Program Files\OpenSSL-Win64\bin\openssl.exe",
        r"C:\Program Files (x86)\OpenSSL-Win32\bin\openssl.exe",
    ]
    local = os.environ.get("LOCALAPPDATA")
    if local:
        candidates.append(str(Path(local) / "Programs" / "Git" / "usr" / "bin" / "openssl.exe"))
    for path in candidates:
        if Path(path).exists():
            return path
    return None


def lan_ip() -> str | None:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:  # noqa: BLE001
        return None


def check_adb(port: int) -> dict:
    """Android：零证书、零账号、零局域网配置，USB 直连即可。"""
    adb = shutil.which("adb")
    if not adb:
        return {"name": "Android · adb reverse（推荐，零证书）", "status": WARN,
                "detail": "未找到 adb。装 Android Platform Tools 即可，Windows / macOS 都有官方包。",
                "how": "下载 platform-tools 解压后把目录加进 PATH"}
    code, out = _run([adb, "devices"])
    devices = [ln.split("\t")[0] for ln in out.splitlines()[1:]
               if "\tdevice" in ln]
    if not devices:
        return {"name": "Android · adb reverse（推荐，零证书）", "status": WARN,
                "detail": f"adb 已就位（{adb}），但没有已授权的设备。手机插 USB 并允许「USB 调试」。",
                "how": f"adb reverse tcp:{port} tcp:{port}"}
    return {"name": "Android · adb reverse（推荐，零证书）", "status": OK,
            "detail": f"已连接设备：{', '.join(devices)}",
            "how": (f"adb reverse tcp:{port} tcp:{port}\n"
                    f"       手机浏览器打开 http://localhost:{port}/capture.html\n"
                    f"       （localhost 即安全上下文，麦克风直接可用，不需要任何证书）")}


def check_tailscale(port: int) -> dict:
    """iOS 与 Android 通用，真证书，还能远程。"""
    ts = shutil.which("tailscale")
    if not ts and os.name == "nt":
        for p in [r"C:\Program Files\Tailscale\tailscale.exe"]:
            if Path(p).exists():
                ts = p
                break
    if not ts and sys.platform == "darwin":
        for p in ["/Applications/Tailscale.app/Contents/MacOS/Tailscale"]:
            if Path(p).exists():
                ts = p
                break
    if not ts:
        return {"name": "iOS / Android · Tailscale Serve（真证书）", "status": WARN,
                "detail": "未找到 tailscale。iOS 走这条最省事：真证书，不用在手机上装根证书。",
                "how": "装 Tailscale 桌面端与手机端并登录同一 tailnet"}
    code, out = _run([ts, "status"])
    logged_in = code == 0 and "Logged out" not in out
    return {"name": "iOS / Android · Tailscale Serve（真证书）",
            "status": OK if logged_in else WARN,
            "detail": "已登录" if logged_in else "已安装但未登录",
            "how": (f"tailscale serve https / http://127.0.0.1:{port}\n"
                    f"       手机打开它给出的 https://<机器名>.<tailnet>.ts.net/capture.html")}


def check_openssl(port: int) -> dict:
    """自签证书：能用，但手机要手动装根证书，iOS 还要单独开完全信任。"""
    openssl = find_openssl()
    if not openssl:
        hint = ("装 Git for Windows 会自带 openssl（开发机通常已有）"
                if os.name == "nt" else "用包管理器装 openssl")
        return {"name": "任意手机 · 自签证书（需手动信任）", "status": WARN,
                "detail": f"未找到 openssl。{hint}", "how": "或改用上面两条路"}
    return {"name": "任意手机 · 自签证书（需手动信任）", "status": OK,
            "detail": f"openssl: {openssl}",
            "how": (f"python scripts/serve.py --port 8443\n"
                    f"       手机装一次根证书；iOS 还要在「关于本机 → 证书信任设置」开完全信任")}


def check_import_fallback() -> dict:
    """兜底：手机自带录音 App 录 WAV，回桌面端导入。零门槛，但没有设备指纹。"""
    return {"name": "任意手机 · 录音 App 导入 WAV（兜底）", "status": OK,
            "detail": "不需要任何网络配置，但会失去设备指纹与断档检测，等级封顶 grade_c。",
            "how": "手机录 WAV → 传到电脑 → 桌面端导入（见 ADR-004）"}


def check_loopback(port: int) -> dict:
    """没有手机也能做的事：桌面浏览器本身就是安全上下文。"""
    return {"name": "无手机 · 桌面回环自测", "status": OK,
            "detail": "127.0.0.1 本身是安全上下文，可用电脑麦克风走完整条链路。",
            "how": (f"python server/main.py\n"
                    f"       浏览器打开 http://127.0.0.1:{port}/capture.html\n"
                    f"       以及 python scripts/verify_capture.py（完全不需要麦克风）")}


def main() -> int:
    port = DEFAULT_PORT
    print("=" * 72)
    print("08 真机采集 · 接入体检")
    print("=" * 72)
    print(f"操作系统 : {platform.system()} {platform.release()} ({platform.machine()})")
    print(f"Python   : {sys.version.split()[0]}")
    ip = lan_ip()
    print(f"局域网 IP : {ip or '（取不到）'}")
    print()
    print("前提：浏览器只在安全上下文开放麦克风。")
    print(f"      手机直接访问 http://{ip or '192.168.x.x'}:{port} 一定失败 —— 这不是 bug。")
    print()

    checks = [
        check_adb(port),
        check_tailscale(port),
        check_openssl(port),
        check_loopback(port),
        check_import_fallback(),
    ]

    usable = 0
    for item in checks:
        mark = {OK: "[可用]", WARN: "[待装]", BAD: "[不可用]"}[item["status"]]
        if item["status"] == OK:
            usable += 1
        print(f"{mark} {item['name']}")
        print(f"       {item['detail']}")
        if item.get("how"):
            print(f"       → {item['how']}")
        print()

    print("=" * 72)
    print(f"结论：这台机器当前有 {usable} 条路可走。")
    if usable:
        print("      不确定选哪条：Android 选 adb reverse，iPhone 选 Tailscale，都不想装选桌面回环自测。")
    else:
        print("      没有可用路径，先按上面的「待装」提示补一项。")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
