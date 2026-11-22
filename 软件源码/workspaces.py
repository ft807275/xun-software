"""Industry catalogue, independent SQLite libraries, and portable all-industry backups."""

import hashlib
import os
import re
import shutil
import sqlite3
import tempfile
import time
import zipfile
from contextlib import closing
from pathlib import Path

import sections
import presets
from library import dbopen, init, norm, rows


def location(root, industry):
    if industry < 0:
        return sections.location(root, -industry)
    return root if industry == 1 else root / "industries" / str(industry)


def catalog(db):
    return rows(db, "SELECT id,name FROM industry_catalog ORDER BY id")


def gallery_total(root):
    with closing(dbopen(root)) as master:
        industries = catalog(master)
    digests = set()
    for item in industries:
        with closing(dbopen(location(root, item["id"]))) as db:
            digests.update(row[0] for row in db.execute("SELECT digest FROM gallery_images"))
    return len(digests)


def initialize(root):
    init(root)
    with closing(dbopen(root)) as db, db:
        db.execute(
            "CREATE TABLE IF NOT EXISTS industry_catalog(id INTEGER PRIMARY KEY,name TEXT NOT NULL, name_key TEXT NOT NULL UNIQUE)"
        )
        db.execute("INSERT OR IGNORE INTO industry_catalog VALUES(1,'包装袋','包装袋')")
        db.execute("""CREATE TABLE IF NOT EXISTS recent_project(slot INTEGER PRIMARY KEY CHECK(slot=1),
                   industry INTEGER NOT NULL,section INTEGER NOT NULL,project INTEGER NOT NULL)""")
        db.execute(presets.SCHEMA)
        children = catalog(db)[1:]
    import skill_library
    with closing(dbopen(root)) as db:
        db.executescript(skill_library.SCHEMA)
    sections.initialize(root)
    for item in children:
        folder = location(root, item["id"])
        if not (folder / "library.sqlite3").is_file():
            raise ValueError("行业数据库缺失，请从整库备份恢复。")
        init(folder, seed=False, industry_name=item["name"])


def create_industry(root, name):
    name = str(name).strip()
    if not 1 <= len(name) <= 80:
        raise ValueError("请填写 1 至 80 个字符的行业名称。")
    with closing(dbopen(root)) as db, db:
        db.execute("BEGIN IMMEDIATE")
        found = db.execute(
            "SELECT id,name FROM industry_catalog WHERE name_key=?", (norm(name),)
        ).fetchone()
        if found:
            return dict(found, duplicate=True)
        ident = db.execute(
            "INSERT INTO industry_catalog(name,name_key) VALUES(?,?)",
            (name, norm(name)),
        ).lastrowid
        folder = location(root, ident)
        init(folder, seed=False, industry_name=name)
        return {"id": ident, "name": name, "duplicate": False}


def resolve(root, value):
    ident = int(value)
    if ident == 1:
        return root
    with closing(dbopen(root)) as db:
        if not db.execute(
            "SELECT 1 FROM industry_catalog WHERE id=?", (ident,)
        ).fetchone():
            raise ValueError("行业不存在，请重新选择。")
    return location(root, ident)


def remember_project(root, industry, section, project):
    with closing(dbopen(root)) as db, db:
        db.execute(
            """INSERT INTO recent_project(slot,industry,section,project) VALUES(1,?,?,?)
            ON CONFLICT(slot) DO UPDATE SET industry=excluded.industry,section=excluded.section,
            project=excluded.project WHERE (industry,section,project)<>(excluded.industry,excluded.section,excluded.project)""",
            (industry, section, project),
        )


