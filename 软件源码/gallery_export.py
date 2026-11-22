"""Export the images currently selected by the gallery filters, with their sources."""
import csv
import io
import json
import zipfile
from pathlib import PurePath
import gallery

def image_ids(db, filters):
    if "ids" in filters:
        ids = json.loads(filters["ids"])
        if not isinstance(ids, list) or not ids or any(type(i) is not int or i < 1 for i in ids):
            raise ValueError("请先勾选要下载的图片。")
        yield from dict.fromkeys(ids)
        return
    search = {key: filters[key] for key in ("q","category","kind","role","linkstate") if filters.get(key)}
    while True:
        group = gallery.listed(db, search)
        yield from (row["id"] for row in group["rows"])
        if not group["more"]:
            return
        search["after"] = group["rows"][-1]["id"]


def write(db, output, industry, filters):
    db.execute("BEGIN")
    with zipfile.ZipFile(output,"w",allowZip64=True) as z:
        index=io.StringIO()
        csvout=csv.writer(index);csvout.writerow(["行业","包内图片","原文件名","来源类型","产品分类","用途","来源路径"])
        for ident in image_ids(db, filters):
            img=gallery.detail(db,ident)
            file="images/"+str(img["id"])+"-"+PurePath(img["filename"].replace("\\","/")).name
            external=db.execute("SELECT 1 FROM gallery_external WHERE image=?",(img["id"],)).fetchone()
            if external:z.write(gallery.external_path(db,img["id"]),file)
            else:z.writestr(file,db.execute("SELECT original FROM gallery_files WHERE image=?",(img["id"],)).fetchone()[0])
            for source in img["origins"] or [dict(kind="手动上传",category="",role="",path="")]:
                csvout.writerow([industry,file,img["filename"],source["kind"],source["category"],source["role"],source["path"]])
        z.writestr("产品图来源清单.csv",index.getvalue().encode("utf-8-sig"))

