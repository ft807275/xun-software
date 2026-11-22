"""Project knowledge pages backed by the same database as their source records."""

import argparse
from contextlib import closing
import json
from pathlib import Path
import re
import sys

from library import clock, dbopen

SCHEMA = """
CREATE TABLE IF NOT EXISTS wiki_pages(
 project INTEGER NOT NULL REFERENCES build_projects(id), slug TEXT NOT NULL,
 title TEXT NOT NULL, summary TEXT NOT NULL, body TEXT NOT NULL, sources TEXT NOT NULL,
 related TEXT NOT NULL, updated TEXT NOT NULL, version INTEGER NOT NULL,
 PRIMARY KEY(project,slug));
CREATE TABLE IF NOT EXISTS wiki_updates(
 project INTEGER NOT NULL, slug TEXT NOT NULL, version INTEGER NOT NULL,
 updated TEXT NOT NULL, change TEXT NOT NULL,
 PRIMARY KEY(project,slug,version),
 FOREIGN KEY(project,slug) REFERENCES wiki_pages(project,slug));
CREATE TABLE IF NOT EXISTS wiki_automation(
 project INTEGER PRIMARY KEY REFERENCES build_projects(id), enabled INTEGER NOT NULL DEFAULT 0,
 since TEXT NOT NULL, checked TEXT NOT NULL DEFAULT '', warning TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS wiki_chat_updates(
 answer INTEGER PRIMARY KEY REFERENCES chat_text(id), prompt INTEGER REFERENCES chat_text(id),
 project INTEGER NOT NULL, slug TEXT NOT NULL, topic TEXT NOT NULL, body TEXT NOT NULL,
 sent TEXT NOT NULL, updated TEXT NOT NULL,
 FOREIGN KEY(project,slug) REFERENCES wiki_pages(project,slug));
CREATE INDEX IF NOT EXISTS wiki_chat_topic ON wiki_chat_updates(project,slug,topic,sent,answer);
CREATE TABLE IF NOT EXISTS wiki_pending_updates(
 answer INTEGER PRIMARY KEY REFERENCES chat_text(id), prompt INTEGER REFERENCES chat_text(id),
 project INTEGER NOT NULL REFERENCES build_projects(id), reason TEXT NOT NULL,
 slug TEXT NOT NULL, topic TEXT NOT NULL, body TEXT NOT NULL,
 sent TEXT NOT NULL, stamped TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS wiki_pending_project ON wiki_pending_updates(project,sent DESC,answer DESC);
"""

SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
REF = re.compile(r"(note|chat):([1-9][0-9]{0,14})")
UPDATE_PREFIX = "【知识页更新】"


def index(db, project=None):
    sql = "SELECT project,slug,title,summary,updated,version FROM wiki_pages"
    if project is None:
        return [dict(row) for row in db.execute(sql + " ORDER BY project,title")]
    return [dict(row) for row in db.execute(sql + " WHERE project=? ORDER BY title", (project,))]


def search_pages(db, query):
    return [
        dict(row) for row in db.execute(
            """WITH term(value) AS (VALUES(lower(?)))
               SELECT p.project,p.slug,p.title,p.summary,p.updated,p.version FROM wiki_pages p,term
               WHERE instr(lower(p.title || ' ' || p.summary || ' ' || p.body),term.value)>0
               OR EXISTS (SELECT 1 FROM wiki_chat_updates w WHERE w.project=p.project AND w.slug=p.slug
                          AND instr(lower(w.topic || ' ' || w.body),term.value)>0)
               ORDER BY p.project,p.title""",
            (query,),
        )
    ]


def source_record(db, project, ref):
    match = REF.fullmatch(ref)
    if not match:
        raise ValueError("请使用有效的原文编号，例如 note:12 或 chat:34。")
    kind, ident = match.groups()
    if kind == "note":
        sql = """SELECT e.title,e.kind,e.version FROM build_entries e
                 JOIN build_steps s ON s.id=e.step WHERE s.project=? AND e.id=?"""
    else:
        sql = """SELECT l.title,CASE m.role WHEN 'user' THEN '用户提问' ELSE 'Codex 回复' END AS kind,
                 1 AS version FROM chat_text m JOIN project_chats l ON l.id=m.link
                 WHERE l.project=? AND m.id=?"""
    row = db.execute(sql, (project, int(ident))).fetchone()
    return dict(row, source=kind, id=int(ident), ref=ref) if row else None


