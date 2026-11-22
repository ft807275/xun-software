"""Recognize and import each worksheet independently using the normal importers."""

import csv
import itertools
import json
import os
import re
from xml.etree.ElementTree import ParseError
import zipfile
from contextlib import closing
from library import TableFormatError, choose, clock, dbopen, file_rows, sheet_paths, domain, norm, import_file
from sitebook import mapping, import_sites


class BlankTable(ValueError):
    pass


DIRECTORY_REFERENCE_SHEETS = {
    "按产品筛选": "产品筛选参考已随原文件保存。",
    "官网证据": "官网证据已随原文件保存。",
    "待复核线索": "待复核线索已随原文件保存。",
    "检索范围": "检索范围已随原文件保存。",
}


def layout(path, sheet, filename):
    with closing(file_rows(path, sheet)) as source:
        sample = list(itertools.islice(source, 24))
    nonempty = [(i, r) for i, r in enumerate(sample) if any(str(c).strip() for c in r)]
    if not nonempty:
        raise BlankTable("空白工作表")
    for i, row in nonempty:
        words = choose(row)
        if words["word"] >= 0:
            return "words", {"mapping": words, "skip": i}
        sites = mapping(row)
        if sites["url"] >= 0:
            return "sites", {"mapping": sites, "skip": i}
    start = nonempty[0][0]

    def looks_like_site(value):
        host = domain(value.strip())
        return bool(
            host
            and re.fullmatch(r"(?:[\w-]+\.)+(?:[a-z]{2,63}|xn--[a-z0-9-]+)", host, re.I)
        )

    if all(len(r) == 1 and looks_like_site(r[0]) for _, r in nonempty):
        return "sites", {"skip": start}
    label = (sheet or filename).casefold()
    if all(len(r) == 1 for _, r in nonempty) and any(
        t in label for t in ("关键词", "词表", "搜索词", "keyword")
    ):
        return "words", {"skip": start, "headerless": True, "mapping": {"word": 0}}
    raise ValueError("未识别到关键词列或同行官网列")


def import_all(data, path, name, opts, digest, progress=lambda n: None, on_sheet=lambda item: None):
    sheets = [""]
    if zipfile.is_zipfile(path):
        try:
            with zipfile.ZipFile(path) as wb:
                sheets = [s for s, _ in sheet_paths(wb)]
            if not sheets:
                raise TableFormatError("Excel 文件没有可读取的工作表。请重新导出包含数据的 XLSX 或 CSV。")
        except TableFormatError as error:
            item = {"sheet": "", "error": str(error), "replace_file": True}
            on_sheet(item)
            return {"sheets": [item]}
    master_options = {}
    candidates = [sheet for sheet in sheets if norm(sheet) in ("同行总表", "同行主表")]
    if len(candidates) == 1 and any(norm(sheet) in DIRECTORY_REFERENCE_SHEETS for sheet in sheets):
        try:
            kind, options = layout(path, candidates[0], name)
            if kind == "sites":
                master_options = dict(options, directory_main=True)
        except (ValueError, KeyError, IndexError, csv.Error):
            pass  # The normal sheet handler reports a problem readers can fix.
    details = []
    total = 0
    for sheet in sheets:
        if sheet in opts.get("skip_sheets", ()):
            continue
        item = {"sheet": sheet}
        if master_options and norm(sheet) in DIRECTORY_REFERENCE_SHEETS:
            item["reference"] = DIRECTORY_REFERENCE_SHEETS[norm(sheet)]
            details.append(item)
            on_sheet(item)
            continue
        try:
            if master_options and sheet == candidates[0]:
                kind, options = "sites", master_options
            else:
                kind, options = layout(path, sheet, name)
            item["kind"] = kind
            loader = import_sites if kind == "sites" else import_file
            result = loader(
                data,
                path,
                name,
                dict(options, sheet=sheet),
                digest,
                lambda n: progress(total + n),
            )
            item.update(result)
            total += result["seen"]
            progress(total)
        except BlankTable as exc:
            item.update(error=str(exc), empty=True)
        except TableFormatError as exc:
            item.update(error=str(exc), replace_file=True)
        except (
            ValueError,
            KeyError,
            IndexError,
            csv.Error,
            ParseError,
            zipfile.BadZipFile,
        ) as exc:
            item["error"] = str(exc)
        details.append(item)
        on_sheet(item)
    return {"sheets": details}


def finish_replacements(db, ident, sheets, stamp):
    if any(not item.get("error") and (item.get("site_valid", item.get("written")) or 0) > 0 for item in sheets):
        db.execute(
            """UPDATE import_runs SET state='replaced',pending=0,updated=?
               WHERE replacement=? AND replacement<>'' AND state='needs_file'""",
            (stamp, ident),
        )


