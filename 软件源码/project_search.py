"""Find archived prompts, replies and work notes across website projects."""

from contextlib import closing
from collections import defaultdict
import heapq
import json
import re
from datetime import datetime
from urllib.parse import urlsplit

import buildwork
from library import rows
import project_archive
import project_maps

PAGE_SIZE = 24
QUERY_LIMIT = 2048
PROJECTS = "SELECT p.id,p.name,p.site FROM build_projects p"
LINKED = "EXISTS (SELECT 1 FROM chat_folders f WHERE f.project=p.id AND f.enabled=1)"
PAGE_REFS = """
    SELECT project,entry AS id,'note' AS source,page_key FROM map_issue_links
    UNION ALL
    SELECT project,prompt,source,page_key FROM map_prompt_links
    UNION ALL
    SELECT project,answer,'chat',page_key FROM map_page_updates
    UNION ALL
    SELECT project,prompt,'chat',page_key FROM map_page_updates WHERE prompt IS NOT NULL
"""
RECORDS = """
WITH records AS (
    SELECT e.id,'note' AS source,s.project,e.kind,e.title,e.body,e.resolution,
           e.created,s.title AS step,'' AS origin,'' AS next_task
    FROM build_entries e JOIN build_steps s ON s.id=e.step
    UNION ALL
    SELECT m.id,'chat',l.project,CASE m.role WHEN 'user' THEN '提示词' ELSE 'Codex 回复' END,
           l.title,m.body,'',coalesce(strftime('%Y-%m-%d %H:%M:%S',m.sent,'localtime'),''),
           coalesce(s.title,''),l.title,coalesce(cp.next_task,'')
    FROM chat_text m JOIN project_chats l ON l.id=m.link LEFT JOIN build_steps s ON s.id=m.step
    LEFT JOIN chat_progress cp ON cp.message=m.id
    WHERE m.role IN ('user','assistant')
    UNION ALL
    SELECT r.id,'reference',r.project,'复用提示词',r.origin,r.body,'',r.created,coalesce(s.title,''),r.origin,''
    FROM project_prompt_copies r LEFT JOIN build_steps s ON s.id=r.step
), term(value,kind,path,alias) AS (VALUES(lower(?),?,?,?)),
page_refs AS ({page_refs}),
page_matches AS (
    SELECT DISTINCT r.project,r.id,r.source
    FROM term CROSS JOIN page_refs r JOIN build_projects p ON p.id=r.project
    WHERE term.path<>'' AND r.page_key IN (term.path,term.alias) AND same_website(p.site)
), matches AS (
    SELECT r.*,p.name AS project_name,p.site,
           instr(lower(r.body),term.value) AS body_at,
           instr(lower(r.resolution),term.value) AS solution_at,
           page_matches.id IS NOT NULL AS page_at
    FROM records r JOIN build_projects p ON p.id=r.project CROSS JOIN term
    LEFT JOIN page_matches ON (page_matches.project,page_matches.id,page_matches.source)=(r.project,r.id,r.source)
    WHERE (?=0 OR p.id=?) AND
        (term.kind='' OR r.kind=term.kind OR (term.kind='提示词' AND r.kind IN ('复用模板','复用提示词'))
            OR (term.kind='待解决' AND r.kind='问题' AND trim(r.resolution)='')
            OR (term.kind='下一步' AND trim(r.next_task)<>''))
    {scope_clause}
), found AS (
    SELECT id,source,project,project_name,site,title,step,origin,created,
        CASE WHEN term.kind='下一步' AND trim(next_task)<>'' THEN '下一步' ELSE matches.kind END AS kind,
        CASE WHEN matches.kind='问题' THEN trim(resolution)='' ELSE 0 END AS unresolved,
        CASE WHEN term.value<>'' AND (body_at>0 OR solution_at>0 OR page_at) THEN 1 ELSE 0 END AS match_in_text,
        CASE
            WHEN term.kind='下一步' AND trim(next_task)<>'' AND
                 (term.value='' OR instr(lower(next_task),term.value)>0) THEN substr(next_task,1,200)
            WHEN term.value<>'' AND body_at>0 THEN
                (CASE WHEN body_at>61 THEN '…' ELSE '' END) || substr(body,max(1,body_at-60),200) ||
                (CASE WHEN length(body)>max(1,body_at-60)+199 THEN '…' ELSE '' END)
            WHEN term.value<>'' AND solution_at>0 THEN '解决办法 · ' || substr(resolution,max(1,solution_at-60),185)
            ELSE substr(body,1,200) || (CASE WHEN length(body)>200 THEN '…' ELSE '' END)
        END AS preview
    FROM matches CROSS JOIN term
    WHERE term.value='' OR body_at>0 OR solution_at>0 OR page_at
       OR instr(lower(title||' '||step||' '||origin||' '||project_name||' '||site||' '||next_task),term.value)>0
)
SELECT * FROM found
"""


