"""Import and classify competitor websites in one industry."""

import re
import itertools
import csv
import hashlib
import json
import zipfile
from contextlib import closing
from pathlib import Path
from library import (
    archive_original,
    clock,
    dbopen,
    domain,
    keyhead,
    norm,
    sheet_paths,
    table_data,
    web,
)

FIELDS = {
    "url": (
        "官网主页",
        "官方主页",
        "官方网站",
        "官网",
        "官网网址",
        "官网入口 · 点击查看",
        "官网入口",
        "官网链接",
        "网址",
        "网站",
        "网站链接",
        "域名",
        "同行域名",
        "同行网站",
        "官方域名",
        "官网域名",
        "网站地址",
        "主域名",
        "website",
        "domain",
        "url",
        "website url",
        "company website",
    ),
    "name": (
        "企业或官网名称",
        "企业名称",
        "企业",
        "名称",
        "网站名称",
        "同行名称",
        "公司",
        "公司名称",
        "企业或品牌",
        "企业/品牌",
        "网站/品牌名称",
        "company",
        "name",
        "company name",
        "brand",
    ),
    "audience": (
        "客户类型",
        "商业模式",
        "业务类型",
        "网站类型",
        "同行类型",
        "类型",
        "b2b/b2c",
        "business model",
        "audience",
        "type",
    ),
    "region": ("地区", "国家", "国家/地区", "国家或地区", "市场", "country", "region"),
    "products": (
        "产品类别",
        "产品",
        "主营产品",
        "已核实产品",
        "产品大类",
        "经营产品",
        "产品线",
        "products",
        "product",
    ),
    "notes": ("备注", "产品及企业采购证据", "说明", "notes", "note"),
}
LABELS = ("未标注", "B2B", "B2C", "B2B + B2C")
KEYWORD_STATUSES = ("ready", "missing")
SITE_DIRECTORY = " FROM sites s LEFT JOIN site_channels c ON c.site=s.id"
SITE_HAS_KEYWORDS = """(
    EXISTS (SELECT 1 FROM obs o JOIN words w ON w.id=o.word WHERE o.site=s.id AND w.state<>2)
    OR EXISTS (SELECT 1 FROM refs r JOIN words w ON w.id=r.word WHERE r.site=s.id AND w.state<>2)
)"""


def mapping(headers):
    cols = [re.sub(r"[（(].*?[)）]", "", keyhead(h)).strip() for h in headers]
    return {
        k: next((cols.index(keyhead(a)) for a in aliases if keyhead(a) in cols), -1)
        for k, aliases in FIELDS.items()
    }


def site_headers(headers):
    auto = mapping(headers)
    if auto["url"] >= 0:
        return headers, False
    urls = [i for i, h in enumerate(headers) if domain(h)]
    if len(urls) != 1:
        return headers, False
    return [
        "官网" if i == urls[0] else f"第 {i + 1} 列" for i in range(len(headers))
    ], True


def mask(value):
    text = norm(value)
    if text in ("0", "1", "2", "3"):
        return int(text)
    if text in ("两者兼有", "两者", "兼营", "both", "混合"):
        return 3
    b2b = any(
        t in text
        for t in ("b2b", "批发", "企业客户", "wholesale", "business-to-business")
    )
    b2c = any(
        t in text for t in ("b2c", "零售", "消费者", "retail", "business-to-consumer")
    )
    return int(b2b) | (int(b2c) << 1)


def audience_from_name(filename, sheet):
    for label in (sheet, Path(filename).stem):
        text = norm(label)
        if re.search(r"排除|剔除|待核|待查|线索|说明|证据|非\s*b2[bc]", text):
            return 0
        channels = set(re.findall(r"(?<![a-z0-9])b2[bc](?![a-z0-9])", text))
        if len(channels) == 1:
            return 1 if "b2b" in channels else 2
        if channels:
            return 0
    return 0


