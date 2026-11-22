"""Read page-level evidence from project files without executing or extracting a repository."""
import csv
from datetime import datetime
import hashlib
import io
import json
import re
import zipfile
from pathlib import PurePosixPath
from urllib.parse import urlsplit
from xml.etree import ElementTree

from library import clock, sheet_paths, xlsx_rows

SCHEMA = """
CREATE TABLE IF NOT EXISTS map_import_pages(
 project INTEGER NOT NULL REFERENCES build_projects(id), path TEXT NOT NULL,
 title TEXT NOT NULL, parent TEXT NOT NULL, PRIMARY KEY(project,path));
CREATE TABLE IF NOT EXISTS map_import_prompts(
 project INTEGER NOT NULL REFERENCES build_projects(id),digest TEXT NOT NULL,
 entry INTEGER NOT NULL REFERENCES build_entries(id),PRIMARY KEY(project,digest));
CREATE TABLE IF NOT EXISTS map_issue_links(
 project INTEGER NOT NULL REFERENCES build_projects(id),page_key TEXT NOT NULL,
 entry INTEGER NOT NULL REFERENCES build_entries(id),PRIMARY KEY(project,page_key,entry));
CREATE TABLE IF NOT EXISTS map_page_keywords(
 project INTEGER NOT NULL REFERENCES build_projects(id),page_key TEXT NOT NULL,
 term TEXT NOT NULL COLLATE BINARY,PRIMARY KEY(project,page_key,term));
CREATE TABLE IF NOT EXISTS map_page_skills(
 project INTEGER NOT NULL REFERENCES build_projects(id),page_key TEXT NOT NULL,
 answer INTEGER NOT NULL REFERENCES chat_text(id),name TEXT NOT NULL COLLATE NOCASE,
 detail TEXT NOT NULL,origin TEXT NOT NULL,PRIMARY KEY(project,page_key,answer,name));
CREATE TABLE IF NOT EXISTS map_page_updates(
 project INTEGER NOT NULL REFERENCES build_projects(id),page_key TEXT NOT NULL,
 answer INTEGER NOT NULL REFERENCES chat_text(id),prompt INTEGER REFERENCES chat_text(id),
 stage TEXT NOT NULL,todo TEXT NOT NULL,evidence TEXT NOT NULL,issue TEXT NOT NULL,
 sent TEXT NOT NULL,updated TEXT NOT NULL,origin TEXT NOT NULL,
 skills_checked INTEGER NOT NULL DEFAULT 0,
 PRIMARY KEY(project,page_key,answer));
CREATE INDEX IF NOT EXISTS map_page_update_order ON map_page_updates(project,page_key,sent,answer);
CREATE INDEX IF NOT EXISTS map_page_update_answer ON map_page_updates(project,answer,page_key);
"""
UPDATE_PREFIX = "【页面更新】"
PAGE_SKILL_FIELD = '"skills":'
MAX_DOCUMENT = 16 * 1024**2
MAX_TOTAL = 96 * 1024**2
UTC_NOW = "strftime('%Y-%m-%dT%H:%M:%fZ','now')"
URL_TOKEN = re.compile(r"""https?://[^\s<>()\[\]{}"'，。；、]+|(?<![\w./:=])/(?!/)[\w%~./-]+""", re.I)
FORMATS = {".json", ".xml", ".csv", ".md", ".txt", ".xlsx", ".docx", ".zip"}


def host(value):
    u = urlsplit(value)
    return (u.hostname or "").lower().removeprefix("www."), u.port


def route(value, site):
    if not isinstance(value, str):
        return ""
    value = value.strip()
    if not value or len(value) > 2048 or re.search(r"[\s\\\x00-\x1f]", value) or value.startswith("//"):
        return ""
    try:
        u = urlsplit(value)
        if u.netloc:
            if u.scheme not in ("https", "http") or u.username or u.password or (site and host(value) != host(site)):
                return ""
        elif not value.startswith("/"):
            return ""
    except ValueError:
        return ""
    path = u.path or "/"
    if any(part in (".", "..") for part in path.split("/")):
        return ""
    return path.rstrip("/") + ("" if "." in path.rsplit("/", 1)[-1] else "/")