def project_key(value):
    if not value:
        return None
    if not re.fullmatch(r"[1-9][0-9]{0,18}/[1-9][0-9]{0,18}/[1-9][0-9]{0,18}", value):
        raise ValueError("请选择有效的网站项目。")
    parsed = tuple(int(part) for part in value.split("/"))
    if max(parsed) >= 2**63:
        raise ValueError("请选择有效的网站项目。")
    return parsed


def search_cursor(value):
    if not value:
        return None
    cursor = json.loads(value)
    if (not isinstance(cursor, list) or len(cursor) != 6 or type(cursor[0]) is not int or cursor[0] not in (0, 1)
        or not isinstance(cursor[1], str) or cursor[4] not in ("note", "chat", "reference", "page")
        or any(type(cursor[i]) is not int or not 0 < cursor[i] < 2**63 for i in (2, 3))):
        raise ValueError("翻页位置无效，请重新查找。")
    ident = cursor[5]
    if cursor[4] == "page":
        valid = isinstance(ident, str) and 0 < len(ident) <= 2100
    else:
        valid = type(ident) is int and 0 < ident < 2**63
    if not valid:
        raise ValueError("翻页位置无效，请重新查找。")
    return cursor


def order(item):
    return item["match_in_text"], item["created"], item["industry"], item["section"], item["source"], item["id"]


def page_query(query):
    if not query.startswith("/") and not query.lower().startswith(("https://", "http://")):
        return "", None
    try:
        path = project_maps.route(query, "")
        site = project_maps.host(query) if urlsplit(query).netloc else None
        return path, site
    except ValueError:
        return "", None


def page_tasks(db, project, site):
    tasks = {path: work for path, work in project_maps.page_work_index(db, project, site).items()
             if path.startswith("/") and work["todo"].strip()}
    if not tasks:
        return
    titles = {}
    labels = db.execute(
        """SELECT path,title FROM build_pages WHERE project=?
           UNION ALL SELECT path,title FROM map_import_pages WHERE project=?""", (project, project),
    )
    for path, title in labels:
        path = project_maps.route(path, site)
        if path in tasks:
            titles.setdefault(path, title or path)
    if tasks.keys() - titles.keys():
        for item in project_maps.snapshot_pages(db, project, site):
            path = project_maps.route(item.get("path"), site)
            if path in tasks:
                titles.setdefault(path, item.get("title") or path)
    for path, work in tasks.items():
        if path not in titles:
            continue
        origin = work.get("origin") or work.get("source", "")
        at = project_maps.instant(work.get("sent") or work.get("edited_at", ""))
        created = datetime.fromtimestamp(at).strftime("%Y-%m-%d %H:%M:%S") if at is not None else ""
        yield dict(
            id=f"{project}:{path}", source="page", project=project, title=titles[path], path=path,
            stage=work["stage"], todo=work["todo"], origin=origin, created=created,
            todoSource=project_maps.todo_source(work),
        )


def add_page_targets(db, items):
    if not items:
        return
    keys = {(r["project"], r["id"], r["source"]): r for r in items}
    params = [value for key in keys for value in key]
    placeholders = ",".join("(?,?,?)" for _ in keys)
    cached = {}
    for r in db.execute(
        f"""WITH selected(project,id,source) AS (VALUES {placeholders}), page_refs AS ({PAGE_REFS})
            SELECT DISTINCT p.project,p.id,p.source,p.page_key FROM page_refs p JOIN selected s
            ON (p.project,p.id,p.source)=(s.project,s.id,s.source) ORDER BY p.page_key""",
        params,
    ):
        key = r["project"], r["page_key"]
        if key not in cached:
            path = project_maps.known_page(db, *key)
            title = None
            if path:
                title = db.execute(
                    """SELECT title FROM build_pages WHERE project=? AND path IN (?,?)
                       UNION ALL SELECT title FROM map_import_pages WHERE project=? AND path=? LIMIT 1""",
                    (key[0], path, path.rstrip("/") or "/", key[0], path),
                ).fetchone()
            label = (title[0] if title else "") or path
            cached[key] = {"path": path, "title": label} if path else None
        target = cached[key]
        if target:
            record = keys[(r["project"], r["id"], r["source"])]
            pages = record.setdefault("pages", [])
            if target not in pages:
                pages.append(target)