def save_upload(data, staged, name, digest, ident, replaces=""):
    original = data / "raw" / digest
    original.parent.mkdir(exist_ok=True)
    with closing(dbopen(data)) as db, db:
        db.execute("BEGIN IMMEDIATE")
        if replaces:
            previous = run_record(db, replaces)
            if previous["state"] != "needs_file":
                raise ValueError("这份文件的状态已变化，请刷新导入记录后再试。")
            if previous["digest"] == digest:
                raise ValueError("选中的仍是原失败文件。请选择重新导出的 XLSX 或 CSV。")
        if original.exists():
            staged.unlink()
        else:
            os.replace(staged, original)
        now = clock()
        db.execute(
            """INSERT INTO import_runs(id,filename,digest,created,updated,state,job,resume_job,resume_options)
               VALUES(?,?,?,?,?,'queued',?,?,?) ON CONFLICT(digest) DO NOTHING""",
            (ident, name, digest, now, now, ident, ident, json.dumps({"kind": "auto"})),
        )
        existing = db.execute("SELECT id FROM import_runs WHERE digest=?", (digest,)).fetchone()[0]
        run = run_record(db, existing)
        if replaces:
            db.execute("UPDATE import_runs SET replacement=? WHERE id=?", (existing, replaces))
            if run["state"] == "done" and not run["pending"]:
                finish_replacements(db, existing, run["sheets"], now)
        return original, run


def run_record(db, ident):
    row = db.execute("SELECT * FROM import_runs WHERE id=?", (str(ident),)).fetchone()
    if not row:
        raise ValueError("没有找到这次导入。")
    run = dict(row, sheets=json.loads(row["sheets"]))
    if run["state"] == "replaced":
        replacement = db.execute("SELECT filename,digest FROM import_runs WHERE id=?", (run["replacement"],)).fetchone()
        if replacement:
            run["replacement_file"] = dict(replacement)
    return run


def resume_candidate(db):
    entry = db.execute(
        """SELECT id FROM import_runs WHERE resume_job=job AND resume_job<>''
           AND state IN ('queued','running') ORDER BY state='running' DESC,updated,id LIMIT 1"""
    ).fetchone()
    return run_record(db, entry[0]) if entry else None


def recent_runs(db, before, pending_only):
    where = "WHERE rowid<?" + (" AND (state NOT IN ('done','replaced') OR pending>0)" if pending_only else "")
    rows = db.execute(
        """SELECT rowid AS seq,id,filename,created,updated,state,sheets,error,pending FROM import_runs """
        + where + " ORDER BY rowid DESC LIMIT 41", (before,),
    ).fetchall()
    items = [dict(r, sheets=json.loads(r["sheets"])) for r in rows[:40]]
    return dict(items=items, next_before=items[-1]["seq"] if len(rows) > 40 else None)


def save_state(data, ident, job, state, sheets=None, error=""):
    pending = None
    if sheets is not None:
        issues = [item for item in sheets if item.get("error") and not item.get("empty")]
        pending = len(issues)
        if state == "done" and issues and all(item.get("replace_file") for item in issues):
            state = "needs_file"
    with closing(dbopen(data)) as db, db:
        stamp = clock()
        changed = db.execute(
            """UPDATE import_runs SET state=?,updated=?,sheets=coalesce(?,sheets),error=?,pending=coalesce(?,pending)
               WHERE id=? AND job=?""",
            (state, stamp, json.dumps(sheets, ensure_ascii=False) if sheets is not None else None,
             error, pending, ident, job),
        )
        if changed.rowcount and state == "done" and pending == 0:
            finish_replacements(db, ident, sheets, stamp)
        return bool(changed.rowcount)


def start_retry(db, ident, job, previous, options):
    with db:
        if not db.execute(
            """UPDATE import_runs SET job=?,resume_job=?,resume_options=?,updated=?,state='queued',error=''
               WHERE id=? AND job=? AND NOT (resume_job=job AND state IN ('queued','running'))""",
            (job, job, json.dumps(options, ensure_ascii=False), clock(), ident, previous),
        ).rowcount:
            raise ValueError("这份文件的状态刚刚更新，请刷新后再试。")


def record_sheet(items, result):
    fields = ("sheet", "kind", "id", "seen", "written", "site_valid", "added", "blank",
              "distinct_words", "prior_word_id", "source_rows", "source_sites", "unlinked_rows",
              "market", "report_date", "inferred_sites",
              "duplicate", "error", "empty", "replace_file", "reference")
    result = {name: result[name] for name in fields if name in result}
    if not result.get("error") and result.get("site_valid", result.get("written")) == 0:
        result["error"] = "发现表头，但没有导入有效行。请核对字段和表头位置。"
    for i, item in enumerate(items):
        if item["sheet"] == result["sheet"]:
            items[i] = result
            return
    items.append(result)
