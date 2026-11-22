"""Export one website page's saved work, keyword evidence and confirmed photos."""

import csv
import io
import json
import re
import zipfile
from urllib.parse import urljoin

import ai_reader
import gallery
import project_archive
import project_maps
from library import csv_cell, norm


def page_details(db, project, key):
    path = project_maps.known_page(db, project, key)
    if not path:
        raise ValueError("请选择网站地图里有完整路径的页面。")
    site = db.execute("SELECT name,site FROM build_projects WHERE id=?", (project,)).fetchone()
    aliases = (path, path.rstrip("/") or "/")
    page = db.execute(
        """SELECT title,keyword,notes,status FROM build_pages WHERE project=? AND path IN (?,?)
           ORDER BY path=? DESC LIMIT 1""", (project, *aliases, path),
    ).fetchone()
    imported = db.execute(
        "SELECT title FROM map_import_pages WHERE project=? AND path=?", (project, path),
    ).fetchone()
    details = dict(page) if page else {"title": imported[0] if imported else "", "keyword": "", "notes": "", "status": ""}
    terms = [details["keyword"]] if details["keyword"].strip() else []
    terms.extend(row["term"] for row in db.execute(
        "SELECT term FROM map_page_keywords WHERE project=? AND page_key=? ORDER BY rowid",
        (project, path),
    ) if row["term"] != details["keyword"])
    return dict(details, title=details["title"] or path, path=path, project=site["name"], terms=terms,
                url=urljoin(site["site"], path) if site["site"] else "")


def change_keyword(db, page, project, term, action):
    if not isinstance(term, str) or len(term) > 1000 or not norm(term) or any(c in term for c in "\n\r\0"):
        raise ValueError("请填写一个完整关键词，最多 1000 个字符。")
    if term == page["keyword"]:
        raise ValueError("这是本页的主关键词，可在栏目规划里编辑。")
    args = (project, page["path"], term)
    if action == "remove":
        return {"changed": bool(db.execute(
            "DELETE FROM map_page_keywords WHERE project=? AND page_key=? AND term=?", args,
        ).rowcount)}
    if term in page["terms"]:
        return {"changed": False}
    if len(page["terms"]) - bool(page["keyword"].strip()) >= 100:
        raise ValueError("每个页面最多保存 100 个补充关键词。")
    db.execute("INSERT INTO map_page_keywords(project,page_key,term) VALUES(?,?,?)", args)
    return {"changed": True}


def keyword_details(db, terms):
    found = {}
    for term in terms:
        word = db.execute("SELECT state,id FROM words WHERE term=?", (term,)).fetchone()
        state = gallery.word_state(word)
        found[term] = {
            "keyword": term, "id": word[1] if word else None,
            "status": {"absent": "未入词库", "excluded": "已排除", "unmatched": "在库"}[state],
        }
    available = [item["id"] for item in found.values() if item["status"] == "在库"]
    for start in range(0, len(available), 400):
        for result in ai_reader.keyword_rows(db, {"state": "active"}, ids=available[start:start + 400]):
            found[result["keyword"]].update(result)
    return list(found.values())


def page_assets(db, page, industry):
    keywords = keyword_details(db, page["terms"])
    eligible = [item for item in keywords if item["status"] != "已排除"]
    linked = []
    for item in eligible:
        images = gallery.matches(db, item["keyword"], limit=5)
        if images:
            linked.append(dict(keyword=item["keyword"], more=len(images) > 4,
                               images=[dict(image, industry=industry) for image in images[:4]]))
    term = eligible[0]["keyword"] if eligible else ""
    candidates = []
    if term and not any(item["keyword"] == term for item in linked):
        existing = {image["id"] for item in linked for image in item["images"]}
        suggestions = gallery.suggest(db, term)["rows"]
        candidates = [dict(image, industry=industry) for image in suggestions if image["id"] not in existing][:4]
    return dict(industry=industry, main_keyword=page["keyword"], keywords=keywords,
                linked_images=linked, candidate_keyword=term if candidates else "", candidate_images=candidates)


def write_csv(z, filename, headers, records):
    with z.open(filename, "w", force_zip64=True) as entry:
        with io.TextIOWrapper(entry, encoding="utf-8-sig", newline="") as text:
            writer = csv.writer(text)
            writer.writerow(headers)
            for item in records:
                writer.writerow(csv_cell(value) for value in item)


def source_rows(db, keywords):
    for item in keywords:
        if item["status"] in ("未入词库", "已排除"):
            continue
        for row in db.execute(
            """SELECT o.market,o.report_date,o.volume,o.traffic,o.dr,o.position,
               s.domain,s.url,p.url,b.filename,o.rownum
               FROM obs o LEFT JOIN sites s ON s.id=o.site LEFT JOIN pages p ON p.id=o.page
               JOIN batches b ON b.id=o.batch WHERE o.word=? ORDER BY o.id DESC""",
            (item["id"],),
        ):
            yield (item["keyword"], "关键词报告", *row)
        for row in db.execute(
            """SELECT s.domain,s.url,r.url FROM refs r LEFT JOIN sites s ON s.id=r.site
               WHERE r.word=? ORDER BY r.url""", (item["id"],),
        ):
            yield (item["keyword"], "手工来源", "", "", "", "", "", "", *row, "", "")