def mentions(text, path, site):
    if not path.startswith("/"):
        return False
    for m in URL_TOKEN.finditer(text):
        try:
            token = m.group().rstrip(".,;:")
            if token.startswith("http") and not site:
                continue
            if route(token, site) == path:
                return True
        except ValueError:
            continue
    return False


def known_page(db, project, value):
    record = db.execute("SELECT site FROM build_projects WHERE id=?", (project,)).fetchone()
    if not record:
        return ""
    site = record[0]
    try:
        if not site and isinstance(value, str) and urlsplit(value).netloc:
            return ""
        path = route(value, site)
    except ValueError:
        return ""
    if not path:
        return ""
    variants = (path, path.rstrip("/") or "/")
    if db.execute(
        """SELECT 1 FROM build_pages WHERE project=? AND path IN (?,?)
           UNION ALL SELECT 1 FROM map_import_pages WHERE project=? AND path IN (?,?) LIMIT 1""",
        (project, *variants, project, *variants),
    ).fetchone():
        return path
    if any(item.get("path") in variants for item in snapshot_pages(db, project, site)):
        return path
    return ""


def snapshot_pages(db, project, site):
    if not site:
        return []
    snapshot = db.execute(
        """SELECT b.body FROM build_steps s JOIN build_entries e ON e.step=s.id
           JOIN build_files f ON f.entry=e.id JOIN build_blobs b ON b.digest=f.digest
           WHERE s.project=? AND e.title='网站地图 · 官网与规划快照' AND f.filename='网站地图.json'
           AND f.size<=? ORDER BY e.id DESC,f.id DESC LIMIT 1""",
        (project, MAX_DOCUMENT),
    ).fetchone()
    if not snapshot:
        return []
    try:
        data = json.loads(snapshot[0])
        if not isinstance(data, dict) or data.get("version") != 1:
            return []
        if not isinstance(data.get("site"), str) or host(data["site"]) != host(site):
            return []
        return [item for key in ("live", "plan") if isinstance(data.get(key), list)
                for item in data[key] if isinstance(item, dict)]
    except (ValueError, RecursionError):
        return []


WORK_FIELDS = "page_key,stage,todo,source,version,edited_at"
WORK_ORDER = "(source='手动更新') DESC,edited_at DESC"


def saved_work(db, project, key, path):
    row = db.execute(
        f"""SELECT {WORK_FIELDS} FROM map_page_work WHERE project=? AND page_key IN (?,?,?)
            ORDER BY {WORK_ORDER},page_key=? DESC LIMIT 1""",
        (project, key, path, path.rstrip("/") or path, key),
    ).fetchone()
    return dict(row) if row else None


def instant(value):
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except (ValueError, OverflowError, OSError):
        return None


def current_work(saved, latest):
    if not latest:
        return saved
    if saved and saved["source"] == "手动更新":
        edited = instant(saved["edited_at"])
        sent = instant(latest["sent"])
        if edited is None or sent is None or edited >= sent:
            return saved
    return latest


def todo_source(work):
    if not work or not work.get("answer") or not work["todo"].strip():
        return None
    source = dict(source="chat", id=work["answer"])
    if work.get("wikiSlug"):
        source["knowledge"] = dict(slug=work["wikiSlug"], topic=work["wikiTopic"])
    return source


def page_work_index(db, project, site):
    saved = {}
    for row in db.execute(
        f"""SELECT {WORK_FIELDS} FROM map_page_work WHERE project=?
            ORDER BY {WORK_ORDER},page_key DESC""", (project,),
    ):
        saved.setdefault(route(row["page_key"], site) or row["page_key"], dict(row))
    latest = {row["page_key"]: dict(row) for row in db.execute(
        """WITH updates AS (
               SELECT u.page_key,u.answer,u.sent,u.stage,u.todo,u.origin,u.updated,
                      row_number() OVER (PARTITION BY u.page_key ORDER BY u.sent DESC,u.answer DESC) AS item
               FROM map_page_updates u JOIN chat_text m ON m.id=u.answer
               JOIN project_chats l ON l.id=m.link AND l.project=u.project
               JOIN chat_progress cp ON cp.message=u.answer
               WHERE u.project=?
           )
           SELECT u.*,w.slug AS wikiSlug,w.topic AS wikiTopic FROM updates u
           LEFT JOIN wiki_chat_updates w ON w.project=? AND w.answer=u.answer WHERE u.item=1""",
        (project, project),
    )}
    return {path: current_work(saved.get(path), latest.get(path)) for path in saved.keys() | latest.keys()}


