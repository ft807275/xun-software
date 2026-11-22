"""Verify and reassemble downloaded GitHub release volumes."""
import argparse
import hashlib
import json
import re
import tempfile
from pathlib import Path


def copy_verified(source, expected, destination=None, overall=None):
    count = 0
    digest = hashlib.sha256()
    with source.open("rb") as stream:
        while block := stream.read(8 * 1024 * 1024):
            count += len(block)
            digest.update(block)
            if overall is not None:
                overall.update(block)
            if destination is not None:
                destination.write(block)
    if count != expected["size"] or digest.hexdigest() != expected["sha256"]:
        raise ValueError(f"校验失败，请重新下载 {source.name}")
    return count


def reassemble(downloads, manifest, output_dir):
    package = manifest["restore"]
    output = output_dir / package["name"]
    if output.exists():
        copy_verified(output, package)
        print(f"现有完整换机包已通过校验，保留 {output}")
        return output
    if any(not re.fullmatch(r"xun-restore-[0-9.]+\.part[0-9]{2,3}", item["name"])
           for item in package["parts"]):
        raise ValueError("分卷清单无效")
    output_dir.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    written = 0
    with tempfile.NamedTemporaryFile(dir=output_dir, delete=False) as partial:
        pending = Path(partial.name)
        try:
            for item in package["parts"]:
                file = downloads / item["name"]
                if not file.is_file():
                    raise ValueError(f"缺少分卷 {file.name}")
                written += copy_verified(file, item, partial, digest)
                print(f"已校验 {file.name}", flush=True)
            if written != package["size"] or digest.hexdigest() != package["sha256"]:
                raise ValueError("重组后的换机包与清单不一致")
            partial.close()
            if output.exists():
                raise ValueError(f"目标已存在，请检查 {output}")
            pending.replace(output)
        finally:
            pending.unlink(missing_ok=True)
    print(f"完整换机包校验成功 {output}", flush=True)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("downloads", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--manifest", type=Path, default=Path(__file__).resolve().parents[1] / "release-manifest.json")
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    try:
        reassemble(args.downloads, manifest, args.output_dir or args.downloads)
    except (ValueError, OSError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
