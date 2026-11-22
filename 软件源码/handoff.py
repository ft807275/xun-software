"""Open the owner's project workspace or prepare a copy of its archived site."""
import hashlib
import io
import os
import plistlib
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
import project_archive

SOURCE_ARCHIVE = """SELECT f.digest,f.id FROM build_files f JOIN build_entries e ON e.id=f.entry
    JOIN build_steps s ON s.id=e.step WHERE s.project=? AND e.kind='仓库原件' AND lower(f.filename) LIKE '%.zip'
    ORDER BY e.created DESC,f.id DESC LIMIT 1"""


def mac_codex():
    if sys.platform != "darwin":
        return None
    for location in (Path("/Applications"), Path.home() / "Applications"):
        for name in ("ChatGPT.app", "Codex.app"):
            app = location / name
            try:
                manifest = plistlib.loads((app / "Contents/Info.plist").read_bytes())
            except (OSError, ValueError, plistlib.InvalidFileException):
                continue
            if not isinstance(manifest, dict) or manifest.get("CFBundleIdentifier") != "com.openai.codex":
                continue
            for filename in (
                "Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex",
                "Contents/Resources/codex",
            ):
                cli = app / filename
                if cli.is_file() and os.access(cli, os.X_OK):
                    return cli
            cli = shutil.which("codex")
            if cli:
                return Path(cli)
    return None


def workspace_options(db, pid, local):
    if not local:
        return {"local": False, "folders": [], "archive": False, "codex": False}
    rows = db.execute(
        """SELECT f.id,f.directory FROM chat_folders f WHERE f.project=? AND f.enabled=1
           ORDER BY (SELECT max(c.stamp) FROM chat_candidates c WHERE c.rule=f.id) DESC,f.id DESC""",
        (pid,),
    )
    folders = [
        {"id": row["id"], "name": Path(row["directory"]).name, "path": row["directory"],
         "available": Path(row["directory"]).is_absolute() and Path(row["directory"]).is_dir()}
        for row in rows
    ]
    return {"local": True, "folders": folders, "archive": bool(db.execute(SOURCE_ARCHIVE, (pid,)).fetchone()),
            "codex": bool(mac_codex())}


def open_workspace(db, pid, selection):
    if type(selection) is not int or not 0 < selection < 2**63:
        raise ValueError("请从已关联的建站文件夹中选择。")
    row = db.execute(
        "SELECT directory FROM chat_folders WHERE project=? AND id=? AND enabled=1",
        (pid, selection),
    ).fetchone()
    if not row:
        raise ValueError("这个建站文件夹已解绑或属于其他项目。")
    folder = Path(row["directory"])
    if not folder.is_absolute() or not folder.is_dir():
        raise ValueError("本机暂时找不到这个文件夹。请连接硬盘或选用另一个已关联的目录。")
    cli = mac_codex()
    options = dict(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=12)
    if cli:
        try:
            if subprocess.run([str(cli), "app", str(folder)], **options).returncode == 0:
                return {"opened": "codex"}
        except (OSError, subprocess.TimeoutExpired):
            pass
    try:
        if os.name == "nt":
            os.startfile(str(folder))
        else:
            command = ["/usr/bin/open", "-a", "Finder"] if sys.platform == "darwin" else [shutil.which("xdg-open")]
            if not command[0] or subprocess.run([*command, str(folder)], **options).returncode:
                raise OSError("Folder launcher unavailable")
    except (OSError, subprocess.TimeoutExpired):
        raise ValueError("暂时无法打开文件夹，可以从交接窗口复制目录位置。") from None
    return {"opened": "folder"}


def prepare(db,pid,destination=None):
    p=db.execute("SELECT name FROM build_projects WHERE id=?",(pid,)).fetchone()
    if not p: raise ValueError("没有这个建站项目。")
    record=db.execute(SOURCE_ARCHIVE,(pid,)).fetchone()
    if not record: raise ValueError("这个项目尚未归档网站仓库 ZIP，仍可用 Codex 读取已有步骤和附件。")
    base=Path(destination) if destination else Path.home()/"Documents"/"建站工作区"/(re.sub(r'[^\w.\-（）]+','-',p["name"])[:70]+"-"+record[0][:8])
    for f in db.execute("SELECT directory FROM chat_folders WHERE project=? AND enabled=1",(pid,)):
        current=Path(f[0]);marker=current/"网站源码"/".资料库快照"
        if marker.is_file() and marker.read_text().strip()==record[0]:
            return dict(directory=str(current),code=str(marker.parent),existing=True)
    base.mkdir(parents=True,exist_ok=True)
    dest=base/"网站源码"
    if dest.exists():raise ValueError("已有同名源码目录，已保留现有编辑。请在原文件夹继续。")
    with tempfile.TemporaryDirectory(dir=base) as tmp:
        stage=Path(tmp)/"tree";stage.mkdir()
        blob=db.execute("SELECT body FROM build_blobs WHERE digest=?",(record[0],)).fetchone()[0]
        if hashlib.sha256(blob).hexdigest()!=record[0]:raise ValueError("原包校验未通过。")
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            members=[i for i in z.infolist() if not i.is_dir()]
            prefixes={PurePosixPath(i.filename).parts[0] for i in members}
            strip=len(prefixes)==1 and all(len(PurePosixPath(i.filename).parts)>1 for i in members)
            for i in members:
                path=PurePosixPath(i.filename)
                if path.is_absolute() or any(x in (".","..") or ":" in x or "\\" in x for x in path.parts) or stat.S_ISLNK(i.external_attr>>16):
                    raise ValueError("仓库含特殊路径，请下载原包查看。")
                target=stage.joinpath(*(path.parts[1:] if strip else path.parts))
                target.parent.mkdir(parents=True,exist_ok=True)
                with target.open("xb") as out,z.open(i) as inp:shutil.copyfileobj(inp,out,1024*1024)
        (stage/".资料库快照").write_text(record[0])
        rules=base/"AGENTS.md"
        original=rules.read_text() if rules.exists() else ""
        block=project_archive.tracking_rules(p,[r[0] for r in db.execute("SELECT title FROM build_steps WHERE project=? ORDER BY seq,id",(pid,))])
        old=re.search(r"\n?<!-- site-journal:begin -->.*?<!-- site-journal:end -->\n?",original,re.S)
        if old and "为「"+p["name"]+"」实际建站" not in old.group():raise ValueError("这个目录属于另一项目。")
        updated=original[:old.start()]+block+original[old.end():] if old else original+block
        additions="\n网站源码在同目录的「网站源码」下。在本目录启动建站对话，从最新项目记录读取进度。原仓库记录的旧电脑路径只作历史参考，工具应在当前电脑重新定位。\n"
        if additions not in updated:updated+=additions
        draft=Path(tmp)/"rules";draft.write_text(updated,encoding="utf-8")
        if dest.exists():raise ValueError("已有工作副本。")
        os.rename(stage,dest);os.replace(draft,rules)
    since=datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00","Z")
    with db:
        db.execute("""INSERT INTO chat_folders(project,directory,since,enabled) VALUES(?,?,?,1)
        ON CONFLICT(project,directory) DO UPDATE SET enabled=1""",(pid,str(base.resolve()),since))
    return dict(directory=str(base),code=str(dest),existing=False)

