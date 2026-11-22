"""Private, per-industry site projects, working notes and top-level navigation plans."""

import hashlib
from pathlib import PureWindowsPath
import re
from urllib.parse import urlsplit
from library import clock, rows

STEPS = (
    ("项目需求", "记录产品、目标客户、市场和网站目标。"),
    ("关键词与同行", "从行业资料库挑选目标词，核对同行官网和排名页。"),
    ("网站架构与一级栏目", "确定导航顺序，为每个一级页面填写目标、路径和主关键词。"),
    ("页面内容与配图", "整理文案、产品资料和页面配图。"),
    ("设计与开发", "记录设计决定、实现提示词和开发问题。"),
    ("验收与上线", "检查导航、表单、手机显示和上线结果。"),
)
NAV = (
    ("首页", "/", "介绍核心业务，引导访客进入产品和询盘。"),
    ("产品中心", "/products/", "按产品类型展示产品，链接到具体产品页。"),
    ("解决方案", "/solutions/", "说明产品适用的行业与场景。"),
    ("关于我们", "/about/", "介绍企业、制造能力与可核实的资质。"),
    ("联系我们", "/contact/", "提供联系方式和询价入口。"),
)
STORE_STEPS = (
    ("选品与客户定位", "记录目标买家、商品范围和定价依据。"),
    ("关键词与竞店", "核对商品词和同类商店。"),
    ("网站架构与一级栏目", "规划商城导航和商品集合。"),
    ("商品详情与配图", "整理商品信息、规格、图片和购买说明。"),
    ("支付、配送与退换", "记录支付方式、运费、配送范围和退换政策。"),
    ("下单测试与上线", "验证下单、结账和订单通知。"),
)
STORE_NAV = (
    ("商城首页", "/", "介绍店铺与主推商品。"),
    ("全部商品", "/collections/", "按集合浏览商品。"),
    ("新品", "/new/", "查看新上架商品。"),
    ("配送与退换", "/shipping-returns/", "说明运费、配送和退换。"),
    ("联系我们", "/contact/", "提供售前与售后联系入口。"),
)
STEP_STATUS = ("待开始", "进行中", "已完成")
PAGE_STATUS = ("草案", "已确认", "已上线", "暂不采用")
KINDS = ("步骤笔记", "提示词", "对话", "问题")
SCHEMA = """
CREATE TABLE IF NOT EXISTS build_projects(
 id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, site TEXT NOT NULL, notes TEXT NOT NULL,
 created TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS build_project_names(
 project INTEGER NOT NULL REFERENCES build_projects(id) ON DELETE CASCADE,
 name TEXT NOT NULL, PRIMARY KEY(project,name));
CREATE TRIGGER IF NOT EXISTS build_project_previous_name
 AFTER UPDATE OF name ON build_projects WHEN OLD.name<>NEW.name
 BEGIN
   INSERT OR IGNORE INTO build_project_names(project,name) VALUES(OLD.id,OLD.name);
 END;
CREATE TABLE IF NOT EXISTS build_steps(
 id INTEGER PRIMARY KEY, project INTEGER NOT NULL REFERENCES build_projects(id),
 seq INTEGER NOT NULL, title TEXT NOT NULL, notes TEXT NOT NULL, status TEXT NOT NULL,
 version INTEGER NOT NULL DEFAULT 1, UNIQUE(project,seq));
CREATE TABLE IF NOT EXISTS build_pages(
 id INTEGER PRIMARY KEY, project INTEGER NOT NULL REFERENCES build_projects(id),
 seq INTEGER NOT NULL, title TEXT NOT NULL, path TEXT NOT NULL, keyword TEXT NOT NULL,
 notes TEXT NOT NULL, status TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1, UNIQUE(project,path));
CREATE INDEX IF NOT EXISTS build_page_order ON build_pages(project,seq,id);
CREATE TABLE IF NOT EXISTS build_skills(
 id INTEGER PRIMARY KEY, project INTEGER NOT NULL REFERENCES build_projects(id), name TEXT NOT NULL,
 description TEXT NOT NULL, instructions TEXT NOT NULL DEFAULT '', version INTEGER NOT NULL DEFAULT 1,
 UNIQUE(project,name));
CREATE TABLE IF NOT EXISTS build_entries(
 id INTEGER PRIMARY KEY, step INTEGER REFERENCES build_steps(id), subcategory INTEGER NOT NULL DEFAULT 0,kind TEXT NOT NULL,
 title TEXT NOT NULL, body TEXT NOT NULL, resolution TEXT NOT NULL, created TEXT NOT NULL,
 version INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS build_blobs(digest TEXT PRIMARY KEY, body BLOB NOT NULL);
CREATE TABLE IF NOT EXISTS build_files(id INTEGER PRIMARY KEY,entry INTEGER NOT NULL REFERENCES build_entries(id),
 filename TEXT NOT NULL,size INTEGER NOT NULL,digest TEXT NOT NULL REFERENCES build_blobs(digest),UNIQUE(entry,filename,digest));
CREATE INDEX IF NOT EXISTS build_entry_order ON build_entries(created,id);
CREATE INDEX IF NOT EXISTS build_entry_step ON build_entries(step,id);
CREATE TABLE IF NOT EXISTS build_requests(
 token TEXT PRIMARY KEY, action TEXT NOT NULL, item INTEGER NOT NULL) WITHOUT ROWID;
"""


