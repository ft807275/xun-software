"""Read the same project records, files and skill evidence used by the desktop app."""
import base64
from contextlib import closing
import project_archive
from skill_library import CHUNK

SCOPED_FILES="""FROM build_files f JOIN build_entries e ON e.id=f.entry
 JOIN build_steps s ON s.id=e.step WHERE s.project=?"""

def records(db,pid,args):
    page=args.get("page",1)
    if "id" not in args:
        return project_archive.journal(db,pid,dict(kind=args.get("kind",""),find=args.get("query",""),offset=(page-1)*20))
    if args.get("source")=="chat":
        row=project_archive.message(db,pid,args["id"])
    else:
        r=db.execute("""SELECT e.id,e.title,e.kind,e.body,e.resolution,s.title AS step
          FROM build_entries e JOIN build_steps s ON s.id=e.step WHERE s.project=? AND e.id=?""",(pid,args["id"])).fetchone()
        if not r: raise ValueError("本项目没有这条记录。")
        row=dict(r)
        row["files"]=[dict(f) for f in db.execute("SELECT id,filename,size FROM build_files WHERE entry=? ORDER BY id",(r["id"],))]
    body=row["body"]
    row.update(body=body[(page-1)*10000:page*10000],next_page=page+1 if len(body)>page*10000 else None)
    return row


def handoff_archive(db, pid, next_source):
    def original(source, ident):
        return dict(records(db, pid, {"source": source, "id": ident}), source=source, id=ident)

    latest = project_archive.latest_archived_turn(db, pid)
    result = {"latest_archive": latest}
    if latest:
        latest["reply_original"] = original("chat", latest["answer"])
        latest["prompt_original"] = original("chat", latest["prompt"]) if latest["prompt"] else None
    if next_source and not (
        latest and next_source["source"] == "chat" and next_source["id"] == latest["answer"]
    ):
        result["next_task_original"] = original(next_source["source"], next_source["id"])
    return result


def files(db,pid,args):
    page=args.get("page",1)
    if "id" not in args:
        selected=db.execute("""SELECT f.id,f.filename,f.size,f.digest,e.title AS record,e.id AS record_id,s.title AS step """+
            SCOPED_FILES+" AND instr(lower(f.filename),lower(?))>0 ORDER BY f.id LIMIT 51 OFFSET ?",
            (pid,args.get("query",""),(page-1)*50)).fetchall()
        return dict(items=[dict(x) for x in selected[:50]],more=len(selected)>50)
    row=db.execute("SELECT f.id,f.filename,f.size,f.digest "+SCOPED_FILES+" AND f.id=?",(pid,args["id"])).fetchone()
    if not row: raise ValueError("此项目没有这个附件。")
    result=dict(row)
    if args.get("binary"):
        offset=(page-1)*CHUNK
        b=db.execute("SELECT substr(body,?,?) FROM build_blobs WHERE digest=?",(offset+1,CHUNK,row["digest"])).fetchone()[0]
        return dict(result,encoding="base64",data=base64.b64encode(b).decode(),next_page=page+1 if offset+len(b)<row["size"] else None)
    if row["size"]>8*1024**2:
        raise ValueError("大型文件请使用 binary 分页或在资料库下载原件。")
    body=db.execute("SELECT body FROM build_blobs WHERE digest=?",(row["digest"],)).fetchone()[0]
    try: text=body.decode("utf-8-sig")
    except UnicodeError: raise ValueError("此文件是二进制，请使用 binary 读取原件。")
    return dict(result,text=text[(page-1)*10000:page*10000],next_page=page+1 if len(text)>page*10000 else None)

def usage(root, skill_name=""):
    from ai_reader import readonly
    from workspaces import location
    from sections import location as section_folder
    with closing(readonly(root)) as master:
        stores=[(location(root,r[0]),r[0],2) for r in master.execute("SELECT id FROM industry_catalog")]
        stores +=[(section_folder(root,r[0]),1,r[0]) for r in master.execute("SELECT id FROM top_sections WHERE id>=3 AND kind IN ('build','store')")]
    result=[]
    for folder,ind,sec in stores:
        with closing(readonly(folder)) as db:
            for r in db.execute("""SELECT k.name, p.id AS project,p.name AS project_name,'项目技能清单' AS kind,
              k.instructions AS detail,'' AS stamp,'' AS page FROM build_skills k JOIN build_projects p ON p.id=k.project
              WHERE (?='' OR k.name=? COLLATE NOCASE)
              UNION ALL SELECT e.title,p.id,p.name,'实际使用',e.body,e.created,'' FROM build_entries e
              JOIN build_steps s ON s.id=e.step JOIN build_projects p ON p.id=s.project
              WHERE e.kind='技能使用' AND (?='' OR e.title=? COLLATE NOCASE)
              UNION ALL SELECT k.name,p.id,p.name,'页面实际使用',k.detail,
              strftime('%Y-%m-%d %H:%M:%S',m.sent,'localtime'),k.page_key
              FROM map_page_skills k JOIN build_projects p ON p.id=k.project
              JOIN chat_text m ON m.id=k.answer WHERE (?='' OR k.name=? COLLATE NOCASE)
              ORDER BY stamp DESC""",(skill_name,)*6):
                result.append(dict(r,industry=ind,section=sec))
    return result

