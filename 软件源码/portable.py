"""Open a portable library and remember an explicitly selected existing data folder."""

import argparse
import base64
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from contextlib import closing
from tempfile import NamedTemporaryFile

from restore import restore_with_feedback
from transfer import BACKUP_INDEX, SNAPSHOT

DATA_LINK = "资料位置.json"


def existing_library(value):
    folder = Path(value).expanduser().resolve()
    if folder.name == "library.sqlite3" and folder.is_file():
        folder = folder.parent
    database = folder / "library.sqlite3"
    if not database.is_file():
        raise ValueError("请选择旧版的「我的资料」文件夹。")
    try:
        with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as db:
            tables = set(r[0] for r in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('words','settings','industry_catalog')"
            ))
    except sqlite3.Error as exc:
        raise ValueError("打不开这份资料库。请检查原文件夹是否可用。") from exc
    if tables != {"words", "settings", "industry_catalog"}:
        raise ValueError("请选择完整的主资料库文件夹。")
    return folder


def link_library(package, selected):
    folder = existing_library(selected)
    target = package / DATA_LINK
    with NamedTemporaryFile(mode="w", encoding="utf-8", dir=package, delete=False) as tmp:
        path = Path(tmp.name)
        json.dump({"data": str(folder)}, tmp, ensure_ascii=False)
    try:
        os.replace(path, target)
    finally:
        path.unlink(missing_ok=True)
    return folder


def remembered_library(package):
    try:
        location = json.loads((package / DATA_LINK).read_text(encoding="utf-8"))
        if isinstance(location, dict) and isinstance(location.get("data"), str) and location["data"]:
            return existing_library(location["data"])
    except (OSError, ValueError):
        return None


def choose_native_path(backup=False):
    if sys.platform == "darwin":
        prompt = ('choose file with prompt "选择勋的软件的备份 ZIP"' if backup
                  else 'choose folder with prompt "选择旧版的「我的资料」文件夹"')
        command = ["/usr/bin/osascript", "-e", f"POSIX path of ({prompt})"]
    elif os.name == "nt":
        script = r"""
            Add-Type -AssemblyName System.Windows.Forms
            [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
        """
        if backup:
            script += """
                $picker = New-Object System.Windows.Forms.OpenFileDialog
                $picker.Title = '选择勋的软件的备份 ZIP'
                $picker.Filter = 'ZIP (*.zip)|*.zip'
                if ($picker.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {
                    [Console]::Write($picker.FileName)
                }
            """
        else:
            script += """
                $picker = New-Object System.Windows.Forms.FolderBrowserDialog
                $picker.Description = '选择旧版的「我的资料」文件夹'
                $picker.ShowNewFolderButton = $false
                if ($picker.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {
                    [Console]::Write($picker.SelectedPath)
                }
            """
        payload = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
        command = ["powershell.exe", "-NoProfile", "-NonInteractive", "-STA", "-EncodedCommand", payload]
    else:
        raise OSError("没有可用的文件选择器。")
    ran = subprocess.run(command, capture_output=True, encoding="utf-8", errors="replace")
    if ran.returncode == 0:
        return ran.stdout.rstrip("\r\n") or None
    if sys.platform == "darwin" and "(-128)" in ran.stderr:
        return None
    raise OSError("无法打开文件选择器。")


def choose_library():
    try:
        return choose_native_path()
    except OSError:
        pass
    if sys.stdin.isatty():
        return input("请输入旧版「我的资料」文件夹的完整路径，或按回车退出：").strip().strip('"') or None
    raise ValueError("请选择旧版的「我的资料」文件夹，或用 --data-dir 指定路径。")


def prepare(package):
    if (package / DATA_LINK).exists():
        return remembered_library(package)
    folder = package / "我的资料"
    if not folder.exists():
        snap = package / SNAPSHOT
        if not snap.is_file():
            if (package / BACKUP_INDEX).is_file():
                raise ValueError("这个换机包缺少 library-data.zip，请完整解压 ZIP 后重新打开。")
            return None
        try:
            restore_with_feedback(snap, folder)
        except (FileExistsError, OSError, ValueError):
            if not (folder / "library.sqlite3").is_file():
                raise
    if not (folder / "library.sqlite3").is_file():
        raise ValueError("资料夹缺少数据库，请在新文件夹恢复备份。")
    return folder


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--remote", action="store_true")
    p.add_argument("--data-dir")
    args = p.parse_args()
    here = Path(__file__).resolve().parent
    package = here.parent
    try:
        data = link_library(package, args.data_dir) if args.data_dir else prepare(package)
        while data is None:
            selected = choose_library()
            if not selected:
                return
            try:
                data = link_library(package, selected)
            except ValueError as exc:
                print(exc, flush=True)
    except (ValueError, OSError) as exc:
        p.exit(1, str(exc) + "\n")
    print("当前资料夹：" + str(data), flush=True)
    try:
        subprocess.run(
            [
                sys.executable,
                "-X",
                "utf8",
                "-B",
                "-u",
                str(here / ("remote.py" if args.remote else "desktop.py")),
                "--data",
                str(data),
            ],
            check=True,
        )
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
