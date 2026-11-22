"""The system's top-level areas and user-editable filing categories."""

import json
import re
from library import dbopen, init, norm, rows
from contextlib import closing

DEFAULTS = [
    (1, "行业关键词库", "keywords"),
    (2, "软件与建站资料", "build"),
    (3, "价值投资资料", "notes"),
    (4, "B2C 建站资料", "store"),
]
CHILDREN = {
    2: [
        ("软件使用", "软件设置|安装|配置"),
        ("建站流程", "建站步骤|建站流程"),
        ("提示词与对话", "提示词|prompt|对话"),
        ("问题与解决办法", "报错|排查|故障|修复"),
        ("文档与代码", "源码|代码|开发文档"),
    ],
    3: [
        ("公司研究", "公司研究|商业模式|竞争优势"),
        ("财报分析", "财报|年报|资产负债表|现金流量表"),
        ("估值记录", "估值|市盈率|现金流折现"),
        ("投资笔记", "投资笔记|投资复盘"),
    ],
    4: [
        ("选品与定位", "选品|用户画像"),
        ("店铺与商品页", "商品详情|商品页|店铺装修"),
        ("支付与结账", "支付|结账|checkout"),
        ("物流与退换", "物流|退货|退款|退换货"),
        ("营销与转化", "广告投放|转化率|促销"),
    ],
}


def location(root, sid):
    return root / "sections" / str(int(sid))


def initialize(root):
    with closing(dbopen(root)) as db, db:
        db.execute("BEGIN IMMEDIATE")
        db.execute(
            "CREATE TABLE IF NOT EXISTS top_sections(id INTEGER PRIMARY KEY,name TEXT NOT NULL UNIQUE,kind TEXT NOT NULL)"
        )
        db.execute("""CREATE TABLE IF NOT EXISTS sub_sections(id INTEGER PRIMARY KEY,section INTEGER NOT NULL REFERENCES top_sections(id),
                     name TEXT NOT NULL,cues TEXT NOT NULL,UNIQUE(section,name))""")
        for ident, name, kind in DEFAULTS:
            if db.execute("SELECT 1 FROM top_sections WHERE id=?", (ident,)).fetchone():
                continue
            if ident >= 3:
                init(location(root, ident), seed=False)
            db.execute("INSERT INTO top_sections VALUES(?,?,?)", (ident, name, kind))
            db.executemany(
                "INSERT INTO sub_sections(section,name,cues) VALUES(?,?,?)",
                ((ident, n, cues) for n, cues in CHILDREN.get(ident, [])),
            )
        ids = [r[0] for r in db.execute("SELECT id FROM top_sections WHERE id>=3")]
    for ident in ids:
        folder = location(root, ident)
        if not (folder / "library.sqlite3").is_file():
            raise ValueError("类目资料库缺失，请从整库备份恢复。")
        init(folder, seed=False)


def listing(db):
    result = rows(db, "SELECT * FROM top_sections WHERE kind<>'skillbank' ORDER BY id")
    groups = {}
    for r in rows(db, "SELECT * FROM sub_sections ORDER BY id"):
        groups.setdefault(r["section"], []).append(r)
    for r in result:
        r["children"] = groups.get(r["id"], [])
    return result


def save(root, p, child=False):
    name = str(p.get("name", "")).strip()
    if not 1 <= len(name) <= 72:
        raise ValueError("请填写类目名称，最多 72 个字。")
    with closing(dbopen(root)) as db, db:
        db.execute("BEGIN IMMEDIATE")
        if child:
            parent = int(p["section"])
            if parent == 1:
                raise ValueError("请从行业关键词库添加行业。")
            cues = "|".join(
                dict.fromkeys(
                    x.strip()
                    for x in re.split(r"[\r\n|，,]+", p.get("cues", ""))
                    if x.strip()
                )
            )
            if len(cues) > 1500:
                raise ValueError("识别词过长。")
            db.execute(
                "INSERT OR IGNORE INTO sub_sections(section,name,cues) VALUES(?,?,?)",
                (parent, name, cues),
            )
            return {
                "id": db.execute(
                    "SELECT id FROM sub_sections WHERE section=? AND name=?",
                    (parent, name),
                ).fetchone()[0]
            }
        existing = db.execute(
            "SELECT id FROM top_sections WHERE name=?", (name,)
        ).fetchone()
        if existing:
            return {"id": existing[0]}
        kind = p.get("kind", "notes")
        if kind not in ("notes", "build"):
            raise ValueError("类目类型无效。")
        ident = db.execute(
            "INSERT INTO top_sections(name,kind) VALUES(?,?)", (name, kind)
        ).lastrowid
        init(location(root, ident), seed=False)
        return {"id": ident}


def classify(root, section, p):
    value = p.get("subcategory", "auto")
    with closing(dbopen(root)) as db:
        children = rows(db, "SELECT * FROM sub_sections WHERE section=?", (section,))
    if value != "auto":
        ident = int(value or 0)
        if ident and not any(r["id"] == ident for r in children):
            raise ValueError("二级类目不属于当前一级类目。")
        return ident
    # When the text points to multiple topics, leave it at this parent for review.
    text = norm(
        " ".join(str(p.get(k, "")) for k in ("title", "kind", "body", "filenames"))
    )
    matches = [
        r["id"]
        for r in children
        if any(norm(v) in text for v in [r["name"], *r["cues"].split("|")] if v.strip())
    ]
    return matches[0] if len(matches) == 1 else 0
