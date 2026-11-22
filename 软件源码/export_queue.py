"""Host-local export history and a restartable ZIP worker."""

from contextlib import closing
import json
import logging
import re
import sqlite3
import threading
import time
import uuid
import zipfile

import bulk_export
from presets import clean_filters
from transfer import bundle
from workspaces import backup

DAY = 86400
BACKUP_TYPES = {"backup": "整库备份", "transfer": "Win11 / Mac 换机包"}
JOB_TABLES = ("jobs", "filtered_jobs")
JOB_FIELDS = """(
    id TEXT PRIMARY KEY,
    config TEXT NOT NULL,
    title TEXT NOT NULL,
    state TEXT NOT NULL,
    created REAL NOT NULL,
    updated REAL NOT NULL,
    files_done INTEGER NOT NULL DEFAULT 0,
    files_total INTEGER NOT NULL DEFAULT 0,
    industry TEXT NOT NULL DEFAULT '',
    kind TEXT NOT NULL DEFAULT '',
    written INTEGER NOT NULL DEFAULT 0,
    written_total INTEGER NOT NULL DEFAULT 0,
    size INTEGER NOT NULL DEFAULT 0,
    error TEXT NOT NULL DEFAULT ''
)"""
SCHEMA = f"""
CREATE TABLE IF NOT EXISTS jobs{JOB_FIELDS};
CREATE TABLE IF NOT EXISTS filtered_jobs{JOB_FIELDS};
CREATE UNIQUE INDEX IF NOT EXISTS one_active_config ON jobs(config) WHERE state IN ('queued','running');
CREATE UNIQUE INDEX IF NOT EXISTS one_active_filtered_config ON filtered_jobs(config) WHERE state IN ('queued','running');
"""


def byte_range(header, size):
    match = re.fullmatch(r"bytes=(\d{0,20})-(\d{0,20})", header)
    if not match or not size or not any(match.groups()):
        raise ValueError("下载范围无效。")
    start, end = match.groups()
    if not start:
        if int(end) == 0:
            raise ValueError("下载范围无效。")
        return max(0, size - int(end)), size - 1
    start = int(start)
    end = min(int(end), size - 1) if end else size - 1
    if start > end:
        raise ValueError("下载范围无效。")
    return start, end


