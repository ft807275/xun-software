"""Private keyword library. SQLite is authoritative for terms, sites, evidence and imports."""

import codecs, shutil, zlib, contextlib, csv, hashlib, json, os, re, sqlite3, time, unicodedata, uuid, zipfile
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit
import xml.etree.ElementTree as ET

import product_types
from current_metrics import report_day, workbook_day, setup as setup_metrics

ROOT = Path(__file__).resolve().parent
FIELDS = {
    "word": (
        "关键词",
        "关键字",
        "keyword",
        "keywords",
        "query",
        "search query",
        "搜索词",
        "搜索关键词",
        "关键词（原文）",
        "英文关键词",
        "关键词/keyword",
        "search term",
    ),
    "url": (
        "同行排名网址",
        "排名网址",
        "排名url",
        "目标网址",
        "当前网址",
        "url",
        "current url",
        "top url",
        "landing page",
        "ranking url",
        "page url",
        "landing page url",
        "目标url",
        "网址",
    ),
    "site": (
        "域名",
        "同行域名",
        "主域名",
        "同行官网",
        "官网域名",
        "domain",
        "hostname",
        "competitor domain",
        "website",
    ),
    "traffic": (
        "流量（原表）",
        "同行自然流量（代表记录）",
        "同行自然流量(代表记录)",
        "自然流量",
        "预估流量",
        "traffic",
        "organic traffic",
        "current organic traffic",
        "current traffic",
        "estimated traffic",
        "当前自然流量",
        "自然搜索流量",
        "流量",
    ),
    "volume": (
        "搜索量（原表）",
        "同行搜索量",
        "搜索量",
        "搜索次数",
        "search volume",
        "volume",
        "monthly search volume",
        "avg monthly searches",
    ),
    "dr": (
        "DR（原表）",
        "DR",
        "Domain Rating",
        "Current Domain Rating",
        "Ahrefs DR",
        "Ahrefs Domain Rating",
        "域名评级",
        "域名评分（DR）",
        "域名评分",
        "同行DR",
        "网站DR",
        "网站域名评级",
        "网站权重（DR）",
    ),
    "position": (
        "排名（原表）",
        "同行排名",
        "自然排名",
        "当前排名",
        "排名",
        "position",
        "current position",
        "rank",
        "organic position",
    ),
    "market": (
        "同行地区或数据库",
        "市场",
        "国家",
        "地区",
        "数据库",
        "country",
        "market",
        "database",
        "country code",
        "location",
    ),
    "date": (
        "报告日期",
        "日期",
        "date",
        "report date",
        "snapshot date",
        "last updated",
        "timestamp",
    ),
}

SEMRUSH_POSITIONS_NAME = re.compile(
    r"-organic\.positions-([a-z]{2})-(\d{8})"
    r"(?:-\d{4}-\d{2}-\d{2}t\d{2}_\d{2}_\d{2}z)?(?: \(\d+\))?$",
    re.I,
)
SEMRUSH_KEYWORD_NAME = re.compile(
    r"_(?:broad|phrase|exact)-match_([a-z]{2})_(\d{4}-\d{2}-\d{2})(?: \(\d+\))?$",
    re.I,
)


def norm(s):
    return " ".join(unicodedata.normalize("NFKC", str(s or "")).casefold().split())


@lru_cache(maxsize=65536)
def domain(s):
    try:
        u = urlsplit(s if "://" in s else "//" + s)
        h = (u.hostname or "").lower().rstrip(".")
        if (
            u.scheme
            and u.scheme not in ("http", "https")
            or u.username
            or u.password
            or "." not in h
            or any(c.isspace() for c in h)
        ):
            return ""
        return h[4:] if h.startswith("www.") else h
    except (ValueError, UnicodeError):
        return ""


def web(s):
    s = s.strip()
    return (s if "://" in s else "https://" + s) if domain(s) else ""


def keyhead(s):
    return norm(s).lstrip("\ufeff").strip().replace("_", " ")


def choose(headers):
    h = [keyhead(s) for s in headers]
    return {
        k: next((h.index(keyhead(a)) for a in aliases if keyhead(a) in h), -1)
        for k, aliases in FIELDS.items()
    }


def keyword_report_defaults(filename):
    name = Path(filename).stem
    match = SEMRUSH_POSITIONS_NAME.search(name) or SEMRUSH_KEYWORD_NAME.search(name)
    if match:
        market, date = match.groups()
        return market.upper(), report_day(date, "")
    return "", ""