def checked(p, key, limit, required=False, literal=False):
    value = p.get(key, "")
    if (
        not isinstance(value, str)
        or len(value) > limit
        or (required and not value.strip())
    ):
        raise ValueError("请检查必填内容及长度。")
    return value if literal else value.strip()


def enum(p, key, values):
    value = p.get(key)
    if value not in values:
        raise ValueError("所选类型或状态无效。")
    return value


def project_list(db):
    return rows(
        db,
        """SELECT p.id,p.name,p.site,p.notes,p.version,
        (SELECT count(*) FROM build_steps s WHERE s.project=p.id) AS steps,
        (SELECT count(*) FROM build_steps s WHERE s.project=p.id AND s.status='已完成') AS done,
        (SELECT count(*) FROM build_pages n WHERE n.project=p.id) AS pages
        FROM build_projects p ORDER BY p.id DESC""",
    )


def project(db, ident):
    p = db.execute("SELECT * FROM build_projects WHERE id=?", (int(ident),)).fetchone()
    if not p:
        raise ValueError("当前行业中未找到这个建站项目。")
    steps = rows(
        db, "SELECT * FROM build_steps WHERE project=? ORDER BY seq,id", (p["id"],)
    )
    entries = rows(
        db,
        """SELECT e.id,e.step,e.kind,e.title,e.created FROM build_entries e
        JOIN build_steps s ON s.id=e.step WHERE s.project=? ORDER BY e.id DESC""",
        (p["id"],),
    )
    by_step = {}
    for e in entries:
        by_step.setdefault(e["step"], []).append(e)
    for step in steps:
        step["entries"] = by_step.get(step["id"], [])
    return dict(
        p,
        steps=steps,
        importedPages=rows(db, "SELECT path,title,parent FROM map_import_pages WHERE project=? ORDER BY path", (p["id"],)),
        skills=rows(
            db, "SELECT * FROM build_skills WHERE project=? ORDER BY id", (p["id"],)
        ),
        pages=rows(
            db, "SELECT * FROM build_pages WHERE project=? ORDER BY seq,id", (p["id"],)
        ),
    )


def entry(db, ident):
    e = db.execute("SELECT * FROM build_entries WHERE id=?", (int(ident),)).fetchone()
    if not e:
        raise ValueError("当前行业中未找到这条记录。")
    return dict(
        e,
        files=rows(
            db,
            "SELECT id,filename,size FROM build_files WHERE entry=? ORDER BY id",
            (int(ident),),
        ),
    )


