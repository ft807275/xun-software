"""Reusable filters and bulk export selections, shared across the workspace."""

import json
from contextlib import closing

from library import dbopen, norm, rows
from product_types import valid_review_key
from sitebook import KEYWORD_STATUSES

SCHEMA = """CREATE TABLE IF NOT EXISTS saved_presets(
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL,
    industry INTEGER NOT NULL,
    name TEXT NOT NULL,
    name_key TEXT NOT NULL,
    payload TEXT NOT NULL,
    UNIQUE(kind, industry, name_key)
)"""

FILTERS = {
    "words": {"q", "state", "ptype", "category", "traffic", "featured", "site", "market", "batch", "batch_scope", "mode", "type_review"},
    "sites": {"q", "audience", "batch", "keyword_status"},
    "gallery": {"q", "kind", "category", "role", "linkstate"},
}


def positive_id(value):
    if type(value) not in (str, int) or not str(value).isascii() or not str(value).isdecimal():
        raise ValueError("编号无效。")
    ident = int(value)
    if not 0 < ident < 2**63:
        raise ValueError("编号无效。")
    return ident


def list_saved(root, scope, industry):
    sql = "SELECT id, kind, industry, name, payload FROM saved_presets"
    args = ()
    if scope == "export":
        sql += " WHERE kind=?"
        args = (scope,)
    elif scope in FILTERS:
        sql += " WHERE kind=? AND industry=?"
        args = (scope, positive_id(industry))
    elif scope != "all":
        raise ValueError("方案类型无效。")
    with closing(dbopen(root)) as db:
        data = rows(db, sql + " ORDER BY id DESC", args)
    for row in data:
        row.update(json.loads(row.pop("payload")))
    return data


def save(root, kind, industry, payload, title):
    from bulk_export import KINDS

    if not isinstance(title, str) or not 1 <= len(title.strip()) <= 80:
        raise ValueError("请填写 1 至 80 个字符的方案名称。")
    name = title.strip()
    if not isinstance(payload, dict):
        raise ValueError("方案内容无效。")
    with closing(dbopen(root)) as db, db:
        industries = {r[0] for r in db.execute("SELECT id FROM industry_catalog")}
        if kind == "export":
            industry = 0
            ids, kinds = payload.get("ids"), payload.get("kinds")
            if not isinstance(ids, list) or not isinstance(kinds, list):
                raise ValueError("至少勾选一个行业和一种资料。")
            ids = sorted({positive_id(i) for i in ids})
            if not ids or set(ids) - industries or not kinds or any(
                not isinstance(k, str) or k not in KINDS for k in kinds
            ):
                raise ValueError("请选择有效的行业和资料类型。")
            data = {"ids": ids, "kinds": [k for k in KINDS if k in kinds]}
        elif kind in FILTERS:
            industry = positive_id(industry)
            if industry not in industries:
                raise ValueError("行业不存在。")
            filters = payload.get("filters")
            if not isinstance(filters, dict):
                raise ValueError("筛选条件无效。")
            data = {"filters": clean_filters(kind, filters)}
        else:
            raise ValueError("方案类型无效。")
        inserted = db.execute(
            "INSERT INTO saved_presets(kind,industry,name,name_key,payload) VALUES (?,?,?,?,?) "
            "ON CONFLICT(kind,industry,name_key) DO NOTHING",
            (kind, industry, name, norm(name), json.dumps(data, ensure_ascii=False)),
        )
        if not inserted.rowcount:
            raise ValueError("已有同名方案，请换个名字。")
        return {"id": inserted.lastrowid, "name": name}


def clean_filters(kind, source):
    result = {}
    for key in FILTERS[kind] & source.keys():
        value = source[key]
        if value is None or value == "":
            continue
        if type(value) not in (str, int) or len(str(value)) > 1000:
            raise ValueError("筛选条件无效或过长。")
        if key in ("site", "batch") or (key == "ptype" and str(value) not in ("0", "-1")):
            value = positive_id(value)
        if key == "type_review" and not valid_review_key(str(value)):
            raise ValueError("待确认分组无效。")
        if key == "batch_scope" and value not in ("new", "existing"):
            raise ValueError("批次范围无效。")
        if key == "keyword_status" and value not in KEYWORD_STATUSES:
            raise ValueError("同行关键词状态无效。")
        result[key] = str(value)
    return result


def remove(root, ident):
    with closing(dbopen(root)) as db, db:
        db.execute("DELETE FROM saved_presets WHERE id=?", (positive_id(ident),))
    return {"ok": True}
