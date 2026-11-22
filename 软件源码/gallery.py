"""Industry-local product images, literal keyword links, and offline site assets."""

import csv
import hashlib
import json
import os
import pathlib
import re
import shutil
import tempfile
import zipfile

from library import csv_cell, rows
from product_types import clean

MAX_IMAGE = 32 * 1024 * 1024
MAX_THUMB = 256 * 1024

WEB_ASSET = """g.mime IN ('image/jpeg','image/png','image/webp','image/gif')
 AND NOT EXISTS (
     SELECT 1 FROM gallery_origins blocked WHERE blocked.image=g.id
     AND blocked.kind IN ('同行参考','示例素材','来源待核实','设计源文件','教程参考')
 )"""
PRODUCT_ASSET = WEB_ASSET + """
 AND EXISTS (SELECT 1 FROM gallery_origins o WHERE o.image=g.id AND o.kind='产品素材')"""
IMAGE_EXTENSIONS = {
    "image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/gif": ".gif",
    "image/tiff": ".tif", "image/bmp": ".bmp", "image/heic": ".heic", "image/heif": ".heif",
    "image/avif": ".avif", "image/vnd.adobe.photoshop": ".psd",
}

CATEGORY_TERMS = {
    "快递袋": ("poly mailer", "poly mailers", "polymailers", "courier bags", "shipping mailers"),
    "印字快递袋": ("printed poly mailer", "printed poly mailers", "logo poly mailers"),
    "气泡袋": ("bubble mailer", "bubble mailers", "bubble bags", "bubble pouches"),
    "拉链与自封袋": ("ziplock bags", "zip lock bags", "zipper bags", "resealable bags", "自封袋"),
    "服装袋": ("garment bags", "clothing packaging bags", "apparel packaging bags"),
    "缠绕膜": ("stretch film", "stretch wrap", "pallet wrap"),
    "胶带与胶带器": ("packing tape", "tape dispenser", "tape dispensers", "胶带器"),
    "标签纸": ("shipping labels", "label paper", "thermal labels"),
    "牛皮纸袋": ("kraft paper bags", "kraft bags"),
    "食品袋": ("food bags", "food packaging bags"),
    "自立袋": ("stand up pouch", "stand up pouches", "doypack"),
    "平底袋": ("flat bottom bag", "flat bottom bags", "flat bottom pouch", "flat bottom pouches"),
    "铝箔袋": ("foil pouches", "aluminum foil bags"),
    "包装卷材": ("rollstock", "roll stock film"),
    "气柱袋": ("air column bag", "air column bags", "air column packaging"),
    "蜂窝纸袋": ("honeycomb paper mailers", "honeycomb padded mailers", "honeycomb paper bags"),
    "相机电池素材 · 佳能兼容系列": ("canon camera battery", "canon camera batteries", "佳能相机电池"),
    "相机电池素材 · 索尼兼容系列": ("sony camera battery", "sony camera batteries", "索尼相机电池"),
    "相机电池素材 · 尼康兼容系列": ("nikon camera battery", "nikon camera batteries", "尼康相机电池"),
    "相机电池素材 · 富士兼容系列": ("fuji camera battery", "fujifilm camera battery", "富士相机电池"),
    "相机电池素材 · 松下兼容系列": ("panasonic camera battery", "panasonic camera batteries", "松下相机电池"),
    "相机电池素材 · GoPro系列": ("gopro battery", "gopro batteries", "gopro camera battery"),
}