class ExportQueue:
    def __init__(self, root):
        self.root = root
        self.folder = root / "exports"
        self.folder.mkdir(mode=0o700, exist_ok=True)
        self.wake = threading.Event()
        with closing(self.connect()) as db, db:
            db.executescript(SCHEMA)
            db.execute("BEGIN IMMEDIATE")
            columns = {row[1] for row in db.execute("PRAGMA table_info(jobs)")}
            for name in ("files_total", "written_total"):
                if name not in columns:
                    db.execute("ALTER TABLE jobs ADD COLUMN " + name + " INTEGER NOT NULL DEFAULT 0")
        threading.Thread(target=self.worker, name="bulk-export", daemon=True).start()

    def connect(self):
        db = sqlite3.connect(self.folder / "jobs.sqlite3", timeout=10)
        db.row_factory = sqlite3.Row
        return db

    def enqueue(self, ids, kinds, title="", filters=None):
        if not isinstance(ids, list) or not isinstance(kinds, list):
            raise ValueError("请选择有效的行业和资料类型。")
        if any(type(i) not in (str, int) for i in ids) or any(not isinstance(k, str) for k in kinds):
            raise ValueError("请选择有效的行业和资料类型。")
        ids = sorted({int(i) for i in ids})
        kinds = sorted(set(kinds))
        selected = bulk_export.selection(self.root, ids, kinds)
        if not isinstance(title, str):
            raise ValueError("方案名称无效。")
        config = {"ids": ids, "kinds": kinds}
        default_title = "、".join(item["name"] for item in selected)
        if filters is not None:
            if len(ids) != 1 or set(kinds) - {"words", "evidence"} or not isinstance(filters, dict):
                raise ValueError("当前筛选可导出一个行业的关键词和来源明细。")
            config["filters"] = clean_filters("words", filters)
            default_title += " · 筛选词表"
        return self.add(
            json.dumps(config, ensure_ascii=False, separators=(",", ":"), sort_keys=True),
            (title.strip() or default_title)[:80],
            table="filtered_jobs" if filters is not None else "jobs",
        )

    def enqueue_backup(self, task):
        if not isinstance(task, str) or task not in BACKUP_TYPES:
            raise ValueError("请选择整库备份或换机包。")
        return self.add(json.dumps({"task": task}), BACKUP_TYPES[task])

    def add(self, config, title, *, table="jobs"):
        now = time.time()
        with closing(self.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(f"SELECT id FROM {table} WHERE config=? AND state IN ('queued','running')", (config,)).fetchone()
            if existing:
                ident = existing["id"]
            else:
                ident = uuid.uuid4().hex
                db.execute(f"INSERT INTO {table}(id,config,title,state,created,updated) VALUES(?,?,?,'queued',?,?)",
                    (ident, config, title, now, now))
        self.wake.set()
        return {"id": ident}

    def archive(self, ident):
        return self.folder / (ident + ".zip")

    def read(self, ident):
        if not isinstance(ident, str) or not re.fullmatch(r"[a-f0-9]{32}", ident):
            raise ValueError("找不到这次导出。")
        with closing(self.connect()) as db:
            for table in JOB_TABLES:
                row = db.execute(f"SELECT * FROM {table} WHERE id=?", (ident,)).fetchone()
                if row:
                    return self.describe(row)
        raise ValueError("找不到这次导出。")

    def list(self):
        with closing(self.connect()) as db:
            records = [row for table in JOB_TABLES for row in db.execute(f"SELECT * FROM {table}")]
        records.sort(key=lambda row: (row["state"] in ("queued", "running"), row["created"], row["id"]), reverse=True)
        return [self.describe(row) for row in records]

    def describe(self, row):
        item = dict(row)
        item.update(json.loads(item.pop("config")))
        if item["state"] == "ready":
            try:
                complete = self.archive(item["id"]).stat().st_size == item["size"]
            except FileNotFoundError:
                complete = False
            if not complete or item["updated"] < time.time() - 7 * DAY:
                item["state"] = "expired"
        return item

    def retry(self, ident):
        item = self.read(ident)
        if item.get("task") in BACKUP_TYPES:
            return self.enqueue_backup(item["task"])
        return self.enqueue(item["ids"], item["kinds"], item["title"], item.get("filters"))

    def worker(self):
        while True:
            self.wake.clear()
            try:
                self.run_pending()
            except Exception:
                logging.exception("导出队列暂时无法运行")
            self.wake.wait(5)

    def run_pending(self):
        # The desktop app and the optional remote server can share this data
        # folder. A separate SQLite lock elects one worker across both processes.
        with closing(sqlite3.connect(self.folder / "worker.sqlite3", timeout=0)) as guard:
            try:
                guard.execute("BEGIN EXCLUSIVE")
            except sqlite3.OperationalError as error:
                if "locked" in str(error):
                    return
                raise
            with closing(self.connect()) as db:
                self.expire(db)
                while True:
                    # An older server can share the same library. Keep filtered
                    # jobs out of its queue so it cannot export all the words instead.
                    choice = db.execute("""SELECT * FROM (
                        SELECT id,created,state,'jobs' AS job_table FROM jobs WHERE state IN ('running','queued')
                        UNION ALL
                        SELECT id,created,state,'filtered_jobs' FROM filtered_jobs WHERE state IN ('running','queued')
                    ) ORDER BY state='running' DESC, created, id LIMIT 1""").fetchone()
                    if not choice:
                        break
                    table = choice["job_table"]
                    job = db.execute(f"SELECT * FROM {table} WHERE id=?", (choice["id"],)).fetchone()
                    self.build(db, job, table)

    def build(self, db, job, table):
        ident = job["id"]
        target = self.archive(ident)
        partial = target.with_suffix(".part")
        config = json.loads(job["config"])
        task = config.get("task")
        count = 0 if task in BACKUP_TYPES else len(config["ids"]) * len(config["kinds"])
        try:
            if not zipfile.is_zipfile(target):
                with db:
                    db.execute(f"""UPDATE {table} SET state='running', updated=?,
                        files_done=0, files_total=?, industry='', kind='', written=0, written_total=0 WHERE id=?""",
                        (time.time(), count, ident))

                def progress(done, total, industry, kind, written, written_total):
                    with db:
                        db.execute(f"""UPDATE {table} SET files_done=?, files_total=?, industry=?, kind=?,
                            written=?, written_total=?, updated=? WHERE id=?""",
                            (done, total, industry, kind, written, written_total, time.time(), ident))

                if task == "backup":
                    backup(self.root, partial, progress)
                elif task == "transfer":
                    bundle(self.root, partial, progress)
                else:
                    bulk_export.build(self.root, partial, config["ids"], config["kinds"],
                        lambda done, industry, kind, written: progress(done, count, industry, kind, written, 0),
                        filters=config.get("filters"))
                partial.replace(target)
            with db:
                db.execute(f"""UPDATE {table} SET state='ready', updated=?, files_done=max(files_total,?),
                    size=?, industry='', kind='', written=0, written_total=0, error='' WHERE id=?""",
                    (time.time(), count, target.stat().st_size, ident))
        except Exception as error:
            logging.exception("生成导出 ZIP 失败")
            message = str(error) if isinstance(error, ValueError) else "生成失败，请检查资料库和磁盘可用空间后重试。"
            with db:
                db.execute(f"UPDATE {table} SET state='error', updated=?, error=? WHERE id=?", (time.time(), message, ident))
        finally:
            partial.unlink(missing_ok=True)

    def expire(self, db):
        now = time.time()
        with db:
            for table in JOB_TABLES:
                for row in db.execute(f"SELECT id FROM {table} WHERE state='ready' AND updated<?", (now - 7 * DAY,)).fetchall():
                    try:
                        self.archive(row["id"]).unlink(missing_ok=True)
                    except PermissionError:
                        # Windows can keep a file locked while a download is open.
                        continue
                    db.execute(f"UPDATE {table} SET state='expired' WHERE id=?", (row["id"],))
                db.execute(f"DELETE FROM {table} WHERE state IN ('error','expired') AND updated<?", (now - 30 * DAY,))