def num(v):
    s = str(v or "").strip()
    if not re.fullmatch(r"(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d+)?", s):
        return None
    return float(s.replace(",", ""))


def clock():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def dbopen(data):
    db = sqlite3.connect(str(Path(data) / "library.sqlite3"), timeout=55)
    db.row_factory = sqlite3.Row
    db.execute("pragma foreign_keys=on")
    db.execute("pragma synchronous=NORMAL")
    db.execute("pragma temp_store=FILE")
    db.execute("pragma cache_size=-64000")
    return db


def rows(db, sql, args=()):
    return [dict(r) for r in db.execute(sql, args)]


def csv_cell(value):
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


class TableFormatError(ValueError):
    """The file needs a fresh export or a supported spreadsheet format."""


def ensure_literal_identity(db):
    """V1 used a folded unique key. Keep IDs and relationships while changing the unique index."""

    def legacy():
        return any(
            r[0] == "norm"
            for r in db.execute(
                "SELECT ii.name FROM pragma_index_list('words') il, pragma_index_info(il.name) ii WHERE il.[unique]=1"
            )
        )

    if not legacy():
        return
    db.execute("PRAGMA foreign_keys=OFF")
    try:
        with db:
            db.execute("BEGIN IMMEDIATE")
            if not legacy():
                return
            db.execute(
                "CREATE TABLE words_literal(id INTEGER PRIMARY KEY,norm TEXT NOT NULL,term TEXT NOT NULL COLLATE BINARY UNIQUE,category TEXT NOT NULL DEFAULT '',state INTEGER NOT NULL DEFAULT 0,manual INTEGER NOT NULL DEFAULT 0,reason TEXT NOT NULL DEFAULT '',notes TEXT NOT NULL DEFAULT '')"
            )
            db.execute(
                "INSERT INTO words_literal SELECT id,norm,term,category,state,manual,reason,notes FROM words"
            )
            db.execute("DROP TABLE words")
            db.execute("ALTER TABLE words_literal RENAME TO words")
            db.execute("CREATE INDEX words_state_id ON words(state,id)")
            db.execute(
                "CREATE TRIGGER words_search_insert AFTER INSERT ON words BEGIN INSERT INTO search_terms(rowid,norm) VALUES(new.id,new.norm); END"
            )
            if db.execute("PRAGMA foreign_key_check").fetchone():
                raise ValueError("关键词关联校验失败，旧库已保留。")
    finally:
        db.execute("PRAGMA foreign_keys=ON")


