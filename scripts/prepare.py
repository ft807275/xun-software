"""Prepare a new, verified portable installation, including the later saved records."""
import argparse
from contextlib import closing
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import sqlite3
import sys
from tempfile import TemporaryDirectory
from zipfile import ZipFile

from reassemble import copy_verified, reassemble

NAME = "勋的软件"
VALID_ENTRY = re.compile(
    r"(?:(?:industries|sections)/[1-9][0-9]*/)?(?:library\.sqlite3|(?:raw|media)/[a-f0-9]{64})"
)


def safe_member(path):
    if not VALID_ENTRY.fullmatch(path):
        raise ValueError(f"资料更新路径无效 {path}")
    return path


def add_file(archive, data, spec):
    name = safe_member(spec["path"])
    dest = data / name
    dest.parent.mkdir(parents=True, exist_ok=True)
    with archive.open("files/" + name) as block, dest.open("xb") as output:
        shutil.copyfileobj(block, output, 8 * 1024 * 1024)
    expected = {"size": archive.getinfo("files/" + name).file_size, "sha256": spec["sha256"]}
    copy_verified(dest, expected)


def update_database(archive, data, change):
    rel = safe_member(change["path"])
    path = data / rel
    copy_verified(path, {"size": path.stat().st_size, "sha256": change["base_sha256"]})
    previous = 0
    with archive.open("pages/" + rel) as incoming, path.open("r+b") as database:
        for offset, length in change["ranges"]:
            if not 0 < length <= 65536 or not previous <= offset <= change["size"] - length:
                raise ValueError(f"资料库更新区间无效 {rel}")
            block = incoming.read(length)
            if len(block) != length:
                raise ValueError(f"资料库更新不完整 {rel}")
            database.seek(offset)
            database.write(block)
            previous = offset + length
        if incoming.read(1):
            raise ValueError(f"资料库更新长度有误 {rel}")
        database.truncate(change["size"])
    copy_verified(path, change)
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as connection:
        if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise ValueError(f"更新后的资料库检查失败 {rel}")


def apply_update(update, data, base):
    with ZipFile(update) as archive:
        changes = json.loads(archive.read("updates.json"))
        if changes["base_sha256"] != base["sha256"]:
            raise ValueError("资料更新包和完整换机包版本不匹配")
        for change in changes["databases"]:
            update_database(archive, data, change)
        for spec in changes["add"]:
            add_file(archive, data, spec)
        for item in changes["remove"]:
            (data / safe_member(item)).unlink()
    print(f"资料已更新到 {changes['created']}", flush=True)


def extract_package(archive, stage):
    with ZipFile(archive) as data:
        for name in data.namelist():
            path = PurePosixPath(name)
            if not path.parts or path.parts[0] != NAME or ".." in path.parts or "\\" in name or ":" in name:
                raise ValueError(f"程序包路径无效 {name}")
        data.extractall(stage)
    for launcher in (stage / NAME).glob("*.command"):
        launcher.chmod(launcher.stat().st_mode | 0o100)


def prepare(downloads, target, manifest):
    target = target.resolve()
    if target.exists():
        raise ValueError(f"请选择新的安装文件夹，已有文件继续保留 {target}")
    update = manifest["records_update"]
    update_path = downloads / update["name"]
    copy_verified(update_path, update)
    full = reassemble(downloads, manifest, downloads)
    target.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=target.parent) as temp:
        extract_package(full, Path(temp))
        package = Path(temp) / NAME
        sys.path.insert(0, str(package / "program"))
        try:
            from workspaces import restore
            folder = package / "我的资料"
            restore(package / "library-data.zip", folder)
            apply_update(update_path, folder, manifest["restore"])
        finally:
            sys.path.pop(0)
        if target.exists():
            raise ValueError(f"请选择新的安装文件夹 {target}")
        package.rename(target)
    print(f"恢复完成，打开此文件夹中的 Mac 或 Windows 启动文件 {target}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("downloads", type=Path)
    parser.add_argument("target", type=Path)
    args = parser.parse_args()
    manifest_path = Path(__file__).resolve().parents[1] / "release-manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        prepare(args.downloads, args.target, manifest)
    except (OSError, ValueError, sqlite3.Error) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