def add_site(db, p, *, inferred=0):
    url = web(p.get("url", ""))
    url_host = domain(url)
    main = domain(p.get("main_domain", ""))
    host = (
        main
        if main and (url_host == main or url_host.endswith("." + main))
        else url_host
    )
    if not host:
        raise ValueError("请输入有效的官网域名或网址。")
    found = db.execute("SELECT site FROM aliases WHERE domain=?", (host,)).fetchone()
    fields = [
        str(p.get(k, "") or "").strip() for k in ("name", "region", "products", "notes")
    ]
    name, region, products, notes = fields
    role = str(p.get("role", "") or "").strip()
    if found:
        sid = found[0]
        if any(fields) or role:
            db.execute(
                """UPDATE sites SET name=CASE WHEN name=domain AND ?<>'' THEN ? ELSE name END,
                region=CASE WHEN region='' THEN ? ELSE region END,products=CASE WHEN products='' THEN ? ELSE products END,
                notes=CASE WHEN notes='' THEN ? ELSE notes END,
                role=CASE WHEN role='' THEN ? ELSE role END WHERE id=?""",
                (name, name, region, products, notes, role, sid),
            )
    else:
        sid = db.execute(
            "INSERT INTO sites(name,domain,url,region,products,notes,role) VALUES(?,?,?,?,?,?,?)",
            (name or host, host, url, region, products, notes, role),
        ).lastrowid
        db.execute("INSERT INTO aliases VALUES(?,?)", (host, sid))
    if url_host != host:
        db.execute("INSERT OR IGNORE INTO aliases VALUES(?,?)", (url_host, sid))
    code = mask(p.get("audience", ""))
    inferred_now = False
    if code:
        db.execute(
            """INSERT INTO site_channels(site,mask) VALUES(?,?) ON CONFLICT(site) DO UPDATE SET
               mask=CASE WHEN inferred=1 THEN excluded.mask ELSE (mask | excluded.mask) END,inferred=0""",
            (sid, code),
        )
    elif inferred:
        inferred_now = bool(db.execute(
            "INSERT OR IGNORE INTO site_channels(site,mask,inferred) VALUES(?,?,1)", (sid, inferred),
        ).rowcount)
    return {"id": sid, "duplicate": bool(found), "inferred": inferred_now}


def site_scope(db, p):
    text = norm(p.get("q", ""))
    where = []
    args = []
    if text:
        where.append("(instr(lower(s.name),?) OR instr(s.domain,?) OR instr(lower(s.products),?))")
        args.extend([text] * 3)
    if p.get("audience", "") != "":
        code = int(p["audience"])
        if code not in range(4):
            raise ValueError("同行类型无效。")
        where.append("(coalesce(c.mask,0) & ?) = ?" if code else "coalesce(c.mask,0)=0")
        if code:
            args.extend([code, code])
    keyword_batch = None
    if p.get("batch"):
        batch = int(p["batch"])
        if db.execute(
            "SELECT 1 FROM batches b WHERE b.id=? AND b.written>0 "
            "AND NOT EXISTS (SELECT 1 FROM site_batches WHERE batch=b.id)", (batch,),
        ).fetchone():
            keyword_batch = batch
            where.append("s.id IN (SELECT site FROM obs WHERE batch=? AND site IS NOT NULL)")
        else:
            where.append("s.id IN (SELECT site FROM site_members WHERE batch=?)")
        args.append(batch)
    return where, args, keyword_batch


def site_keyword_condition(batch):
    if batch is None:
        return SITE_HAS_KEYWORDS, []
    return ("EXISTS (SELECT 1 FROM obs o JOIN words w ON w.id=o.word "
            "WHERE o.batch=? AND o.site=s.id AND w.state<>2)"), [batch]


def site_coverage(db, p):
    where, args, keyword_batch = site_scope(db, p)
    has_words, inputs = site_keyword_condition(keyword_batch)
    scope = " WHERE " + " AND ".join(where) if where else ""
    total, ready = db.execute(
        "SELECT count(*), coalesce(sum(" + has_words + "),0)" + SITE_DIRECTORY + scope,
        inputs + args,
    ).fetchone()
    return {"total": total, "ready": ready, "missing": total - ready}, keyword_batch


