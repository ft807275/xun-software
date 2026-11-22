"""Run a short-lived, single-mailbox Cloudflare tunnel to the password-protected app."""

import argparse, contextlib, datetime, hashlib, os, pathlib, platform, queue, re, shutil, signal, subprocess, sys, tarfile, tempfile, threading, time, urllib.request

RELEASE = "2026.11.1"
HASHES = {
    "cloudflared-windows-amd64.exe": "341deda3db5ec498a0482254d6c38c0b7cf01a30c37bb5dd95d2216d08955e35",
    "cloudflared-darwin-arm64.tgz": "02fe4bcf08f2c09699cff30658228a739a0c47fb75f3653d1b8772a27ade4462",
    "cloudflared-darwin-amd64.tgz": "5e0403b188dfee71fbd9b995e7dc9910d61b661c52371935ab6475d41185632f",
}


def binary(folder):
    arch = platform.machine().lower()
    name = (
        "cloudflared-windows-amd64.exe"
        if os.name == "nt"
        else "cloudflared-darwin-"
        + ("arm64" if arch in ("arm64", "aarch64") else "amd64")
        + ".tgz"
    )
    dest = folder / ("cloudflared-" + RELEASE + (".exe" if os.name == "nt" else ""))
    if dest.is_file():
        return dest
    with tempfile.TemporaryDirectory(dir=folder) as tmp:
        blob = pathlib.Path(tmp) / "download"
        exe = pathlib.Path(tmp) / "binary"
        with (
            urllib.request.urlopen(
                "https://github.com/cloudflare/cloudflared/releases/download/"
                + RELEASE
                + "/"
                + name,
                timeout=100,
            ) as src,
            blob.open("wb") as out,
        ):
            shutil.copyfileobj(src, out)
        if hashlib.sha256(blob.read_bytes()).hexdigest() != HASHES[name]:
            raise ValueError("连接程序下载校验失败。")
        if name.endswith(".tgz"):
            with tarfile.open(blob) as arc:
                ent = next(
                    a
                    for a in arc
                    if a.isfile() and pathlib.Path(a.name).name == "cloudflared"
                )
                with arc.extractfile(ent) as src, exe.open("wb") as out:
                    shutil.copyfileobj(src, out)
        else:
            blob.rename(exe)
        exe.chmod(0o700)
        exe.replace(dest)
    return dest


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--email")
    ap.add_argument("--until", type=float)
    ap.add_argument("--data", type=pathlib.Path)
    args = ap.parse_args()
    if os.name != "nt":
        os.umask(0o077)
    email = (args.email or input("允许收验证码的邮箱：")).strip()
    if not re.fullmatch(r"[A-Za-z0-9._+%-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", email):
        raise ValueError("需要一个明确的邮箱地址。")
    now = time.time()
    until = min(args.until or now + 72 * 3600, now + 72 * 3600)
    if until <= now:
        return
    base = (
        pathlib.Path(os.environ["LOCALAPPDATA"])
        if os.name == "nt"
        else pathlib.Path.home() / "Library/Application Support"
    )
    data = args.data or base / "ZhijianKeywordLibrary"
    control = base / "ZhijianKeywordRemote"
    control.mkdir(mode=0o700, parents=True, exist_ok=True)
    urlfile = control / "当前外地入口.txt"
    tool = binary(control)
    root = pathlib.Path(__file__).resolve().parent
    stopped = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stopped.set())
    signal.signal(signal.SIGINT, lambda *_: stopped.set())
    with contextlib.ExitStack() as stack:

        def start(cmd, **kwargs):
            proc = subprocess.Popen(cmd, **kwargs)

            def end():
                if proc.poll() is None:
                    proc.terminate()
                    try:
                        proc.wait(timeout=6)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait()

            stack.callback(end)
            return proc

        origin = start(
            [
                sys.executable,
                "-X",
                "utf8",
                "-B",
                "-u",
                str(root / "server.py"),
                "--host",
                "127.0.0.1",
                "--port",
                "0",
                "--data",
                str(data),
            ],
            stdout=subprocess.PIPE,
            text=True,
        )
        line = origin.stdout.readline()
        if not line.startswith("PORT="):
            raise RuntimeError("私人词库服务未能启动。")
        port = int(line.split("=")[1])
        tunnel = start(
            [
                str(tool),
                "tunnel",
                "--no-autoupdate",
                "--protocol",
                "http2",
                "--allowed-mail",
                email,
                "--url",
                "http://127.0.0.1:" + str(port),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if sys.platform == "darwin":
            start(["/usr/bin/caffeinate", "-i", "-w", str(os.getpid())])
        events = queue.Queue()

        def read():
            for item in tunnel.stdout:
                if (
                    "trycloudflare.com" in item
                    or "One-Time PIN" in item
                    or "Registered tunnel connection" in item
                    or "Unable to establish connection" in item
                ):
                    events.put(item)

        threading.Thread(target=read, daemon=True).start()
        url = ""
        gated = registered = announced = False
        while (
            not stopped.is_set()
            and time.time() < until
            and origin.poll() is None
            and tunnel.poll() is None
        ):
            try:
                s = events.get(timeout=0.6)
            except queue.Empty:
                continue
            m = re.search(r"https://[a-z0-9-]+\.trycloudflare\.com\b", s)
            if m:
                url = m.group()
                print("已申请临时地址，正在连接主机：" + url, flush=True)
            if "Unable to establish connection" in s:
                print("正在重试与 Cloudflare 的加密连接。", flush=True)
            gated |= "One-Time PIN" in s
            registered |= "Registered tunnel connection" in s
            if url and gated and registered and not announced:
                expiry = datetime.datetime.fromtimestamp(until).strftime(
                    "%Y-%m-%d %H:%M"
                )
                msg = f"{url}\n允许邮箱：{email}\n本机时间截止：{expiry}\n首次使用：先验证邮箱，再用本机词库数据目录内的「首次启用码.txt」设置自己的词库密码。\n"
                urlfile.write_text(msg, encoding="utf-8")
                print(msg, flush=True)
                announced = True
        if announced:
            urlfile.write_text("本次临时入口已关闭。", encoding="utf-8")
        if not stopped.is_set() and time.time() < until:
            raise RuntimeError("临时连接已断开。请重新打开外地访问入口。")


if __name__ == "__main__":
    main()
