"""Read the latest known metrics for a single keyword, competitor and market."""

import datetime
import json
import re
import zlib


def report_day(value, fallback):
    value = (value or "").strip()
    if re.match(r"^\d{4}[-/.]\d{1,2}[-/.]\d{1,2}(?:$|[ T])", value):
        try:
            y, m, d = re.split(r"[-/.]", re.split("[ T]", value)[0])
            return datetime.date(int(y), int(m), int(d)).isoformat()
        except ValueError:
            pass
    if re.fullmatch(r"\d{8}", value):
        try:
            return datetime.datetime.strptime(value, "%Y%m%d").date().isoformat()
        except ValueError:
            pass
    return fallback[:10]


def workbook_day(value, date_1904):
    if re.fullmatch(r"[0-9]{4,6}(?:\.\d+)?", value):
        base = datetime.date(1904, 1, 1) if date_1904 else datetime.date(1899, 12, 30)
        return (base + datetime.timedelta(days=int(float(value)))).isoformat()
    return value


def setup(db, choose):
    db.execute("BEGIN IMMEDIATE")
    columns = [r[1] for r in db.execute("PRAGMA table_info(obs)")]
    if "dr" not in columns:
        db.execute("ALTER TABLE obs ADD COLUMN dr TEXT")
        for batch, header in db.execute("SELECT batch,headers FROM archived"):
            index = choose(json.loads(header))["dr"]
            if index >= 0:
                for n, blob in db.execute(
                    "SELECT rownum,body FROM extras WHERE batch=?", (batch,)
                ):
                    raw = json.loads(zlib.decompress(blob))
                    val = (
                        str(raw[index]).strip()
                        if index < len(raw) and raw[index] is not None
                        else ""
                    )
                    if val:
                        db.execute(
                            "UPDATE obs SET dr=? WHERE batch=? AND rownum=?",
                            (val, batch, n),
                        )
    if "sort_day" not in columns:
        db.execute("ALTER TABLE obs ADD COLUMN sort_day TEXT")
        db.create_function("report_day", 2, report_day)
        db.execute(
            """UPDATE obs SET sort_day=report_day(report_date,(SELECT created FROM batches b WHERE b.id=obs.batch))"""
        )
    db.execute(
        "CREATE INDEX IF NOT EXISTS obs_recent ON obs(word,sort_day DESC,id DESC)"
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS obs_source_recent ON obs(word,site,market,sort_day DESC,id DESC)"
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS obs_market_word ON obs(market COLLATE NOCASE,word)"
    )
    db.commit()


def markets(db):
    # Seek to the next distinct market instead of scanning every source row.
    return [
        row[0] for row in db.execute(
            """
            WITH RECURSIVE market_names(value) AS (
                SELECT '' UNION ALL
                SELECT (SELECT market FROM obs WHERE market COLLATE NOCASE > market_names.value
                        ORDER BY market COLLATE NOCASE LIMIT 1)
                FROM market_names WHERE value IS NOT NULL
            )
            SELECT value FROM market_names WHERE value IS NOT NULL AND value<>''
            """
        )
    ]

def _field(name):
    return f"""(SELECT h.{name} FROM obs h WHERE h.word=o.word AND h.site IS o.site
           AND h.market IS o.market AND h.{name} IS NOT NULL ORDER BY h.sort_day DESC,h.id DESC LIMIT 1)"""


SOURCE_COLUMNS = """SELECT o.id,o.word,o.site,o.market,o.sort_day,o.report_date,
    (SELECT domain FROM sites WHERE id=o.site) AS domain,"""

# The latest view carries forward fields within the same source and market.
CURRENT_SELECT = (
    SOURCE_COLUMNS + _field("traffic")
    + " AS traffic,"
    + _field("dr")
    + " AS dr,"
    + "(SELECT url FROM pages WHERE id="
    + _field("page")
    + ") AS url "
    + "FROM obs o"
)
RAW_SELECT = SOURCE_COLUMNS + "o.traffic,o.dr,(SELECT url FROM pages WHERE id=o.page) AS url FROM obs o"


def observation_scope(q, alias, with_traffic=False):
    clauses, params = [], []
    for key in ("site", "batch"):
        if q.get(key):
            clauses.append(alias + "." + key + "=?")
            params.append(int(q[key]))
    if q.get("market"):
        clauses.append(alias + ".market COLLATE NOCASE=?")
        params.append(q["market"])
    if with_traffic and q.get("traffic") == "1":
        clauses.append(alias + ".traffic_num>0")
    return clauses, params


def representative_join(q):
    # Put all selectors used by the displayed source into the ID lookup.
    raw = bool(q.get("batch") or (q.get("market") and q.get("traffic") == "1"))
    clauses, params = observation_scope(q, "last", with_traffic=raw)
    return (
        " LEFT JOIN ("
        + (RAW_SELECT if raw else CURRENT_SELECT)
        + ") cur ON cur.id=(SELECT last.id FROM obs last WHERE "
        + " AND ".join(["last.word=w.id", *clauses])
        + " ORDER BY last.sort_day DESC,last.id DESC LIMIT 1) ",
        params,
    )


def summaries(db, word, filters=None):
    filters = filters or {}
    raw = bool(filters.get("market") and filters.get("traffic") == "1")
    clauses, params = observation_scope(filters, "g", with_traffic=raw)
    scope = " AND ".join(["g.word=?", *clauses])
    positive = " AND z.traffic_num>0" if raw else ""
    return [
        dict(r)
        for r in db.execute(
            (RAW_SELECT if raw else CURRENT_SELECT)
            + """
        WHERE o.id IN (SELECT (SELECT z.id FROM obs z WHERE z.word=g.word AND z.site IS g.site
            AND z.market IS g.market""" + positive + """ ORDER BY z.sort_day DESC,z.id DESC LIMIT 1)
            FROM obs g WHERE """
            + scope + """ GROUP BY g.word,g.site,g.market)
        ORDER BY o.sort_day DESC,o.id DESC LIMIT 101""",
            (word, *params),
        )
    ]
