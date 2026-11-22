"""Find original spreadsheets and their results in both generations of import records."""

import heapq
import json
import re
from contextlib import closing

from autoimport import run_record
from library import dbopen, keyword_batch_summary, rows
from workspaces import catalog, location

PAGE = 30
BATCH_JOIN = "FROM batches b LEFT JOIN archived a ON a.batch=b.id LEFT JOIN site_batches s ON s.batch=b.id"
BATCH_KEY = "coalesce(a.digest,'batch:' || b.id)"

FILE_ROWS = f"""
WITH copies AS (
    SELECT {BATCH_KEY} AS key, b.filename, b.created AS stamp,
           b.id AS seq, 0 AS is_run, '' AS run, '' AS job, b.id AS batch,
           a.digest IS NOT NULL AS archived, 'done' AS state, 0 AS pending, 0 AS resumable
    {BATCH_JOIN}
    UNION ALL
    SELECT digest, filename, updated, rowid, 1, id, job, NULL, 1, state, pending, resume_job=job AND resume_job<>''
    FROM import_runs
), ranked AS (
    SELECT *, instr(lower(filename),lower(?)) > 0 AS matches,
           row_number() OVER (PARTITION BY key ORDER BY is_run DESC, stamp DESC, seq DESC) AS priority
    FROM copies
), files AS (
    SELECT key, max(CASE WHEN priority=1 THEN filename END) AS filename,
           max(stamp) AS stamp, max(run) AS run, max(job) AS job, max(batch) AS batch,
           max(archived) AS archived, max(CASE WHEN is_run=1 THEN state END) AS state,
           max(pending) AS pending, max(resumable) AS resumable, count(batch) AS batches,
           max(CASE WHEN matches THEN filename END) AS matched_filename
    FROM ranked
    GROUP BY key
    HAVING max(matches) > 0
)
"""


def order(item):
    return item["stamp"], item["industry"], item["key"]


def page(root, scope, query, pending_only, before=None):
    query = str(query).strip()[:300]
    with closing(dbopen(root)) as db:
        industries = catalog(db)
    if scope != "all":
        industries = [item for item in industries if item["id"] == int(scope)]
        if not industries:
            raise ValueError("行业不存在。")
    streams = []
    for industry in industries:
        sql = FILE_ROWS + "SELECT * FROM files WHERE 1=1"
        args = [query]
        if pending_only:
            sql += " AND (state NOT IN ('done','replaced') OR pending>0)"
        if before:
            sql += " AND (stamp,?,key) < (?,?,?)"
            args.extend((industry["id"], *before))
        sql += " ORDER BY stamp DESC, key DESC LIMIT ?"
        with closing(dbopen(location(root, industry["id"]))) as db:
            files = rows(db, sql, (*args, PAGE + 1))
        streams.append([dict(item, industry=industry["id"], industry_name=industry["name"]) for item in files])
    available = heapq.nlargest(PAGE + 1, (item for stream in streams for item in stream), key=order)
    return {
        "items": available[:PAGE],
        "before": order(available[PAGE - 1]) if len(available) > PAGE else None,
    }


def read_cursor(value):
    if not value:
        return None
    cursor = json.loads(value)
    if (not isinstance(cursor, list) or len(cursor) != 3 or
        not isinstance(cursor[0], str) or type(cursor[1]) is not int or
        not isinstance(cursor[2], str)):
        raise ValueError("翻页位置无效，请重新搜索。")
    return cursor


def live_state(item, jobs):
    if item["state"] in ("queued", "running"):
        status = jobs.get(item["job"], {}).get("status")
        if status in ("queued", "running"):
            item["state"] = status
        elif not (item.get("resumable") or (item.get("resume_job") and item["resume_job"] == item["job"])):
            item["state"] = "interrupted"
    return item


def file_details(db, key):
    if not re.fullmatch(r"(?:[a-f0-9]{64}|batch:[1-9][0-9]{0,18})", key):
        raise ValueError("找不到这份导入文件。")
    batches = rows(db,
        "SELECT b.id,b.filename,b.created,b.written,b.added,b.blank,b.distinct_words,b.prior_word_id,s.valid AS site_valid "
        + BATCH_JOIN + f" WHERE {BATCH_KEY}=? ORDER BY b.id DESC", (key,))
    record = db.execute("SELECT id FROM import_runs WHERE digest=?", (key,)).fetchone()
    run = run_record(db, record["id"]) if record else None
    if not batches and not run:
        raise ValueError("找不到这份导入文件。")
    summaries = {}
    for batch in batches:
        if batch["site_valid"] is None:
            summary = keyword_batch_summary(db, batch)
            summaries[batch["id"]] = summary
            batch.update(summary)
    if run:
        for item in run["sheets"]:
            if item.get("kind") == "words" and item.get("id") in summaries:
                item.update(summaries[item["id"]])
    known = {row["id"] for row in run["sheets"] if row.get("id") and not row.get("error")} if run else set()
    return {"run": run, "other_batches": [batch for batch in batches if batch["id"] not in known]}