def map_work_overview(db, project):
    website = db.execute("SELECT site FROM build_projects WHERE id=?", (project,)).fetchone()
    if not website:
        raise ValueError("找不到这个建站项目。")
    site = website[0]
    result = {}
    for path, work in page_work_index(db, project, site).items():
        todo = work["todo"].strip()
        preview = todo[:219] + "…" if len(todo) > 220 else todo
        result[path] = dict(stage=work["stage"], todo=preview, todoSource=todo_source(work))
    seen = set()
    for row in db.execute(
        """SELECT l.page_key,e.id FROM map_issue_links l JOIN build_entries e ON e.id=l.entry
           JOIN build_steps s ON s.id=e.step AND s.project=l.project
           WHERE l.project=? AND e.kind IN ('问题','待办','下一步') AND trim(e.resolution)=''""", (project,),
    ):
        path = route(row["page_key"], site) or row["page_key"]
        pair = path, row["id"]
        if pair not in seen:
            item = result.setdefault(path, {})
            item["issues"] = item.get("issues", 0) + 1
            seen.add(pair)
    return result


def save_page_skill(db, project, path, answer, name, detail, origin):
    return bool(db.execute(
        """INSERT OR IGNORE INTO map_page_skills(project,page_key,answer,name,detail,origin)
           VALUES(?,?,?,?,?,?)""", (project, path, answer, name, detail, origin),
    ).rowcount)


def read_page_skills(db, project, path):
    return [dict(row) for row in db.execute(
        """SELECT k.answer,k.name,k.detail,k.origin,
                  strftime('%Y-%m-%d %H:%M:%S',m.sent,'localtime') AS used
           FROM map_page_skills k JOIN chat_text m ON m.id=k.answer
           WHERE k.project=? AND k.page_key=? ORDER BY m.sent DESC,k.answer DESC,k.name""",
        (project, path),
    )]


def archive_page_skills(db, project, path, answer, skills):
    if isinstance(skills, list):
        for skill in skills[:12]:
            if not isinstance(skill, dict):
                continue
            name, detail = skill.get("name"), skill.get("detail")
            if (isinstance(name, str) and isinstance(detail, str) and
                0 < len(name.strip()) <= 180 and 0 < len(detail.strip()) <= 1600 and
                len(name.splitlines()) == 1):
                save_page_skill(db, project, path, answer, name.strip(), detail.strip(), "Codex 页面回执")
    db.execute(
        "UPDATE map_page_updates SET skills_checked=1 WHERE project=? AND page_key=? AND answer=? AND skills_checked=0",
        (project, path, answer),
    )


