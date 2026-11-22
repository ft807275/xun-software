"""Local, opt-in archive of the visible text in a project's Codex conversations."""

from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import sqlite3
import threading
import time
from library import clock, dbopen, rows
import project_maps
import knowledge

SCHEMA = project_maps.SCHEMA + knowledge.SCHEMA + """
CREATE TABLE IF NOT EXISTS map_page_work(
 project INTEGER NOT NULL REFERENCES build_projects(id),page_key TEXT NOT NULL,
 stage TEXT NOT NULL,todo TEXT NOT NULL,source TEXT NOT NULL DEFAULT '',
 version INTEGER NOT NULL DEFAULT 1,edited_at TEXT NOT NULL DEFAULT '',PRIMARY KEY(project,page_key));
CREATE TABLE IF NOT EXISTS map_prompt_links(
 project INTEGER NOT NULL REFERENCES build_projects(id),page_key TEXT NOT NULL,
 source TEXT NOT NULL,prompt INTEGER NOT NULL,label TEXT NOT NULL,
 PRIMARY KEY(project,page_key,source,prompt));
CREATE TABLE IF NOT EXISTS project_chats(
 id INTEGER PRIMARY KEY, project INTEGER NOT NULL REFERENCES build_projects(id),
 thread TEXT NOT NULL, title TEXT NOT NULL, step INTEGER REFERENCES build_steps(id),
 enabled INTEGER NOT NULL DEFAULT 1, offset INTEGER NOT NULL DEFAULT 0, stamp TEXT NOT NULL DEFAULT '',
 bound TEXT NOT NULL, checked TEXT NOT NULL DEFAULT '', issue TEXT NOT NULL DEFAULT '',
 UNIQUE(project,thread));
CREATE TABLE IF NOT EXISTS chat_text(
 id INTEGER PRIMARY KEY, link INTEGER NOT NULL REFERENCES project_chats(id),
 token TEXT NOT NULL, role TEXT NOT NULL, body TEXT NOT NULL, sent TEXT NOT NULL, 
 step INTEGER REFERENCES build_steps(id), UNIQUE(link,token));
CREATE TABLE IF NOT EXISTS chat_progress(
 message INTEGER PRIMARY KEY REFERENCES chat_text(id), step INTEGER NOT NULL REFERENCES build_steps(id),
 status TEXT NOT NULL, next_task TEXT NOT NULL, sent TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS chat_progress_step_date ON chat_progress(step,sent,message);
CREATE TABLE IF NOT EXISTS chat_issue_origins(
 entry INTEGER NOT NULL REFERENCES build_entries(id) ON DELETE CASCADE,
 answer INTEGER NOT NULL REFERENCES chat_progress(message) ON DELETE CASCADE,
 reported TEXT NOT NULL,PRIMARY KEY(entry,answer));
CREATE INDEX IF NOT EXISTS chat_issue_origin_answer ON chat_issue_origins(answer,entry);
CREATE TABLE IF NOT EXISTS project_prompt_copies(id INTEGER PRIMARY KEY,project INTEGER NOT NULL REFERENCES build_projects(id),
 step INTEGER REFERENCES build_steps(id),body TEXT NOT NULL,created TEXT NOT NULL,origin TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS prompt_copy_project ON project_prompt_copies(project,step);
CREATE TABLE IF NOT EXISTS chat_folders(id INTEGER PRIMARY KEY,project INTEGER NOT NULL REFERENCES build_projects(id),directory TEXT NOT NULL,
 since TEXT NOT NULL,enabled INTEGER NOT NULL,UNIQUE(project,directory));
CREATE TABLE IF NOT EXISTS chat_candidates(rule INTEGER NOT NULL REFERENCES chat_folders(id),thread TEXT NOT NULL,offset INTEGER NOT NULL,
 stamp TEXT NOT NULL,PRIMARY KEY(rule,thread));
CREATE INDEX IF NOT EXISTS chat_text_link_time ON chat_text(link,sent);
"""
SYNC_LOCK = threading.Lock()
UID = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}")
ROOT_TAG = re.compile(
    r"^<(environment_context|system[-_\w]*|developer[-_\w]*|permissions[^ >]*|turn_aborted|subagent[^ >]*|user_message|local_command[^ >]*|app-context|skills_instructions|collaboration_mode|instruction[^ >]*|goal_context|codex_internal_context|agent[^ >]*)\b",
    re.I,
)


def home():
    return (
        Path(os.getenv("CODEX_HOME") or (Path.home() / ".codex")).expanduser().resolve()
    )