MODEL_SEPARATOR = r"[\s\-‐‑‒–—_]*"
CAMERA_BATTERY_MODEL = re.compile(
    rf"(?<![a-z0-9])(?:np|lp|en{MODEL_SEPARATOR}el|nb|bp|dmw|bln|blx|ble|blk)"
    rf"{MODEL_SEPARATOR}[a-z]{{0,4}}[0-9]{{1,5}}[a-z0-9]{{0,4}}(?![a-z0-9])"
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS gallery_images (
    id INTEGER PRIMARY KEY, digest TEXT UNIQUE NOT NULL, filename TEXT NOT NULL,
    mime TEXT NOT NULL, size INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS gallery_files (
    image INTEGER PRIMARY KEY REFERENCES gallery_images(id), original BLOB NOT NULL, thumb BLOB
);
CREATE TABLE IF NOT EXISTS gallery_external(image INTEGER PRIMARY KEY REFERENCES gallery_images(id), digest TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS gallery_origins(image INTEGER NOT NULL REFERENCES gallery_images(id),
 path TEXT NOT NULL,category TEXT NOT NULL,kind TEXT NOT NULL,role TEXT NOT NULL,
 PRIMARY KEY(image,path)) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS gallery_categories ON gallery_origins(category,kind,image);
CREATE TABLE IF NOT EXISTS gallery_tags (
    image INTEGER NOT NULL REFERENCES gallery_images(id), term TEXT COLLATE BINARY NOT NULL,
    PRIMARY KEY(image,term)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS gallery_term ON gallery_tags(term,image);
CREATE TABLE IF NOT EXISTS gallery_covers (
    term TEXT PRIMARY KEY, image INTEGER NOT NULL,
    FOREIGN KEY(image,term) REFERENCES gallery_tags(image,term) ON DELETE CASCADE
) WITHOUT ROWID;
"""


def image_type(b):
    if (
        b.startswith(b"\x89PNG\r\n\x1a\n")
        and b[12:16] == b"IHDR"
        and b[-8:-4] == b"IEND"
    ):
        return "image/png"
    if b.startswith(b"\xff\xd8\xff") and b.rstrip(b"\0\r\n").endswith(b"\xff\xd9"):
        return "image/jpeg"
    if (
        b[:4] == b"RIFF"
        and b[8:12] == b"WEBP"
        and b[12:16] in (b"VP8 ", b"VP8L", b"VP8X")
    ):
        return "image/webp"
    raise ValueError("请选择有效的 JPG、PNG 或 WebP 图片。")


def store(db, filename, original, thumbnail=b"", word=None, category="", kind="产品素材"):
    filename = pathlib.PureWindowsPath(filename).name
    if not filename or len(filename) > 255 or not 0 < len(original) <= MAX_IMAGE:
        raise ValueError("每张图片最多 32 MB，请保留有效文件名。")
    mime = image_type(original)
    if thumbnail and (
        len(thumbnail) > MAX_THUMB or image_type(thumbnail) != "image/jpeg"
    ):
        raise ValueError("预览图无效，请重新选择图片。")
    digest = hashlib.sha256(original).hexdigest()
    db.execute("BEGIN IMMEDIATE")
    term = None
    if word is not None:
        found = db.execute("SELECT term FROM words WHERE id=?", (int(word),)).fetchone()
        if not found:
            raise ValueError("当前行业中没有这个词。")
        term = found[0]
    old = db.execute(
        "SELECT id,filename FROM gallery_images WHERE digest=?", (digest,)
    ).fetchone()
    if old:
        ident = old["id"]
    else:
        ident = db.execute(
            "INSERT INTO gallery_images(digest,filename,mime,size) VALUES(?,?,?,?)",
            (digest, filename, mime, len(original)),
        ).lastrowid
        db.execute(
            "INSERT INTO gallery_files VALUES(?,?,?)",
            (ident, original, thumbnail or None),
        )
    if kind not in ("产品素材", "同行参考", "来源待核实", "示例素材", "教程参考", "设计源文件"):
        raise ValueError("图片来源无效。")
    category = category.strip()
    if len(category) > 120:
        raise ValueError("分类名称最多 120 字。")
    origins = {r[0] for r in db.execute("SELECT kind FROM gallery_origins WHERE image=?", (ident,))}
    if not origins or (kind == "同行参考" and kind not in origins):
        if not category:
            candidates = [r[0] for r in db.execute("SELECT DISTINCT category FROM gallery_origins WHERE category <> '待细分' ORDER BY length(category) DESC, category") if r[0] and r[0].casefold() in filename.casefold()]
            category = candidates[0] if candidates else "待细分"
        path = "手动上传/" + kind + "/" + filename
        db.execute("INSERT INTO gallery_origins(image,path,category,kind,role) VALUES(?,?,?,?,?)",
                   (ident, path, category, kind, "参考图" if kind == "同行参考" else "产品展示"))
    if term is None and (not old or old["filename"] != filename):
        term = pathlib.PurePath(filename).stem
    if term and term.strip():
        db.execute(
            "INSERT OR IGNORE INTO gallery_tags(image,term) VALUES(?,?)", (ident, term)
        )
    return {"id": ident, "duplicate": bool(old)}


ACTIVE_TAG_COUNT = "(SELECT count(*) FROM gallery_tags t JOIN words w ON w.term=t.term WHERE t.image=g.id AND w.state<>2)"


def image_filters(db, q):
    where, args = [], []
    query = q.get("q") or ""
    model_query = camera_battery_models(clean(query))
    if query and not model_query:
        where.append("""(instr(lower(g.filename),lower(?)) OR EXISTS (
            SELECT 1 FROM gallery_tags s WHERE s.image=g.id AND instr(lower(s.term),lower(?))) OR EXISTS (
            SELECT 1 FROM gallery_origins o WHERE o.image=g.id AND (instr(lower(o.category),lower(?)) OR instr(lower(o.role),lower(?)))))""")
        args.extend([query] * 4)
    origin_filters = [key for key in ("category", "kind", "role") if q.get(key)]
    conditions = " AND ".join("o." + key + "=?" for key in origin_filters)
    include_unclassified = origin_filters == ["category"] and q["category"] == "待细分"
    if model_query:
        other_terms = photo_text(CAMERA_BATTERY_MODEL.sub(" ", clean(query))).split()
        tags = "(SELECT group_concat(term, ' ') FROM gallery_tags WHERE image=g.id)" if other_terms else "''"

        def matches_model(filename, category, path, role, names):
            models, _ = image_battery_models(
                pathlib.PurePath(filename).stem, pathlib.PureWindowsPath(path or ""), category or ""
            )
            if not model_query.issubset(models):
                return False
            if not other_terms:
                return True
            labels = " ".join(category_aliases(category or ""))
            context = photo_text(f"{filename} {path or ''} {role or ''} {labels} {names or ''}")
            return all(term in context for term in other_terms)

        db.create_function("gallery_matches_model", 5, matches_model)
        origin_scope = conditions or "1"
        if include_unclassified:
            origin_scope = f"(o.image IS NULL OR {origin_scope})"
        where.append(
            f"""EXISTS (SELECT 1 FROM gallery_images photo
               LEFT JOIN gallery_origins o ON o.image=photo.id WHERE photo.id=g.id
               AND {origin_scope} AND gallery_matches_model(g.filename,o.category,o.path,o.role,{tags}))"""
        )
        args.extend(q[key] for key in origin_filters)
    elif origin_filters:
        clause = "EXISTS (SELECT 1 FROM gallery_origins o WHERE o.image=g.id AND " + conditions + ")"
        if include_unclassified:
            clause = "(" + clause + " OR NOT EXISTS (SELECT 1 FROM gallery_origins o WHERE o.image=g.id))"
        where.append(clause)
        args.extend(q[key] for key in origin_filters)
    if q.get("kind") == "产品素材":
        where.append("NOT EXISTS (SELECT 1 FROM gallery_origins r WHERE r.image=g.id AND r.kind='同行参考')")
    if q.get("linkstate") in ("ready", "pending"):
        where.append(ACTIVE_TAG_COUNT + (" > 0" if q["linkstate"] == "ready" else " = 0"))
    return where, args


def listed(db, q, with_total=False, limit=50):
    where, args = image_filters(db, q)
    if with_total:
        total = db.execute("SELECT count(*) FROM gallery_images g " + ("WHERE " + " AND ".join(where) if where else ""), args).fetchone()[0]
    if q.get("after"):
        where.append("g.id < ?")
        args.append(int(q["after"]))
    result = rows(
        db,
        "SELECT g.id,g.filename,g.size,g.mime,coalesce((SELECT group_concat(DISTINCT category) FROM gallery_origins o WHERE o.image=g.id),'待细分') AS category,(SELECT group_concat(DISTINCT kind) FROM gallery_origins o WHERE o.image=g.id) AS origin_kind,"
        + "(" + PRODUCT_ASSET + ") AS website_candidate,"
        + ACTIVE_TAG_COUNT
        + " AS matches FROM gallery_images g "
        + ("WHERE " + " AND ".join(where) if where else "")
        + " ORDER BY g.id DESC LIMIT ?",
        (*args, limit + 1),
    )
    return {"rows": result[:limit], "more": len(result) > limit, **({"total": total} if with_total else {})}


def search_industries(root, q):
    from contextlib import closing
    from ai_reader import readonly
    from workspaces import catalog, location

    with closing(readonly(root)) as master:
        industries = catalog(master)
    owner = int(q.get("owner") or 0)
    if owner and not any(item["id"] == owner for item in industries):
        raise ValueError("请选择已有行业。")
    filters = {key: str(q.get(key, "")).strip()[:limit] for key, limit in
               (("q", 240), ("kind", 30), ("category", 120), ("linkstate", 16))}
    groups = []
    categories = set()
    for item in industries:
        if owner and owner != item["id"]:
            continue
        with closing(readonly(location(root, item["id"]))) as db:
            categories.update(row[0] for row in db.execute("SELECT DISTINCT category FROM gallery_origins"))
            if db.execute(
                """SELECT 1 FROM gallery_images g
                   WHERE NOT EXISTS (SELECT 1 FROM gallery_origins o WHERE o.image=g.id) LIMIT 1"""
            ).fetchone():
                categories.add("待细分")
            result = listed(db, filters, with_total=True, limit=8)
        if result["total"]:
            groups.append(dict(item, total=result["total"], images=result["rows"], more=result["more"]))
    return {"groups": groups, "categories": sorted(categories), "total": sum(group["total"] for group in groups)}


def detail(db, ident):
    entry = db.execute(
        "SELECT id,filename,size,mime FROM gallery_images WHERE id=?", (int(ident),)
    ).fetchone()
    if not entry:
        raise ValueError("当前行业中没有这张图片。")
    tags = rows(
        db,
        """SELECT t.term,w.id AS word,w.state FROM gallery_tags t
                       LEFT JOIN words w ON w.term=t.term WHERE t.image=? ORDER BY t.term""",
        (ident,),
    )
    return dict(entry, tags=tags, origins=rows(db,"SELECT path,category,kind,role FROM gallery_origins WHERE image=? ORDER BY path",(int(ident),)))


def asset_details(db, ident):
    original = db.execute(
        f"SELECT g.digest,({PRODUCT_ASSET}) AS website_candidate FROM gallery_images g WHERE g.id=?",
        (ident,),
    ).fetchone()
    if original is None:
        raise ValueError("当前行业中没有这张图片。")
    return dict(detail(db, ident), sha256=original["digest"],
                website_candidate=bool(original["website_candidate"]))


def prepare_image(root, industry, ident):
    from contextlib import closing
    from ai_reader import readonly
    from workspaces import digest_file, resolve

    root = root.resolve()
    with closing(readonly(resolve(root, industry))) as db:
        image = asset_details(db, ident)
        digest = image["sha256"]
        if not re.fullmatch("[a-f0-9]{64}", digest):
            raise ValueError("图片的原件校验值无效。")
        cache = root / "image-cache"
        if cache.is_symlink():
            raise ValueError("请使用资料库中的本机图片目录。")
        cache.mkdir(mode=0o700, exist_ok=True)
        target = cache / (digest + IMAGE_EXTENSIONS.get(image["mime"], ".bin"))
        if target.is_file() and not target.is_symlink() and digest_file(target) == digest:
            return dict(image, industry=industry, local_file=str(target))

        stage = None
        try:
            with tempfile.NamedTemporaryFile(dir=cache, delete=False) as output:
                stage = pathlib.Path(output.name)
                if db.execute("SELECT 1 FROM gallery_external WHERE image=?", (ident,)).fetchone():
                    with external_path(db, ident).open("rb") as source:
                        shutil.copyfileobj(source, output, 1024 * 1024)
                else:
                    row = db.execute("SELECT original FROM gallery_files WHERE image=?", (ident,)).fetchone()
                    if not row:
                        raise ValueError("找不到这张图片的原件。")
                    output.write(row[0])
            if stage.stat().st_size != image["size"] or digest_file(stage) != digest:
                raise ValueError("图片原件未通过完整性校验。")
            os.replace(stage, target)
        except OSError:
            raise ValueError("无法读取原件或准备本机图片副本，请核对图库文件。") from None
        finally:
            if stage:
                stage.unlink(missing_ok=True)
    return dict(image, industry=industry, local_file=str(target))


def classification_name(category):
    if not isinstance(category, str) or not 1 <= len(category.strip()) <= 120:
        raise ValueError("请填写产品分类，最多 120 字。")
    return category.strip()


def classify_selected(db, ids, category):
    if not isinstance(ids, list) or not ids or any(type(i) is not int or not 0 < i < 2**63 for i in ids):
        raise ValueError("请先勾选要分类的图片。")
    category = classification_name(category)
    selected = dict.fromkeys(ids)
    with db:
        db.execute("BEGIN IMMEDIATE")
        for ident in selected:
            if db.execute("UPDATE gallery_origins SET category=? WHERE image=?", (category, ident)).rowcount:
                continue
            added = db.execute(
                """INSERT INTO gallery_origins(image,path,category,kind,role)
                   SELECT id,'手动分类',?,'来源待核实','待核实' FROM gallery_images WHERE id=?""",
                (category, ident),
            )
            if not added.rowcount:
                raise ValueError("有图片已移出当前行业，请刷新选择后再试。")
    return {"count": len(selected), "category": category}


def checked_gallery_filters(filters):
    limits = {"q": 1000, "category": 120, "kind": 30, "role": 180, "linkstate": 16}
    if not isinstance(filters, dict) or any(
        key not in limits or not isinstance(value, str) or len(value) > limits[key]
        for key, value in filters.items()
    ):
        raise ValueError("图片筛选条件无效。")
    return filters


def filtered_classification(db, filters, page=None):
    filters = checked_gallery_filters(filters)
    if page is not None and (type(page) is not int or page < 1):
        raise ValueError("图片预览页码无效。")
    where, params = image_filters(db, filters)
    origins = [key for key in ("category", "kind", "role") if filters.get(key)]
    if origins:
        origin_scope = " AND ".join("o." + key + "=?" for key in origins)
        where.append(f"(o.image IS NULL OR ({origin_scope}))")
        params.extend(filters[key] for key in origins)
    clause = " WHERE " + " AND ".join(where) if where else ""
    matches = db.execute(
        "SELECT g.id,g.filename,o.path,o.category,o.kind,o.role"
        " FROM gallery_images g LEFT JOIN gallery_origins o ON o.image=g.id" +
        clause + " ORDER BY g.id DESC,o.path", params,
    ).fetchall()
    revision = hashlib.sha256()
    images = {}
    for row in matches:
        revision.update(json.dumps(tuple(row), ensure_ascii=False).encode("utf-8"))
        images[row["id"]] = row["filename"]
    result = {
        "count": len(images),
        "origins": len(matches),
        "revision": revision.hexdigest(),
    }
    if page is not None:
        page_size = 12
        pages = (len(images) + page_size - 1) // page_size
        page = min(page, max(1, pages))
        start = (page - 1) * page_size
        sample = {
            ident: {"id": ident, "filename": images[ident], "sources": []}
            for ident in list(images)[start:start + page_size]
        }
        for row in matches:
            shown = sample.get(row["id"])
            if shown is not None:
                kind = row["kind"] or "来源待核实"
                if kind not in shown["sources"]:
                    shown["sources"].append(kind)
        result.update(page=page, pages=pages, photos=list(sample.values()))
    return matches, result


def classify_filtered(db, filters, category, revision, excluded=None):
    category = classification_name(category)
    if excluded is None:
        excluded = []
    if not isinstance(excluded, list) or any(type(i) is not int or not 0 < i < 2**63 for i in excluded):
        raise ValueError("待确认图片编号无效。")
    skipped = set(excluded)
    with db:
        db.execute("BEGIN IMMEDIATE")
        matches, preview = filtered_classification(db, filters)
        if not matches or preview["revision"] != revision:
            raise ValueError("筛选结果或图片分类已有变化，请重新预览后再保存。")
        if skipped:
            if not skipped.issubset(row["id"] for row in matches):
                raise ValueError("待确认图片不在本次筛选结果中。")
            matches = [row for row in matches if row["id"] not in skipped]
            if not matches:
                raise ValueError("请至少勾选一张要归类的图片。")
        db.executemany(
            "UPDATE gallery_origins SET category=? WHERE image=? AND path=?",
            ((category, row["id"], row["path"]) for row in matches if row["path"] is not None),
        )
        db.executemany(
            """INSERT INTO gallery_origins(image,path,category,kind,role)
               VALUES(?,'手动分类',?,'来源待核实','待核实')""",
            ((row["id"], category) for row in matches if row["path"] is None),
        )
    return {"count": preview["count"] - len(skipped), "category": category}


def change(db, payload):
    ident = int(payload["id"])
    term = payload["term"]
    action = payload["action"]
    if not isinstance(term, str) or not term.strip() or len(term) > 1000:
        raise ValueError("请填写完整关键词，最多 1000 个字。")
    db.execute("BEGIN IMMEDIATE")
    if not db.execute("SELECT 1 FROM gallery_images WHERE id=?", (ident,)).fetchone():
        raise ValueError("当前行业中没有这张图片。")
    if action == "link":
        db.execute("INSERT OR IGNORE INTO gallery_tags VALUES(?,?)", (ident, term))
    elif action == "unlink":
        db.execute("DELETE FROM gallery_tags WHERE image=? AND term=?", (ident, term))
    elif action == "cover":
        db.execute(
            "INSERT INTO gallery_covers(term,image) VALUES(?,?) ON CONFLICT(term) DO UPDATE SET image=excluded.image",
            (term, ident),
        )
    else:
        raise ValueError("配图操作无效。")
    return {"ok": True}


def matches(db, term, limit=None):
    sql = (
        f"""SELECT g.id,g.filename,g.mime FROM gallery_tags t
                       JOIN words w ON w.term=t.term AND w.state<>2
                       JOIN gallery_images g ON g.id=t.image
                       LEFT JOIN gallery_covers c ON c.term=t.term
                       WHERE t.term=? AND {WEB_ASSET} ORDER BY (g.id IS c.image) DESC,g.id"""
    )
    return rows(db, sql, (term,)) if limit is None else rows(db, sql + " LIMIT ?", (term, limit))


def terms_from_text(value):
    if not isinstance(value, str):
        raise ValueError("请每行输入一个关键词。")
    terms = list(
        dict.fromkeys(t for t in value.replace("\r\n", "\n").split("\n") if t.strip())
    )
    if not terms or len(terms) > 10000 or any(len(t) > 1000 for t in terms):
        raise ValueError("请每行填写一个完整关键词，每次最多 10,000 个。")
    return terms


def word_state(word):
    if word is None:
        return "absent"
    return "excluded" if word[0] == 2 else "unmatched"


def preview(db, text, offset=0, unmatched=False):
    terms = terms_from_text(text)
    offset = max(0, int(offset))
    result = []
    counts = dict(matched=0, unmatched=0, absent=0, excluded=0)
    visible = 0
    for term in terms:
        status = word_state(db.execute("SELECT state FROM words WHERE term=?", (term,)).fetchone())
        images = matches(db, term) if status == "unmatched" else []
        if images:
            status = "matched"
        counts[status] += 1
        if unmatched and status == "matched":
            continue
        if offset <= visible < offset + 100:
            result.append(
                {
                    "term": term,
                    "count": len(images),
                    "first": images[0] if images else None,
                    "status": status,
                }
            )
        visible += 1
    return dict(counts, rows=result, total=len(terms), offset=offset, more=visible > offset + 100)


def photo_text(value):
    return " ".join(re.findall(r"[^\W_]+", clean(value)))


def has_phrase(text, phrase):
    if not phrase:
        return False
    if re.search(r"[\u3400-\u9fff]", phrase):
        return phrase in text
    return f" {phrase} " in f" {text} "


def camera_battery_models(text):
    return {re.sub(r"[^a-z0-9]", "", match[0]) for match in CAMERA_BATTERY_MODEL.finditer(text)}


def image_battery_models(stem, source, category):
    filename_models = camera_battery_models(clean(stem))
    if filename_models:
        return filename_models, True
    # Prefer the closest model label when an archive groups several products.
    for part in (*reversed(source.parent.parts), category):
        models = camera_battery_models(clean(part))
        if models:
            return models, False
    return set(), False


def category_aliases(label):
    yield label
    while label:
        yield from CATEGORY_TERMS.get(label, ())
        label = label.rpartition(" · ")[0]


def suggest(db, term, category="", query="", offset=0, browse=False):
    if not isinstance(term, str) or not term.strip() or len(term) > 1000:
        raise ValueError("请填写完整关键词，最多 1000 个字。")
    if len(category) > 120 or len(query) > 180:
        raise ValueError("搜索内容过长。")
    offset = max(0, int(offset))
    word = db.execute(
        """SELECT w.state,w.category,t.name FROM words w LEFT JOIN product_types t
           ON t.id=w.product_type WHERE w.term=?""", (term,)
    ).fetchone()
    status = word_state(word)
    attached = matches(db, term) if status == "unmatched" else []
    linked_ids = {image["id"] for image in attached}
    cover_id = attached[0]["id"] if attached else None
    original_category, product_type = (word[1], word[2]) if word else ("", "")
    phrase = photo_text(term)
    requested_models = camera_battery_models(clean(term))
    query_models = camera_battery_models(clean(query))
    search_terms = photo_text(CAMERA_BATTERY_MODEL.sub(" ", clean(query))).split()
    filtering = bool(category or query_models or search_terms or browse)
    categories = set()
    category_scores = {}
    candidates = {}
    model_tokens = {
        token for token in phrase.split() if len(token) >= 4 and
        re.search("[a-z]", token) and re.search("[0-9]", token)
    }
    for ident, filename, label, path in db.execute(
        f"""SELECT g.id,g.filename,o.category,o.path FROM gallery_images g
            JOIN gallery_origins o ON o.image=g.id AND o.kind='产品素材'
            WHERE {WEB_ASSET}"""
    ):
        categories.add(label)
        if category and label != category:
            continue
        if label not in category_scores:
            if label in (original_category, product_type):
                category_scores[label] = 32
            else:
                category_scores[label] = max(
                    (24 + min(30, len(alias)) for alias in category_aliases(label)
                     if has_phrase(phrase, photo_text(alias))),
                    default=0,
                )
        stem = pathlib.PurePath(filename).stem
        filename_text = photo_text(stem)
        source = pathlib.PureWindowsPath(path)
        parent = source.parent.name
        searchable = photo_text(f"{filename} {label} {parent}")
        if search_terms and not all(part in searchable for part in search_terms):
            continue
        model_reason = ""
        if query_models or requested_models:
            models, model_from_filename = image_battery_models(stem, source, label)
            if query_models and not query_models.issubset(models):
                continue
            if (query_models or requested_models).intersection(models):
                model_reason = "文件名含完整型号" if model_from_filename else "图库分类或来源目录含完整型号"
            if requested_models and not model_reason and ident not in linked_ids and not filtering:
                continue
        if ident in linked_ids:
            score, reason = 100, "已经用于这个关键词"
        elif phrase and has_phrase(filename_text, phrase) and (not requested_models or model_reason):
            score, reason = 85, "文件名含完整词"
        elif model_reason:
            score, reason = (82 if model_from_filename else 78), model_reason
        elif not requested_models and model_tokens.intersection(searchable.split()):
            score, reason = 62, "文件名或来源目录含型号"
        elif not requested_models and category_scores[label]:
            score, reason = category_scores[label], "产品分类相符"
        elif filtering:
            score, reason = 0, "筛选结果"
        else:
            continue
        if ident not in candidates or score > candidates[ident][0]:
            candidates[ident] = (score, {
                "id": ident, "filename": filename, "category": label, "reason": reason,
                "linked": ident in linked_ids, "cover": ident == cover_id,
            })
    ranked = sorted(candidates.values(), key=lambda item: (-item[0], item[1]["id"]))
    return {
        "status": "matched" if attached else status,
        "matched": attached[:20],
        "categories": sorted(categories),
        "rows": [item[1] for item in ranked[offset:offset + 16]],
        "total": len(ranked),
        "more": len(ranked) > offset + 16,
    }


def attach_for_build(db, term, image, cover=False):
    if not isinstance(term, str) or not term.strip() or len(term) > 1000:
        raise ValueError("请填写完整关键词，最多 1000 个字。")
    if type(cover) is not bool:
        raise ValueError("首图选项无效。")
    image = int(image)
    with db:
        db.execute("BEGIN IMMEDIATE")
        word = db.execute("SELECT state FROM words WHERE term=?", (term,)).fetchone()
        if word_state(word) != "unmatched":
            raise ValueError("先把这个完整关键词加入词库并设为可用。")
        if not db.execute(
            f"SELECT 1 FROM gallery_images g WHERE g.id=? AND {PRODUCT_ASSET}", (image,)
        ).fetchone():
            raise ValueError("这张图片已不属于可用的产品素材，请重新选图。")
        db.execute("INSERT OR IGNORE INTO gallery_tags VALUES(?,?)", (image, term))
        if cover:
            db.execute(
                """INSERT INTO gallery_covers(term,image) VALUES(?,?)
                   ON CONFLICT(term) DO UPDATE SET image=excluded.image""", (term, image)
            )
    return {"ok": True}


def bulk_photo_selection(db, selection):
    if not isinstance(selection, dict) or set(selection) not in ({"ids"}, {"filters"}):
        raise ValueError("请选择要批量配图的图片范围。")
    sql = f"""SELECT g.id,g.filename,({PRODUCT_ASSET}) AS eligible,
               (SELECT CASE WHEN count(DISTINCT o.category)=1 THEN min(o.category) ELSE '' END
                FROM gallery_origins o WHERE o.image=g.id AND o.kind='产品素材') AS category
               FROM gallery_images g"""
    if "filters" in selection:
        where, args = image_filters(db, checked_gallery_filters(selection["filters"]))
        return db.execute(sql + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY g.id DESC", args).fetchall()
    ids = selection["ids"]
    if not isinstance(ids, list) or not ids or any(type(i) is not int or not 0 < i < 2**63 for i in ids):
        raise ValueError("请先勾选要配图的图片。")
    ids = sorted(set(ids), reverse=True)
    selected = []
    for offset in range(0, len(ids), 500):
        chunk = ids[offset:offset + 500]
        selected.extend(db.execute(sql + " WHERE g.id IN (" + ",".join("?" for _ in chunk) + ") ORDER BY g.id DESC", chunk))
    if len(selected) != len(ids):
        raise ValueError("有图片已移出当前行业，请刷新图库后重新选择。")
    return selected


def bulk_link_revision(selected):
    digest = hashlib.sha256()
    for row in selected:
        digest.update(json.dumps(tuple(row), ensure_ascii=False).encode())
        digest.update(b"\n")
    return digest.hexdigest()


def preview_bulk_links(db, selection, page=1):
    if type(page) is not int or page < 1:
        raise ValueError("图片预览页码无效。")
    selected = bulk_photo_selection(db, selection)
    eligible = [row for row in selected if row["eligible"]]
    categories = {row["category"] for row in eligible}
    stems = {pathlib.PurePath(row["filename"]).stem for row in eligible}
    terms = list(stems) if len(stems) == 1 else []
    if len(categories) == 1:
        terms.extend(category_aliases(next(iter(categories))))
    suggested = []
    for term in dict.fromkeys(terms):
        word = db.execute("SELECT id,term FROM words WHERE term=? AND state<>2", (term,)).fetchone()
        if word:
            suggested.append(dict(word))
    page_size = 12
    pages = (len(eligible) + page_size - 1) // page_size
    page = min(page, max(1, pages))
    start = (page - 1) * page_size
    return dict(total=len(selected), eligible=len(eligible), revision=bulk_link_revision(selected),
                photos=[dict(row) for row in eligible[start:start + page_size]],
                page=page, pages=pages, suggested=suggested)


def apply_bulk_links(db, selection, word_id, revision, excluded=None):
    if type(word_id) is not int or not 0 < word_id < 2**63:
        raise ValueError("请从当前行业词库选择一个完整关键词。")
    excluded = [] if excluded is None else excluded
    if not isinstance(excluded, list) or any(type(i) is not int or not 0 < i < 2**63 for i in excluded):
        raise ValueError("图片选择无效。")
    with db:
        db.execute("BEGIN IMMEDIATE")
        word = db.execute("SELECT term FROM words WHERE id=? AND state<>2", (word_id,)).fetchone()
        if not word:
            raise ValueError("这个关键词已排除或移出词库，请重新选择。")
        selected = bulk_photo_selection(db, selection)
        if revision != bulk_link_revision(selected):
            raise ValueError("图片筛选结果或来源已有变化，请关闭后重新预览。")
        eligible = {row["id"] for row in selected if row["eligible"]}
        excluded = set(excluded)
        if not excluded.issubset(eligible):
            raise ValueError("有图片不在这次配图预览中，请重新选择。")
        included = eligible - excluded
        if not included:
            raise ValueError("请至少选一张可用的产品图。")
        added = db.executemany("INSERT OR IGNORE INTO gallery_tags(image,term) VALUES(?,?)",
                               ((ident, word[0]) for ident in sorted(included))).rowcount
    return dict(term=word[0], added=added, existing=len(included)-added,
                skipped=len(selected)-len(eligible), excluded=len(excluded))


def asset_path(image):
    extension = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "image/gif": "gif"}[
        image["mime"]
    ]
    return f"images/{image['id']:08d}.{extension}"


def pack(db, output, industry, terms=None):
    """One physical file per matched photo. The manifest keeps every input term."""
    db.execute("BEGIN")
    with zipfile.ZipFile(output, "w", allowZip64=True) as z:
        write_pack(db, z, industry, terms)


def write_pack(db, z, industry, terms):
    """Write the photo manifest and originals into an open ZIP."""
    if terms is None:
        terms = (
            r[0]
            for r in db.execute("""SELECT DISTINCT t.term FROM gallery_tags t
                 JOIN words w ON w.term=t.term WHERE w.state<>2 ORDER BY t.term""")
        )
    included = set()
    # Spill large manifests to disk without holding a full industry in RAM.

    with (
        tempfile.TemporaryFile(
            mode="w+", encoding="utf-8-sig", newline=""
        ) as sheet,
        tempfile.TemporaryFile(mode="w+", encoding="utf-8") as manifest,
    ):
        writer = csv.writer(sheet)
        writer.writerow(
            ["行业", "完整关键词", "配图状态", "顺序", "图片相对路径", "原文件名"]
        )
        manifest.write(
            '{"industry":'
            + json.dumps(industry, ensure_ascii=False)
            + ',"keywords":['
        )
        for index, term in enumerate(terms):
            images = matches(db, term)
            paths = []
            for rank, image in enumerate(images, 1):
                path = asset_path(image)
                if image["id"] not in included:
                    content = db.execute(
                        "SELECT original FROM gallery_files WHERE image=?",
                        (image["id"],),
                    ).fetchone()[0]
                    if content:
                        z.writestr(path, content, compress_type=zipfile.ZIP_STORED)
                    else:
                        z.write(external_path(db, image["id"]), path, compress_type=zipfile.ZIP_STORED)
                    included.add(image["id"])
                paths.append(path)
                writer.writerow(
                    [csv_cell(industry), csv_cell(term), "已配图", rank, path, csv_cell(image["filename"])]
                )
            if not paths:
                writer.writerow([csv_cell(industry), csv_cell(term), "未配图", "", "", ""])
            if index:
                manifest.write(",")
            json.dump(
                {
                    "keyword": term,
                    "cover": paths[0] if paths else None,
                    "images": paths,
                },
                manifest,
                ensure_ascii=False,
            )
        manifest.write("]}")
        for name, file in [("配图清单.csv", sheet), ("image-map.json", manifest)]:
            file.flush()
            file.buffer.seek(0)
            with z.open(name, "w", force_zip64=True) as dst:
                shutil.copyfileobj(file.buffer, dst)

def external_path(db, ident):
    row=db.execute("SELECT digest FROM gallery_external WHERE image=?",(ident,)).fetchone()
    if not row or not __import__("re").fullmatch("[a-f0-9]{64}",row[0]):
        raise ValueError("找不到图片原件。")
    return pathlib.Path(db.execute("PRAGMA database_list").fetchone()[2]).parent/"media"/row[0]

def filters(db):
    counts = rows(db, """SELECT coalesce(o.category,'待细分') AS name, count(DISTINCT g.id) AS count
        FROM gallery_images g LEFT JOIN gallery_origins o ON o.image=g.id
        GROUP BY coalesce(o.category,'待细分') ORDER BY count DESC,name""")
    result = {key: [r[0] for r in db.execute("SELECT DISTINCT " + key + " FROM gallery_origins ORDER BY 1")] for key in ("kind","role")}
    return dict(result, category=sorted(row["name"] for row in counts), categories=counts,
                industry_total=db.execute("SELECT count(*) FROM gallery_images").fetchone()[0],
                peers=db.execute("SELECT count(DISTINCT image) FROM gallery_origins WHERE kind='同行参考'").fetchone()[0])