def search(root, query="", kind="", owner="", before=None, linked_only=False):
    from ai_reader import readonly

    query = query.strip()[:QUERY_LIMIT]
    path, search_site = page_query(query)
    kind = kind.strip()[:60]
    pages_only = kind == "页面待办"
    if before and (before[4] == "page") != pages_only:
        raise ValueError("请重新查找这个记录类型。")
    key = project_key(owner)
    projects, candidates = [], []
    folders = {}
    for ind, sec, label, folder in project_archive.folders(root):
        if key and linked_only and (ind, sec) != key[:2]:
            continue
        scope = dict(industry=ind, section=sec, label=label)
        folders[(ind, sec)] = folder
        with closing(readonly(folder)) as db:
            group = rows(db, PROJECTS + (" WHERE " + LINKED if linked_only else "") + " ORDER BY p.name")
            counts = dict(db.execute(
                """SELECT s.project,count(*) FROM build_entries e JOIN build_steps s ON s.id=e.step
                   WHERE e.kind='问题' AND trim(e.resolution)='' GROUP BY s.project"""
            )) if kind == "待解决" else {}
            projects.extend(dict(p, **scope, openIssues=counts.get(p["id"], 0)) for p in group)
            if key and (ind, sec) != key[:2]:
                continue
            pid = key[2] if key else 0
            if pages_only:
                needle = query.casefold()
                for p in group:
                    if pid and p["id"] != pid:
                        continue
                    if search_site and (not p["site"] or page_query(p["site"])[1] != search_site):
                        continue
                    for item in page_tasks(db, p["id"], p["site"]):
                        body = item.pop("todo")
                        hay = " ".join((item["path"], item["title"], item["stage"], p["name"], label, body))
                        exact = bool(path and item["path"] == path)
                        if not exact and needle not in hay.casefold():
                            continue
                        pos = body.casefold().find(needle) if needle else 0
                        start = max(0, pos - 50)
                        preview = ("…" if start else "") + body[start:start + 280]
                        if len(body) > start + 280:
                            preview += "…"
                        item.update(scope, preview=preview, project_name=p["name"], match_in_text=int(exact), kind=kind)
                        if not before or order(item) < tuple(before):
                            candidates.append(item)
                continue
            same_sites = {
                p["site"] for p in projects if (p["industry"], p["section"]) == (ind, sec)
                and p["site"] and page_query(p["site"])[1] == search_site
            } if search_site else set()
            db.create_function("same_website", 1, lambda site: not search_site or site in same_sites, deterministic=True)
            sql = RECORDS.format(scope_clause="AND " + LINKED if linked_only else "", page_refs=PAGE_REFS)
            args = [query, kind, path, path.rstrip("/") or "/", pid, pid]
            if before:
                sql += " WHERE (match_in_text,created,?,?,source,id)<(?,?,?,?,?,?)"
                args.extend((ind, sec, *before))
            sql += " ORDER BY match_in_text DESC,created DESC,source DESC,id DESC LIMIT ?"
            candidates.extend(dict(row, **scope) for row in rows(db, sql, (*args, PAGE_SIZE + 1)))
    if key and not any((r["industry"], r["section"], r["id"]) == key for r in projects):
        raise ValueError("找不到这个网站项目。")
    selected = heapq.nlargest(PAGE_SIZE + 1, candidates, key=order)
    groups = defaultdict(list)
    if not pages_only:
        for record in selected[:PAGE_SIZE]:
            groups[(record["industry"], record["section"])].append(record)
    for scope_key, group in groups.items():
        with closing(readonly(folders[scope_key])) as db:
            add_page_targets(db, group)
            issues = {item["id"]: item for item in group if item["source"] == "note" and item["kind"] == "问题"}
            if issues:
                markers = ",".join("?" for _ in issues)
                for ident, count in db.execute(
                    "SELECT entry,count(*) FROM chat_issue_origins WHERE entry IN (" + markers + ") GROUP BY entry",
                    tuple(issues),
                ):
                    issues[ident]["reportCount"] = count
    return dict(projects=projects, items=selected[:PAGE_SIZE],
                before=order(selected[PAGE_SIZE - 1]) if len(selected) > PAGE_SIZE else None)


def original(db, pid, source, ident, page=""):
    ident = int(ident)
    if source == "chat":
        raw = project_archive.message(db, pid, ident)
        result = dict(raw, kind="提示词" if raw["role"] == "user" else "Codex 回复")
    elif source == "reference":
        raw = project_archive.prompt_text(db, pid, "reference", ident)
        result = dict(raw, title=raw["origin"], kind="复用提示词")
    elif source == "note" and db.execute(
        "SELECT 1 FROM build_entries e JOIN build_steps s ON s.id=e.step WHERE s.project=? AND e.id=?",
        (pid, ident),
    ).fetchone():
        result = buildwork.entry(db, ident)
    else:
        raise ValueError("找不到这条项目原文。")
    target = {"project": pid, "id": ident, "source": source}
    add_page_targets(db, [target])
    origins = project_archive.issue_origins(db, pid, ident) if result["kind"] == "问题" else []
    if source == "chat" and page:
        site = db.execute("SELECT site FROM build_projects WHERE id=?", (pid,)).fetchone()[0]
        path = project_maps.route(page, site)
        saved = db.execute(
            """SELECT todo,origin FROM map_page_updates WHERE project=? AND answer=? AND page_key=?
               AND trim(todo)<>''""", (pid, ident, path),
        ).fetchone() if path else None
        if saved:
            result["pageTask"] = dict(saved, path=path)
    return dict(result, pages=target.get("pages", []), issueOrigins=origins)