def page(db, project, slug):
    row = db.execute("SELECT * FROM wiki_pages WHERE project=? AND slug=?", (project, slug)).fetchone()
    if row is None:
        raise ValueError("这个知识页不存在。")
    result = dict(row)
    result["sources"] = []
    for ref, version in json.loads(row["sources"]):
        record = source_record(db, project, ref)
        result["sources"].append(
            dict(record, changed=record["version"] != version) if record else {"ref": ref, "missing": True}
        )
    result["related"] = json.loads(row["related"])
    website_pages = {}
    for item in db.execute(
        """SELECT m.answer,m.page_key AS path,coalesce(b.title,i.title,'') AS title
           FROM wiki_chat_updates w JOIN map_page_updates m ON m.answer=w.answer AND m.project=w.project
           LEFT JOIN build_pages b ON b.project=m.project AND b.path=m.page_key
           LEFT JOIN map_import_pages i ON i.project=m.project AND i.path=m.page_key
           WHERE w.project=? AND w.slug=? ORDER BY m.page_key""",
        (project, slug),
    ):
        website_pages.setdefault(item["answer"], []).append({"path": item["path"], "title": item["title"]})
    by_topic = {}
    for item in db.execute(
        """WITH revisions AS (
             SELECT w.topic,w.body,m.id AS prompt,w.answer,w.updated,w.sent
             FROM wiki_chat_updates w LEFT JOIN chat_text m ON m.id=w.prompt
               AND trim(m.body) NOT LIKE '<codex_internal_context%'
             WHERE w.project=? AND w.slug=?
           ) SELECT topic,body,prompt,answer,updated FROM revisions ORDER BY sent DESC,answer DESC""",
        (project, slug),
    ):
        topic = item["topic"]
        update = dict(item, websitePages=website_pages.get(item["answer"], []))
        if topic in by_topic:
            by_topic[topic]["history"].append(update)
        else:
            by_topic[topic] = dict(update, history=[])
    result["automatic"] = list(by_topic.values())
    return result


def auto_status(db, project):
    row = db.execute(
        "SELECT enabled,checked,warning FROM wiki_automation WHERE project=?", (project,)
    ).fetchone()
    folders = [
        Path(r[0]).name for r in db.execute(
            "SELECT directory FROM chat_folders WHERE project=? AND enabled=1 ORDER BY id",
            (project,),
        )
    ]
    return dict(row or {"enabled": 0, "checked": "", "warning": ""}, folders=folders)


PENDING_REASONS = {
    "format": "回复中的知识更新格式无法识别。",
    "slug": "回复缺少有效的知识页编号。",
    "topic": "回复缺少有效的知识主题。",
    "body": "知识更新的内容为空或超过 3,000 字。",
    "missing_page": "找不到回复指定的知识页。",
}
UNSTORABLE_TEXT = re.compile(r"[\x00\ud800-\udfff]")


def chat_update_fields(slug, topic, body):
    return (
        slug if isinstance(slug, str) and len(slug) <= 60 and SLUG.fullmatch(slug) else "",
        topic.strip() if isinstance(topic, str) and 1 <= len(topic.strip()) <= 100
        and "\n" not in topic and "\r" not in topic and not UNSTORABLE_TEXT.search(topic) else "",
        body.strip() if isinstance(body, str) and 1 <= len(body.strip()) <= 3000
        and not UNSTORABLE_TEXT.search(body) else "",
    )


def append_chat_update(db, project, answer, prompt, sent, stamp, fields, version, change):
    slug, topic, body = fields
    added = db.execute(
        """INSERT OR IGNORE INTO wiki_chat_updates
             (answer,prompt,project,slug,topic,body,sent,updated) VALUES(?,?,?,?,?,?,?,?)""",
        (answer, prompt, project, slug, topic, body, sent, stamp),
    ).rowcount
    if added:
        at = clock()
        db.execute("UPDATE wiki_pages SET updated=?,version=? WHERE project=? AND slug=?", (at, version + 1, project, slug))
        db.execute("INSERT INTO wiki_updates VALUES(?,?,?,?,?)", (project, slug, version + 1, at, change + " · " + topic))
    db.execute("DELETE FROM wiki_pending_updates WHERE project=? AND answer=?", (project, answer))


def pending_updates(db, project, answer=None):
    if answer is not None:
        row = db.execute("SELECT * FROM wiki_pending_updates WHERE project=? AND answer=?", (project, answer)).fetchone()
        if not row:
            raise ValueError("这条待补录记录已处理，请刷新知识库。")
        return dict(row, reason=PENDING_REASONS[row["reason"]])
    total = db.execute("SELECT count(*) FROM wiki_pending_updates WHERE project=?", (project,)).fetchone()[0]
    items = [dict(row, reason=PENDING_REASONS[row["reason"]]) for row in db.execute(
        """SELECT p.answer,p.prompt,p.slug,p.topic,p.reason,p.stamped,l.title
           FROM wiki_pending_updates p JOIN chat_text m ON m.id=p.answer
           JOIN project_chats l ON l.id=m.link AND l.project=p.project
           WHERE p.project=? ORDER BY p.sent DESC,p.answer DESC LIMIT 12""", (project,)
    )]
    return dict(total=total, items=items)


