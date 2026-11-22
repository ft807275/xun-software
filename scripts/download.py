"""Download every asset declared in the current backup, verifying each file."""
import argparse
import json
from pathlib import Path
import subprocess

from reassemble import copy_verified


def verified(path, entry):
    if not path.is_file() or path.stat().st_size != entry["size"]:
        return False
    try:
        copy_verified(path, entry)
    except ValueError:
        return False
    return True


def download(root, destination, gh):
    manifest = json.loads((root / "release-manifest.json").read_text(encoding="utf-8"))
    destination.mkdir(parents=True, exist_ok=True)
    incoming = destination / ".github-incoming"
    incoming.mkdir(exist_ok=True)
    groups = {}
    release = manifest.get("release_tag", "v" + manifest["version"])
    base = manifest["restore"]
    groups[base.get("release_tag", release)] = list(base["parts"])
    for key in ("program", "records_update", "project_files", "workspace_update"):
        if key in manifest:
            entry = manifest[key]
            groups.setdefault(entry.get("release_tag", release), []).append(entry)
    for tag, assets in groups.items():
        pending = []
        for entry in assets:
            name = entry["name"]
            if Path(name).name != name or "\\" in name or ":" in name:
                raise ValueError("无效的 GitHub 发布附件名")
            if verified(destination / name, entry):
                print(f"已校验 {name}", flush=True)
                continue
            partial = incoming / name
            if verified(partial, entry):
                partial.replace(destination / name)
            else:
                pending.append(entry)
        if not pending:
            continue
        args = [gh, "release", "download", tag, "--repo", "ft807275/xun-software",
                "--dir", str(incoming), "--clobber"]
        for entry in pending:
            args.extend(("--pattern", entry["name"]))
        result = subprocess.run(args)
        missing = []
        for entry in pending:
            name = entry["name"]
            partial = incoming / name
            if verified(partial, entry):
                partial.replace(destination / name)
                print(f"已校验 {name}", flush=True)
            else:
                missing.append(name)
        if missing:
            raise ValueError(f"{tag} 仍有附件未下载完整，重新运行可保留已校验的文件。"
                             f"待下载 {'、'.join(missing)}，GitHub CLI 状态 {result.returncode}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("downloads", type=Path)
    parser.add_argument("--gh", default="gh")
    args = parser.parse_args()
    try:
        download(Path(__file__).resolve().parents[1], args.downloads, args.gh)
    except (ValueError, OSError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
