"""Shared collection of original skill packages, instructions and project usage."""
import base64
import hashlib
import io
import re
import stat
import zipfile
from pathlib import PurePosixPath
from urllib import parse, request, error

MAX_ZIP = 48 * 1024 * 1024
CHUNK = 24576
SCHEMA = """
CREATE TABLE IF NOT EXISTS skill_packages(
 digest TEXT PRIMARY KEY, filename TEXT NOT NULL, raw BLOB NOT NULL);
CREATE TABLE IF NOT EXISTS skill_cards(
 id INTEGER PRIMARY KEY, source_key TEXT NOT NULL UNIQUE, name TEXT NOT NULL,
 description TEXT NOT NULL, guidance TEXT NOT NULL DEFAULT '', url TEXT NOT NULL DEFAULT '',
 package TEXT REFERENCES skill_packages(digest), member TEXT NOT NULL DEFAULT '');
CREATE INDEX IF NOT EXISTS skill_card_name ON skill_cards(name COLLATE NOCASE);
"""

def field(text, key):
    match = re.search(r"(?m)^" + key + r":[ \t]*(.*(?:\n[ \t]+[^\n]*)*)", text)
    if not match:
        return ""
    return " ".join(match[1].strip().lstrip(">|- ").split()).strip("\"'")

def manifest(body):
    parts = body.decode("utf-8-sig").replace("\r\n", "\n").split("\n---", 1)
    if len(parts) != 2 or not parts[0].startswith("---\n"):
        return "", ""
    return field(parts[0], "name"), field(parts[0], "description")

def members(z):
    result = []
    seen = set()
    if len(z.infolist()) > 12000:
        raise ValueError("压缩包文件过多，请按技能拆分。")
    for item in z.infolist():
        path = PurePosixPath(item.filename)
        if item.is_dir() or any(x.startswith(("._",".git")) or x=="__MACOSX" for x in path.parts):
            continue
        if path.is_absolute() or ".." in path.parts or "\\" in item.filename or ":" in item.filename:
            raise ValueError("压缩包包含链接或无效文件路径。")
        if stat.S_ISLNK(item.external_attr >> 16): continue
        if item.filename in seen or item.flag_bits & 1:
            raise ValueError("压缩包包含重名或加密文件。")
        seen.add(item.filename)
        result.append(item)
    if sum(i.file_size for i in result) > 300 * 1024**2:
        raise ValueError("解压后超过 300 MB，请按技能拆分。")
    return result

def import_zip(db, raw, filename, url="", prefix="", selected=""):
    if not 0 < len(raw) <= MAX_ZIP:
        raise ValueError("单个 ZIP 请控制在 48 MB 以内。")
    digest = hashlib.sha256(raw).hexdigest()
    cards = []
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        for item in members(z):
            path = PurePosixPath(item.filename)
            relative = "/".join(path.parts[1:]) if len(path.parts)>1 else str(path)
            if path.name.lower() != "skill.md" or (prefix and not (relative == prefix or relative.startswith(prefix.rstrip("/")+"/"))):
                continue
            if item.file_size > 1024**2:
                raise ValueError("SKILL.md 超过 1 MB。")
            name, desc = manifest(z.read(item))
            if not name:
                name = path.parent.name or PurePosixPath(filename).stem
            if selected and name.casefold() != selected.casefold():
                continue
            cards.append((name[:180], desc[:8000], item.filename))
    if not cards:
        raise ValueError("未找到对应的 SKILL.md。请选择包含技能说明的 ZIP。")
    db.execute("INSERT OR IGNORE INTO skill_packages VALUES(?,?,?)",(digest, PurePosixPath(filename.replace("\\","/")).name or "skills.zip",raw))
    ids = []
    for name, desc, member in cards:
        key = digest+"/"+member
        db.execute("""INSERT INTO skill_cards(source_key,name,description,url,package,member)
            VALUES(?,?,?,?,?,?) ON CONFLICT(source_key) DO UPDATE SET url=CASE WHEN url='' THEN excluded.url ELSE url END""",
            (key,name,desc or "可打开技能原文查看用途。",url,digest,member))
        ids.append(db.execute("SELECT id FROM skill_cards WHERE source_key=?",(key,)).fetchone()[0])
    return ids

def clean_url(value):
    url = str(value).strip()
    p = parse.urlsplit(url)
    if len(url)>2000 or p.scheme not in ("https","http") or not p.hostname or p.username or p.password or any(ord(c)<33 for c in url):
        raise ValueError("请填写完整的 http 或 https 网址。")
    return url

