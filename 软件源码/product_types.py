"""Industry-owned product type rules. Classification never changes keyword identity."""

import hashlib
import json
import re
import struct
import unicodedata
from collections import Counter, defaultdict

PENDING = {0: "待归类", -1: "待确认"}
PACKAGING = [
    (
        "袋类",
        "bag|bags|pouch|pouches|baggie|baggies|poly mailer|poly mailers|bubble mailer|bubble mailers|polymailer|polymailers|袋",
    ),
    ("盒类 / 箱类", "box|boxes|carton|cartons|盒|纸箱|纸板箱|包装箱"),
    ("信封类", "envelope|envelopes|信封"),
    ("标签类", "label|labels|sticker|stickers|标签|贴纸"),
    ("胶带类", "tape|tapes|胶带"),
    ("薄膜类", "film|films|shrink wrap|stretch wrap|薄膜|缠绕膜|收缩膜"),
]
BATTERIES = [
    (
        "笔记本电池",
        "laptop battery|laptop batteries|notebook battery|notebook batteries|笔记本电池|笔记本电脑电池",
    ),
    ("电芯", "battery cell|battery cells|18650|21700|电芯"),
    ("充电器", "charger|chargers|充电器"),
    ("电池组", "battery pack|battery packs|电池组"),
]
SOURCE_GROUPS = (
    "邮政与物流",
    "包装服务、采购与品牌",
    "包装设备与加工",
    "环保包装与回收",
    "工业与功能包装",
    "填充与包裹",
    "气柱包装",
    "冷链包装",
    "鞋包定型",
    "饮水与储水",
)
BOX_EXCEPTIONS = re.compile(
    r"\b(?:p\.?\s*o\.?|post office|box office)\s+box(?:es)?\b|\bbox (?:office|truck)|\bxbox\b|邮政信箱"
)
PHRASE_RUN = re.compile(r"[^\W_]+(?:[\s-]+[^\W_]+)+")
HAN_RUN = re.compile(r"[\u3400-\u9fff]{2,}")
ASCII_WORD = re.compile(r"[a-z0-9]+")
PHRASE_EDGES = set(
    "a an and are as at be by can do for from how in is it me my of on or our the to was what when where which who will with your".split()
)
SUGGESTION_SAMPLE = 30000


def clean(text):
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def all_types(db):
    return [
        dict(id=row[0], name=row[1], phrases=json.loads(row[2]))
        for row in db.execute("SELECT id,name,phrases FROM product_types ORDER BY id")
    ]


def compile_types(groups):
    compiled = []
    for group in groups:
        alternatives = []
        for phrase in group["phrases"]:
            phrase = clean(phrase)
            escaped = re.escape(phrase).replace(r"\ ", r"[\s-]+")
            if phrase[:1].isascii() and phrase[:1].isalnum():
                escaped = r"(?<![a-z0-9])" + escaped
            if phrase[-1:].isascii() and phrase[-1:].isalnum():
                escaped += r"(?![a-z0-9])"
            alternatives.append(escaped)
        if alternatives:
            compiled.append(
                (group["id"], group["name"], re.compile("|".join(alternatives)))
            )
    return compiled


def review_key(compiled, text, manual):
    if manual:
        return "manual"
    matched = []
    for ident, name, pattern in compiled:
        if pattern.search(text):
            if name == "盒类 / 箱类" and BOX_EXCEPTIONS.search(text):
                return "box"
            matched.append(str(ident))
    return "types-" + ",".join(matched) if len(matched) > 1 else "other"


def valid_review_key(key):
    return bool(re.fullmatch(r"(?:manual|box|other|types-[1-9]\d*(?:,[1-9]\d*)+)", key, re.ASCII))


def prepare_review_filter(db, q):
    if q.get("type_review"):
        compiled = compile_types(all_types(db))
        db.create_function(
            "type_review_key", 2,
            lambda text, manual: review_key(compiled, text, manual),
            deterministic=True,
        )


def review_groups(db):
    compiled = compile_types(all_types(db))
    items = {}
    total = 0
    for row in db.execute(
        "SELECT term,norm,type_manual FROM words WHERE product_type=-1 AND state<>2 ORDER BY id DESC"
    ):
        key = review_key(compiled, row[1], row[2])
        item = items.setdefault(key, {"key": key, "count": 0, "examples": []})
        item["count"] += 1
        total += 1
        if len(item["examples"]) < 3:
            item["examples"].append(row[0])
    return {"items": sorted(items.values(), key=lambda item: -item["count"]), "total": total}