def query_sites(db, p, all_rows=False):
    where, args, keyword_batch = site_scope(db, p)
    keyword_status = p.get("keyword_status", "")
    if keyword_status and keyword_status not in KEYWORD_STATUSES:
        raise ValueError("同行关键词状态无效。")
    has_words, inputs = site_keyword_condition(keyword_batch)
    if keyword_status:
        where.append(has_words if keyword_status == "ready" else "NOT " + has_words)
        args.extend(inputs)
    columns = "s.*, coalesce(c.mask,0) AS audience"
    select_args = []
    if not all_rows:
        keyword_flag = {"ready": "1", "missing": "0"}.get(keyword_status, has_words)
        if not keyword_status:
            select_args = inputs
        columns += ", " + keyword_flag + " AS has_keywords"
        where.append("s.id>?")
        args.append(int(p.get("after") or 0))
    scope = " WHERE " + " AND ".join(where) if where else ""
    sql = "SELECT " + columns + SITE_DIRECTORY + scope + " ORDER BY s.id"
    return db.execute(sql + ("" if all_rows else " LIMIT 51"), select_args + args)


def export_sites(db, out, params):
    w = csv.writer(out)
    w.writerow(["企业名称", "官网", "同行类型", "地区", "产品", "备注"])
    for r in query_sites(db, params, True):
        values = (
            r["name"],
            r["url"],
            LABELS[r["audience"]],
            r["region"],
            r["products"],
            r["notes"],
        )
        w.writerow(
            [
                "'" + v if v.lstrip().startswith(("=", "+", "-", "@")) else v
                for v in values
            ]
        )