def save(db, action, p):
    db.execute("BEGIN IMMEDIATE")
    ident = int(p.get("id") or 0)
    version = int(p.get("version") or 0)
    token = p.get("request", "")
    if action == "project-name" and ident < 1:
        raise ValueError("请选择要改名的项目。")
    if not ident:
        if not re.fullmatch(r"[a-zA-Z0-9-]{16,64}", token):
            raise ValueError("表单已过期，请重新打开。")
        prior = db.execute(
            "SELECT action,item FROM build_requests WHERE token=?", (token,)
        ).fetchone()
        if prior:
            if prior["action"] != action:
                raise ValueError("请重新打开表单。")
            return {"id": prior["item"]}
    if action == "project":
        name = checked(p, "name", 140, True)
        site = checked(p, "site", 1000)
        if site:
            site = site if "://" in site else "https://" + site
            u = urlsplit(site)
            if (
                u.scheme not in ("http", "https")
                or not u.hostname
                or u.username
                or u.password
                or any(c.isspace() for c in site)
            ):
                raise ValueError("请填写有效的官网网址。")
        data = {"name": name, "site": site, "notes": checked(p, "notes", 10000)}
        table = "build_projects"
    elif action == "project-name":
        table = "build_projects"
        data = {"name": checked(p, "name", 140, True)}
    elif action == "skill":
        table = "build_skills"
        data = {
            "name": checked(p, "name", 160, True),
            "description": checked(p, "description", 12000, True, True),
            "instructions": checked(p, "instructions", 120000, False, True),
        }
    elif action == "step":
        table = "build_steps"
        data = {
            "title": checked(p, "title", 160, True),
            "notes": checked(p, "notes", 50000, literal=True),
            "status": enum(p, "status", STEP_STATUS),
        }
    elif action == "page":
        table = "build_pages"
        path = checked(p, "path", 1000, True)
        if (
            not path.startswith("/")
            or path.startswith("//")
            or any(c.isspace() or c in "\\?#" for c in path)
        ):
            raise ValueError("页面路径应以 / 开头，例如 /products/。")
        seq = int(p.get("seq", 10))
        if not 1 <= seq <= 100000:
            raise ValueError("顺序需要在 1 到 100000 之间。")
        data = {
            "seq": seq,
            "title": checked(p, "title", 140, True),
            "path": path,
            "keyword": checked(p, "keyword", 1000, literal=True),
            "notes": checked(p, "notes", 12000, literal=True),
            "status": enum(p, "status", PAGE_STATUS),
        }
    elif action == "entry":
        table = "build_entries"
        data = {
            "kind": checked(p, "kind", 70, True),
            "subcategory": int(p.get("subcategory") or 0),
            "title": checked(p, "title", 180, True),
            "body": checked(p, "body", 600000, False, True),
            "resolution": checked(p, "resolution", 50000, literal=True),
        }
    else:
        raise ValueError("未知操作。")
    if ident:
        assignments = ",".join(k + "=?" for k in data)
        changed = db.execute(
            f"UPDATE {table} SET {assignments},version=version+1 WHERE id=? AND version=?",
            [*data.values(), ident, version],
        )
        if not changed.rowcount:
            raise ValueError("记录已在其他窗口更新，请重新打开后再保存。")
        return {"id": ident}
    if action in ("project", "entry"):
        data["created"] = clock()
    if action in ("step", "page", "skill"):
        data["project"] = int(p["project"])
    if action == "step":
        data["seq"] = db.execute(
            "SELECT coalesce(max(seq),0)+1 FROM build_steps WHERE project=?",
            (data["project"],),
        ).fetchone()[0]
    if action == "entry":
        data["step"] = int(p.get("step") or 0) or None
    ident = db.execute(
        f"INSERT INTO {table}({','.join(data)}) VALUES({','.join('?' for _ in data)})",
        list(data.values()),
    ).lastrowid
    if action == "project":
        db.executemany(
            "INSERT INTO build_steps(project,seq,title,notes,status) VALUES(?,?,?,?,'待开始')",
            (
                (ident, i, title, note)
                for i, (title, note) in enumerate(
                    STORE_STEPS if p.get("store") else STEPS, 1
                )
            ),
        )
        if p.get("template", True):
            db.executemany(
                """INSERT INTO build_pages(project,seq,title,path,keyword,notes,status)
                           VALUES(?,?,?,?,'',?,'草案')""",
                (
                    (ident, i * 10, title, path, notes)
                    for i, (title, path, notes) in enumerate(
                        STORE_NAV if p.get("store") else NAV, 1
                    )
                ),
            )
    db.execute("INSERT INTO build_requests VALUES(?,?,?)", (token, action, ident))
    return {"id": ident}


def material_rows(db, industry, name, q):
    conditions = []
    params = []
    if q.get("sub") not in ("", None):
        conditions.append("e.subcategory=?")
        params.append(int(q["sub"]))
    text = q.get("find", "").strip().lower()
    if text:
        conditions.append("""(instr(lower(e.title),?) OR instr(lower(e.kind),?) OR instr(lower(e.body),?) OR
            instr(lower(e.resolution),?) OR instr(lower(coalesce(p.name,'')),?) OR EXISTS
            (SELECT 1 FROM build_files f WHERE f.entry=e.id AND instr(lower(f.filename),?)))""")
        params.extend([text] * 6)
    if q.get("before"):
        conditions.append("(e.created,?,e.id)<(?,?,?)")
        params.extend([industry, q["before"], int(q["lastindustry"]), int(q["lastid"])])
    where = " WHERE " + " AND ".join(conditions) if conditions else ""
    sql = """SELECT e.id,e.title,e.kind,e.subcategory,e.created,s.title AS step,p.name AS project,
           (SELECT count(*) FROM build_files f WHERE f.entry=e.id) AS files
           FROM build_entries e LEFT JOIN build_steps s ON s.id=e.step LEFT JOIN build_projects p ON p.id=s.project"""
    return [
        dict(r, industry=industry, industryName=name)
        for r in db.execute(
            sql + where + " ORDER BY e.created DESC,e.id DESC LIMIT 51", params
        )
    ]


def attach(db, owner, filename, content):
    name = PureWindowsPath(filename).name
    if not name.strip() or len(name) > 255 or not content:
        raise ValueError("请重新选择一个有文件名和内容的文件。")
    digest = hashlib.sha256(content).hexdigest()
    db.execute("BEGIN IMMEDIATE")
    if not db.execute("SELECT 1 FROM build_entries WHERE id=?", (owner,)).fetchone():
        raise ValueError("这条资料不存在。")
    db.execute("INSERT OR IGNORE INTO build_blobs VALUES(?,?)", (digest, content))
    db.execute(
        "INSERT OR IGNORE INTO build_files(entry,filename,size,digest) VALUES(?,?,?,?)",
        (owner, name, len(content), digest),
    )
    return {"ok": True}