def type_candidates(groups):
    by_prefix = defaultdict(set)
    always_check = set()
    needs_non_ascii = set()
    for group in groups:
        for phrase in group["phrases"]:
            phrase = clean(phrase)
            head = ASCII_WORD.match(phrase)
            if head:
                # The corresponding rule requires a boundary before this first token.
                by_prefix[head.group()].add(group["id"])
            elif phrase.isascii():
                always_check.add(group["id"])
            else:
                needs_non_ascii.add(group["id"])

    def candidates(text):
        eligible = always_check.copy()
        if not text.isascii():
            eligible.update(needs_non_ascii)
        for token in ASCII_WORD.findall(text):
            matches = by_prefix.get(token)
            if matches:
                eligible.update(matches)
        return eligible

    return candidates


def classifier(groups, explain=False):
    compiled = compile_types(groups)
    by_source = {g["name"]: g["id"] for g in groups}
    candidates = type_candidates(groups)

    def which(text, category):
        matched = None
        eligible = candidates(text) if compiled else ()
        for ident, name, pattern in compiled:
            if ident not in eligible:
                continue
            hit = pattern.search(text)
            if not hit:
                continue
            if name == "盒类 / 箱类" and BOX_EXCEPTIONS.search(text):
                return (-1, "词中有可能与产品箱盒无关的含义") if explain else -1
            if matched:
                if explain:
                    key = review_key(compiled, text, False)
                    if key == "box":
                        return -1, "词中有可能与产品箱盒无关的含义"
                    ids = set(key.removeprefix("types-").split(","))
                    names = "、".join(f"「{label}」" for ident, label, _ in compiled if str(ident) in ids)
                    return -1, "同时命中" + names
                return -1
            matched = (ident, name, hit)
        if matched:
            return (matched[0], f"命中识别词「{matched[2].group()}」") if explain else matched[0]
        source = by_source.get(category, 0)
        if not explain:
            return source
        return source, f"沿用原表分类「{category}」" if source else "未命中识别词或同名原表分类"

    return which


def matcher(db):
    return classifier(all_types(db))


def word_reason(db, word):
    if word["type_manual"]:
        return "手动标为待确认" if word["product_type"] == -1 else "手动归类"
    return classifier(all_types(db), explain=True)(word["norm"], word["category"])[1]


def classify(db, after=0):
    classify_one = matcher(db)
    db.create_function("product_classify", 2, classify_one, deterministic=True)
    db.execute(
        "UPDATE words SET product_type=product_classify(norm,category) WHERE id>? AND type_manual=0",
        (after,),
    )


def setup(db, industry):
    with db:
        db.execute("BEGIN IMMEDIATE")
        db.execute(
            "CREATE TABLE IF NOT EXISTS product_types(id INTEGER PRIMARY KEY,name TEXT UNIQUE NOT NULL,phrases TEXT NOT NULL)"
        )
        columns = {c[1] for c in db.execute("PRAGMA table_info(words)")}
        if "product_type" not in columns:
            db.execute(
                "ALTER TABLE words ADD COLUMN product_type INTEGER NOT NULL DEFAULT 0"
            )
            db.execute(
                "ALTER TABLE words ADD COLUMN type_manual INTEGER NOT NULL DEFAULT 0"
            )
            rules = (
                PACKAGING
                if industry in ("包装袋", "包装")
                else BATTERIES
                if industry in ("电池", "笔记本电池")
                else []
            )
            db.executemany(
                "INSERT INTO product_types(name,phrases) VALUES(?,?)",
                (
                    (name, json.dumps(values.split("|"), ensure_ascii=False))
                    for name, values in rules
                ),
            )
        if not db.execute(
            "SELECT 1 FROM settings WHERE k='source_type_defaults_v1'"
        ).fetchone():
            if industry in ("包装袋", "包装"):
                db.executemany(
                    "INSERT OR IGNORE INTO product_types(name,phrases) VALUES(?,'[]')",
                    ((n,) for n in SOURCE_GROUPS),
                )
            classify(db)
            db.execute("INSERT INTO settings VALUES('source_type_defaults_v1','1')")
        db.execute(
            "CREATE INDEX IF NOT EXISTS words_product_type ON words(product_type,id)"
        )


def overview(db):
    counts = dict(
        db.execute("SELECT product_type,count(*) FROM words GROUP BY product_type")
    )
    groups = all_types(db) + [
        {"id": i, "name": n, "phrases": []} for i, n in PENDING.items()
    ]
    return [dict(g, count=counts.get(g["id"], 0)) for g in groups]