def init(data, seed=True, industry_name=None):
    data = Path(data)
    data.mkdir(parents=True, exist_ok=True)
    (data / "incoming").mkdir(exist_ok=True)
    with contextlib.closing(dbopen(data)) as db:
        db.execute("pragma journal_mode=WAL")
        db.executescript("""
  CREATE TABLE IF NOT EXISTS settings(k TEXT PRIMARY KEY,v TEXT NOT NULL);
  CREATE TABLE IF NOT EXISTS sites(id INTEGER PRIMARY KEY, domain TEXT UNIQUE NOT NULL, name TEXT NOT NULL, url TEXT NOT NULL DEFAULT '', region TEXT NOT NULL DEFAULT '',role TEXT NOT NULL DEFAULT '',products TEXT NOT NULL DEFAULT '',notes TEXT NOT NULL DEFAULT '',status TEXT NOT NULL DEFAULT '已收录',evidence TEXT NOT NULL DEFAULT '[]',queries TEXT NOT NULL DEFAULT '[]');
  CREATE TABLE IF NOT EXISTS aliases(domain TEXT PRIMARY KEY,site INTEGER NOT NULL REFERENCES sites(id)) WITHOUT ROWID;
  CREATE TABLE IF NOT EXISTS words(id INTEGER PRIMARY KEY,norm TEXT NOT NULL,term TEXT NOT NULL COLLATE BINARY UNIQUE,category TEXT NOT NULL DEFAULT '',state INTEGER NOT NULL DEFAULT 0,manual INTEGER NOT NULL DEFAULT 0,reason TEXT NOT NULL DEFAULT '',notes TEXT NOT NULL DEFAULT '');
  CREATE TABLE IF NOT EXISTS profiles(word INTEGER PRIMARY KEY REFERENCES words(id),translation TEXT,subtype TEXT,featured TEXT,english TEXT);
  CREATE INDEX IF NOT EXISTS prof_featured ON profiles(featured,word);
  CREATE TABLE IF NOT EXISTS archived(batch INTEGER PRIMARY KEY REFERENCES batches(id),digest TEXT NOT NULL,headers TEXT NOT NULL);
  CREATE TABLE IF NOT EXISTS import_runs(id TEXT PRIMARY KEY,filename TEXT NOT NULL,digest TEXT NOT NULL,
    created TEXT NOT NULL,updated TEXT NOT NULL,state TEXT NOT NULL,job TEXT NOT NULL,
    sheets TEXT NOT NULL DEFAULT '[]',error TEXT NOT NULL DEFAULT '',pending INTEGER NOT NULL DEFAULT 0,
    replacement TEXT NOT NULL DEFAULT '',resume_job TEXT NOT NULL DEFAULT '',resume_options TEXT NOT NULL DEFAULT '');
  CREATE UNIQUE INDEX IF NOT EXISTS import_runs_digest ON import_runs(digest);
  CREATE UNIQUE INDEX IF NOT EXISTS import_runs_job ON import_runs(job);
  CREATE TABLE IF NOT EXISTS extras(batch INTEGER NOT NULL,rownum INTEGER NOT NULL,body BLOB NOT NULL,PRIMARY KEY(batch,rownum)) WITHOUT ROWID;
  CREATE INDEX IF NOT EXISTS words_state_id ON words(state,id);
  CREATE VIRTUAL TABLE IF NOT EXISTS search_terms USING fts5(norm,content='words',content_rowid='id',tokenize='unicode61 remove_diacritics 0');
  CREATE TRIGGER IF NOT EXISTS words_search_insert AFTER INSERT ON words BEGIN INSERT INTO search_terms(rowid,norm) VALUES(new.id,new.norm); END;
  CREATE TABLE IF NOT EXISTS rules(id INTEGER PRIMARY KEY,phrase TEXT UNIQUE NOT NULL);
  CREATE TABLE IF NOT EXISTS batches(id INTEGER PRIMARY KEY,signature TEXT NOT NULL UNIQUE,filename TEXT NOT NULL,source TEXT,market TEXT,report_date TEXT,created TEXT NOT NULL,seen INTEGER NOT NULL DEFAULT 0,written INTEGER NOT NULL DEFAULT 0,added INTEGER NOT NULL DEFAULT 0,blank INTEGER NOT NULL DEFAULT 0,distinct_words INTEGER,prior_word_id INTEGER);
  CREATE TABLE IF NOT EXISTS pages(id INTEGER PRIMARY KEY,site INTEGER NOT NULL REFERENCES sites(id),url TEXT NOT NULL,UNIQUE(site,url));
  CREATE TABLE IF NOT EXISTS obs(id INTEGER PRIMARY KEY,word INTEGER NOT NULL REFERENCES words(id),site INTEGER REFERENCES sites(id),page INTEGER REFERENCES pages(id),batch INTEGER NOT NULL REFERENCES batches(id),rownum INTEGER NOT NULL,traffic TEXT,volume TEXT,position TEXT,market TEXT,report_date TEXT, traffic_num REAL);
  CREATE INDEX IF NOT EXISTS obs_word_site ON obs(word,site);
  CREATE INDEX IF NOT EXISTS obs_site_word ON obs(site,word);
  CREATE INDEX IF NOT EXISTS obs_batch_row ON obs(batch,rownum);
  CREATE INDEX IF NOT EXISTS obs_batch_word ON obs(batch,word);
  CREATE INDEX IF NOT EXISTS obs_batch_site ON obs(batch,site);
  CREATE TABLE IF NOT EXISTS refs(word INTEGER NOT NULL REFERENCES words(id),site INTEGER REFERENCES sites(id),url TEXT NOT NULL,UNIQUE(word,url,site));
  CREATE INDEX IF NOT EXISTS refs_site_word ON refs(site,word);
  CREATE TABLE IF NOT EXISTS site_channels(site INTEGER PRIMARY KEY REFERENCES sites(id), mask INTEGER NOT NULL CHECK(mask BETWEEN 0 AND 3), inferred INTEGER NOT NULL DEFAULT 0);
  CREATE TABLE IF NOT EXISTS site_batches(batch INTEGER PRIMARY KEY REFERENCES batches(id), valid INTEGER NOT NULL);
  CREATE TABLE IF NOT EXISTS site_members(batch INTEGER NOT NULL REFERENCES batches(id),site INTEGER NOT NULL REFERENCES sites(id),PRIMARY KEY(batch,site)) WITHOUT ROWID;
  CREATE TABLE IF NOT EXISTS history(code TEXT PRIMARY KEY,text TEXT,source TEXT,page INTEGER);
  """)
        with db:
            db.execute("BEGIN IMMEDIATE")
            if not any(row[1] == "english" for row in db.execute("PRAGMA table_info(profiles)")):
                db.execute("ALTER TABLE profiles ADD COLUMN english TEXT")
            columns = {item[1] for item in db.execute("PRAGMA table_info(batches)")}
            for column in ("distinct_words", "prior_word_id"):
                if column not in columns:
                    db.execute("ALTER TABLE batches ADD COLUMN " + column + " INTEGER")
            run_columns = {row[1] for row in db.execute("PRAGMA table_info(import_runs)")}
            for column in ("replacement", "resume_job", "resume_options"):
                if column not in run_columns:
                    db.execute("ALTER TABLE import_runs ADD COLUMN " + column + " TEXT NOT NULL DEFAULT ''")
            # The original job ID is used by automatic uploads. Retries may
            # have used manually chosen columns and cannot recover those choices.
            if "resume_job" not in run_columns:
                db.execute(
                    """UPDATE import_runs SET resume_job=job,resume_options=?
                       WHERE id=job AND state IN ('queued','running')""",
                    (json.dumps({"kind": "auto"}),),
                )
            db.execute("CREATE INDEX IF NOT EXISTS import_run_replacement ON import_runs(replacement) WHERE replacement<>''")
            db.execute("""CREATE INDEX IF NOT EXISTS import_runs_next
                       ON import_runs(state,updated,id) WHERE resume_job=job AND resume_job<>''
                       AND state IN ('queued','running')""")
            if not any(row[1] == "inferred" for row in db.execute("PRAGMA table_info(site_channels)")):
                db.execute("ALTER TABLE site_channels ADD COLUMN inferred INTEGER NOT NULL DEFAULT 0")
        ensure_literal_identity(db)
        setup_metrics(db, choose)
        from gallery import SCHEMA as gallery_schema

        db.executescript(gallery_schema)
        from buildwork import SCHEMA as build_schema

        db.executescript(build_schema)
        from project_archive import SCHEMA as archive_schema, migrate_issue_origins, migrate_page_skills, migrate_page_work

        db.executescript(archive_schema)
        migrate_page_work(db)
        migrate_page_skills(db)
        migrate_issue_origins(db)
        if seed and not db.execute("SELECT 1 FROM settings WHERE k='seed'").fetchone():
            s = json.loads((ROOT / "seed.json").read_text(encoding="utf-8"))
            with db:
                for x in s["sites"]:
                    db.execute(
                        "INSERT INTO sites(id,domain,name,url,region,role,products,notes,status,evidence,queries) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            x["id"],
                            x["domain"],
                            x["name"],
                            x["url"],
                            x["region"],
                            x["role"],
                            x["products"],
                            x["notes"],
                            x["status"],
                            json.dumps(x["evidence"], ensure_ascii=False),
                            json.dumps(x["queries"], ensure_ascii=False),
                        ),
                    )
                    db.executemany(
                        "INSERT INTO aliases VALUES(?,?)",
                        ((domain(a), x["id"]) for a in [x["domain"], *x["aliases"]]),
                    )
                for x in s["keywords"]:
                    w = db.execute(
                        "INSERT INTO words(norm,term,category) VALUES(?,?,?)",
                        (norm(x["term"]), x["term"], x["category"]),
                    ).lastrowid
                    db.executemany(
                        "INSERT INTO refs VALUES(?,?,?)",
                        ((w, v["siteId"], v["url"]) for v in x["sources"]),
                    )
                db.executemany(
                    "INSERT INTO history VALUES(?,?,?,?)",
                    (
                        (x["code"], x["text"], x["source"], x["page"])
                        for x in s["queries"]
                    ),
                )
                db.execute("INSERT INTO settings VALUES('seed','2026-11-21')")

        product_types.setup(db, industry_name or ("包装袋" if seed else ""))