def home_shortcuts(root):
    from project_archive import latest_archive, project_followup

    with closing(dbopen(root)) as db:
        industries = catalog(db)
        areas = rows(
            db,
            "SELECT id,name FROM top_sections WHERE kind IN ('build','store') ORDER BY id",
        )
        last = db.execute(
            "SELECT industry,section,project FROM recent_project WHERE slot=1"
        ).fetchone()
    owners = {i["id"]: i["name"] for i in industries}
    sections_by_id = {a["id"]: a["name"] for a in areas}
    latest, latest_industry = "", 1
    for ind in industries:
        with closing(dbopen(location(root, ind["id"]))) as saved:
            when = saved.execute(
                "SELECT created FROM batches ORDER BY id DESC LIMIT 1"
            ).fetchone()
            if when and when[0] > latest:
                latest, latest_industry = when[0], ind["id"]
    candidates = []
    if last and last["industry"] in owners and last["section"] in sections_by_id:
        candidates.append(tuple(last))
    candidates.extend((i["id"], 2, None) for i in industries)
    candidates.extend((1, a["id"], None) for a in areas if a["id"] != 2)
    for industry, section, ident in candidates:
        folder = (
            location(root, industry)
            if section == 2
            else sections.location(root, section)
        )
        with closing(dbopen(folder)) as db:
            project = (
                db.execute(
                    "SELECT id,name FROM build_projects WHERE id=?", (ident,)
                ).fetchone()
                if ident
                else db.execute(
                    "SELECT id,name FROM build_projects ORDER BY id DESC LIMIT 1"
                ).fetchone()
            )
            if not project:
                continue
            followup = project_followup(db, project["id"])
            step = db.execute(
                """SELECT title FROM build_steps WHERE project=? AND status<>'已完成'
                 ORDER BY (id IS ?) DESC,(status='进行中') DESC,seq,id LIMIT 1""",
                (project["id"], followup["nextTaskStep"]),
            ).fetchone()
            total, done = db.execute(
                "SELECT count(*),count(CASE WHEN status='已完成' THEN 1 END) FROM build_steps WHERE project=?",
                (project["id"],),
            ).fetchone()
            return {
                "industry": latest_industry,
                "project": dict(
                    project,
                    industry=industry,
                    section=section,
                    label=owners[industry] if section == 2 else sections_by_id[section],
                    step=step[0] if step else "",
                    total=total,
                    done=done,
                    visited=ident is not None,
                    latestArchive=latest_archive(db, project["id"]),
                    **followup,
                ),
            }
    return {"industry": latest_industry, "project": None}


def snapshot_children(db):
    result = []
    if db.execute(
        "SELECT 1 FROM sqlite_master WHERE name='industry_catalog'"
    ).fetchone():
        result.extend(
            r[0]
            for r in db.execute(
                "SELECT id FROM industry_catalog WHERE id>1 ORDER BY id"
            )
        )
    if db.execute("SELECT 1 FROM sqlite_master WHERE name='top_sections'").fetchone():
        result.extend(
            -r[0]
            for r in db.execute("SELECT id FROM top_sections WHERE id>=3 ORDER BY id")
        )
    return result


def digest_file(path):
    sha = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            sha.update(block)
    return sha.hexdigest()


def raw_digests(db):
    sql = "SELECT DISTINCT digest FROM archived"
    if db.execute("SELECT 1 FROM sqlite_master WHERE name='import_runs'").fetchone():
        sql += " UNION SELECT digest FROM import_runs"
    return [row[0] for row in db.execute(sql)]


def snapshot_members(archive):
    members = archive.infolist()
    names = [item.filename for item in members]
    if "library.sqlite3" not in names or len(set(names)) != len(names) or any(
        not re.fullmatch(
            r"(?:(?:industries|sections)/[1-9][0-9]*/)?(?:library\.sqlite3|(?:raw|media)/[a-f0-9]{64})",
            name,
        )
        for name in names
    ):
        raise ValueError("备份文件结构无效，请选完整的资料库备份。")
    return members


def snapshot_inventory(members):
    return {
        "databases": sum(item.filename.endswith("library.sqlite3") for item in members),
        "originals": sum("raw" in item.filename.split("/") for item in members),
        "media": sum("media" in item.filename.split("/") for item in members),
        "restore_bytes": sum(item.file_size for item in members),
    }


def backup(root, target, progress=None):
    root = Path(root)
    with (
        tempfile.TemporaryDirectory() as tmp,
        zipfile.ZipFile(
            target,
            "w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=1,
            allowZip64=True,
        ) as z,
    ):
        ids = [1]
        labels = {1: "主资料库"}
        for done, ident in enumerate(ids):
            folder = location(root, ident)
            snap = Path(tmp) / ("industry-" + str(ident) + ".sqlite3")
            label = labels.get(ident, "资料库 " + str(ident))
            last_update = 0.0

            def report(stage, written=0, written_total=0, force=False):
                nonlocal last_update
                now = time.monotonic()
                if progress and (force or now - last_update >= 0.5):
                    progress(done, len(ids), label, stage, written, written_total)
                    last_update = now

            report("database", force=True)
            with closing(dbopen(folder)) as src, closing(sqlite3.connect(snap)) as dst:
                if progress:
                    src.backup(dst, pages=256, progress=lambda _, remaining, total: report("database", total - remaining, total))
                else:
                    src.backup(dst)
                dst.execute("PRAGMA secure_delete=ON")
                dst.execute("DELETE FROM settings WHERE k='password'")
                dst.commit()
                has_media = dst.execute("SELECT 1 FROM sqlite_master WHERE name='gallery_external'").fetchone()
                media = [r[0] for r in dst.execute("SELECT DISTINCT digest FROM gallery_external")] if has_media else []
                files = raw_digests(dst)
                if ident == 1:
                    ids.extend(snapshot_children(dst))
                    for table, sign in (("industry_catalog", 1), ("top_sections", -1)):
                        if dst.execute("SELECT 1 FROM sqlite_master WHERE name=?", (table,)).fetchone():
                            labels.update({r[0] * sign: r[1] for r in dst.execute("SELECT id,name FROM " + table)})
                    label = labels[1]
            prefix = "" if ident == 1 else folder.relative_to(root).as_posix() + "/"
            total_files = 1 + len(files) + len(media)
            report("archive", 0, total_files, force=True)
            z.write(snap, prefix + "library.sqlite3")
            written = 1
            for digest in files:
                z.write(folder / "raw" / digest, prefix + "raw/" + digest)
                written += 1
                report("archive", written, total_files)
            for digest in media:
                if not re.fullmatch("[a-f0-9]{64}",digest): raise ValueError("图片文件编号无效。")
                z.write(folder/"media"/digest,prefix+"media/"+digest,compress_type=zipfile.ZIP_STORED)
                written += 1
                report("archive", written, total_files)
            snap.unlink()
            if progress:
                progress(done + 1, len(ids), "", "packaging", 0, 0)
        return dict(snapshot_inventory(z.infolist()), libraries=[labels[i] for i in ids])


