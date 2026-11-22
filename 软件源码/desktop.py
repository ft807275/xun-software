"""Cross-platform single-user launcher for Python 3.9+ with SQLite FTS5."""

import argparse, os, pathlib, secrets, subprocess, sys, webbrowser
from urllib.parse import urlencode

root = pathlib.Path(__file__).resolve().parent
if sys.platform == "darwin":
    base = pathlib.Path.home() / "Library" / "Application Support"
elif os.name == "nt":
    base = pathlib.Path(os.environ["LOCALAPPDATA"])
else:
    base = pathlib.Path(
        os.environ.get("XDG_DATA_HOME", str(pathlib.Path.home() / ".local/share"))
    )
parser = argparse.ArgumentParser()
parser.add_argument("--data", type=pathlib.Path, default=base / "ZhijianKeywordLibrary")
data = parser.parse_args().data.expanduser().resolve()
ticket = secrets.token_urlsafe(32)
env = dict(
    os.environ, PAPER_LOCAL_KEY=secrets.token_urlsafe(32), PAPER_LAUNCH_TICKET=ticket
)
with subprocess.Popen(
    [
        sys.executable,
        "-X",
        "utf8",
        "-B",
        "-u",
        str(root / "server.py"),
        "--local",
        "--port",
        "0",
        "--data",
        str(data),
    ],
    env=env,
    stdout=subprocess.PIPE,
    text=True,
) as p:
    try:
        line = p.stdout.readline().strip()
        if not line.startswith("PORT="):
            raise RuntimeError("请检查 Python 和 SQLite FTS5 环境。")
        url = (
            "http://127.0.0.1:"
            + str(int(line[5:]))
            + "/open?"
            + urlencode({"ticket": ticket})
        )
        webbrowser.open(url)
        print("勋的软件已打开。保持这个窗口运行，按 Ctrl+C 退出。")
        p.wait()
    except KeyboardInterrupt:
        pass
    finally:
        p.terminate()