def sheet_paths(z):
    ns = {
        "m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
        "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    }
    import posixpath

    members = set(z.namelist())
    if "xl/workbook.xml" not in members:
        raise TableFormatError("这个 ZIP 里没有 Excel 工作簿。请解压后选择其中的 XLSX 或 CSV 文件。")
    try:
        workbook = ET.fromstring(z.read("xl/workbook.xml"))
        relationships = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    except (KeyError, ET.ParseError, RuntimeError, zipfile.BadZipFile) as error:
        raise TableFormatError("无法读取 Excel 目录。请重新导出未加密的 XLSX 或 CSV。") from error
    links = {x.get("Id"): x.get("Target", "") for x in relationships}
    out = []
    for x in workbook.findall("m:sheets/m:sheet", ns):
        target = links.get(x.get("{" + ns["r"] + "}id"), "")
        path = (
            target.lstrip("/")
            if target.startswith("/")
            else posixpath.normpath(posixpath.join("xl", target))
        )
        if path.startswith("xl/worksheets/") and path in members:
            out.append((x.get("name"), path))
    return out


def xlsx_rows(path, sheet):
    tag = lambda s: "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}" + s
    with zipfile.ZipFile(path) as z:
        sheets = sheet_paths(z)
        choices = dict(sheets)
        target = choices.get(sheet) if sheet else sheets[0][1] if sheets else None
        if not target:
            raise ValueError("Excel 工作表不存在。")
        shared = []
        if "xl/sharedStrings.xml" in z.namelist():
            with z.open("xl/sharedStrings.xml") as f:
                for _, el in ET.iterparse(f):
                    if el.tag == tag("si"):
                        shared.append("".join(t.text or "" for t in el.iter(tag("t"))))
                        el.clear()
        with z.open(target) as f:
            for _, el in ET.iterparse(f):
                if el.tag != tag("row"):
                    continue
                vals = []
                for c in el.findall(tag("c")):
                    col = 0
                    for a in re.match("^[A-Z]+", c.get("r", "A1"))[0]:
                        col = col * 26 + ord(a) - 64
                    if col > 2048:
                        raise ValueError("导入表列数超过 2048，请只导出排名数据表。")
                    while len(vals) < col:
                        vals.append("")
                    v = c.findtext(tag("v"), "")
                    t = c.get("t", "")
                    if t == "s":
                        v = shared[int(v)] if v else ""
                    elif t == "inlineStr":
                        v = "".join(a.text or "" for a in c.iter(tag("t")))
                    vals[col - 1] = v
                yield vals
                el.clear()


def file_rows(path, sheet=""):
    if zipfile.is_zipfile(path):
        try:
            yield from xlsx_rows(path, sheet)
        except (ET.ParseError, RuntimeError, zipfile.BadZipFile) as error:
            raise TableFormatError("无法读取这张 Excel 工作表。请重新导出未加密的 XLSX 或 CSV。") from error
        return
    with open(path, "rb") as f:
        sample = f.read(65536)
    if sample.startswith(b"\xd0\xcf"):
        raise TableFormatError("旧版或加密的 Excel 文件，请另存为未加密的 XLSX 或 CSV，再上传。")
    if sample.startswith(b"PK\x03\x04"):
        raise TableFormatError("Excel 或 ZIP 文件没有下载完整。请重新下载后上传。")
    if sample[:2] in (b"\xff\xfe", b"\xfe\xff"):
        enc = "utf-16"
    elif b"\0" in sample[:100]:
        enc = (
            "utf-16-le"
            if sample[1::2].count(b"\0") >= sample[::2].count(b"\0")
            else "utf-16-be"
        )
    else:
        try:
            codecs.getincrementaldecoder("utf-8-sig")().decode(sample, final=False)
            enc = "utf-8-sig"
        except UnicodeDecodeError:
            enc = "gb18030"
    text = sample.decode(enc, errors="ignore")
    start = text.lstrip("\ufeff \t\r\n")
    start = re.sub(r"^(?:<!--.*?-->\s*)+", "", start, flags=re.S)
    if re.match(r"(?i)(?:<!doctype\s+html\b|<(?:html|head|body)(?:\s|>))", start) or re.match(
        r"(?i)<script(?:\s[^>]*)?>\s*(?:(?:window|document)\s*\.\s*)?location"
        r"(?:\s*\.\s*(?:href|assign|replace))?\s*(?:=|\()",
        start,
    ):
        raise TableFormatError("文件内容是网页，里面没有可导入的表格。请回原平台重新导出 XLSX 或 CSV。")
    line = text.splitlines()[0] if text.splitlines() else ""
    if line.casefold().startswith("sep=") and len(line.strip()) == 5:
        sep = line.strip()[-1]
    else:
        try:
            sep = (
                csv.Sniffer()
                .sniff("\n".join(text.splitlines()[:10]), delimiters=",\t;")
                .delimiter
            )
        except csv.Error:
            sample_lines = [v for v in text.splitlines()[:24] if v.strip()]
            sep = max(
                (",", "\t", ";"),
                key=lambda sep: (
                    sum(sep in v for v in sample_lines),
                    sum(v.count(sep) for v in sample_lines),
                ),
            )
    with open(path, encoding=enc, newline="") as f:
        if line.casefold().startswith("sep="):
            next(f)
        yield from csv.reader(f, delimiter=sep)


def table_data(path, sheet="", skip=0, headerless=False):
    it = file_rows(path, sheet)
    for _ in range(skip):
        if next(it, None) is None:
            raise ValueError("所选表头行超出文件范围。")
    if headerless:
        return ["关键词"], it
    for row in it:
        if any(str(v or "").strip() for v in row):
            return [str(x or "").strip() for x in row], it
    raise ValueError("文件里没有表头。")


def preview(path, sheet="", skip=0):
    names = []
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as z:
            names = [n for n, _ in sheet_paths(z)]
    hdr, it = table_data(path, sheet, skip)
    import itertools

    try:
        samples = list(itertools.islice(it, 3))
    finally:
        it.close()
    return {
        "headers": hdr,
        "mapping": choose(hdr),
        "examples": samples,
        "sheets": names,
    }


def rule_match(word, phrase):
    if not phrase:
        return False
    if phrase.isascii() and any(c.isalnum() for c in phrase):
        return bool(
            re.search(r"(?<![a-z0-9])" + re.escape(phrase) + r"(?![a-z0-9])", word)
        )
    return phrase in word


def evaluate(word, rules):
    for p in rules:
        if rule_match(word, p):
            return p
    return ""


def archive_original(data, path, digest):
    rawdir = Path(data) / "raw"
    rawdir.mkdir(exist_ok=True)
    target = rawdir / digest
    if not target.is_file():
        temp = rawdir / (uuid.uuid4().hex + ".partial")
        try:
            shutil.copyfile(path, temp)
            os.replace(temp, target)
        finally:
            temp.unlink(missing_ok=True)


def keyword_batch_summary(db, batch):
    count, linked, sites = db.execute(
        """SELECT coalesce(sum(n),0),coalesce(sum(CASE WHEN site IS NOT NULL THEN n ELSE 0 END),0),count(site)
           FROM (SELECT site,count(*) AS n FROM obs WHERE batch=? GROUP BY site)""",
        (batch["id"],),
    ).fetchone()
    sources = dict(
        source_rows=linked,
        source_sites=sites,
        unlinked_rows=count - linked if count == batch["written"] else None,
    )
    if batch["distinct_words"] is not None:
        return dict(sources, distinct_words=batch["distinct_words"], prior_word_id=batch["prior_word_id"])
    if count == batch["written"]:
        distinct = db.execute(
            "SELECT count(DISTINCT word) FROM obs WHERE batch=?", (batch["id"],)
        ).fetchone()[0]
        if distinct >= batch["added"]:
            return dict(sources, distinct_words=distinct, prior_word_id=None)
    return dict(sources, distinct_words=None, prior_word_id=None)


def import_file(data, path, filename, opts, digest=None, progress=lambda n: None):
    hdr, it = table_data(
        path, opts.get("sheet", ""), opts.get("skip", 0), opts.get("headerless", False)
    )
    auto = choose(hdr)
    mapping = opts.get("mapping") or auto
    idx = {k: int(mapping.get(k, -1)) for k in FIELDS}
    if (
        idx["word"] < 0
        or idx["word"] >= len(hdr)
        or any(i >= len(hdr) or i < -1 for i in idx.values())
    ):
        it.close()
        raise ValueError("请选择正确的关键词列。")
    given = opts.get("domain", "").strip()
    forced = domain(given) if given else ""
    if given and not forced:
        it.close()
        raise ValueError("同行域名格式不正确。")
    provided_market = opts.get("market", "").strip()
    provided_date = opts.get("date", "").strip()
    inferred_market, inferred_date = keyword_report_defaults(filename)
    market = provided_market or inferred_market
    date = provided_date or inferred_date
    if not digest:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        digest = h.hexdigest()
    archive_original(data, path, digest)
    sheet = opts.get("sheet", "")
    is_workbook = zipfile.is_zipfile(path)
    date_1904 = False
    if is_workbook:
        with zipfile.ZipFile(path) as workbook:
            sheets = sheet_paths(workbook)
            props = ET.fromstring(workbook.read("xl/workbook.xml")).find(
                "{*}workbookPr"
            )
            date_1904 = props is not None and props.get("date1904", "").lower() in (
                "1",
                "true",
            )
        if sheets and sheet == sheets[0][0]:
            sheet = ""

    def signature(indices, default_market, default_date):
        reviewed_header = [["review_header", opts["skip"]]] if opts.get("review") and opts.get("skip") else []
        return hashlib.sha256(
            json.dumps(
                [digest, forced, default_market, default_date, sheet, indices]
                + (["headerless"] if opts.get("headerless") else []) + reviewed_header,
                sort_keys=True,
            ).encode()
        ).hexdigest()

    legacy = {k: v for k, v in idx.items() if k != "dr"}
    sig = signature(idx, market, date)
    # Earlier uploads could have supplied either, both or neither default.
    # Keep recognizing those batches when the same file is uploaded again.
    compatible = {
        signature(indices, source_market, source_date)
        for indices in ([idx, legacy] if idx["dr"] == auto["dr"] else [idx])
        for source_market in {market, provided_market}
        for source_date in {date, provided_date}
    }
    imported_at = clock()
    with contextlib.closing(it), contextlib.closing(dbopen(data)) as db, db:
        db.execute("BEGIN IMMEDIATE")
        parameters = ",".join("?" for _ in compatible)
        existing = db.execute(
            f"SELECT * FROM batches WHERE signature IN ({parameters}) ORDER BY signature=? DESC,id LIMIT 1",
            (*compatible, sig),
        ).fetchone()
        if existing:
            return dict(existing, **keyword_batch_summary(db, existing), duplicate=True)
        bid = db.execute(
            "INSERT INTO batches(signature,filename,source,market,report_date,created) VALUES(?,?,?,?,?,?)",
            (sig, filename, forced, market, date, imported_at),
        ).lastrowid
        db.execute(
            "INSERT INTO archived VALUES(?,?,?)",
            (bid, digest, json.dumps(hdr, ensure_ascii=False)),
        )
        profile_indices = [
            hdr.index(h) if h in hdr else -1
            for h in ("中文翻译", "一级分类", "二级分类", "包装袋精选")
        ]
        keep_extra = any(i not in idx.values() for i in range(len(hdr)))
        extra = []
        supplement = []
        hasprofile = any(i >= 0 for i in profile_indices)
        if hasprofile:
            db.execute(
                "CREATE TEMP TABLE profiles_in(k TEXT,tr TEXT,cat TEXT,sub TEXT,feat TEXT)"
            )

        def flushmeta():
            if extra:
                db.executemany("INSERT INTO extras VALUES(?,?,?)", extra)
                extra.clear()
            if supplement:
                db.executemany("INSERT INTO profiles_in VALUES(?,?,?,?,?)", supplement)
                supplement.clear()

        db.execute(
            "CREATE TEMP TABLE incoming(n INTEGER PRIMARY KEY, k TEXT,w TEXT,h TEXT,url TEXT,traffic TEXT,volume TEXT,position TEXT,market TEXT,d TEXT,traffic_num REAL,dr TEXT,sort_day TEXT)"
        )
        insert = "INSERT INTO incoming VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)"
        buffer = []
        seen = written = 0
        for row in it:
            seen += 1

            def col(k):
                j = idx[k]
                return str(row[j]).strip() if 0 <= j < len(row) else ""

            term = str(row[idx["word"]]) if idx["word"] < len(row) else ""
            k = norm(term)
            if not k:
                continue
            raw_date = col("date")
            effective_date = (
                workbook_day(raw_date, date_1904) if is_workbook else raw_date
            ) or date
            url = web(col("url"))
            site = forced or domain(col("site")) or domain(url)
            buffer.append(
                (
                    seen,
                    k,
                    term,
                    site,
                    url,
                    col("traffic") or None,
                    col("volume") or None,
                    col("position") or None,
                    col("market") or market or None,
                    effective_date or None,
                    num(col("traffic")),
                    col("dr") or None,
                    report_day(effective_date, imported_at),
                )
            )
            written += 1
            if keep_extra:
                extra.append(
                    (
                        bid,
                        seen,
                        zlib.compress(
                            json.dumps(
                                row, ensure_ascii=False, separators=(",", ":")
                            ).encode(),
                            1,
                        ),
                    )
                )
            if hasprofile:
                supplement.append(
                    (
                        term,
                        *[
                            str(row[j] or "") if 0 <= j < len(row) else ""
                            for j in profile_indices
                        ],
                    )
                )
            if len(buffer) >= 5000:
                db.executemany(insert, buffer)
                buffer.clear()
                flushmeta()
                progress(seen)
        if buffer:
            db.executemany(insert, buffer)
        flushmeta()
        progress(seen)
        db.execute(
            "INSERT OR IGNORE INTO sites(domain,name,url) SELECT h,h,'https://'||h FROM incoming WHERE h<>'' AND h NOT IN (SELECT domain FROM aliases) GROUP BY h"
        )
        db.execute(
            "INSERT OR IGNORE INTO aliases SELECT s.domain,s.id FROM sites s WHERE s.domain IN (SELECT DISTINCT h FROM incoming WHERE h<>'')"
        )
        db.execute(
            "INSERT OR IGNORE INTO pages(site,url) SELECT DISTINCT a.site,i.url FROM incoming i JOIN aliases a ON a.domain=i.h WHERE i.url<>''"
        )
        rules = [r[0] for r in db.execute("SELECT phrase FROM rules ORDER BY id")]
        maxid = db.execute("SELECT ifnull(max(id),0) FROM words").fetchone()[0]
        db.execute(
            "INSERT OR IGNORE INTO words(norm,term) SELECT min(k),w FROM incoming GROUP BY w COLLATE BINARY"
        )
        added = db.execute("SELECT changes()").fetchone()[0]
        if hasprofile:
            db.execute(
                "INSERT OR IGNORE INTO profiles(word,translation,subtype,featured) SELECT w.id,p.tr,p.sub,p.feat FROM profiles_in p JOIN words w ON w.term=p.k"
            )
            db.execute("CREATE INDEX temp.prof_in_k ON profiles_in(k)")
            db.execute(
                "UPDATE words SET category=(SELECT p.cat FROM profiles_in p WHERE p.k=words.term LIMIT 1) WHERE category='' AND term IN (SELECT k FROM profiles_in WHERE cat<>'')"
            )
            db.execute(
                "UPDATE words SET state=1,reason='原表包装袋精选' WHERE manual=0 AND state=0 AND term IN (SELECT k FROM profiles_in WHERE feat='是')"
            )
        if hasprofile:
            db.execute(
                """UPDATE words SET product_type=(SELECT id FROM product_types WHERE name=words.category)
                          WHERE type_manual=0 AND product_type=0 AND id<=? AND category IN (SELECT name FROM product_types)
                          AND term IN (SELECT k FROM profiles_in WHERE cat<>'')""",
                (maxid,),
            )
        if added:
            product_types.classify(db, maxid)
        if rules and added:
            db.create_function(
                "which_rule", 1, lambda k: evaluate(k, rules), deterministic=True
            )
            db.execute(
                "UPDATE words SET state=2,reason=which_rule(norm) WHERE id>? AND which_rule(norm)<>''",
                (maxid,),
            )
        db.execute(
            """INSERT INTO obs(word,site,page,batch,rownum,traffic,volume,position,market,report_date,traffic_num,dr,sort_day)
   SELECT w.id,a.site,p.id,?,i.n,i.traffic,i.volume,i.position,i.market,i.d,i.traffic_num,i.dr,i.sort_day FROM incoming i
   JOIN words w ON w.term=i.w LEFT JOIN aliases a ON a.domain=i.h LEFT JOIN pages p ON p.site=a.site AND p.url=i.url ORDER BY i.n""",
            (bid,),
        )
        distinct = written if written == added else db.execute(
            "SELECT count(DISTINCT word) FROM obs WHERE batch=?", (bid,),
        ).fetchone()[0]
        db.execute(
            "UPDATE batches SET seen=?,written=?,added=?,blank=?,distinct_words=?,prior_word_id=? WHERE id=?",
            (seen, written, added, seen - written, distinct, maxid, bid),
        )
        row = db.execute("SELECT * FROM batches WHERE id=?", (bid,)).fetchone()
        return dict(row, **keyword_batch_summary(db, row), duplicate=False)
