import product_types
from current_metrics import observation_scope, representative_join, summaries
from sitebook import add_site, query_sites, site_coverage
import csv, json, re, zlib
from library import norm, domain, web, rows, evaluate, rule_match

STATES = ("待筛选", "保留", "排除")


def chinese_text(value):
    return any("\u3400" <= c <= "\u9fff" for c in value)


def fulltext_query(value):
    tokens = re.findall(r"[^\W_]+", value, re.UNICODE)
    return " AND ".join('"' + token + '"*' for token in tokens)


def word_filter(q, search_plan=None, *, observation_alias=None):
    search = norm(q.get("q", ""))
    state = q.get("state", "active")
    site = q.get("site", "")
    scoped = q.get("batch") or q.get("market")
    clauses = []
    args = []
    word_id = observation_alias + ".word" if observation_alias else (
        "search_terms.rowid" if search_plan == "index_order" else "w.id"
    )
    if state == "active":
        clauses.append("w.state<>2")
    elif state in ["0", "1", "2"]:
        clauses.append("w.state=?")
        args.append(int(state))
    if search:
        if chinese_text(search):
            translation = (
                "EXISTS (SELECT 1 FROM profiles WHERE word=w.id AND instr(translation,?)>0)"
                if search_plan == "single_word"
                else "w.id IN (SELECT word FROM profiles WHERE instr(translation,?)>0)"
            )
            clauses.append("(instr(w.norm,?)>0 OR " + translation + ")")
            args.extend((search, search))
        elif not re.search(r"\w", search) or q.get("mode") == "contains":
            clauses.append("instr(w.norm,?)>0")
            args.append(search)
        else:
            match = fulltext_query(search)
            if match:
                if search_plan == "index_order":
                    clauses.append("search_terms MATCH ?")
                elif search_plan == "single_word":
                    clauses.append("EXISTS (SELECT 1 FROM search_terms WHERE rowid=w.id AND search_terms MATCH ?)")
                else:
                    clauses.append("w.id IN (SELECT rowid FROM search_terms WHERE search_terms MATCH ?)")
                args.append(match)
    if site and not scoped:
        clauses.append(
            "w.id IN (SELECT word FROM obs WHERE site=? UNION SELECT word FROM refs WHERE site=?)"
        )
        args.extend([int(site)] * 2)
        if search_plan == "index_order":
            clauses.append("""search_terms.rowid <= max(
                coalesce((SELECT max(word) FROM obs WHERE site=?),0),
                coalesce((SELECT max(word) FROM refs WHERE site=?),0))""")
            args.extend([int(site)] * 2)
    if scoped:
        scope, scope_args = observation_scope(q, observation_alias or "o", with_traffic=True)
        scope_sql = " AND ".join(scope)
        if observation_alias:
            clauses.extend(scope)
        elif search_plan in ("index_order", "single_word"):
            clauses.append("EXISTS (SELECT 1 FROM obs o WHERE o.word=w.id AND " + scope_sql + ")")
        else:
            clauses.append("w.id IN (SELECT o.word FROM obs o WHERE " + scope_sql + ")")
        args.extend(scope_args)
        batch_scope = q.get("batch_scope")
        if q.get("batch") and batch_scope in ("new", "existing"):
            comparison = ">" if batch_scope == "new" else "<="
            clauses.append(word_id + " " + comparison + " (SELECT prior_word_id FROM batches WHERE id=?)")
            args.append(int(q["batch"]))
        if search_plan == "index_order":
            clauses.append("search_terms.rowid <= coalesce((SELECT max(o.word) FROM obs o WHERE " + scope_sql + "),0)")
            args.extend(scope_args)
    if q.get("featured") == "1":
        clauses.append("w.id IN (SELECT word FROM profiles WHERE featured='是')")
    if q.get("ptype") not in ("", None):
        clauses.append("w.product_type=?")
        args.append(int(q["ptype"]))
    if q.get("type_review"):
        clauses.extend(("w.product_type=-1", "type_review_key(w.norm,w.type_manual)=?"))
        args.append(q["type_review"])
    if q.get("category"):
        clauses.append("w.category=?")
        args.append(q["category"])
    if q.get("traffic") == "1" and not scoped:
        if site:
            clauses.append(
                "EXISTS (SELECT 1 FROM obs t WHERE t.word=w.id AND t.site=? AND t.traffic_num>0)"
            )
            args.append(int(site))
        else:
            clauses.append(
                "EXISTS (SELECT 1 FROM obs t WHERE t.word=w.id AND t.traffic_num>0)"
            )
    if q.get("after"):
        clauses.append(word_id + "<?")
        args.append(int(q["after"]))
    return (" WHERE " + " AND ".join(clauses) if clauses else ""), args