def restore(archive, destination, progress=None):
    dest = Path(destination).absolute()
    if dest.exists():
        raise ValueError("恢复目录已存在，已有资料受到保护。")
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=dest.parent) as tmp:
        out = Path(tmp) / "library"
        out.mkdir(mode=0o700)
        verified_files = set()
        written = 0
        last_update = 0.0
        try:
            with zipfile.ZipFile(archive) as z:
                members = snapshot_members(z)
                inventory = snapshot_inventory(members)
                total = inventory["restore_bytes"]
                databases = inventory["databases"]
                free = shutil.disk_usage(dest.parent).free
                if free < total:
                    raise ValueError(
                        f"磁盘空间不足。恢复至少需要 {total / 10**9:.2f} GB，"
                        f"当前可用 {free / 10**9:.2f} GB。请换到空间充足的磁盘再打开。"
                    )
                if progress:
                    progress("extract", 0, total)
                    last_update = time.monotonic()
                for member in members:
                    path = out / member.filename
                    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                    digest = None if path.name == "library.sqlite3" else hashlib.sha256()
                    with z.open(member) as src, path.open("xb") as dst:
                        while block := src.read(1024 * 1024):
                            dst.write(block)
                            written += len(block)
                            if digest is not None:
                                digest.update(block)
                            if progress and time.monotonic() - last_update >= 2:
                                progress("extract", written, total)
                                last_update = time.monotonic()
                    if digest is not None:
                        if digest.hexdigest() != path.name:
                            raise ValueError("备份中的原件校验失败，请检查备份是否完整。")
                        verified_files.add(path)
                    path.chmod(0o600)
        except (EOFError, zipfile.BadZipFile) as exc:
            raise ValueError("备份 ZIP 已损坏或下载不完整，请重新取得完整文件。") from exc
        if progress:
            progress("extract", written, total)
        ids = [1]
        for done, ident in enumerate(ids):
            folder = location(out, ident)
            dbfile = folder / "library.sqlite3"
            if not dbfile.is_file():
                raise ValueError("缺少行业数据库。")
            if progress:
                progress("verify", done, databases)
            with closing(sqlite3.connect(dbfile)) as db:
                if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                    raise ValueError("数据库校验失败。")
                if ident == 1:
                    ids.extend(snapshot_children(db))
                if db.execute("SELECT 1 FROM sqlite_master WHERE name='gallery_external'").fetchone():
                    for (digest,) in db.execute("SELECT DISTINCT digest FROM gallery_external"):
                        if not re.fullmatch("[a-f0-9]{64}", digest) or folder / "media" / digest not in verified_files:
                            raise ValueError("备份缺少产品图原件。")
                for digest in raw_digests(db):
                    if (
                        not re.fullmatch(r"[a-f0-9]{64}", digest)
                        or folder / "raw" / digest not in verified_files
                    ):
                        raise ValueError("备份缺少导入的原始文件。")
        for namespace, expected in [
            ("industries", {str(i) for i in ids if i > 1}),
            ("sections", {str(-i) for i in ids if i < 0}),
        ]:
            children = out / namespace
            found = {p.name for p in children.iterdir()} if children.exists() else set()
            if found != expected:
                raise ValueError("备份目录与资料清单不一致。")
        if dest.exists():
            raise ValueError("目标已存在，请重新打开现有资料库。")
        os.rename(out, dest)
        if progress:
            progress("verify", len(ids), len(ids))