def local_files():
    base = home()
    indices = sorted(
        base.glob("state_[0-9]*.sqlite"),
        key=lambda p: int(re.search(r"\d+", p.name).group()),
        reverse=True,
    )
    names = {}
    index = base / "session_index.jsonl"
    if index.is_file():
        with index.open(encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    r = json.loads(line)
                    if r.get("thread_name"):
                        names[r["id"]] = r["thread_name"]
                except (ValueError, KeyError):
                    continue
    catalog = {}

    def add(uid, path, title, source, workspace, updated, created):
        if not UID.fullmatch(str(uid)) or "subagent" in str(source).lower():
            return
        file = Path(path).expanduser().resolve()
        if not any(
            parent in file.parents
            for parent in [base / "sessions", base / "archived_sessions"]
        ):
            return
        if not file.name.endswith(str(uid) + ".jsonl") or not file.is_file():
            return
        title = str(names.get(uid) or title or "").partition("\n")[0][:140]
        if not title or title.startswith(("<", "#")):
            title = "Codex 对话 · " + uid[-8:]
        catalog[uid] = dict(
            id=uid,
            path=file,
            title=title,
            workspace=Path(workspace or "").name,
            directory=str(Path(workspace).resolve()) if workspace else "",
            updated=updated or 0,
            created=created or 0,
        )

    for index in indices:
        try:
            with closing(
                sqlite3.connect(index.as_uri() + "?mode=ro", uri=True, timeout=2)
            ) as db:
                db.row_factory = sqlite3.Row
                for item in db.execute("SELECT * FROM threads"):
                    r = dict(item)
                    if r.get("agent_path"):
                        continue
                    add(
                        r["id"],
                        r["rollout_path"],
                        r.get("name") or r.get("title"),
                        r.get("source"),
                        r.get("cwd"),
                        r.get("updated_at"),
                        r.get("created_at"),
                    )
            return catalog
        except (sqlite3.Error, KeyError):
            continue
    for folder in (base / "sessions", base / "archived_sessions"):
        for file in folder.glob("**/rollout-*.jsonl"):
            try:
                with file.open("rb") as f:
                    meta = json.loads(f.readline(2**20)).get("payload", {})
                add(
                    meta.get("id"),
                    file,
                    "",
                    meta.get("source"),
                    meta.get("cwd"),
                    int(file.stat().st_mtime),
                    datetime.fromisoformat(
                        meta["timestamp"].replace("Z", "+00:00")
                    ).timestamp(),
                )
            except (OSError, ValueError, KeyError):
                continue
    return catalog


def visible(record):
    p = record.get("payload", {})
    if record.get("type") != "response_item":
        return
    if p.get("type") == "function_call_output" and p.get("name") == "create_thread" and p.get("namespace") == "codex_app":
        output = p.get("output")
        match = re.fullmatch(
            r"\s*<codex_delegation>\s*<source_thread_id>[0-9a-f-]+</source_thread_id>\s*<input>(.+)</input>\s*</codex_delegation>\s*",
            output if isinstance(output, str) else "", re.S,
        )
        if match and match[1].strip():
            return "user", match[1].strip(), None
    if p.get("type") != "message":
        return
    role = p.get("role")
    if role not in ("user", "assistant") or (
        role == "assistant"
        and p.get("phase") not in ("final_answer", "commentary", None)
    ):
        return
    parts = []
    for c in p.get("content") or []:
        if c.get("type") != ("input_text" if role == "user" else "output_text"):
            continue
        t = c.get("text")
        if not isinstance(t, str) or not t.strip():
            continue
        if role == "user":
            stripped = t.strip()
            if ROOT_TAG.match(stripped) or stripped.startswith(
                ("<image", "</image", "<user_instructions>", "# AGENTS.md instructions")
            ):
                continue
            if stripped.startswith("<send_user_message_question_reply>"):
                try:
                    answers = json.loads(stripped.partition(">")[2].rsplit("</", 1)[0])
                    t = "\n".join(
                        str(a.get("question", "")) + "\n" + str(a.get("answer", ""))
                        for a in answers
                    )
                except (ValueError, AttributeError):
                    continue
            elif "## My request:" in t and t.lstrip().startswith(
                "# Files mentioned by the user:"
            ):
                attachments = t.partition("## My request:")[0]
                files = re.findall(r"^## (.+?): ", attachments, re.M)
                t = t.partition("## My request:")[2].strip()
                if files:
                    t += "\n\n附件名：" + "、".join(files)
        if t.strip():
            parts.append(t)
    if parts:
        return role, "\n".join(parts), p.get("phase")


def local_time(sent):
    return (
        datetime.fromisoformat(sent.replace("Z", "+00:00"))
        .astimezone()
        .strftime("%Y-%m-%d %H:%M:%S")
    )


def log_revision(stat):
    return f"{stat.st_mtime_ns:020d}:{stat.st_ctime_ns}:{stat.st_dev}:{stat.st_ino}:{stat.st_size}"


def log_unchanged(path, stamp):
    return stamp.startswith("2|") and stamp.startswith("2|" + log_revision(path.stat()) + "|")


def boundary_hash(source, offset):
    start = max(0, offset - 4096)
    source.seek(start)
    return hashlib.sha256(source.read(offset - start)).hexdigest()


def can_resume(stamp, revision, offset, size):
    if not 0 < offset <= size:
        return False
    previous = stamp.split("|")
    if len(previous) != 4 or previous[0] != "2":
        return False
    if previous[1] == revision:
        return True
    old = previous[1].split(":")
    current = revision.split(":")
    # The same file may grow while Codex writes a reply. Re-read a rewritten or
    # replaced file, even if its length and first metadata line stayed the same.
    return len(old) == 5 and old[2:4] == current[2:4] and old[4].isdecimal() and int(old[4]) < size


def read_new(file, offset, stamp):
    messages = []
    with file.open("rb") as f:
        observed = os.fstat(f.fileno())
        revision = log_revision(observed)
        first = f.readline(2048)
        fingerprint = hashlib.sha256(first).hexdigest()
        start = 0
        if can_resume(stamp, revision, offset, observed.st_size):
            _, _, head, tail = stamp.split("|")
            if head == fingerprint and tail == boundary_hash(f, offset):
                start = offset
        f.seek(start)
        end = start
        while True:
            line = f.readline(4096)
            if not line:
                break
            header = line[:900]
            wanted = b'"response_item"' in line[:192] and (
                re.search(rb'"type"\s*:\s*"message"', header)
                or (b'"function_call_output"' in header and b'"create_thread"' in header and b'"codex_app"' in header)
            )
            if not line.endswith(b"\n"):
                if wanted:
                    line += f.readline()
                else:
                    while line and not line.endswith(b"\n"):
                        line = f.readline(1024 * 1024)
            if not line.endswith(b"\n"):
                break
            if wanted:
                data = json.loads(line)
                output = visible(data)
                if output:
                    role, body, phase = output
                    sent = data.get("timestamp", "")
                    local_time(sent)
                    key = hashlib.sha256(
                        json.dumps([sent, role, body], ensure_ascii=False).encode()
                    ).hexdigest()
                    messages.append((key, role, body, sent, phase))
            end = f.tell()
        checkpoint = "|".join(("2", revision, fingerprint, boundary_hash(f, end)))
    return end, checkpoint, messages


def receipt_lines(body):
    lines = []
    fence = None
    for line in body.splitlines():
        line = line.strip()
        if line.startswith(("```", "~~~")):
            marker = line[:3]
            if not fence:
                fence = marker
            elif marker == fence:
                fence = None
        elif not fence:
            lines.append(line)
    return lines


def receipt(db, project, name, body):
    # Explicit final receipt only. Pasted prompts, examples in code blocks and old history never advance a step.
    lines = receipt_lines(body)
    for line in lines:
        match = re.fullmatch(
            r"【建站进度】\s*(.+?)\s*｜\s*(.+?)\s*｜\s*(进行中|已完成)", line
        )
        if not match or match[1] != name:
            continue
        step = db.execute(
            "SELECT id FROM build_steps WHERE project=? AND title=?",
            (project, match[2]),
        ).fetchall()
        if len(step) != 1:
            return
        sid = step[0][0]
        return sid, match[3], lines


def skill_marker(line):
    match = re.fullmatch(r"【使用技能】\s*([^｜]{1,180})｜(.{1,1600})", line)
    if match:
        name, detail = (part.strip() for part in match.groups())
        if name and detail:
            return name, detail
    return None


def page_receipts(lines):
    page_lines = [line[len(project_maps.UPDATE_PREFIX):].strip() for line in lines
                  if line.startswith(project_maps.UPDATE_PREFIX)]
    for raw in page_lines[:12]:
        if len(raw) > 16000:
            continue
        try:
            item = json.loads(raw)
        except (ValueError, RecursionError):
            continue
        if isinstance(item, dict):
            yield item


def reported_issue(line):
    return line[len("【待解决】"):].strip() if line.startswith("【待解决】") else ""


def link_report_issue(db, step, answer, text, created=None):
    existing = db.execute(
        """SELECT e.id FROM build_entries e WHERE e.step=? AND e.kind='问题'
           AND (e.body=? OR EXISTS (
             SELECT 1 FROM chat_issue_origins o WHERE o.entry=e.id AND o.reported=?
           )) ORDER BY e.id LIMIT 1""",
        (step, text, text),
    ).fetchone()
    if existing:
        entry = existing[0]
    elif created is not None:
        entry = db.execute(
            """INSERT INTO build_entries(step,kind,title,body,resolution,created)
               VALUES(?,'问题',?,?,'',?)""",
            (step, text[:120], text, created),
        ).lastrowid
    else:
        return
    db.execute(
        "INSERT OR IGNORE INTO chat_issue_origins(entry,answer,reported) VALUES(?,?,?)",
        (entry, answer, text),
    )


def migrate_issue_origins(db):
    key = "chat_issue_origins_v1"
    revision = "SELECT printf('%d:%d',count(*),coalesce(max(message),0)) FROM chat_progress"
    saved = db.execute("SELECT v FROM settings WHERE k=?", (key,)).fetchone()
    if saved and saved[0] == db.execute(revision).fetchone()[0]:
        return
    with db:
        db.execute("BEGIN IMMEDIATE")
        current = db.execute(revision).fetchone()[0]
        saved = db.execute("SELECT v FROM settings WHERE k=?", (key,)).fetchone()
        if saved and saved[0] == current:
            return
        for row in db.execute(
            """SELECT c.message,c.step,m.body FROM chat_progress c
               JOIN chat_text m ON m.id=c.message AND m.role='assistant'
               JOIN project_chats l ON l.id=m.link
               JOIN build_steps s ON s.id=c.step AND s.project=l.project
               WHERE instr(m.body,'【待解决】')>0
                 AND NOT EXISTS (SELECT 1 FROM chat_issue_origins o WHERE o.answer=c.message)"""
        ):
            for text in dict.fromkeys(map(reported_issue, receipt_lines(row["body"]))):
                if text:
                    link_report_issue(db, row["step"], row["message"], text)
        db.execute("INSERT INTO settings VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (key, current))


def previous_receipt(db, linked, mid, sent):
    return db.execute(
        """SELECT cp.sent,cp.message FROM chat_progress cp JOIN chat_text m ON m.id=cp.message
           WHERE m.link=? AND (cp.sent,cp.message)<(?,?) ORDER BY cp.sent DESC,cp.message DESC LIMIT 1""",
        (linked["id"], sent, mid),
    ).fetchone() or (linked["bound"], 0)


def receipt_prompt(db, linked, mid, sent):
    previous = previous_receipt(db, linked, mid, sent)
    row = db.execute(
        """SELECT id FROM chat_text WHERE link=? AND role='user' AND sent>?
           AND (sent,id)>(?,?) AND (sent,id)<(?,?)
           AND trim(body) NOT LIKE '<codex_internal_context%'
           ORDER BY sent DESC,id DESC LIMIT 1""",
        (linked["id"], linked["bound"], *previous, sent, mid),
    ).fetchone()
    if row:
        return row[0]
    if previous[1] and previous[0] == sent:
        # A rewritten reply can have the same timestamp. Keep the original
        # prompt when no newer user message separates the two receipts.
        first = db.execute(
            """SELECT min(cp.message) FROM chat_progress cp JOIN chat_text m ON m.id=cp.message
               WHERE m.link=? AND cp.sent=? AND cp.message<?""",
            (linked["id"], sent, mid),
        ).fetchone()[0]
        if first:
            return receipt_prompt(db, linked, first, sent)
    return None


def archive_receipt_details(db, linked, mid, sent, directory, lines):
    if not any(line.startswith((knowledge.UPDATE_PREFIX, project_maps.UPDATE_PREFIX)) for line in lines):
        return
    project = linked["project"]
    authorized = [
        row["since"] for row in db.execute(
            "SELECT directory,since FROM chat_folders WHERE project=? AND enabled=1", (project,)
        ) if in_project_folder(directory, Path(row["directory"]))
    ]
    if not authorized:
        return
    step = db.execute("SELECT step FROM chat_progress WHERE message=?", (mid,)).fetchone()[0]
    prompt_id = receipt_prompt(db, linked, mid, sent)
    if prompt_id:
        db.execute("UPDATE chat_text SET step=? WHERE id=? AND step IS NULL", (step, prompt_id))
    stamp = local_time(sent)
    knowledge.apply_chat_update(db, project, mid, prompt_id, sent, stamp, lines)
    if not any(sent > since for since in authorized):
        return
    for item in page_receipts(lines):
        project_maps.save_chat_update(db, project, mid, prompt_id, stamp, item)


def report(db, linked, mid, body, sent, directory, replay=False):
    found = receipt(db, linked["project"], linked["name"], body)
    if not found:
        return False
    sid, status, lines = found
    next_task = next((line[6:].strip() for line in lines if line.startswith("【下次继续】")), "")
    inserted = db.execute(
        "INSERT OR IGNORE INTO chat_progress VALUES(?,?,?,?,?)",
        (mid, sid, status, next_task, sent),
    ).rowcount
    if not inserted:
        if replay:
            archive_receipt_details(db, linked, mid, sent, directory, lines)
        return False

    previous = previous_receipt(db, linked, mid, sent)
    db.execute(
        """UPDATE chat_text SET step=? WHERE link=? AND sent>?
           AND (sent,id)>(?,?) AND (sent,id)<=(?,?)""",
        (sid, linked["id"], linked["bound"], *previous, sent, mid),
    )
    newer = db.execute(
        "SELECT 1 FROM chat_progress WHERE step=? AND (sent,message)>(?,?) LIMIT 1",
        (sid, sent, mid),
    ).fetchone()
    if not newer and not replay:
        db.execute(
            "UPDATE build_steps SET status=?,version=version+1 WHERE id=? AND status<>?",
            (status, sid, status),
        )

    created = local_time(sent)
    for line in lines:
        use = skill_marker(line)
        if use:
            title, detail = use
            db.execute(
                """INSERT INTO build_entries(step,kind,title,body,resolution,created)
                   SELECT ?,'技能使用',?,?,'',? WHERE NOT ? OR NOT EXISTS(
                       SELECT 1 FROM build_entries WHERE step=? AND kind='技能使用'
                       AND title=? AND body=? AND created=?)""",
                (sid, title, detail, created, replay, sid, title, detail, created),
            )
        elif (issue := reported_issue(line)):
            link_report_issue(db, sid, mid, issue, created)
    archive_receipt_details(db, linked, mid, sent, directory, lines)
    return True


def sync(db, ident, catalog, rewind=False):
    with SYNC_LOCK:
        link = db.execute(
            "SELECT l.*,p.name FROM project_chats l JOIN build_projects p ON p.id=l.project WHERE l.id=?",
            (ident,),
        ).fetchone()
        if not link or not link["enabled"]:
            return 0
        source = catalog.get(link["thread"])
        if not source:
            with db:
                db.execute(
                    "UPDATE project_chats SET issue='本机未找到原对话，已备份文字可查看' WHERE id=? AND issue=''",
                    (ident,),
                )
            return 0
        offset, stamp = link["offset"], link["stamp"]
        if not rewind and not link["issue"] and log_unchanged(source["path"], stamp):
            return 0
        end, newstamp, messages = read_new(source["path"], 0 if rewind else offset, stamp)
        num = 0
        with db:
            # Another local instance may have synced or paused this link during the scan.
            updated = db.execute(
                "UPDATE project_chats SET offset=?,stamp=?,issue='',checked=? WHERE id=? AND offset=? AND stamp=? AND enabled=1",
                (end, newstamp, clock(), ident, offset, stamp),
            )
            if not updated.rowcount:
                return 0
            for key, role, body, sent, phase in messages:
                result = db.execute(
                    "INSERT OR IGNORE INTO chat_text(link,token,role,body,sent,step) VALUES(?,?,?,?,?,?)",
                    (ident, key, role, body, sent, link["step"]),
                )
                num += int(bool(result.rowcount))
                if (
                    role == "assistant"
                    and phase == "final_answer"
                    and sent > link["bound"]
                ):
                    if result.rowcount:
                        report(db, link, result.lastrowid, body, sent, source["directory"])
                    elif rewind:
                        archived = db.execute(
                            "SELECT id FROM chat_text WHERE link=? AND token=?", (ident, key),
                        ).fetchone()
                        if archived and report(db, link, archived[0], body, sent, source["directory"], replay=True):
                            num += 1
        return num


def bind(db, project, thread, step, catalog):
    source = catalog.get(thread)
    if not source:
        raise ValueError("本机未找到这段 Codex 对话。")
    step = int(step or 0) or None
    if (
        step
        and not db.execute(
            "SELECT 1 FROM build_steps WHERE id=? AND project=?", (step, project)
        ).fetchone()
    ):
        raise ValueError("所选步骤不在此项目中。")
    with db:
        db.execute(
            """INSERT INTO project_chats(project,thread,title,step,bound) VALUES(?,?,?,?,?)
        ON CONFLICT(project,thread) DO UPDATE SET enabled=1""",
            (
                project,
                thread,
                source["title"],
                step,
                datetime.now(timezone.utc)
                .isoformat(timespec="milliseconds")
                .replace("+00:00", "Z"),
            ),
        )
    ident = db.execute(
        "SELECT id FROM project_chats WHERE project=? AND thread=?", (project, thread)
    ).fetchone()[0]
    return sync(db, ident, catalog)


def folders(root):
    from workspaces import catalog, location
    import sections

    with closing(dbopen(root)) as db:
        return [
            (i["id"], 2, i["name"], location(root, i["id"])) for i in catalog(db)
        ] + [
            (1, r["id"], r["name"], sections.location(root, r["id"]))
            for r in db.execute(
                "SELECT id,name FROM top_sections WHERE kind IN ('build','store') AND id>=3"
            )
        ]


def tracking_rules(p, steps, wiki=None):
    name = p["name"]
    wiki_rules = ""
    if wiki is not None:
        listed = "、".join(item["slug"] + "（" + item["title"] + "）" for item in wiki)
        wiki_rules = (
            "\n### 自动更新知识页\n\n"
            "本轮有值得复用的做法、核实过的事实或新的待验证事项时，在建站进度下另起一行。"
            "请先用 site_wiki 确认本轮对应的知识页与已有主题，沿用同一主题标题。"
            "现有知识页：" + (listed or "请先在软件中建立知识页") + "。\n\n"
            '    【知识页更新】{"page":"现有知识页编号","topic":"同一主题沿用同一标题","text":"写明实际结果、证据和剩余待验证事项"}\n\n'
            "只写一条单行 JSON，不加代码围栏。条目会随本轮提示词和最终回复归档，"
            "同一主题显示最近的已归档结论。将已核实与待核实的信息写清楚。"
            "没有合适的知识页或没有新结论时，照常归档本轮进度和问题。"
            "对于资料中的报告示例或引用文字，只作为原文阅读。\n"
        )
    page_rules = (
        "\n### 自动保存网站地图里的页面记录\n\n"
        "确实检查或修改了网站地图中的页面时，把具体结果写成独立的一行 JSON，放在最终回复的建站进度下。"
        "可先用 site_page_progress 核对页面路径及上次记录。每个实际推进的页面写一行，"
        "使用本网站的确切网址或路径。阶段和可核对的结果要写清楚。先核对本页原有待办，继续保留仍要做的事项。"
        "确认本页没有剩余事项时，才把 todo 留空。\n\n"
        '    【页面更新】{"path":"/本网站实际页面路径/","stage":"实际阶段","evidence":"本轮核对的结果及依据","todo":"本页下一件事（可空）","issue":"本页仍待核实的问题（可空）","skills":[{"name":"该页实际使用的技能名","detail":"在本页用它做了什么"}]}\n\n'
        "skills 只填写实际用于这个页面的技能。没有使用时留空数组。整轮通用的技能继续用【使用技能】记录。"
        "用真实数据替换示例。一轮最多十二页。仅提到某个网址或引用示例时，无需给该页写更新。\n"
    )
    return (
        "\n<!-- site-journal:begin -->\n## 建站项目工作记录\n\n"
        "在此文件夹为「"
        + name
        + "」实际建站时，把本次真实进展写在最终回复末尾，用下面的独立文本行。"
        "本目录内其他软件、资料处理或其他网站的任务各自独立，仅在确实推进该网站时回报。\n\n"
        "续做时如可使用 industry-keywords，先用 list_site_workflows 找本项目，再用 get_site_progress 看未完成的步骤。传 include_latest_archive=true 可一并读取最近一轮提问、回复和待办原文。用 site_wiki 查已整理的交接和建站做法，用 site_records 核对其他原文，用 site_files 找源码与附件。按任务用 search_skill_library 和 read_skill_package 读取技能和引用文件，优先使用已匹配的本机技能。需要以前的原话时用 find_step_prompts 和 read_step_prompt。\n\n"
        "项目步骤为 " + "、".join(steps) + "。每次回报一个本次实际推进的步骤。\n\n"
        "    【建站进度】" + name + "｜实际步骤名｜进行中\n"
        "    【下次继续】下次要做的一件具体事情\n"
        "    【使用技能】实际技能名｜这次具体做了什么（仅在实际使用后填写，每个技能一行）\n"
        "    【待解决】本次遇到且仍未解决的问题（有才写）\n\n"
        "请用实际信息替换示例，正常回复时独立成行，不加代码围栏或引用。"
        "核实整步做完时才写「已完成」。只讨论计划时无需回报完成。\n"
        + page_rules + wiki_rules + "<!-- site-journal:end -->\n"
    )


def write_tracking_rules(directory, row, steps, wiki=None):
    from tempfile import NamedTemporaryFile

    directory = directory.resolve()
    if (
        not directory.is_dir()
        or directory in (Path(directory.anchor), Path.home(), home())
        or home() in directory.parents
    ):
        raise ValueError("请选择在专用网站文件夹里创建的对话。")
    path = directory / "AGENTS.md"
    if path.is_symlink():
        raise ValueError("该文件夹的说明是链接，请选择网站本身的文件夹。")
    original = path.read_bytes() if path.exists() else b""
    text = original.decode("utf-8")
    old = re.search(
        r"\n?<!-- site-journal:begin -->.*?<!-- site-journal:end -->\n?", text, re.S
    )
    if old and "为「" + row["name"] + "」实际建站" not in old.group():
        raise ValueError("该文件夹已配置给另一网站，请选用该站独立的文件夹。")
    block = tracking_rules(row, steps, wiki)
    updated = (text[: old.start()] + block + text[old.end() :]) if old else text + block
    if updated != text:
        with NamedTemporaryFile(dir=directory, delete=False) as f:
            tmp = Path(f.name)
            f.write(updated.encode("utf-8"))
        try:
            if (path.read_bytes() if path.exists() else b"") != original:
                raise ValueError("说明文件刚有改动，请再试一次。")
            if path.exists():
                os.chmod(tmp, path.stat().st_mode & 0o777)
            os.replace(tmp, path)
        finally:
            if tmp.exists():
                tmp.unlink()
    return directory


def step_names(db, project):
    return [row[0] for row in db.execute(
        "SELECT title FROM build_steps WHERE project=? ORDER BY seq,id", (project,)
    )]


def configure_wiki(db, project, enabled):
    p = db.execute("SELECT name FROM build_projects WHERE id=?", (project,)).fetchone()
    if not p:
        raise ValueError("没有这个建站项目。")
    active = [
        Path(r[0]) for r in db.execute(
            "SELECT directory FROM chat_folders WHERE project=? AND enabled=1 ORDER BY id", (project,)
        )
    ]
    active = [path for path in active if path.is_dir()]
    if enabled and not active:
        raise ValueError("请先在这台电脑关联该项目的建站文件夹。")
    pages = knowledge.index(db, project) if enabled else None
    if enabled and not pages:
        raise ValueError("请先建立一页可接收更新的知识页。")
    steps = step_names(db, project)
    for directory in active:
        write_tracking_rules(directory, p, steps, pages)
    stamp = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    with db:
        db.execute(
            """INSERT INTO wiki_automation(project,enabled,since) VALUES(?,?,?)
               ON CONFLICT(project) DO UPDATE SET enabled=excluded.enabled,warning='',
               since=CASE WHEN wiki_automation.enabled=excluded.enabled THEN wiki_automation.since ELSE excluded.since END""",
            (project, int(enabled), stamp),
        )
    return knowledge.auto_status(db, project)


def enable_folder(db, project, link, catalog):
    row = db.execute(
        "SELECT p.name,l.thread FROM project_chats l JOIN build_projects p ON l.project=p.id WHERE l.id=? AND p.id=?",
        (link, project),
    ).fetchone()
    source = catalog.get(row["thread"]) if row else None
    if not source or not source["directory"]:
        raise ValueError("请先关联这个网站在本机的 Codex 对话。")
    return attach_workspace(db, project, source["directory"])


def attach_workspace(db, project, directory):
    row = db.execute("SELECT name FROM build_projects WHERE id=?", (project,)).fetchone()
    folder = Path(directory).resolve()
    if not row:
        raise ValueError("没有这个建站项目。")
    if db.execute(
        "SELECT 1 FROM chat_folders WHERE directory=? AND enabled=1 AND project<>?",
        (str(folder), project),
    ).fetchone():
        raise ValueError("这个文件夹已启用给另一个建站项目。")
    enabled = knowledge.auto_status(db, project)["enabled"]
    directory = write_tracking_rules(
        folder, row, step_names(db, project),
        knowledge.index(db, project) if enabled else None,
    )
    since = (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )
    with db:
        db.execute(
            """INSERT INTO chat_folders(project,directory,since,enabled) VALUES(?,?,?,1)
           ON CONFLICT(project,directory) DO UPDATE SET enabled=1,since=CASE WHEN enabled=0 THEN excluded.since ELSE since END""",
            (project, str(directory), since),
        )
    return directory.name


def workspace_choices(db, project, catalog):
    bound = {r[0]: r[1] for r in db.execute(
        "SELECT directory,project FROM chat_folders WHERE enabled=1"
    )}
    choices = {}
    for source in sorted(catalog.values(), key=lambda item: item["updated"], reverse=True):
        directory = source["directory"]
        if not directory or directory in choices or directory in bound:
            continue
        folder = Path(directory)
        if folder in (Path(folder.anchor), Path.home(), home()) or not folder.is_dir() or home() in folder.parents:
            continue
        choices[directory] = dict(thread=source["id"], path=directory, name=folder.name)
    current = [dict(path=path, name=Path(path).name) for path,pid in bound.items() if pid == project]
    return dict(available=list(choices.values()), current=current)


def in_project_folder(directory, root):
    return bool(directory) and Path(directory).is_relative_to(Path(root))


def discover(db, rule, sources):
    name = db.execute(
        "SELECT name FROM build_projects WHERE id=?", (rule["project"],)
    ).fetchone()[0]
    threshold = datetime.fromisoformat(rule["since"].replace("Z", "+00:00")).timestamp()
    # Linking already stores a resolved directory. Archiving uses the Codex
    # log and the saved path, so an unavailable workspace cannot stall it.
    project_directory = Path(rule["directory"])
    known = {
        r[0]
        for r in db.execute(
            "SELECT thread FROM project_chats WHERE project=?", (rule["project"],)
        )
    }
    for src in sources.values():
        if (
            src["id"] in known
            or not in_project_folder(src["directory"], project_directory)
            or int(src["created"]) + 1 < threshold
        ):
            continue
        cached = db.execute(
            "SELECT offset,stamp FROM chat_candidates WHERE rule=? AND thread=?",
            (rule["id"], src["id"]),
        ).fetchone()
        start, stamp = tuple(cached) if cached else (0, "")
        try:
            if log_unchanged(src["path"], stamp):
                continue
            end, newstamp, messages = read_new(src["path"], start, stamp)
        except (OSError, ValueError):
            logging.exception("Could not read a candidate Codex conversation")
            continue
        match = any(
            role == "assistant"
            and phase == "final_answer"
            and bool(receipt(db, rule["project"], name, body))
            for _, role, body, _, phase in messages
        )
        with db:
            if match:
                db.execute(
                    """INSERT OR IGNORE INTO project_chats(project,thread,title,bound) VALUES(?,?,?,?)""",
                    (rule["project"], src["id"], src["title"], rule["since"]),
                )
            db.execute(
                """INSERT INTO chat_candidates(rule,thread,offset,stamp) VALUES(?,?,?,?)
                ON CONFLICT(rule,thread) DO UPDATE SET offset=excluded.offset,stamp=excluded.stamp""",
                (rule["id"], src["id"], end, newstamp),
            )


def auto_sync(root):
    while True:
        try:
            sources = None
            for _, _, _, folder in folders(root):
                with closing(dbopen(folder)) as db:
                    for rule in db.execute(
                        "SELECT * FROM chat_folders WHERE enabled=1"
                    ).fetchall():
                        if sources is None:
                            sources = local_files()
                        discover(db, rule, sources)
                    for (ident,) in db.execute(
                        "SELECT id FROM project_chats WHERE enabled=1"
                    ).fetchall():
                        try:
                            if sources is None:
                                sources = local_files()
                            sync(db, ident, sources)
                        except (OSError, ValueError, sqlite3.Error):
                            logging.exception("Project chat sync")
                            with db:
                                db.execute(
                                    "UPDATE project_chats SET issue='这次同步中断，下次会重试' WHERE id=?",
                                    (ident,),
                                )
                    knowledge.retry_pending_updates(db)
                    reconcile_page_skills(db)
        except Exception:
            logging.exception("Archive update")
        time.sleep(30)


def sync_project(db, project, sources):
    for rule in db.execute(
        "SELECT * FROM chat_folders WHERE project=? AND enabled=1", (project,)
    ).fetchall():
        discover(db, rule, sources)
    links = db.execute(
        """SELECT l.id,EXISTS(
               SELECT 1 FROM chat_text m LEFT JOIN chat_progress cp ON cp.message=m.id
               WHERE m.link=l.id AND m.role='assistant' AND m.sent>l.bound
                 AND instr(m.body,'【建站进度】')>0 AND cp.message IS NULL
           ) AS needs_replay FROM project_chats l WHERE project=? AND enabled=1""",
        (project,),
    ).fetchall()
    return sum(sync(db, ident, sources, rewind=needs_replay) for ident, needs_replay in links)


def project_followup(db, pid):
    next_task = db.execute(
        """SELECT task,step,at,manual,seq FROM (
          SELECT cp.next_task AS task,s.id AS step,
            strftime('%Y-%m-%d %H:%M:%S',cp.sent,'localtime') AS at,0 AS manual,cp.sent AS sent,cp.message AS seq
          FROM chat_progress cp JOIN build_steps s ON s.id=cp.step
          WHERE s.project=? AND s.status<>'已完成' AND trim(cp.next_task)<>''
          UNION ALL
          SELECT e.body,s.id,e.created,1,'',e.id FROM build_entries e JOIN build_steps s ON s.id=e.step
          WHERE s.project=? AND e.kind='下一步' AND s.status<>'已完成' AND trim(e.body)<>''
        ) ORDER BY at DESC,manual DESC,sent DESC,seq DESC LIMIT 1""",
        (pid, pid),
    ).fetchone()
    source = None
    if next_task:
        source = dict(source="note" if next_task["manual"] else "chat", id=next_task["seq"],
                      created=next_task["at"] or "")
        if source["source"] == "chat":
            article = db.execute(
                "SELECT slug,topic FROM wiki_chat_updates WHERE project=? AND answer=?",
                (pid, source["id"]),
            ).fetchone()
            if article:
                source["knowledge"] = dict(article)
    open_issues = db.execute(
        """SELECT count(*) FROM build_entries e JOIN build_steps s ON s.id=e.step
        WHERE s.project=? AND e.kind='问题' AND trim(e.resolution)=''""",
        (pid,),
    ).fetchone()[0]
    return dict(
        nextTask=next_task["task"] if next_task else "",
        nextTaskStep=next_task["step"] if next_task else None,
        nextTaskSource=source,
        openIssues=open_issues,
    )


ARCHIVED_TURN_SCOPE = """
    FROM project_chats l JOIN chat_text m ON m.link=l.id
    JOIN chat_progress cp ON cp.message=m.id JOIN build_steps s ON s.id=cp.step
    WHERE l.project=?"""


def latest_archive(db, project):
    row = db.execute(
        "SELECT m.id AS answer,m.sent" + ARCHIVED_TURN_SCOPE +
        " ORDER BY m.sent DESC,m.id DESC LIMIT 1", (project,),
    ).fetchone()
    return dict(answer=row["answer"], sent=local_time(row["sent"])) if row else None


def overview(root, prompts_only=False):
    results = []
    for industry, section, label, folder in folders(root):
        with closing(dbopen(folder)) as db:
            for p in db.execute("SELECT id,name,site FROM build_projects ORDER BY id"):
                steps = rows(
                    db,
                    "SELECT id,title,status FROM build_steps WHERE project=? ORDER BY seq,id",
                    (p["id"],),
                )
                if prompts_only:
                    counts = prompt_counts(db, p["id"])
                    results.append(dict(p, label=label, industry=industry, section=section, steps=steps,
                                        promptTotal=sum(counts.values())))
                    continue
                skill_names = [
                    row[0] for row in db.execute(
                        "SELECT name FROM build_skills WHERE project=? ORDER BY id",
                        (p["id"],),
                    )
                ]
                results.append(dict(
                    p, label=label, industry=industry, section=section,
                    steps=steps, skillNames=skill_names, latestArchive=latest_archive(db, p["id"]),
                    **project_followup(db, p["id"]),
                ))
    return results


def links(db, pid):
    return rows(
        db,
        """SELECT l.id,l.thread,l.title,l.enabled,l.issue,l.checked,s.title AS step,count(m.id) AS total,
           count(CASE WHEN m.role='user' THEN 1 END) AS prompts FROM project_chats l
           LEFT JOIN chat_text m ON m.link=l.id LEFT JOIN build_steps s ON s.id=l.step
           WHERE l.project=? GROUP BY l.id ORDER BY l.id""",
        (pid,),
    )


def issue_origins(db, project, entry):
    return rows(
        db,
        """SELECT m.id AS answer,l.title AS chat,
                  strftime('%Y-%m-%d %H:%M:%S',m.sent,'localtime') AS sent,
                  w.slug AS wikiSlug,w.topic AS wikiTopic
           FROM chat_issue_origins o JOIN chat_text m ON m.id=o.answer
           JOIN project_chats l ON l.id=m.link
           LEFT JOIN wiki_chat_updates w ON w.answer=m.id AND w.project=l.project
           WHERE o.entry=? AND l.project=? ORDER BY m.sent DESC,m.id DESC""",
        (entry, project),
    )


def receipt_issues(db, answer, body):
    linked = {
        row["reported"]: {"id": row["id"], "title": row["title"], "resolved": row["resolved"]}
        for row in db.execute(
            """SELECT o.reported,e.id,e.title,length(trim(e.resolution))>0 AS resolved
               FROM chat_issue_origins o JOIN build_entries e ON e.id=o.entry
               WHERE o.answer=? ORDER BY e.id DESC""",
            (answer,),
        )
    }
    issues = {}
    for line in receipt_lines(body):
        text = reported_issue(line)
        if text:
            issues[text] = linked.get(text, {"title": text[:120], "id": None})
    return issues


def archived_turns(db, project, before=None, limit=6, *, answer=None):
    bounds = ""
    args = [project]
    if before:
        earlier = db.execute(
            """SELECT m.sent,m.id FROM chat_text m JOIN chat_progress cp ON cp.message=m.id
               JOIN project_chats l ON l.id=m.link WHERE l.project=? AND m.id=?""",
            (project, int(before)),
        ).fetchone()
        if earlier is None:
            raise ValueError("这条归档记录不属于当前项目。")
        bounds = " AND (m.sent,m.id)<(?,?)"
        args.extend(earlier)
    if answer is not None:
        bounds += " AND m.id=?"
        args.append(int(answer))
    turns = []
    for row in db.execute(
        """SELECT l.id,l.bound,l.title AS chat,m.id AS answer,m.body,m.sent,cp.step,
                  s.title AS stepTitle,cp.status,cp.next_task AS nextTask""" +
        ARCHIVED_TURN_SCOPE + bounds + " ORDER BY m.sent DESC,m.id DESC LIMIT ?",
        (*args, limit + 1),
    ):
        if len(turns) == limit:
            return {"turns": turns, "before": turns[-1]["answer"]}
        answer = row["answer"]
        pages = project_maps.receipt_pages(db, project, answer)
        article = db.execute(
            "SELECT slug,topic,prompt FROM wiki_chat_updates WHERE project=? AND answer=?",
            (project, answer),
        ).fetchone()
        prompt = (article["prompt"] if article else None) or next(
            (page["prompt"] for page in pages if page["prompt"]), None
        ) or receipt_prompt(db, row, answer, row["sent"])
        issues = receipt_issues(db, answer, row["body"])
        for page in pages:
            if page["issue"] in issues:
                page["issue"] = ""
        turn = {key: row[key] for key in ("answer", "chat", "stepTitle", "status", "nextTask")}
        turns.append(dict(turn, sent=local_time(row["sent"]), prompt=prompt,
                          issues=list(issues.values()),
                          wiki=dict(article) if article else None, pages=pages))
    return {"turns": turns, "before": None}


def latest_archived_turn(db, project):
    return next(iter(archived_turns(db, project, limit=1)["turns"]), None)


def journal(db, pid, q):
    sql = """WITH records AS (
      SELECT e.id,'note' AS src,e.kind,e.title,e.body,e.resolution,e.created,s.title AS step,'' AS chat FROM build_entries e
        JOIN build_steps s ON s.id=e.step WHERE s.project=?
      UNION ALL
      SELECT m.id,'chat',CASE m.role WHEN 'user' THEN '提示词' ELSE 'Codex 回复' END,'',m.body,'',
        strftime('%Y-%m-%d %H:%M:%S',m.sent,'localtime'),s.title,l.title FROM chat_text m
        JOIN project_chats l ON l.id=m.link LEFT JOIN build_steps s ON s.id=m.step WHERE l.project=?
    ) SELECT id,src,kind,substr(CASE WHEN title='' THEN body ELSE title END,1,160) AS title,created,step,chat,
      CASE WHEN kind='问题' AND trim(resolution)='' THEN 1 ELSE 0 END AS unresolved FROM records
      WHERE (?='' OR kind=? OR (?='待解决' AND kind='问题' AND trim(resolution)=''))
       AND (?='' OR instr(lower(body||' '||title||' '||resolution||' '||chat||' '||coalesce(step,'')),lower(?))>0)
      ORDER BY created DESC,src,id DESC LIMIT 21 OFFSET ?"""
    kind = q.get("kind", "")
    find = q.get("find", "")
    offset = max(0, int(q.get("offset") or 0))
    result = rows(db, sql, (pid, pid, kind, kind, kind, find, find, offset))
    return dict(
        items=result[:20],
        more=len(result) > 20,
        guideId=db.execute(
            "SELECT max(e.id) FROM build_entries e JOIN build_steps s ON s.id=e.step WHERE s.project=? AND e.kind='操作指南'",
            (pid,),
        ).fetchone()[0],
        **project_followup(db, pid),
    )


def message(db, pid, mid):
    result = db.execute(
        """SELECT m.body,m.role,l.title,s.title AS stepTitle,
        coalesce(strftime('%Y-%m-%d %H:%M:%S',m.sent,'localtime'),'') AS created
        FROM chat_text m JOIN project_chats l ON l.id=m.link LEFT JOIN build_steps s ON s.id=m.step
        WHERE l.project=? AND m.id=?""",
        (pid, mid),
    ).fetchone()
    if not result:
        raise ValueError("没有找到这条项目记录。")
    return dict(result)


def thread_rows(db, pid, link, find, offset):
    source = db.execute(
        "SELECT title FROM project_chats WHERE id=? AND project=?", (link, pid)
    ).fetchone()
    if not source:
        raise ValueError("该对话不在此项目。")
    items = rows(
        db,
        """SELECT m.id,m.role,substr(m.body,1,160) AS preview,
            strftime('%Y-%m-%d %H:%M:%S',m.sent,'localtime') AS sent,s.title AS step FROM chat_text m
            LEFT JOIN build_steps s ON s.id=m.step WHERE m.link=? AND (?='' OR instr(lower(m.body),lower(?))>0)
            ORDER BY m.sent,m.id LIMIT 21 OFFSET ?""",
        (link, find, find, max(0, int(offset))),
    )
    return dict(title=source[0], items=items[:20], more=len(items) > 20)


def prompt_replies(db, pid, mid, offset=0):
    owner = db.execute(
        """SELECT m.link FROM chat_text m JOIN project_chats l ON l.id=m.link
        WHERE l.project=? AND m.id=? AND m.role='user'""",
        (pid, mid),
    ).fetchone()
    if not owner:
        raise ValueError("这句提问不在当前项目。")
    until = db.execute(
        "SELECT min(id) FROM chat_text WHERE link=? AND id>? AND role='user'",
        (owner[0], mid),
    ).fetchone()[0]
    items = rows(
        db,
        "SELECT id,substr(body,1,180) AS preview,sent FROM chat_text WHERE link=? AND role='assistant' AND id>? AND id<? ORDER BY id LIMIT 21 OFFSET ?",
        (owner[0], mid, until or 2**63 - 1, max(0, int(offset))),
    )
    return dict(items=items[:20], more=len(items) > 20)


def revision(db, pid):
    return list(
        db.execute(
            """SELECT
       (SELECT coalesce(sum(version),0) FROM build_steps WHERE project=?),
       (SELECT coalesce(sum(e.version),0) FROM build_entries e JOIN build_steps s ON s.id=e.step WHERE s.project=?),
       (SELECT coalesce(max(m.id),0) FROM chat_text m JOIN project_chats l ON l.id=m.link WHERE l.project=?),
       (SELECT coalesce(max(cp.message),0) FROM chat_progress cp JOIN build_steps s ON s.id=cp.step WHERE s.project=?),
       (SELECT coalesce(sum(version),0) FROM wiki_pages WHERE project=?),
       (SELECT count(*) FROM map_page_updates WHERE project=?)""",
            (pid, pid, pid, pid, pid, pid),
        ).fetchone()
    )


# Every reusable prompt carries its original wording and its source website.
PROMPTS = """SELECT m.id,'chat' AS source,m.step AS step,m.body,m.sent AS created,l.title AS origin
 FROM chat_text m JOIN project_chats l ON l.id=m.link WHERE l.project=? AND m.role='user'
 AND ltrim(m.body) NOT LIKE '<codex_internal_context%'
 UNION ALL SELECT e.id,CASE WHEN e.kind='复用模板' THEN 'template' ELSE 'note' END,e.step,e.body,e.created,coalesce(nullif(e.title,''),'项目记录')
 FROM build_entries e JOIN build_steps s ON s.id=e.step WHERE s.project=? AND e.kind IN ('提示词','复用模板')
 UNION ALL SELECT id,'reference',step,body,created,origin FROM project_prompt_copies WHERE project=?"""


def prompt_counts(db, pid):
    return {
        str(r[0] or 0): r[1]
        for r in db.execute(
            "SELECT step,count(*) FROM (" + PROMPTS + ") GROUP BY step", (pid,) * 3
        )
    }


def prompts(db, pid, q, limit=20):
    conditions = []
    args = [pid] * 3
    if q.get("step", "") != "":
        conditions.append("coalesce(step,0)=?")
        args.append(int(q["step"]))
    if q.get("find", "").strip():
        conditions.append("instr(lower(body||' '||origin),lower(?))>0")
        args.append(q["find"].strip())
    offset = max(0, int(q.get("offset") or 0))
    where = " WHERE " + " AND ".join(conditions) if conditions else ""
    found = rows(
        db,
        "SELECT id,source,step,substr(trim(body),1,150) AS preview,origin,"
        "CASE WHEN source='chat' THEN coalesce(strftime('%Y-%m-%d %H:%M:%S',created,'localtime'),created) ELSE created END AS shown_at FROM ("
        + PROMPTS
        + ")"
        + where
        + " ORDER BY shown_at DESC,source,id DESC LIMIT ? OFFSET ?",
        (*args, limit + 1, offset),
    )
    return dict(items=found[:limit], more=len(found) > limit)


def prompt_stage(db, pid, next_step):
    steps = rows(db, "SELECT id,title,status FROM build_steps WHERE project=? ORDER BY seq,id", (pid,))
    active = [step for step in steps if step["status"] != "已完成"]
    current = next((step for step in active if step["id"] == next_step), None) or next(
        (step for step in active if step["status"] == "进行中"), active[0] if active else None)
    return steps, current["id"] if current else None


def prompt_board(db, pid, q):
    project = db.execute("SELECT id,name,site FROM build_projects WHERE id=?", (pid,)).fetchone()
    steps, current = prompt_stage(db, pid, project_followup(db, pid)["nextTaskStep"])
    selected = q.get("step", "current")
    if selected == "current":
        selected = str(current) if current else "all"
    if selected not in {"all", "0", *(str(step["id"]) for step in steps)}:
        raise ValueError("所选步骤已变动，请从项目提示词重新打开。")
    listing = prompts(db, pid, dict(q, step="" if selected == "all" else selected))
    return dict(listing, project=dict(project, steps=steps), selected=selected, current=current,
                counts=prompt_counts(db, pid))


def prompt_text(db, pid, source, ident):
    r = db.execute(
        "SELECT body,origin FROM (" + PROMPTS + ") WHERE source=? AND id=?",
        (*[pid] * 3, source, int(ident)),
    ).fetchone()
    if not r:
        raise ValueError("这条提示词不在当前项目。")
    return dict(r)


def migrate_page_work(db):
    if any(row[1] == "edited_at" for row in db.execute("PRAGMA table_info(map_page_work)")):
        return
    with db:
        db.execute("BEGIN IMMEDIATE")
        if not any(row[1] == "edited_at" for row in db.execute("PRAGMA table_info(map_page_work)")):
            db.execute("ALTER TABLE map_page_work ADD COLUMN edited_at TEXT NOT NULL DEFAULT ''")
            db.execute(f"UPDATE map_page_work SET edited_at={project_maps.UTC_NOW} WHERE source='手动更新'")


def migrate_page_skills(db):
    with db:
        if not any(row[1] == "skills_checked" for row in db.execute("PRAGMA table_info(map_page_updates)")):
            db.execute("BEGIN IMMEDIATE")
            if not any(row[1] == "skills_checked" for row in db.execute("PRAGMA table_info(map_page_updates)")):
                db.execute("ALTER TABLE map_page_updates ADD COLUMN skills_checked INTEGER NOT NULL DEFAULT 0")
        db.execute("CREATE INDEX IF NOT EXISTS map_skill_scan ON map_page_updates(skills_checked) WHERE skills_checked=0")


def reconcile_page_skills(db):
    pending = db.execute(
        """SELECT u.project,u.page_key,u.answer,m.body,p.name,p.site FROM map_page_updates u
           JOIN chat_text m ON m.id=u.answer JOIN build_projects p ON p.id=u.project
           JOIN project_chats l ON l.id=m.link AND l.project=u.project
           WHERE skills_checked=0 AND m.role='assistant' ORDER BY u.rowid LIMIT 100""",
    ).fetchall()
    with db:
        for row in pending:
            verified = receipt(db, row["project"], row["name"], row["body"])
            items = page_receipts(verified[2]) if verified else ()
            uses = next((item.get("skills") for item in items
                         if project_maps.route(item.get("path"), row["site"]) == row["page_key"]), None)
            project_maps.archive_page_skills(db, row["project"], row["page_key"], row["answer"], uses)


def related_page_skill_rows(db, project, project_name, path, site, answer=None):
    if not path:
        return
    sql = """SELECT m.id,m.body,m.sent FROM chat_text m JOIN project_chats l ON l.id=m.link
             WHERE l.project=? AND m.role='assistant' AND instr(m.body,'【使用技能】')>0
               AND instr(m.body,?)>0"""
    args = [project, path.rstrip("/") or "/"]
    if answer is not None:
        sql += " AND m.id=?"
        args.append(answer)
    for row in db.execute(sql + " ORDER BY m.sent DESC,m.id DESC", args):
        if not project_maps.mentions(row["body"], path, site):
            continue
        verified = receipt(db, project, project_name, row["body"])
        if not verified or any("skills" in item for item in page_receipts(verified[2])):
            continue
        uses = dict(use for line in verified[2] if (use := skill_marker(line)))
        if uses:
            yield row["id"], local_time(row["sent"]), uses


def change_page_skill(db, project, key, answer, name, remove=False):
    if type(answer) is not int or not 0 < answer < 2**63 or not isinstance(name, str):
        raise ValueError("请选择一条实际的技能记录。")
    site = db.execute("SELECT name,site FROM build_projects WHERE id=?", (project,)).fetchone()
    if not site:
        raise ValueError("找不到这个建站项目。")
    with db:
        db.execute("BEGIN IMMEDIATE")
        path = project_maps.known_page(db, project, key)
        if remove:
            return {"changed": bool(db.execute(
                """DELETE FROM map_page_skills WHERE project=? AND page_key=? AND answer=? AND name=?
                   AND origin='已核对历史原文'""",
                (project, path, answer, name),
            ).rowcount)}
        candidate = next(related_page_skill_rows(db, project, site["name"], path, site["site"], answer), None)
        if not candidate or name not in candidate[2]:
            raise ValueError("在本项目中找不到这页的技能原文。")
        return {"changed": project_maps.save_page_skill(
            db, project, path, answer, name, candidate[2][name], "已核对历史原文",
        )}


def page_record(db, pid, key):
    project = db.execute("SELECT name,site FROM build_projects WHERE id=?", (pid,)).fetchone()
    site = project["site"]
    path = project_maps.route(key, site)
    work = project_maps.saved_work(db, pid, key, path)
    variants = (key, path, path.rstrip("/") or path)
    links, attached = [], set()
    for item in rows(db, """SELECT source,prompt AS id,label FROM map_prompt_links
        WHERE project=? AND page_key IN (?,?,?) ORDER BY prompt,source,page_key=? DESC""",
        (pid, *variants, key)):
        pair = item["source"], item["id"]
        if pair not in attached:
            links.append(item)
            attached.add(pair)
    automatic = project_maps.read_chat_updates(db, pid, path) if path else []
    for update in automatic:
        prompt_id = update["prompt"]
        if prompt_id and ("chat", prompt_id) not in attached:
            links.append(dict(source="chat", id=prompt_id, label="本页的 Codex 提问 · " + update["updated"]))
            attached.add(("chat", prompt_id))
    related = []
    issues = []
    if path:
        for r in db.execute("SELECT * FROM (" + PROMPTS + ") WHERE source IN ('chat','note') AND instr(body,?)>0 ORDER BY created DESC,id DESC",
                            (*[pid] * 3, path.rstrip("/") or "/")):
            if (r["source"], r["id"]) not in attached and project_maps.mentions(r["body"], path, site):
                related.append(dict(id=r["id"], source=r["source"], label=r["body"].strip().splitlines()[0][:140]))
    for r in db.execute("""SELECT e.id,e.title,e.body,e.resolution,e.kind,e.version,s.title AS stepTitle,
          EXISTS(SELECT 1 FROM map_issue_links m WHERE m.project=s.project AND m.page_key IN (?,?,?) AND m.entry=e.id) AS linked
          FROM build_entries e JOIN build_steps s ON s.id=e.step
          WHERE s.project=? AND e.kind IN ('问题','待办','下一步') ORDER BY e.id DESC""", (*variants,pid)):
        if r["linked"] or (path and project_maps.mentions(r["title"]+" "+r["body"], path, site)):
            issues.append({k: r[k] for k in ("id", "title", "body", "resolution", "kind", "version", "stepTitle")})
    tracked = db.execute(
        "SELECT 1 FROM chat_folders WHERE project=? AND enabled=1 LIMIT 1", (pid,)
    ).fetchone()
    skills = project_maps.read_page_skills(db, pid, path) if path else []
    confirmed = {(r["answer"], r["name"].casefold()) for r in skills}
    candidates = []
    for answer, used, entries in related_page_skill_rows(db, pid, project["name"], path, site):
        candidates.extend(dict(answer=answer, name=name, detail=detail, used=used)
                          for name, detail in entries.items() if (answer, name.casefold()) not in confirmed)
        if len(candidates) >= 20:
            break
    current = project_maps.current_work(work, automatic[0] if automatic else None)
    return dict(work=work, current=current, todoSource=project_maps.todo_source(current),
                prompts=links, related=related, issues=issues, automatic=automatic, tracked=bool(tracked),
                skills=skills, relatedSkills=candidates[:20])


def update_page_record(db, pid, args):
    from buildwork import checked

    key = checked(args, "key", 2048, True)
    if args.get("attach"):
        source = checked(args, "source", 30, True)
        ident = int(args["id"])
        with db:
            db.execute("BEGIN IMMEDIATE")
            original = prompt_text(db, pid, source, ident)
            label = original["body"].strip().splitlines()
            db.execute("""INSERT OR IGNORE INTO map_prompt_links
                (project,page_key,source,prompt,label) VALUES(?,?,?,?,?)""",
                (pid, key, source, ident, (label[0][:100] if label else "") or original["origin"]))
    else:
        stage = checked(args, "stage", 180, True)
        todo = checked(args, "todo", 12000)
        version = int(args.get("version") or 0)
        with db:
            db.execute("BEGIN IMMEDIATE")
            path = project_maps.known_page(db, pid, key)
            saved = project_maps.saved_work(db, pid, key, path)
            if saved:
                changed = db.execute(f"""UPDATE map_page_work SET stage=?,todo=?,source='手动更新',
                    edited_at={project_maps.UTC_NOW},version=version+1 WHERE project=? AND page_key=? AND version=?""",
                    (stage,todo,pid,saved["page_key"],version))
            elif not version:
                changed = db.execute(f"""INSERT INTO map_page_work
                    (project,page_key,stage,todo,source,edited_at) VALUES(?,?,?,?,'手动更新',{project_maps.UTC_NOW})""",
                    (pid,path or key,stage,todo))
            else:
                raise ValueError("页面记录已更新，请重新打开后再保存。")
            if not changed.rowcount:
                raise ValueError("页面记录已更新，请重新打开后再保存。")
    return page_record(db, pid, key)


def update_issue_resolution(db, entry, args):
    from buildwork import checked

    resolution = checked(args, "resolution", 50000, True, True)
    version = int(args.get("version") or 0)
    changed = db.execute(
        "UPDATE build_entries SET resolution=?,version=version+1 WHERE id=? AND version=?",
        (resolution, entry, version),
    )
    if not changed.rowcount:
        raise ValueError("这条问题已在其他窗口更新，请重新打开后再保存。")


def resolve_project_issue(db, pid, args):
    entry = int(args["id"])
    with db:
        db.execute("BEGIN IMMEDIATE")
        if not db.execute(
            """SELECT 1 FROM build_entries e JOIN build_steps s ON s.id=e.step
               WHERE s.project=? AND e.kind='问题' AND e.id=?""", (pid, entry)
        ).fetchone():
            raise ValueError("这条问题不属于当前项目。")
        update_issue_resolution(db, entry, args)
    return {"id": entry}


def save_page_issue(db, pid, args):
    from buildwork import checked

    key = checked(args, "key", 2048, True)
    with db:
        db.execute("BEGIN IMMEDIATE")
        path = project_maps.known_page(db, pid, key)
        if not path:
            raise ValueError("请先为这个页面添加网址，再保存页面问题。")
        variants = (key, path, path.rstrip("/") or path)
        entry = int(args.get("id") or 0)
        if entry:
            issue = db.execute(
                """SELECT e.id,e.title,e.body,p.site,EXISTS(
                     SELECT 1 FROM map_issue_links m WHERE m.project=s.project
                     AND m.entry=e.id AND m.page_key IN (?,?,?)
                   ) AS linked FROM build_entries e JOIN build_steps s ON s.id=e.step
                   JOIN build_projects p ON p.id=s.project
                   WHERE p.id=? AND e.id=? AND e.kind='问题'""",
                (*variants, pid, entry),
            ).fetchone()
            if not issue or not (issue["linked"] or project_maps.mentions(
                issue["title"] + " " + issue["body"], path, issue["site"]
            )):
                raise ValueError("这条问题不属于当前页面。")
            update_issue_resolution(db, entry, args)
        else:
            step = int(args.get("step") or 0)
            if not db.execute(
                "SELECT 1 FROM build_steps WHERE id=? AND project=?", (step, pid)
            ).fetchone():
                raise ValueError("请选择这个项目的建站步骤。")
            body = checked(args, "body", 20000, True)
            existing = db.execute(
                """SELECT e.id FROM build_entries e JOIN map_issue_links m ON m.entry=e.id
                   WHERE m.project=? AND m.page_key IN (?,?,?) AND e.step=? AND e.kind='问题'
                   AND e.body=? ORDER BY e.id LIMIT 1""",
                (pid, *variants, step, body),
            ).fetchone()
            if existing:
                return {"id": existing[0], "duplicate": True}
            entry = db.execute(
                """INSERT INTO build_entries(step,kind,title,body,resolution,created)
                   VALUES(?,'问题',?,?,'',?)""",
                (step, body.splitlines()[0][:120], body, clock()),
            ).lastrowid
        db.execute(
            "INSERT OR IGNORE INTO map_issue_links(project,page_key,entry) VALUES(?,?,?)",
            (pid, path, entry),
        )
    return {"id": entry}


def copy_workflow(source, target, pid, args):
    import buildwork

    name = buildwork.checked(args, "name", 140, True)
    request = args.get("request", "")
    if not re.fullmatch(r"[a-zA-Z0-9-]{16,64}", request):
        raise ValueError("请重新打开新网站表单。")
    source.execute("BEGIN")
    project = source.execute(
        "SELECT name FROM build_projects WHERE id=?", (pid,)
    ).fetchone()
    if not project:
        raise ValueError("来源项目不存在。")
    template_only = args.get("promptMode") == "templates"
    if (
        template_only
        and not source.execute(
            "SELECT 1 FROM (" + PROMPTS + ") WHERE source='template' LIMIT 1",
            (pid,) * 3,
        ).fetchone()
    ):
        raise ValueError("该项目还没有复用模板。")
    default_notes = dict((*buildwork.STEPS, *buildwork.STORE_STEPS))
    with target:
        target.execute("BEGIN IMMEDIATE")
        existing = target.execute(
            "SELECT action,item FROM build_requests WHERE token=?", (request,)
        ).fetchone()
        if existing:
            if existing["action"] != "copy-workflow":
                raise ValueError("请重新打开表单。")
            return dict(id=existing["item"])
        if target.execute(
            "SELECT 1 FROM build_projects WHERE name=?", (name,)
        ).fetchone():
            raise ValueError("这个名字已被使用，请为新站换一个项目名称。")
        new = target.execute(
            "INSERT INTO build_projects(name,site,notes,created) VALUES(?,'',?,?)",
            (name, "沿用「" + project["name"] + "」的流程与提示词。", clock()),
        ).lastrowid
        ids = {}
        for step in source.execute(
            "SELECT * FROM build_steps WHERE project=? ORDER BY seq,id", (pid,)
        ):
            ids[step["id"]] = target.execute(
                "INSERT INTO build_steps(project,seq,title,notes,status) VALUES(?,?,?,?,'待开始')",
                (
                    new,
                    step["seq"],
                    step["title"],
                    (
                        default_notes.get(step["title"], "填写新网站的目标和进展。")
                        if template_only
                        else step["notes"]
                    ),
                ),
            ).lastrowid
        for r in source.execute(PROMPTS, (pid,) * 3):
            if r["source"] == "template":
                target.execute(
                    "INSERT INTO build_entries(step,kind,title,body,resolution,created) VALUES(?,'复用模板',?,?,'',?)",
                    (ids[r["step"]], r["origin"], r["body"], clock()),
                )
                continue
            if template_only:
                continue
            origin = (
                (project["name"] + " · " + r["origin"])
                if r["source"] != "reference"
                else r["origin"]
            )
            target.execute(
                "INSERT INTO project_prompt_copies(project,step,body,created,origin) VALUES(?,?,?,?,?)",
                (new, ids.get(r["step"]), r["body"], r["created"], origin),
            )
        target.execute(
            "INSERT INTO build_requests VALUES(?,'copy-workflow',?)", (request, new)
        )
        return dict(id=new)
