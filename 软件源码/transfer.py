"""Bundle the application together with a fresh, all-industry snapshot."""

import json, os, pathlib, shutil, time, zipfile
from workspaces import backup, snapshot_inventory, snapshot_members

APP_NAME = "勋的软件"
APP_VERSION = "2.9.71"
TOP = APP_NAME + "/"
SNAPSHOT = "library-data.zip"
BACKUP_INDEX = "换机清单.json"
BACKUP_README = "本次换机包包含的资料.txt"
ROOT = pathlib.Path(__file__).resolve().parent


def template_path():
    base = (
        pathlib.Path(os.environ["LOCALAPPDATA"])
        if os.name == "nt"
        else pathlib.Path.home() / "Library/Application Support"
    )
    return base / "ZhijianKeywordSoftware" / "portable-template.zip"


def make_template(package, output):
    manifest = package / "package-manifest.json"
    paths = json.loads(manifest.read_text(encoding="utf-8"))
    with zipfile.ZipFile(
        output, "w", zipfile.ZIP_DEFLATED, compresslevel=2, allowZip64=True
    ) as z:
        for name in [*paths, "package-manifest.json"]:
            rel = pathlib.PurePosixPath(name)
            if (
                rel.is_absolute()
                or ".." in rel.parts
                or rel.parts[0]
                not in {
                    "program",
                    "runtime",
                    "Windows-打开词库.cmd",
                    "Mac-打开词库.command",
                    "Windows-临时外地访问.cmd",
                    "Mac-临时外地访问.command",
                    "先看这里.txt",
                    "package-manifest.json",
                }
            ):
                raise ValueError("程序清单有误。")
            f = package / name
            if name == "program/seed.json":
                # The linked library or full snapshot already contains the owner's records.
                info = zipfile.ZipInfo.from_file(f, TOP + name)
                z.writestr(info, '{"sites":[],"keywords":[],"queries":[]}', compress_type=zipfile.ZIP_DEFLATED)
                continue
            z.write(
                f,
                TOP + name,
                compress_type=zipfile.ZIP_STORED
                if f.suffix in (".gz", ".zip", ".pkg")
                else zipfile.ZIP_DEFLATED,
            )


def write_program(output):
    package = ROOT.parent
    if (package / "package-manifest.json").exists():
        make_template(package, output)
    elif template_path().is_file():
        shutil.copyfile(template_path(), output)
    else:
        raise ValueError("本机缺少 Win11 / Mac 程序模板，可以先生成整库备份。")


def bundle(data, output, progress=None):
    if progress:
        progress(0, 0, "", "program", 0, 0)
    write_program(output)
    with zipfile.ZipFile(output, "a", allowZip64=True) as z:
        # Stream the data ZIP into the portable package to avoid keeping a
        # second full copy of the library in a temporary directory.
        with z.open(TOP + SNAPSHOT, "w", force_zip64=True) as snapshot:
            details = backup(data, snapshot, progress)
        details.update(version=APP_VERSION, created=time.strftime("%Y-%m-%d %H:%M:%S"))
        z.writestr(TOP + BACKUP_INDEX, json.dumps(details, ensure_ascii=False))
        unpack = sum(info.file_size for info in z.infolist())
        total = unpack + details["restore_bytes"]
        text = (
            f"勋的软件 {APP_VERSION} · 完整换机包\n生成时间 {details['created']}\n\n"
            f"资料库 {details['databases']} 个\n"
            f"上传原件 {details['originals']} 份\n单独保存的图库原件 {details['media']} 张\n"
            f"资料库清单 {'、'.join(details['libraries'])}\n\n"
            f"从已下载的 ZIP 解压并首次恢复，至少还需约 {total / 10**9:.2f} GB 可用空间。\n"
            f"如果软件文件已经解压，首次恢复资料至少还需约 {details['restore_bytes'] / 10**9:.2f} GB。\n"
            "保留此 ZIP，完整解压后用对应系统的启动文件打开。首次恢复会检查原件和数据库。\n"
        )
        z.writestr(TOP + BACKUP_README, text.encode("utf-8-sig"))


def inspect_backup(path):
    path = pathlib.Path(path)
    try:
        with zipfile.ZipFile(path) as z:
            members = z.infolist()
            names = {item.filename for item in members}
            result = {"name": path.name, "archive_bytes": path.stat().st_size}
            if "library.sqlite3" in names:
                return dict(result, type="backup", **snapshot_inventory(snapshot_members(z)))
            if TOP + "package-manifest.json" not in names:
                raise ValueError("请选择勋的软件生成的整库备份、完整换机包或程序升级包。")
            if len(names) != len(members):
                raise ValueError("备份 ZIP 的文件目录有重复项，请重新取得完整文件。")
            result["unpack_bytes"] = sum(item.file_size for item in members)
            if TOP + SNAPSHOT not in names:
                if TOP + BACKUP_INDEX in names:
                    raise ValueError("这个换机包缺少资料快照，请重新取得完整文件。")
                return dict(result, type="program")
            result["type"] = "transfer"
            if TOP + BACKUP_INDEX in names:
                index = z.getinfo(TOP + BACKUP_INDEX)
                if index.file_size > 64 * 1024:
                    raise ValueError("换机包的资料清单无效。")
                try:
                    info = json.loads(z.read(index))
                except (json.JSONDecodeError, UnicodeDecodeError, RecursionError):
                    raise ValueError("换机包的资料清单无效。") from None
                counts = ("databases", "originals", "media", "restore_bytes")
                if not isinstance(info, dict) or any(type(info.get(key)) is not int or info[key] < 0 for key in counts):
                    raise ValueError("换机包的资料清单无效。")
                libraries = info.get("libraries")
                if (not info["databases"] or not info["restore_bytes"] or not isinstance(libraries, list)
                    or len(libraries) != info["databases"] or any(not isinstance(name, str) for name in libraries)):
                    raise ValueError("换机包的资料清单无效。")
                result.update({key: info[key] for key in (*counts, "libraries")})
                for key in ("version", "created"):
                    if isinstance(info.get(key), str):
                        result[key] = info[key]
            return result
    except (EOFError, zipfile.BadZipFile):
        raise ValueError("备份 ZIP 已损坏或下载不完整，请重新取得完整文件。") from None