def import_sites(data, path, filename, opts, digest, progress=lambda n: None):
    hdr, it = table_data(path, opts.get("sheet", ""), opts.get("skip", 0))
    columns, first_is_data = site_headers(hdr)
    selected = opts.get("mapping") or mapping(columns)
    idx = {k: int(selected.get(k, -1)) for k in FIELDS}
    if idx["url"] < 0 or any(i >= len(hdr) or i < -1 for i in idx.values()):
        it.close()
        raise ValueError("请选择官网或域名列。")
    extra_cols = {
        key: hdr.index(key)
        for key in (
            "主域名",
            "同厂或别名域名",
            "其他已核域名",
            "已合并的其他域名",
            "供货身份",
            "B2B销售入口检查",
            "购物车及零售检查",
            "产品依据网址",
            "制造业务依据网址",
            "核查日期",
        )
        if key in hdr
    }

    def read_extra(row, key):
        index = extra_cols.get(key, -1)
        return str(row[index]).strip() if 0 <= index < len(row) else ""

    def positive(value, signals):
        return bool(
            value
            and not re.search(
                r"未见|未发现|未确认|未查|未核|不确定|无|没有|否|未知|未提供|不适用|no\b|not\b",
                value,
                re.I,
            )
            and (value == "是" or any(t in value for t in signals))
        )

    base_mask = mask(opts.get("audience", ""))
    sheet = opts.get("sheet", "")
    audience_hint = audience_from_name(filename, sheet) if opts.get("audience") in (None, "") else 0
    archived_main = "同行网站 · " + sheet if opts.get("directory_main") else ""
    if sheet and zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as wb:
            first = sheet_paths(wb)[0][0]
        if sheet == first:
            sheet = ""
    sig = hashlib.sha256(
        json.dumps(
            ["site-list", digest, sheet, idx, base_mask] +
            ([["review_header", opts["skip"]]] if opts.get("review") and opts.get("skip") else []),
            sort_keys=True
        ).encode()
    ).hexdigest()
    archive_original(data, path, digest)
    with closing(it), closing(dbopen(data)) as db, db:
        db.execute("BEGIN IMMEDIATE")
        prior = db.execute(
            "SELECT b.*,sb.valid AS site_valid FROM batches b JOIN site_batches sb ON sb.batch=b.id WHERE signature=?",
            (sig,),
        ).fetchone()
        if not prior and archived_main:
            prior = db.execute(
                """SELECT b.*,sb.valid AS site_valid FROM batches b JOIN site_batches sb ON sb.batch=b.id
                    JOIN archived a ON a.batch=b.id
                    WHERE a.digest=? AND a.headers=? AND b.source=? AND sb.valid>0
                    ORDER BY b.id LIMIT 1""",
                (digest, json.dumps(hdr, ensure_ascii=False), archived_main),
            ).fetchone()
        if prior:
            return dict(prior, duplicate=True)
        batch = db.execute(
            "INSERT INTO batches(signature,filename,created) VALUES(?,?,?)",
            (sig, filename, clock()),
        ).lastrowid
        db.execute(
            "INSERT INTO archived VALUES(?,?,?)",
            (batch, digest, json.dumps(hdr, ensure_ascii=False)),
        )
        seen = valid = added = inferred_sites = 0
        for row in itertools.chain([hdr], it) if first_is_data else it:
            seen += 1
            if seen % 1000 == 0:
                progress(seen)
            item = {
                k: str(row[i] or "").strip() if 0 <= i < len(row) else ""
                for k, i in idx.items()
            }
            if not domain(item["url"]):
                item["url"] = read_extra(row, "主域名")
            if not domain(item["url"]):
                continue
            inferred = audience_hint if not item["audience"] else 0
            if not item["audience"]:
                b2b = positive(
                    read_extra(row, "B2B销售入口检查"),
                    ("询价", "批发", "企业联系", "定制", "B2B"),
                )
                retail = positive(
                    read_extra(row, "购物车及零售检查"),
                    ("购物车", "零售", "结账", "B2C"),
                )
                item["audience"] = str(base_mask | int(b2b) | (int(retail) << 1))
            item["main_domain"] = read_extra(row, "主域名")
            item["role"] = read_extra(row, "供货身份")
            site = add_site(db, item, inferred=inferred)
            inferred_sites += int(site["inferred"])
            links = [
                {
                    "title": key,
                    "url": web(read_extra(row, key)),
                    "date": read_extra(row, "核查日期"),
                }
                for key in ("产品依据网址", "制造业务依据网址")
                if domain(read_extra(row, key))
            ]
            if links:
                prior = json.loads(
                    db.execute(
                        "SELECT evidence FROM sites WHERE id=?", (site["id"],)
                    ).fetchone()[0]
                )
                fresh = [link for link in links if link not in prior]
                if fresh:
                    db.execute(
                        "UPDATE sites SET evidence=? WHERE id=?",
                        (json.dumps(prior + fresh, ensure_ascii=False), site["id"]),
                    )
            aliases = " ".join(read_extra(row, key) for key in ("同厂或别名域名", "其他已核域名", "已合并的其他域名"))
            for alias in re.split(r"[;,；，\s]+", aliases):
                host = domain(alias)
                if host and re.fullmatch(r"[a-z0-9.-]+", host):
                    db.execute(
                        "INSERT OR IGNORE INTO aliases VALUES(?,?)", (host, site["id"])
                    )
            db.execute(
                "INSERT OR IGNORE INTO site_members VALUES(?,?)", (batch, site["id"])
            )
            valid += 1
            added += int(not site["duplicate"])
        db.execute("INSERT INTO site_batches VALUES(?,?)", (batch, valid))
        db.execute(
            "UPDATE batches SET seen=?,added=?,blank=? WHERE id=?",
            (seen, added, seen - valid, batch),
        )
        return {
            "id": batch,
            "seen": seen,
            "site_valid": valid,
            "added": added,
            "inferred_sites": inferred_sites,
            "blank": seen - valid,
            "duplicate": False,
        }