def file_pending_update(db, project, answer, payload):
    fields = chat_update_fields(payload.get("slug"), payload.get("topic"), payload.get("body"))
    if not all(fields):
        raise ValueError("请选择知识页，填写 100 字以内的主题和 3,000 字以内的结论。")
    with db:
        db.execute("BEGIN IMMEDIATE")
        item = pending_updates(db, project, answer)
        target = db.execute("SELECT version FROM wiki_pages WHERE project=? AND slug=?", (project, fields[0])).fetchone()
        if not target:
            raise ValueError("这个知识页已不存在，请重新选择。")
        append_chat_update(db, project, answer, item["prompt"], item["sent"], item["stamped"], fields, target[0], "从 Codex 原文补录")
    return {"slug": fields[0], "answer": answer}


def retry_pending_updates(db, project=None):
    sql = """SELECT p.* FROM wiki_pending_updates p JOIN wiki_pages w USING(project,slug)
             JOIN wiki_automation a ON a.project=p.project AND a.enabled=1
             WHERE p.reason='missing_page' AND EXISTS (
                 SELECT 1 FROM chat_folders f WHERE f.project=p.project AND f.enabled=1
             )"""
    if project is not None:
        sql += " AND p.project=?"
    args = (project,) if project is not None else ()
    if not db.execute(sql, args).fetchone():
        return 0
    with db:
        db.execute("BEGIN IMMEDIATE")
        pending = db.execute(sql + " ORDER BY sent,answer", args).fetchall()
        for item in pending:
            fields = (item["slug"], item["topic"], item["body"])
            version = db.execute("SELECT version FROM wiki_pages WHERE project=? AND slug=?", (item["project"], item["slug"])).fetchone()[0]
            append_chat_update(db, item["project"], item["answer"], item["prompt"], item["sent"], item["stamped"], fields, version, "Codex 自动补录")
    return len(pending)


def apply_chat_update(db, project, answer, prompt, sent, stamp, lines):
    """Apply one confirmed reply inside the archive transaction."""
    edits = [line[len(UPDATE_PREFIX):].strip() for line in lines if line.startswith(UPDATE_PREFIX)]
    if not edits:
        return
    setting = db.execute(
        "SELECT since FROM wiki_automation WHERE project=? AND enabled=1", (project,)
    ).fetchone()
    if not setting or sent <= setting[0]:
        return
    previous = db.execute("SELECT 1 FROM wiki_chat_updates WHERE project=? AND answer=?", (project, answer)).fetchone()
    if previous:
        if prompt:
            db.execute("UPDATE wiki_chat_updates SET prompt=? WHERE project=? AND answer=? AND prompt IS NOT ?",
                       (prompt, project, answer, prompt))
        return
    entry = None
    if len(edits) == 1 and len(edits[0]) <= 8000:
        try:
            entry = json.loads(edits[0])
        except (ValueError, RecursionError):
            pass
    fields = chat_update_fields(*(entry.get(k) for k in ("page", "topic", "text"))) if isinstance(entry, dict) else ("", "", "")
    reason = "format" if not isinstance(entry, dict) else next((key for key, value in zip(("slug", "topic", "body"), fields) if not value), "")
    if not reason:
        target = db.execute("SELECT version FROM wiki_pages WHERE project=? AND slug=?", (project, fields[0])).fetchone()
        if not target:
            reason = "missing_page"
    if reason:
        db.execute(
            """INSERT OR IGNORE INTO wiki_pending_updates
               (answer,prompt,project,reason,slug,topic,body,sent,stamped) VALUES(?,?,?,?,?,?,?,?,?)""",
            (answer, prompt, project, reason, *fields, sent, stamp),
        )
    else:
        append_chat_update(db, project, answer, prompt, sent, stamp, fields, target[0], "Codex 自动整理")
    db.execute(
        """UPDATE wiki_automation SET checked=?,warning='' WHERE project=? AND checked<=?
           AND NOT EXISTS (SELECT 1 FROM wiki_chat_updates w WHERE w.project=?
                           AND (w.sent,w.answer)>(?,?))""",
        (stamp, project, stamp, project, sent, answer),
    )


def updates(db, project):
    return [dict(row) for row in db.execute(
        """SELECT u.slug,u.updated,u.version,u.change,p.title FROM wiki_updates u
           JOIN wiki_pages p USING (project,slug)
           WHERE u.project=? ORDER BY u.rowid DESC LIMIT 30""", (project,)
    )]