def github_source(url):
    p = parse.urlsplit(url)
    parts = [parse.unquote(x) for x in p.path.strip("/").split("/") if x]
    host = p.hostname.lower()
    if host not in ("github.com","www.github.com","skills.sh","raw.githubusercontent.com","codeload.github.com") or len(parts)<2:
        return
    owner, repo = parts[0],parts[1].removesuffix(".git")
    if not all(re.fullmatch(r"[\w.-]+", x) and x not in (".","..") for x in (owner,repo)):
        return
    rest,ref,prefix,selected = parts[2:],"HEAD","",""
    if host=="skills.sh" and rest:
        selected=rest[0]
    elif host=="raw.githubusercontent.com" and len(rest)>=2:
        ref,*sub=rest
        prefix="/".join(sub)
    elif rest[:1] in (["tree"],["blob"]) and len(rest)>=2:
        ref=rest[1]
        prefix="/".join(rest[2:])
    elif rest[:1]==["archive"] and rest[-1].endswith(".zip"):
        ref="/".join(rest[1:]).removesuffix(".zip")
    elif host=="codeload.github.com" and rest[:1]==["zip"]:
        ref="/".join(rest[1:])
    elif rest:
        return
    if not ref or ".." in ref.split("/") or not re.fullmatch(r"[\w./-]+",ref):
        return
    return ("https://codeload.github.com/"+owner+"/"+repo+"/zip/"+parse.quote(ref,safe="/"),repo+".zip",prefix,selected)

def import_url(db, p):
    url = clean_url(p.get("url",""))
    spec = github_source(url)
    why = ""
    if spec:
        try:
            req=request.Request(spec[0],headers={"User-Agent":"DesktopSkillLibrary/2.7"})
            with request.urlopen(req,timeout=12) as response:
                raw=response.read(MAX_ZIP+1)
            with db:
                ids=import_zip(db,raw,spec[1],url,spec[2],spec[3])
                db.execute("DELETE FROM skill_cards WHERE source_key=? AND guidance='' AND description='尚未读取技能原文，可补充用途或导入 ZIP。'",("url:"+url,))
            return {"ids":ids,"message":"已保存技能原文和压缩包"}
        except (OSError,ValueError,zipfile.BadZipFile,RuntimeError) as exc:
            why = "原包暂未取得，可补传 ZIP。"
    name=(parse.urlsplit(url).path.rstrip("/").split("/")[-1] or parse.urlsplit(url).hostname)[:180]
    with db:
        key="url:"+url
        db.execute("INSERT OR IGNORE INTO skill_cards(source_key,name,description,url) VALUES(?,?,?,?)",
                   (key,name,"尚未读取技能原文，可补充用途或导入 ZIP。",url))
        ident=db.execute("SELECT id FROM skill_cards WHERE source_key=?",(key,)).fetchone()[0]
    return {"ids":[ident],"message":"已收藏网址。"+(why or "可补充用途或导入 ZIP。")}

def cards(db, query="", page=1):
    query=str(query).strip()
    rows=[dict(r) for r in db.execute("""SELECT id,name,description,url,package IS NOT NULL AS offline
       FROM skill_cards WHERE instr(lower(name||' '||description||' '||guidance),lower(?))>0
       ORDER BY name COLLATE NOCASE,id LIMIT 41 OFFSET ?""",(query,(page-1)*40))]
    return dict(items=rows[:40],more=len(rows)>40)

def card(db, ident):
    row=db.execute("SELECT id,name,description,guidance,url,member,package FROM skill_cards WHERE id=?",(ident,)).fetchone()
    if not row: raise ValueError("技能不存在。")
    return dict(row)

def edit(db,p):
    ident=int(p["id"])
    card(db,ident)
    fields=[str(p.get(k,"")).strip() for k in ("name","description","guidance")]
    if not 0<len(fields[0])<=180 or max(map(len,fields[1:]))>10000:
        raise ValueError("请填写技能名称，说明最多一万字。")
    with db:
        db.execute("UPDATE skill_cards SET name=?,description=?,guidance=? WHERE id=?",(*fields,ident))
    return {"id":ident}

def chunk(raw, page):
    start=(page-1)*CHUNK
    return {"encoding":"base64","data":base64.b64encode(raw[start:start+CHUNK]).decode(),"size":len(raw),
            "next_page":page+1 if len(raw)>start+CHUNK else None}

def skill_contents(db, ident, args):
    c=card(db,ident)
    if not c["package"]:
        return dict(c,availability="仅收藏资料或网址，需要原文时打开来源或补传 ZIP。")
    raw=db.execute("SELECT raw FROM skill_packages WHERE digest=?",(c["package"],)).fetchone()[0]
    page=args.get("page",1)
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        if args.get("list_files"):
            files=[i.filename for i in members(z) if args.get("query","").lower() in i.filename.lower()]
            return dict(files=files[(page-1)*80:page*80],more=len(files)>page*80)
        member=args.get("path") or c["member"]
        if member not in {i.filename for i in members(z)}: raise ValueError("文件不在包内可读清单。")
        try: body=z.read(member)
        except KeyError: raise ValueError("原包没有这个路径，请先查看文件列表。")
        if args.get("binary"):
            return dict(path=member,**chunk(body,page))
        try: text=body.decode("utf-8-sig")
        except UnicodeError: raise ValueError("此文件是二进制，请使用 binary 分页读取。")
        return dict(c,path=member,text=text[(page-1)*10000:page*10000],next_page=page+1 if len(text)>page*10000 else None)