def archive_originals(db, z, project, record):
    requested = {(item["source"], item["id"]): "提示词" for item in record["prompts"]}
    for update in record["automatic"]:
        requested[("chat", update["answer"])] = "Codex 回复"
    for skill in record["skills"]:
        requested[("chat", skill["answer"])] = "Codex 回复"
    issues = {item["id"]: item for item in record["issues"]}
    for issue in issues.values():
        requested[("note", issue["id"])] = issue["kind"]
    written = []
    for (source, ident), kind in requested.items():
        try:
            if kind in ("问题", "待办", "下一步"):
                issue = issues[ident]
                body = issue["body"]
                if issue["resolution"]:
                    body += "\n\n解决办法\n" + issue["resolution"]
            elif kind == "Codex 回复":
                body = project_archive.message(db, project, ident)["body"]
            else:
                body = project_archive.prompt_text(db, project, source, ident)["body"]
        except ValueError:
            continue
        name = f"原文/{kind}-{source}-{ident}.txt"
        z.writestr(name, body)
        written.append({"kind": kind, "ref": f"{source}:{ident}", "file": name})
    return written


def handoff_text(page, record, keywords, originals):
    updates = record["automatic"]
    latest = updates[0] if updates else {}
    current = record["current"] or {}
    lines = [
        "# 页面建站交接",
        "",
        page["project"] + " · " + page["title"],
        "",
        page["url"] or page["path"],
        "",
        "## 页面进度",
        "",
        current.get("stage") or page["status"] or "待记录",
    ]
    if current.get("todo"):
        lines.extend(["", "## 本页下一件事", "", current["todo"]])
    if latest.get("evidence"):
        lines.extend(["", "## 最近的 Codex 核查记录", "", latest["evidence"]])
    if page["notes"]:
        lines.extend(["", "## 已保存的页面规划", "", page["notes"]])
    if record["issues"]:
        lines.extend(["", "## 问题和待办", ""])
        for item in record["issues"]:
            detail = f"- {item['title']}（note:{item['id']}）"
            if item["resolution"]:
                detail += " · 已处理"
            lines.append(detail)
    if record["skills"]:
        lines.extend(["", "## 本页用过的技能", ""])
        for item in record["skills"]:
            lines.append(f"- {item['name']} · {item['detail']}（chat:{item['answer']}）")
    if keywords:
        lines.extend(["", "## 本页关键词", ""])
        for item in keywords:
            lines.append(f"- {item['keyword']} · {item['status']}")
    lines.extend(["", "## 同包资料", "", "- 页面资料.json", "- 关键词.csv", "- 关键词来源.csv",
                  "- image-map.json 和配图清单.csv"])
    lines.extend(f"- {item['kind']}（{item['ref']}） · {item['file']}" for item in originals)
    return "\n".join(lines) + "\n"


def bundle(project_db, keyword_db, output, project, key, text, industry):
    page = page_details(project_db, project, key)
    terms = page["terms"] if text is None else gallery.terms_from_text(text) if text.strip() else []
    record = project_archive.page_record(project_db, project, page["path"])
    keywords = keyword_details(keyword_db, terms)
    fields = (
        "keyword", "status", "translation", "product_type", "market", "traffic", "dr",
        "ranking_url", "competitor_domain", "competitor_url", "record_date",
    )
    with zipfile.ZipFile(output, "w", allowZip64=True, compression=zipfile.ZIP_DEFLATED) as z:
        originals = archive_originals(project_db, z, project, record)
        write_csv(z, "关键词.csv", (
            "完整关键词", "词库状态", "中文", "产品类型", "市场", "自然流量", "DR",
            "排名网址", "同行域名", "同行官网", "报告日期",
        ), (tuple(item.get(key) for key in fields) for item in keywords))
        write_csv(z, "关键词来源.csv", (
            "完整关键词", "来源", "市场", "报告日期", "搜索量", "自然流量", "DR", "排名",
            "同行域名", "同行官网", "排名网址", "原表", "原表行号",
        ), source_rows(keyword_db, keywords))
        gallery.write_pack(keyword_db, z, industry, terms)
        z.writestr("页面资料.json", json.dumps(
            dict(page=page, industry=industry, work=record["work"], current=record["current"], checks=record["automatic"],
                 issues=record["issues"], skills=record["skills"], keywords=keywords,
                 originals=originals, image_map="image-map.json"),
            ensure_ascii=False, indent=2,
        ))
        z.writestr("页面交接.md", handoff_text(page, record, keywords, originals))
    title = re.sub(r'[<>:"/\\|?*\x00-\x1f]', " ", page["title"])[:96].strip(" .")
    return (title + "-" if title else "") + "页面建站资料.zip"