def check(db, project):
    issues = []
    listing = index(db, project)
    slugs = {item["slug"] for item in listing}
    for item in listing:
        stored = page(db, project, item["slug"])
        reasons = []
        if not stored["sources"]:
            reasons.append("缺少原始依据")
        for source in stored["sources"]:
            if source.get("missing"):
                reasons.append("找不到原文 " + source["ref"])
            elif source.get("changed"):
                reasons.append("原文已更新 · " + source["title"])
        reasons.extend("找不到关联知识页 · " + slug for slug in stored["related"] if slug not in slugs)
        if reasons:
            issues.append(dict(item, reasons=reasons))
    return issues


def save(db, project, payload):
    from buildwork import checked

    slug = checked(payload, "slug", 60, True)
    if not SLUG.fullmatch(slug):
        raise ValueError("知识页编号只能使用小写英文字母、数字和短横线。")
    title = checked(payload, "title", 120, True)
    summary = checked(payload, "summary", 400, True)
    body = checked(payload, "body", 40000, True)
    change = checked(payload, "change", 240, True)
    refs = payload.get("sources")
    related = payload.get("related", [])
    if not isinstance(refs, list) or not 1 <= len(refs) <= 40 or any(not isinstance(x, str) for x in refs):
        raise ValueError("请提供 1 至 40 条项目原文编号。")
    if not isinstance(related, list) or len(related) > 25 or any(not isinstance(x, str) for x in related):
        raise ValueError("请检查关联知识页。")
    with db:
        db.execute("BEGIN IMMEDIATE")
        pages = {item["slug"]: item for item in index(db, project)}
        if slug in related or any(key not in pages for key in related):
            raise ValueError("关联内容必须是当前项目的其他知识页。")
        if any(item["title"] == title and key != slug for key, item in pages.items()):
            raise ValueError("本项目已有同名知识页，请更新现有页面。")
        current = pages.get(slug, {}).get("version", 0)
        if payload.get("version", 0) != current:
            raise ValueError("知识页已有新版，请先重新读取后再更新。")
        sources = []
        for ref in dict.fromkeys(refs):
            row = source_record(db, project, ref)
            if not row:
                raise ValueError("找不到这条项目原文 " + ref)
            sources.append([ref, row["version"]])
        version, stamp = current + 1, clock()
        db.execute(
            """INSERT INTO wiki_pages(project,slug,title,summary,body,sources,related,updated,version)
               VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(project,slug) DO UPDATE SET
               title=excluded.title,summary=excluded.summary,body=excluded.body,
               sources=excluded.sources,related=excluded.related,updated=excluded.updated,version=excluded.version""",
            (project, slug, title, summary, body, json.dumps(sources),
             json.dumps(list(dict.fromkeys(related))), stamp, version),
        )
        db.execute("INSERT INTO wiki_updates VALUES(?,?,?,?,?)", (project, slug, version, stamp, change))
    return {"slug": slug, "version": version}


def main():
    import project_archive
    import site_resources

    parser = argparse.ArgumentParser(description="读取和维护勋的软件项目知识库")
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--industry", type=int, required=True)
    parser.add_argument("--section", type=int, default=2)
    parser.add_argument("--project", type=int, required=True)
    parser.add_argument("action", choices=("index", "records", "record", "show", "save", "check"))
    parser.add_argument("key", nargs="?", default="")
    parser.add_argument("--page", type=int, default=1)
    args = parser.parse_args()
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    root = args.data.resolve()
    if not (root / "library.sqlite3").is_file():
        raise ValueError("找不到勋的软件资料库。")
    if not 1 <= args.page <= 100000:
        raise ValueError("页码超出范围。")
    target = next((folder for i, s, _, folder in project_archive.folders(root)
                   if (i, s) == (args.industry, args.section)), None)
    if target is None or not (target / "library.sqlite3").is_file():
        raise ValueError("找不到该行业或类目的数据库。")
    pid = args.project
    with closing(dbopen(target)) as db:
        if not db.execute("SELECT 1 FROM build_projects WHERE id=?", (pid,)).fetchone():
            raise ValueError("在指定行业和类目中找不到这个项目。")
        if args.action == "index":
            result = index(db, pid)
        elif args.action == "records":
            result = site_resources.records(db, pid, {"query": args.key, "page": args.page})
        elif args.action == "record":
            if not REF.fullmatch(args.key) or not source_record(db, pid, args.key):
                raise ValueError("找不到这条项目原文。")
            kind, ident = args.key.split(":")
            result = site_resources.records(db, pid, {"source": kind, "id": int(ident), "page": args.page})
        elif args.action == "show":
            result = page(db, pid, args.key)
        elif args.action == "check":
            result = check(db, pid)
        else:
            result = save(db, pid, json.load(sys.stdin))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError) as exc:
        raise SystemExit(str(exc))