def word_page_filter(q, use_index_order=True, single_word=False):
    """Read broad prefix matches in descending ID order without sorting all hits."""
    search = norm(q.get("q", ""))
    if (
        use_index_order and not single_word and search and q.get("mode") != "contains"
        and not chinese_text(search) and fulltext_query(search)
        and (q.get("batch") or (
            q.get("state", "active") not in ("0", "1", "2")
            and q.get("ptype") in (None, "")
            and not any(q.get(key) for key in ("featured", "category", "type_name", "type_review"))
        ))
    ):
        where, args = word_filter(q, "index_order")
        return "search_terms CROSS JOIN words w ON w.id=search_terms.rowid", "search_terms.rowid", where, args
    where, args = word_filter(q, "single_word" if single_word else None)
    return "words w", "w.id", where, args


def matching_names(db, query):
    source, order, where, params = word_page_filter({"q": query})
    exact = rows(db, "SELECT id,term FROM words WHERE term=? AND state<>2", (query,))
    matches = rows(
        db,
        "SELECT w.id,w.term FROM " + source
        + where
        + " AND w.term<>? ORDER BY " + order + " DESC LIMIT ?",
        [*params, query, 8 - len(exact)],
    )
    return exact + matches


def list_words(db, q):
    product_types.prepare_review_filter(db, q)
    scoped = q.get("batch") or q.get("market")
    source, order, wh, args = word_page_filter(q)
    search = norm(q.get("q", ""))
    select = """SELECT w.id,w.term,w.category,w.product_type,w.state,w.reason,w.notes,
        (SELECT translation FROM profiles WHERE word=w.id) AS translation,
        cur.traffic,cur.dr,cur.url,cur.domain,cur.market,cur.sort_day FROM """
    metric_join, metric_args = representative_join(q)
    literal = q.get("q", "")
    exact = []
    if search and not q.get("after"):
        # The literal term already satisfies the text search. Apply the other
        # filters without expanding the prefix query a second time.
        exact_where, exact_args = word_filter(dict(q, q=""), "single_word" if scoped else None)
        exact = rows(db, select + "words w" + metric_join + exact_where +
            (" AND " if exact_where else " WHERE ") + "w.term=?", metric_args + exact_args + [literal])
    if search:
        wh += (" AND " if wh else " WHERE ") + "w.term<>?"
        args.append(literal)
    limit = 50 - len(exact)
    others = []
    if chinese_text(search) and not scoped and not any(q.get(key) for key in ("site", "category", "featured")):
        upper = int(q.get("after") or db.execute("SELECT coalesce(max(id),0)+1 FROM words").fetchone()[0])
        lower = upper - 100_000
        if lower > 0:
            # Prefer a bounded recent range for common Chinese terms. Search
            # older words with the set-based query when that range has too few hits.
            recent_where, recent_args = word_filter(q, "single_word")
            others = rows(db, select + "words w" + metric_join + recent_where +
                " AND w.term<>? AND w.id>=? ORDER BY w.id DESC LIMIT ?",
                metric_args + recent_args + [literal, lower, limit + 1])
            wh += " AND w.id<?"
            args.append(lower)
    remaining = limit + 1 - len(others)
    if remaining and scoped and order == "w.id":
        scoped_where, scoped_args = word_filter(q, "single_word", observation_alias="b")
        if search:
            scoped_where += " AND w.term<>?"
            scoped_args.append(literal)
        # Read one page of distinct terms before joining metrics.
        scope_index = "obs_batch_word" if q.get("batch") else "obs_market_word"
        scoped_page = (
            "SELECT b.word FROM obs b INDEXED BY " + scope_index + " CROSS JOIN words w ON w.id=b.word"
            + scoped_where + " GROUP BY b.word ORDER BY b.word DESC LIMIT ?"
        )
        others += rows(db, select + "words w" + metric_join + " WHERE w.id IN (" + scoped_page +
                       ") ORDER BY w.id DESC", metric_args + scoped_args + [remaining])
    elif remaining:
        others += rows(db, select + source + metric_join + wh + " ORDER BY " + order + " DESC LIMIT ?",
            metric_args + args + [remaining])
    more = len(others) > limit
    result = exact + others[:limit]
    if result:
        ids = [v["id"] for v in result]
        marks = ",".join("?" * len(ids))
        if scoped:
            scope, params = observation_scope(q, "o", with_traffic=True)
            sql = ("SELECT o.word,count(DISTINCT o.site) FROM obs o WHERE o.word IN (" + marks +
                   ") AND " + " AND ".join(scope) + " GROUP BY o.word")
            scope_args = ids + params
        else:
            sql = ("SELECT word,count(*) FROM (SELECT word,site FROM refs WHERE word IN (" + marks +
                   ") AND site IS NOT NULL UNION SELECT word,site FROM obs WHERE word IN (" + marks +
                   ") AND site IS NOT NULL) GROUP BY word")
            scope_args = ids + ids
        source_counts = {
            r[0]: r[1] for r in db.execute(sql, scope_args)
        }
        for r in result:
            r["sites"] = source_counts.get(r["id"], 0)
    return {"rows": result, "more": more}