def save_chat_update(db, project, answer, prompt, stamp, item, origin="Codex 自动整理"):
    """Add evidence for a confirmed page without editing its plan or project step."""
    if not isinstance(item, dict):
        return False
    limits = {"stage": 180, "todo": 1500, "evidence": 2000, "issue": 1500}
    fields = []
    for key, limit in limits.items():
        value = item.get(key, "")
        if not isinstance(value, str) or len(value.strip()) > limit:
            return False
        if key in ("stage", "evidence") and not value.strip():
            return False
        fields.append(value.strip())
    path = known_page(db, project, item.get("path"))
    if not path:
        return False
    source = db.execute(
        """SELECT m.link,m.sent,cp.step FROM chat_text m JOIN chat_progress cp ON cp.message=m.id
           JOIN project_chats l ON l.id=m.link WHERE m.id=? AND l.project=? AND m.role='assistant'""",
        (answer, project),
    ).fetchone()
    if not source:
        return False
    if prompt and not db.execute(
        "SELECT 1 FROM chat_text WHERE id=? AND link=? AND role='user' AND (sent,id)<(?,?)",
        (prompt, source["link"], source["sent"], answer),
    ).fetchone():
        return False
    stage, todo, evidence, issue = fields
    written = db.execute(
        """INSERT OR IGNORE INTO map_page_updates
           (project,page_key,answer,prompt,stage,todo,evidence,issue,sent,updated,origin)
           VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
        (project, path, answer, prompt, stage, todo, evidence, issue, source["sent"], stamp, origin),
    )
    if written.rowcount and issue:
        db.execute(
            """INSERT OR IGNORE INTO map_issue_links(project,page_key,entry)
               SELECT ?,?,id FROM build_entries WHERE step=? AND kind='问题' AND body=?""",
            (project, path, source["step"], issue),
        )
    archive_page_skills(db, project, path, answer, item.get("skills"))
    return bool(written.rowcount)


def read_chat_updates(db, project, path):
    return [
        dict(row) for row in db.execute(
            """SELECT u.answer,u.prompt,u.stage,u.todo,u.evidence,u.issue,u.sent,u.updated,u.origin,
                      l.title AS chat,cp.step,s.title AS stepTitle,w.slug AS wikiSlug,w.topic AS wikiTopic
               FROM map_page_updates u JOIN chat_text m ON m.id=u.answer
               JOIN project_chats l ON l.id=m.link AND l.project=u.project
               JOIN chat_progress cp ON cp.message=u.answer JOIN build_steps s ON s.id=cp.step
               LEFT JOIN wiki_chat_updates w ON w.answer=u.answer AND w.project=u.project
               WHERE u.project=? AND u.page_key=?
               ORDER BY u.sent DESC,u.answer DESC""", (project, path),
        )
    ]


def receipt_pages(db, project, answer):
    return [dict(row) for row in db.execute(
        """SELECT m.page_key AS path,coalesce(b.title,i.title,'') AS title,m.prompt,m.stage,m.issue
           FROM map_page_updates m
           LEFT JOIN build_pages b ON b.project=m.project AND b.path=m.page_key
           LEFT JOIN map_import_pages i ON i.project=m.project AND i.path=m.page_key
           WHERE m.project=? AND m.answer=? ORDER BY m.page_key""",
        (project, answer),
    )]


def field(row, *names):
    for key in names:
        val = row.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return ""


def prompt_values(row):
    value = row.get("prompts") or row.get("prompt") or row.get("提示词") or row.get("used prompts") or []
    for item in value if isinstance(value, list) else [value]:
        body = item if isinstance(item, str) else field(item, "body", "prompt", "text") if isinstance(item, dict) else ""
        if body and body.strip():
            if len(body) > 200000:
                raise ValueError("单条提示词过长，请分段后再导入。")
            yield body.strip()


def table_rows(workbook):
    with zipfile.ZipFile(io.BytesIO(workbook)) as z:
        if sum(i.file_size for i in z.infolist()) > MAX_TOTAL:
            raise ValueError("表格过大，请把地图工作表单独导出。")
        sheets = sheet_paths(z)
    for name, _ in sheets:
        rows = xlsx_rows(io.BytesIO(workbook), name)
        headers = next(rows, [])
        for values in rows:
            yield dict(zip(headers, values))


def document(name, raw):
    ext = PurePosixPath(name).suffix.lower()
    if ext == ".xlsx":
        return "", table_rows(raw)
    if ext == ".docx":
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            member = z.getinfo("word/document.xml")
            if member.file_size > MAX_DOCUMENT:
                raise ValueError("文档文字过多，请分开导入。")
            body = ElementTree.fromstring(z.read(member))
        text = "\n".join("".join(n.text or "" for n in par.findall(".//{*}t")) for par in body.findall(".//{*}p"))
    else:
        if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
            text = raw.decode("utf-16")
        else:
            try:
                text = raw.decode("utf-8-sig")
            except UnicodeDecodeError:
                text = raw.decode("gb18030")
    if ext == ".json":
        data = json.loads(text)
        if isinstance(data, list):
            return "", data
        if isinstance(data, dict):
            records = []
            for group in ("plan", "live", "pages", "livePages", "prompts"):
                if isinstance(data.get(group), list):
                    records.extend(data[group])
            return field(data, "site", "siteUrl"), records
    elif ext == ".xml":
        if re.search(r"<!\s*(DOCTYPE|ENTITY)\b", text, re.I):
            raise ValueError("请导入标准网站地图 XML。")
        try:
            root = ElementTree.fromstring(text)
        except ElementTree.ParseError as e:
            raise ValueError("网站地图 XML 格式有误。") from e
        if root.tag.split("}")[-1] == "urlset":
            return "", [{"url": n.text} for n in root.findall("{*}url/{*}loc")]
    elif ext == ".csv":
        return "", csv.DictReader(io.StringIO(text))
    elif ext in {".md", ".txt", ".docx"}:
        records = []
        row = {}
        active = ""
        labels = re.compile(r"^(页面路径|网址|path|url|页面名称|进度|stage|待办|todo|提示词|prompt)\s*[:：]\s*(.*)$", re.I)
        for line in text.splitlines():
            match = labels.match(line.strip().lstrip("- ").strip())
            if match:
                key, value = match[1].lower(), match[2].strip()
                if key in ("path","url","页面路径","网址") and any(k in row for k in ("path","url","页面路径","网址")):
                    records.append(row)
                    row = {}
                active = key
                row[key] = value
            elif line.startswith("#"):
                active = ""
            elif active in ("prompt","提示词","todo","待办"):
                row[active] += "\n" + line
        if row:
            records.append(row)
        return "", records
    return "", []


def recognized(name):
    path = PurePosixPath(name.lower())
    if ".example." in path.name or ".sample." in path.name or any(
            p.startswith(".") or p in {"node_modules", "vendor", "__macosx", "research", "examples", "fixtures", "tests"}
            for p in path.parts):
        return False
    stem = path.stem
    return path.suffix in FORMATS - {".zip"} and any(k in stem for k in (
        "sitemap", "site-map", "site-plan", "project", "pages", "prompt", "handoff",
        "网站地图", "页面", "规划", "核查", "提示词", "交接"))


def documents(file, filename):
    if PurePosixPath(filename).suffix.lower() != ".zip":
        raw = file.read(MAX_DOCUMENT + 1)
        if len(raw) > MAX_DOCUMENT:
            raise ValueError("单份地图文件最大为 16 MB。")
        yield filename, raw
        return
    with zipfile.ZipFile(file) as archive:
        total = 0
        for f in archive.infolist():
            if f.is_dir() or not recognized(f.filename):
                continue
            total += f.file_size
            if f.file_size > MAX_DOCUMENT or total > MAX_TOTAL:
                raise ValueError("地图清单过大，请分开导入。")
            yield f.filename, archive.read(f)


def collect(file, filename, site):
    pages = {}
    skipped = 0
    for name, raw in documents(file, filename):
        declared, rows = document(name, raw)
        # Homepage design files identify their target even if they omit an explicit route.
        stem = PurePosixPath(name).stem.lower()
        if "homepage" in stem and "prompt" in stem:
            if name.lower().endswith(".txt"):
                body = raw.decode("utf-8-sig").strip()
                rows = [{"path":"/", "name":stem, "prompt":body}]
            elif name.lower().endswith(".json"):
                spec = json.loads(raw.decode("utf-8-sig"))
                if isinstance(spec,dict) and isinstance(spec.get("directions"),list):
                    rows = [dict(r,path="/") for r in spec["directions"] if isinstance(r,dict)]
        if site and declared and host(site) != host(declared):
            raise ValueError("文件标明的网站与当前项目的网址不同。")
        for item in rows:
            r = {"path": item} if isinstance(item, str) else item
            if not isinstance(r, dict):
                continue
            r = {k.strip().casefold():v for k,v in r.items() if isinstance(k,str)}
            target = field(r, "path", "route", "url", "loc", "页面路径", "网址", "站点地图url", "页面网址", "url路径", "page url", "page path")
            if not target:
                continue
            path = route(target, site or declared)
            if not path:
                skipped += 1
                continue
            if not site and not declared and urlsplit(target).hostname:
                raise ValueError("请先在项目里填写网站域名，再导入含完整网址的清单。")
            if len(pages) >= 30000 and path not in pages:
                raise ValueError("单次最多导入三万个页面，请分批选择。")
            page = pages.setdefault(path, {"title": "", "parent": "", "stage": "", "todo": "", "prompts": {}, "source": {}})
            fields = {
                "title": field(r, "title", "name", "页面名称", "标题", "h1", "page title"),
                "parent": route(field(r, "parent", "上级路径", "parent path"), site or declared),
                "stage": field(r, "stage", "progress", "status", "current stage", "进度", "阶段", "页面进度", "状态"),
                "todo": field(r, "todo", "nexttask", "next_task", "next action", "待办", "下一步"),
            }
            for key, value in fields.items():
                if value:
                    if len(value) > (12000 if key == "todo" else 2048):
                        raise ValueError("页面字段过长，请检查原表。")
                    page[key] = value
                    page["source"][key] = PurePosixPath(name).name
            for body in prompt_values(r):
                page["prompts"][body] = field(r, "name", "title") or body.splitlines()[0][:90]
    return pages, skipped


def apply(db, pid, pages, filename):
    step = db.execute("SELECT id FROM build_steps WHERE project=? ORDER BY seq LIMIT 1", (pid,)).fetchone()
    added = 0
    for path, p in pages.items():
        db.execute("""INSERT INTO map_import_pages VALUES(?,?,?,?) ON CONFLICT(project,path) DO UPDATE SET
            title=coalesce(nullif(excluded.title,''),title),parent=coalesce(nullif(excluded.parent,''),parent)""",
            (pid, path, p["title"], p["parent"]))
        old = saved_work(db, pid, path, path)
        if not old or (old["source"] != "手动更新" and (p["stage"] or p["todo"])):
            names = dict.fromkeys(p["source"][k] for k in ("stage", "todo") if k in p["source"])
            source = "导入文件 · " + ("、".join(names) or filename)
            stage = p["stage"] or (old["stage"] if old else "已收录页面，制作进度待确认")
            todo = p["todo"] or (old["todo"] if old else "")
            if not old or (old["stage"], old["todo"]) != (stage,todo):
                db.execute("""INSERT INTO map_page_work(project,page_key,stage,todo,source) VALUES(?,?,?,?,?)
                    ON CONFLICT(project,page_key) DO UPDATE SET stage=excluded.stage,todo=excluded.todo,
                    source=excluded.source,version=version+1""",(pid,path,stage,todo,source))
        for body,label in p["prompts"].items():
            digest = hashlib.sha256(body.encode()).hexdigest()
            found = db.execute("SELECT entry FROM map_import_prompts WHERE project=? AND digest=?",(pid,digest)).fetchone()
            if not found:
                found = db.execute("""SELECT e.id FROM build_entries e JOIN build_steps s ON e.step=s.id
                    WHERE s.project=? AND e.kind='提示词' AND e.body=? ORDER BY e.id LIMIT 1""", (pid,body)).fetchone()
                if found:
                    db.execute("INSERT INTO map_import_prompts VALUES(?,?,?)",(pid,digest,found[0]))
            if not found:
                if not step:
                    raise ValueError("请给项目添加一个建站步骤，再保存提示词。")
                entry = db.execute("""INSERT INTO build_entries(step,kind,title,body,resolution,created)
                    VALUES(?,'提示词',?,?,'',?)""",(step[0],"页面提示词 · "+label[:100],body,clock())).lastrowid
                db.execute("INSERT INTO map_import_prompts VALUES(?,?,?)",(pid,digest,entry))
            else:
                entry = found[0]
            added += db.execute("INSERT OR IGNORE INTO map_prompt_links VALUES(?,?,'note',?,?)",
                                (pid,path,entry,label[:140])).rowcount
    return {"pages":len(pages),"addedPrompts":added}


def import_file(db, pid, filename, stream, required=True):
    project = db.execute("SELECT site FROM build_projects WHERE id=?", (pid,)).fetchone()
    if not project:
        raise ValueError("找不到这个建站项目。")
    pages, skipped = collect(stream, filename, project["site"])
    if required and not pages:
        raise ValueError("没有找到属于这个网站的页面。请选含页面路径的清单、具体页面的网址地图 XML，或含这些文件的网站 ZIP。")
    return dict(apply(db, pid, pages, filename), skipped=skipped)

