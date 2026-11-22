"""Build separate streaming exports for a selection of industries."""

from contextlib import closing
import io
import json
import re
import time
import zipfile
from ai_reader import keyword_rows, readonly
from queries import write_csv
from sitebook import export_sites
from workspaces import catalog, location

KINDS = {
    "words": "去重关键词.csv",
    "evidence": "关键词来源.csv",
    "sites": "同行网站.csv",
    "ai": "AI建站关键词.jsonl",
}


def selection(root, ids, kinds):
    with closing(readonly(root)) as db:
        industries = catalog(db)
    if (
        not ids
        or not kinds
        or set(ids) - {r["id"] for r in industries}
        or set(kinds) - KINDS.keys()
    ):
        raise ValueError("请选择有效的行业和资料类型。")
    return [item for item in industries if item["id"] in ids]


class ProgressWriter:
    def __init__(self, output, progress, headers):
        self.output = output
        self.progress = progress
        self.rows = -headers
        self.last = time.monotonic()

    def write(self, value):
        size = self.output.write(value)
        self.rows += 1
        if self.rows > 0 and self.rows % 4096 == 0:
            now = time.monotonic()
            if now - self.last >= 0.5:
                self.progress(self.rows)
                self.last = now
        return size


def build(root, target, ids, kinds, progress=None, *, filters=None):
    industries = selection(root, ids, kinds)
    keyword_filters = {"state": "all"} if filters is None else filters
    done = 0
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=2) as archive:
        for item in industries:
            prefix = (
                str(item["id"])
                + "-"
                + re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", item["name"]).rstrip(". ")
                + "/"
            )
            with closing(readonly(location(root, item["id"]))) as db:
                db.execute("BEGIN")
                for kind, filename in KINDS.items():
                    if kind not in kinds:
                        continue
                    if progress:
                        def wrote(count):
                            progress(done, item["name"], kind, count)

                        wrote(0)
                    with archive.open(prefix + filename, "w", force_zip64=True) as raw:
                        with io.TextIOWrapper(
                            raw,
                            encoding="utf-8" if kind == "ai" else "utf-8-sig",
                            newline="",
                        ) as output:
                            out = ProgressWriter(output, wrote, int(kind != "ai")) if progress else output
                            if kind == "ai":
                                for row in keyword_rows(db, {"state": "active"}):
                                    out.write(
                                        json.dumps(
                                            dict(row, industry=item["name"]),
                                            ensure_ascii=False,
                                        )
                                        + "\n"
                                    )
                            elif kind == "sites":
                                export_sites(db, out, {})
                            else:
                                write_csv(db, out, {**keyword_filters, "kind": kind})
                    done += 1
                    if progress:
                        progress(done, "", "", 0)