def detail(db, q):
    wid = int(q["id"])
    w = db.execute("SELECT * FROM words WHERE id=?", (wid,)).fetchone()
    if not w:
        raise ValueError("未找到这个关键词。")
    after = int(q.get("after") or 0)
    batch_id = int(q.get("batch") or 0)
    batch = None
    if batch_id:
        item = db.execute("SELECT id,filename FROM batches WHERE id=?", (batch_id,)).fetchone()
        if not item:
            raise ValueError("找不到这次导入批次。")
        batch = dict(item)
    scoped = batch or q.get("market")
    scope, params = observation_scope(q, "o", with_traffic=bool(q.get("market"))) if scoped else ([], [])
    conditions = " AND ".join(["o.word=?", "(?=0 OR o.id<?)", *scope])
    obs = rows(
        db,
        """SELECT o.id,o.batch,s.domain,s.url AS site_url,p.url,o.market,o.report_date,o.traffic,o.dr,o.volume,o.position,b.filename,o.rownum FROM obs o
 LEFT JOIN sites s ON s.id=o.site LEFT JOIN pages p ON p.id=o.page JOIN batches b ON b.id=o.batch WHERE """
        + conditions + " ORDER BY o.id DESC LIMIT 101",
        (wid, after, after, *params),
    )
    for o in obs[:100]:
        raw = db.execute(
            "SELECT a.headers,e.body FROM extras e JOIN archived a ON a.batch=e.batch WHERE e.batch=? AND e.rownum=?",
            (o["batch"], o["rownum"]),
        ).fetchone()
        if raw:
            o["raw"] = [
                (h, v)
                for h, v in zip(json.loads(raw[0]), json.loads(zlib.decompress(raw[1])))
                if v not in ("", None)
            ]
    profile = db.execute(
        "SELECT translation,subtype,featured FROM profiles WHERE word=?", (wid,)
    ).fetchone()
    return {
        "word": {**dict(w), **(dict(profile) if profile else {})},
        "typeReason": product_types.word_reason(db, w),
        "rows": obs[:100],
        "batch": batch,
        "summaries": [] if batch else summaries(db, wid, q if scoped else None),
        "more": len(obs) > 100,
        "refs": [] if scoped else rows(
            db,
            "SELECT r.url,s.name FROM refs r LEFT JOIN sites s ON s.id=r.site WHERE word=?",
            (wid,),
        ),
    }


def stats(db):
    counts = [0, 0, 0]
    for r in db.execute("SELECT state,count(*) FROM words GROUP BY state"):
        counts[r[0]] = r[1]
    b = db.execute("SELECT count(*),ifnull(sum(written),0) FROM batches").fetchone()
    return {
        "words": sum(counts),
        "pending": counts[0],
        "keep": counts[1],
        "excluded": counts[2],
        "sites": db.execute("SELECT count(*) FROM sites").fetchone()[0],
        "files": b[0],
        "observations": b[1],
    }


def sites(db, q):
    result = [dict(r) for r in query_sites(db, q)]
    coverage, keyword_batch = site_coverage(db, q)
    return {"rows": result[:50], "more": len(result) > 50, "coverage": coverage, "keyword_batch": keyword_batch}