def recurring_phrases(text):
    result = set()
    for run in PHRASE_RUN.finditer(text):
        tokens = re.split(r"[\s-]+", run.group())
        for size in (2, 3, 4):
            for i in range(len(tokens) - size + 1):
                parts = tokens[i:i + size]
                if parts[0] in PHRASE_EDGES or parts[-1] in PHRASE_EDGES:
                    continue
                phrase = " ".join(parts)
                if len(phrase) <= 100 and any(c.isalpha() for c in phrase):
                    result.add(phrase)
    for run in HAN_RUN.finditer(text):
        value = run.group()
        for size in (2, 3, 4, 5):
            result.update(value[i:i + size] for i in range(len(value) - size + 1))
    return result


def suggest_phrases(db, q):
    from queries import word_filter

    filters = dict(q=q.get("q", ""), category=q.get("category", ""), ptype=0)
    where, args = word_filter(filters)
    pending = db.execute(
        "SELECT w.term,w.norm FROM words w" + where + " ORDER BY w.id DESC LIMIT ?",
        (*args, SUGGESTION_SAMPLE + 1),
    ).fetchall()
    bounded = len(pending) > SUGGESTION_SAMPLE
    pending = pending[:SUGGESTION_SAMPLE]
    counts = Counter()
    for word in pending:
        counts.update(recurring_phrases(word["norm"]))
    groups = all_types(db)
    existing = {clean(phrase) for group in groups for phrase in group["phrases"]}
    phrases = sorted(
        (phrase for phrase, count in counts.items() if count >= 2 and phrase not in existing),
        key=lambda phrase: (-counts[phrase], -len(phrase), phrase),
    )
    selected = []
    for phrase in phrases:
        overlap = any(counts[alt] == counts[phrase] and
                      (alt.startswith(phrase + " ") or alt.endswith(" " + phrase)
                       or bool(HAN_RUN.fullmatch(alt) and phrase in alt)) for alt in selected)
        if not overlap:
            selected.append(phrase)
        if len(selected) >= 16:
            break
    if not selected:
        return dict(items=[], sampled=len(pending), bounded=bounded)
    keys = set(selected)
    examples = defaultdict(list)
    for word in pending:
        for phrase in keys.intersection(recurring_phrases(word["norm"])):
            if len(examples[phrase]) < 3:
                examples[phrase].append(word["term"])
    sources = defaultdict(Counter)
    classified_where, classified_args = word_filter({**filters, "ptype": ""})
    classified = db.execute(
        "SELECT w.norm,w.product_type FROM words w" + classified_where +
        " AND w.product_type>0 ORDER BY w.id DESC LIMIT ?", (*classified_args, SUGGESTION_SAMPLE),
    ).fetchall()
    for word in classified:
        for phrase in keys.intersection(recurring_phrases(word["norm"])):
            sources[phrase][word["product_type"]] += 1
    names = {group["id"]: group["name"] for group in groups}
    items = []
    for phrase in selected:
        evidence = [(n, hits) for n, hits in sources[phrase].most_common() if n in names]
        total = sum(hits for _, hits in evidence)
        suggested = None
        if evidence and evidence[0][1] >= 4 and evidence[0][1] * 5 >= total * 4 and evidence[0][1] * 2 >= counts[phrase]:
            group, hits = evidence[0]
            suggested = dict(id=group, label=names[group], hits=hits, total=total)
        items.append(dict(phrase=phrase, count=counts[phrase], examples=examples[phrase], suggested=suggested))
    return dict(items=items, sampled=len(pending), bounded=bounded)


def proposed_types(db, p):
    name = str(p.get("name", "")).strip()
    phrases = list(
        dict.fromkeys(clean(s) for s in p.get("phrases", "").splitlines() if s.strip())
    )
    if (
        not name
        or len(name) > 60
        or name in PENDING.values()
        or len(phrases) > 150
        or any(len(s) > 100 for s in phrases)
    ):
        raise ValueError(
            "类型名称最多 60 字，每行一个识别词，每类最多 150 行，每行最多 100 字。"
        )
    current = all_types(db)
    ident = int(p.get("id") or 0)
    if any(item["name"] == name and item["id"] != ident for item in current):
        raise ValueError("这个产品类型已存在，可以编辑它的识别词。")
    if ident:
        if not any(item["id"] == ident for item in current):
            raise ValueError("没有找到这个产品类型。")
    rule = dict(id=ident or max((item["id"] for item in current), default=0) + 1, name=name, phrases=phrases)
    next_types = [rule if item["id"] == ident else item for item in current]
    if not ident:
        next_types.append(rule)
    return current, next_types, rule