def site_detail(db, q):
    r = db.execute("SELECT * FROM sites WHERE id=?", (int(q["id"]),)).fetchone()
    if not r:
        raise ValueError("同行不存在。")
    d = dict(r)
    channel = db.execute(
        "SELECT mask,inferred FROM site_channels WHERE site=?", (d["id"],)
    ).fetchone()
    d["audience"] = channel[0] if channel else 0
    d["audience_inferred"] = bool(channel and channel[1])
    scope, args = word_filter({"site": d["id"], "batch": q.get("batch")})
    d["keyword_count"] = db.execute("SELECT count(*) FROM words w" + scope, args).fetchone()[0]
    d["evidence"] = json.loads(d["evidence"])
    d["queries"] = json.loads(d["queries"])
    return d


def update_words(db, p):
    ids = p.get("ids") or []
    state = int(p.get("state", 0))
    if state not in (0, 1, 2) or not isinstance(ids, list) or not ids:
        raise ValueError("请选择关键词和状态。")
    ids = list(dict.fromkeys(int(n) for n in ids))
    if any(n < 1 or n >= 2**63 for n in ids):
        raise ValueError("关键词编号无效。")
    changed = 0
    for offset in range(0, len(ids), 400):
        chunk = ids[offset : offset + 400]
        changed += db.execute(
            "UPDATE words SET state=?,manual=1,reason='手动标记' WHERE id IN ("
            + ",".join("?" for _ in chunk)
            + ")",
            [state, *chunk],
        ).rowcount
    return {"count": changed}


def add_word(db, p):
    term = p.get("term", "")
    key = norm(term)
    if not key or len(term) > 1000:
        raise ValueError("请填写关键词，最多 1000 个字符。")
    old = db.execute("SELECT id FROM words WHERE term=?", (term,)).fetchone()
    url = web(p.get("url", ""))
    d = domain(url)
    if p.get("url", "").strip() and not d:
        raise ValueError("来源网址无效。")
    site = None
    if d:
        site = add_site(db, {"url": url})["id"]
    if old:
        if url:
            db.execute("INSERT OR IGNORE INTO refs VALUES(?,?,?)", (old[0], site, url))
        return {"id": old[0], "duplicate": True}
    rules = [r[0] for r in db.execute("SELECT phrase FROM rules ORDER BY id")]
    reason = evaluate(key, rules)
    wid = db.execute(
        "INSERT INTO words(norm,term,category,state,reason,notes) VALUES(?,?,?,?,?,?)",
        (
            key,
            term,
            p.get("category", "").strip(),
            2 if reason else 0,
            reason,
            p.get("notes", "").strip(),
        ),
    ).lastrowid
    if url:
        db.execute("INSERT INTO refs VALUES(?,?,?)", (wid, site, url))
    product_types.classify(db, wid - 1)
    return {"id": wid, "duplicate": False}


def rule_preview(db, phrase):
    phrase = norm(phrase)
    if not phrase or len(phrase) > 160:
        raise ValueError("请填写明确的排除词，最多 160 字。")
    db.create_function(
        "rulehit", 1, lambda s: int(rule_match(s, phrase)), deterministic=True
    )
    where = (
        " FROM words WHERE manual=0 AND state<>2 AND instr(norm,?)>0 AND rulehit(norm)"
    )
    total = db.execute("SELECT count(*)" + where, (phrase,)).fetchone()[0]
    return {
        "phrase": phrase,
        "count": total,
        "examples": [
            r[0] for r in db.execute("SELECT term" + where + " LIMIT 8", (phrase,))
        ],
    }


def apply_rule(db, p):
    v = rule_preview(db, p["phrase"])
    phrase = v["phrase"]
    if v["count"] != int(p["count"]):
        raise ValueError("匹配数量发生了变化，请再次预览。")
    db.execute("INSERT OR IGNORE INTO rules(phrase) VALUES(?)", (phrase,))
    db.execute(
        "UPDATE words SET state=2,reason=? WHERE manual=0 AND state<>2 AND instr(norm,?)>0 AND rulehit(norm)",
        (phrase, phrase),
    )
    return v


def remove_rule(db, p):
    r = db.execute("SELECT phrase FROM rules WHERE id=?", (int(p["id"]),)).fetchone()
    if not r:
        raise ValueError("规则不存在。")
    db.execute("DELETE FROM rules WHERE id=?", (int(p["id"]),))
    rest = [v[0] for v in db.execute("SELECT phrase FROM rules ORDER BY id")]
    db.create_function("replacement", 1, lambda k: evaluate(k, rest))
    db.execute(
        """UPDATE words SET
  state=CASE WHEN replacement(norm)<>'' THEN 2 WHEN id IN (SELECT word FROM profiles WHERE featured='是') THEN 1 ELSE 0 END,
  reason=CASE WHEN replacement(norm)<>'' THEN replacement(norm) WHEN id IN (SELECT word FROM profiles WHERE featured='是') THEN '原表包装袋精选' ELSE '' END
  WHERE manual=0 AND reason=?""",
        (r[0],),
    )
    return {"ok": True}


def write_csv(db, writer, params):
    writer = csv.writer(writer)
    product_types.prepare_review_filter(db, params)
    wh, args = word_filter(params)
    if params.get("kind") == "evidence":
        writer.writerow(
            [
                "关键词",
                "同行域名",
                "同行官网",
                "排名网址",
                "市场",
                "报告日期",
                "流量（原表）",
                "DR（原表）",
                "搜索量（原表）",
                "排名（原表）",
                "导入文件",
                "文件数据行",
                "筛选状态",
            ]
        )
        report = """SELECT w.term,s.domain,s.url,p.url,o.market,o.report_date,o.traffic,o.dr,o.volume,o.position,b.filename,o.rownum,w.state
   FROM obs o JOIN words w ON w.id=o.word LEFT JOIN sites s ON s.id=o.site LEFT JOIN pages p ON p.id=o.page JOIN batches b ON b.id=o.batch"""
        scope, scope_args = observation_scope(params, "o", with_traffic=True)
        if scope:
            wh += (" AND " if wh else " WHERE ") + " AND ".join(scope)
            args.extend(scope_args)
        select = report + wh
    else:
        writer.writerow(
            [
                "关键词",
                "中文翻译",
                "产品类型",
                "一级分类",
                "二级分类",
                "包装袋精选",
                "备注",
                "筛选原因",
                "同行域名",
                "同行官网",
                "市场",
                "报告日期（原表）" if params.get("batch") else "最近记录日期",
                "自然流量",
                "DR",
                "排名网址",
                "状态",
            ]
        )
        current_join, current_args = representative_join(params)
        args = current_args + args
        date = "cur.report_date" if params.get("batch") else "cur.sort_day"
        select = (
            "SELECT w.term,pr.translation,CASE w.product_type WHEN 0 THEN '待归类' WHEN -1 THEN '待确认' ELSE (SELECT name FROM product_types WHERE id=w.product_type) END,w.category,pr.subtype,pr.featured,w.notes,w.reason,cur.domain,(SELECT url FROM sites WHERE id=cur.site),cur.market,"
            + date + ",cur.traffic,cur.dr,cur.url,w.state FROM words w LEFT JOIN profiles pr ON pr.word=w.id"
            + current_join
            + wh
        )
    for r in db.execute(select, args):
        # Keep text literal when opening CSV in common spreadsheet programs.
        data = [
            (
                "'" + x
                if isinstance(x, str) and x.lstrip().startswith(("=", "+", "-", "@"))
                else x
            )
            for x in list(r)[:-1]
        ]
        writer.writerow([*data, STATES[r[-1]]])


def group_state(db, p, apply=False):
    q = {
        k: v
        for k, v in (p.get("filter") or {}).items()
        if k
        in (
            "ptype",
            "state",
            "site",
            "market",
            "q",
            "category",
            "featured",
            "traffic",
            "mode",
            "batch",
            "batch_scope",
            "type_review",
        )
    }
    product_types.prepare_review_filter(db, q)
    wh, args = word_filter(q)
    state = int(p["state"])
    if state not in (0, 1, 2):
        raise ValueError("筛选状态错误。")
    cond = wh + (" AND " if wh else " WHERE ") + "w.state<>?"
    a = [*args, state]
    n = db.execute("SELECT count(*) FROM words w" + cond, a).fetchone()[0]
    if apply:
        if int(p["count"]) != n:
            raise ValueError("筛选结果已发生变化，请重新预览。")
        db.execute(
            "UPDATE words SET state=?,manual=1,reason=? WHERE id IN (SELECT w.id FROM words w"
            + cond
            + ")",
            [state, "手动批量标记", *a],
        )
    return {
        "count": n,
        "examples": [
            r[0]
            for r in db.execute("SELECT w.term FROM words w" + cond + " LIMIT 5", a)
        ]
        if not apply
        else [],
    }