def classification_digest(db, *parts):
    identity = db.execute("PRAGMA database_list").fetchone()[2]
    return hashlib.blake2b(repr((identity, *parts)).encode(), digest_size=16)


def rule_plan(db, current, next_types, rule):
    classify_one = classifier(next_types)

    def changed_type(text, category, old_type):
        new_type = classify_one(text, category)
        return new_type if new_type != old_type else None

    db.create_function("rule_type_change", 3, changed_type, deterministic=True)
    db.execute("""CREATE TEMP TABLE IF NOT EXISTS type_rule_plan(
               id INTEGER PRIMARY KEY,old_type INTEGER,next_type INTEGER NOT NULL)""")
    db.execute("DELETE FROM type_rule_plan")
    db.execute("""INSERT OR IGNORE INTO type_rule_plan SELECT id,product_type,rule_type_change(norm,category,product_type)
                  FROM words WHERE type_manual=0""")
    digest = classification_digest(db, current, next_types)
    count, entering, leaving, review = 0, 0, 0, 0
    for row in db.execute("SELECT id,old_type,next_type FROM type_rule_plan ORDER BY id"):
        _, old, new = row
        digest.update(struct.pack(">qqq", *row))
        count += 1
        entering += new == rule["id"]
        leaving += old == rule["id"]
        review += new == -1
    return dict(changed=count, entering=entering, leaving=leaving, review=review, preview=digest.hexdigest())


def preview_rule(db, p):
    db.execute("BEGIN")
    current, next_types, rule = proposed_types(db, p)
    result = rule_plan(db, current, next_types, rule)
    labels = {item["id"]: item["name"] for item in current}
    new_labels = {item["id"]: item["name"] for item in next_types}
    explain = classifier(next_types, explain=True)
    sample = []
    for rec in db.execute(
        """SELECT w.term,w.norm,w.category,p.old_type,p.next_type FROM type_rule_plan p
           JOIN words w ON w.id=p.id ORDER BY (p.next_type=-1) DESC,p.id DESC LIMIT 8""",
    ):
        sample.append(dict(term=rec["term"], before=labels.get(rec["old_type"], PENDING.get(rec["old_type"], "待归类")),
                           after=new_labels.get(rec["next_type"], PENDING.get(rec["next_type"], "待归类")),
                           reason=explain(rec["norm"], rec["category"])[1]))
    return dict(result, manual=db.execute("SELECT count(*) FROM words WHERE type_manual=1").fetchone()[0],
                label=rule["name"], sample=sample)


def save(db, p):
    db.execute("BEGIN IMMEDIATE")
    current, next_types, rule = proposed_types(db, p)
    token = p.get("preview")
    plan = None
    if token is not None:
        plan = rule_plan(db, current, next_types, rule)
        if token != plan["preview"]:
            raise ValueError("分类规则或词库已有变化，请重新预览。")
    db.execute(
        """INSERT INTO product_types(id,name,phrases) VALUES(?,?,?)
           ON CONFLICT(id) DO UPDATE SET name=excluded.name,phrases=excluded.phrases""",
        (rule["id"], rule["name"], json.dumps(rule["phrases"], ensure_ascii=False)),
    )
    if plan is None:
        classify(db)
        return {"id": rule["id"]}
    db.execute("""UPDATE words SET product_type=(SELECT next_type FROM type_rule_plan WHERE id=words.id)
                  WHERE id IN (SELECT id FROM type_rule_plan)""")
    return {"id": rule["id"], "changed": plan["changed"]}


def assign(db, p):
    wid = int(p["id"])
    db.execute("BEGIN IMMEDIATE")
    w = db.execute("SELECT norm,category FROM words WHERE id=?", (wid,)).fetchone()
    if not w:
        raise ValueError("没有找到这个关键词。")
    automatic = str(p["type"]) == "auto"
    group = matcher(db)(w[0], w[1]) if automatic else int(p["type"])
    check_type(db, group)
    db.execute(
        "UPDATE words SET product_type=?,type_manual=? WHERE id=?",
        (group, int(not automatic), wid),
    )
    return {"type": group}


def check_type(db, group):
    if group in PENDING:
        return PENDING[group]
    found = db.execute("SELECT name FROM product_types WHERE id=?", (group,)).fetchone()
    if not found:
        raise ValueError("当前行业中没有这个类型。")
    return found[0]


def batch_source(db, p):
    from queries import word_filter

    if p.get("scope") == "selected":
        ids = p.get("ids")
        if not isinstance(ids, list) or not ids or any(type(i) is not int or not 0 < i < 2**63 for i in ids):
            raise ValueError("请先勾选要归类的关键词。")
        db.execute("CREATE TEMP TABLE IF NOT EXISTS batch_type_selected(id INTEGER PRIMARY KEY)")
        db.execute("DELETE FROM batch_type_selected")
        db.executemany("INSERT OR IGNORE INTO batch_type_selected VALUES(?)", ((i,) for i in ids))
        return "words w JOIN batch_type_selected pick ON pick.id=w.id", "", []
    if p.get("scope") != "filtered" or not isinstance(p.get("filters"), dict):
        raise ValueError("请选择批量归类的范围。")
    fields = ("q", "state", "ptype", "category", "traffic", "featured", "site", "market",
              "batch", "batch_scope", "mode", "type_review")
    filters = {key:str(p["filters"][key]) for key in fields if p["filters"].get(key) is not None}
    literal = filters.pop("q", "")
    prepare_review_filter(db, filters)
    where, params = word_filter(filters)
    if clean(literal):
        lookup, args = word_filter({"q": literal, "mode": filters.get("mode"), "state": "all"})
        if lookup:
            where += (" AND " if where else " WHERE ") + "(" + lookup[len(" WHERE "):] + " OR w.term=?)"
            params.extend((*args, literal))
    return "words w", where, params


def batch_assign(db, p):
    token = p.get("preview")
    if token is not None and (not isinstance(token, str) or not re.fullmatch(r"[a-f0-9]{32}", token)):
        raise ValueError("请先预览批量归类结果。")
    automatic = p.get("type") == "auto"
    if not automatic:
        group = int(p["type"])
    preserve = p.get("preserve") is True
    manual = int(not automatic)
    db.execute("BEGIN IMMEDIATE" if token else "BEGIN")
    source, where, params = batch_source(db, p)
    if automatic:
        db.create_function("batch_type_classify", 2, matcher(db), deterministic=True)
        expression, target = "batch_type_classify(w.norm,w.category)", []
        label = "恢复自动归类"
    else:
        label = check_type(db, group)
        expression, target = "?", [group]
    db.execute("""CREATE TEMP TABLE IF NOT EXISTS batch_type_plan(
               id INTEGER PRIMARY KEY,old_type INTEGER,old_manual INTEGER,next_type INTEGER)""")
    db.execute("DELETE FROM batch_type_plan")
    db.execute(
        "INSERT INTO batch_type_plan SELECT w.id,w.product_type,w.type_manual,"
        " CASE WHEN ? AND w.type_manual=1 THEN NULL ELSE " + expression + " END FROM " + source + where,
        [preserve, *target, *params],
    )
    total, held = db.execute(
        "SELECT count(*),count(CASE WHEN next_type IS NULL THEN 1 END) FROM batch_type_plan"
    ).fetchone()
    changed = "next_type IS NOT NULL AND (old_type<>next_type OR old_manual<>?)"
    digest = classification_digest(db, p["scope"], p["type"], label, manual, total, held)
    count = 0
    for row in db.execute(
        "SELECT id,old_type,old_manual,next_type FROM batch_type_plan WHERE " + changed + " ORDER BY id",
        (manual,),
    ):
        digest.update(struct.pack(">qqqq", *row))
        count += 1
    signature = digest.hexdigest()
    if token:
        if token != signature:
            raise ValueError("相关关键词已有变化，请重新预览后再归类。")
        db.execute(
            """UPDATE words SET product_type=(SELECT next_type FROM batch_type_plan WHERE id=words.id),type_manual=?
               WHERE id IN (SELECT id FROM batch_type_plan WHERE """ + changed + ")",
            (manual, manual),
        )
        return {"changed": count}
    sample = [dict(row) for row in db.execute(
        """SELECT w.term,p.old_type,p.next_type FROM batch_type_plan p JOIN words w ON w.id=p.id
           WHERE """ + changed + " ORDER BY p.id DESC LIMIT 8", (manual,),
    )]
    return dict(total=total, held=held, changed=count, label=label, sample=sample, preview=signature)
