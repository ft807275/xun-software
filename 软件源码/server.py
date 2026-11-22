#!/usr/bin/env python3
"""Single-user web app. The desktop launcher uses a protected loopback listener."""

import tempfile, argparse, contextlib, csv, hashlib, hmac, http.cookies, io, json, logging, mimetypes, os, pathlib, secrets, shutil, sqlite3, sys, threading, time, urllib.parse, uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from library import ROOT, dbopen, rows, preview, import_file
import sections
import skill_library
import site_resources
import autoimport
import import_history
import bulk_export
from export_queue import ExportQueue, byte_range
import presets
import ai_reader
from workspaces import home_shortcuts, remember_project, gallery_total
import buildwork
import project_archive
import project_search
import project_maps
import knowledge
import product_types
import gallery
from current_metrics import markets
from transfer import APP_NAME, APP_VERSION, bundle, inspect_backup, write_program
from workspaces import initialize, catalog, create_industry, resolve, backup, location
from sitebook import site_headers, import_sites, mapping as site_mapping, export_sites
from queries import (
    group_state,
    matching_names,
    list_words,
    sites,
    site_detail,
    detail,
    stats,
    write_csv,
    update_words,
    add_word,
    add_site,
    rule_preview,
    apply_rule,
    remove_rule,
)

CSV_CAP = 4 * 1024**3


def run(data, port, host, local):
    data = pathlib.Path(data).resolve()
    os.umask(0o077)
    initialize(data)
    main_data = data
    local_key = os.environ.get("PAPER_LOCAL_KEY", "") if local else ""
    if local and len(local_key) < 32:
        raise ValueError("请从勋的软件应用启动本机模式。")
    exports = ExportQueue(main_data)
    launch_ticket = [os.environ.get("PAPER_LAUNCH_TICKET", "")]
    local_cookie = secrets.token_urlsafe(36)
    public = ROOT / "public"
    jobs = {}
    oplock = threading.Lock()
    import_wake = threading.Event()
    sessions = {}
    failed = []
    authlock = threading.Lock()
    for f in (data / "incoming").iterdir():
        if f.is_file() and f.stat().st_mtime < time.time() - 86400:
            f.unlink()

    def get_setting(key):
        with contextlib.closing(dbopen(data)) as db:
            r = db.execute("SELECT v FROM settings WHERE k=?", (key,)).fetchone()
            return r[0] if r else ""

    authfile = data / "首次启用码.txt"
    if not local and not get_setting("password") and not authfile.exists():
        authfile.write_text(secrets.token_urlsafe(26))

    def make_job(folder, path, name, opts, digest, key=None, run=None):
        k = key or uuid.uuid4().hex
        sheets = list(run["sheets"]) if run else []
        run_id = run["id"] if run else None
        jobs[k] = {
            "status": "queued",
            "count": 0,
            "file": name,
            "industry": str(folder),
        }

        def work():
            with oplock:
                job = jobs[k]
                job["status"] = "running"
                try:
                    if run_id:
                        if not autoimport.save_state(folder, run_id, k, "running"):
                            jobs.pop(k, None)
                            return
                        if not path.is_file():
                            raise ValueError("原文件不在这台电脑上。重新上传后，可在导入记录中点「继续导入」。")
                    progress = lambda n: job.update(count=n)

                    def on_sheet(item):
                        autoimport.record_sheet(sheets, item)
                        autoimport.save_state(folder, run_id, k, "running", sheets)

                    loader = (
                        autoimport.import_all
                        if opts.get("kind") == "auto"
                        else import_sites
                        if opts.get("kind") == "sites"
                        else import_file
                    )
                    if opts.get("kind") == "auto" and run_id:
                        loader(folder, path, name, opts, digest, progress, on_sheet)
                    else:
                        result = loader(folder, path, name, opts, digest, progress)
                        if run_id:
                            on_sheet(dict(result, sheet=opts["sheet"], kind=opts["kind"]))
                        else:
                            job["result"] = result
                    if run_id:
                        autoimport.save_state(folder, run_id, k, "done", sheets)
                        job["result"] = {"sheets": sheets, "run": run_id}
                    job["status"] = "done"
                except Exception as e:
                    if run_id and opts.get("kind") != "auto":
                        autoimport.record_sheet(sheets, {"sheet": opts["sheet"], "kind": opts["kind"], "error": str(e)})
                    job.update(status="error", error=str(e), result={"sheets": sheets, "run": run_id})
                    if run_id:
                        try:
                            autoimport.save_state(folder, run_id, k, "error", sheets, str(e))
                        except sqlite3.Error:
                            logging.exception("Import state could not be saved")
                    logging.exception("import failed")
                finally:
                    if not run_id:
                        for f in [path, path.with_suffix(".meta")]:
                            f.unlink(missing_ok=True)
                    for old in list(jobs)[:-100]:
                        if jobs[old]["status"] in ("done", "error"):
                            jobs.pop(old, None)

        if run_id:
            work()
        else:
            threading.Thread(target=work, daemon=True).start()
        return k

    def run_pending_imports():
        # Desktop and remote processes can open the same library. Only one
        # worker should advance saved imports, even after either is restarted.
        with contextlib.closing(sqlite3.connect(main_data / "import-worker.sqlite3", timeout=0)) as guard:
            try:
                guard.execute("BEGIN EXCLUSIVE")
            except sqlite3.OperationalError as error:
                if "locked" in str(error):
                    return
                raise
            while True:
                with contextlib.closing(dbopen(main_data)) as db:
                    industries = catalog(db)
                pending = []
                for industry in industries:
                    folder = location(main_data, industry["id"])
                    with contextlib.closing(dbopen(folder)) as db:
                        run = autoimport.resume_candidate(db)
                    if run:
                        pending.append((folder, run))
                if not pending:
                    return
                folder, run = min(pending, key=lambda pair: (
                    pair[1]["state"] != "running", pair[1]["updated"], pair[1]["id"],
                ))
                try:
                    opts = json.loads(run["resume_options"])
                    if not isinstance(opts, dict) or opts.get("kind") not in ("auto", "words", "sites"):
                        raise ValueError("Invalid import options")
                except (TypeError, ValueError):
                    autoimport.save_state(folder, run["id"], run["job"], "error",
                                          error="无法读取上次的导入设置，请从导入记录重新处理。")
                    continue
                if opts["kind"] == "auto":
                    opts["skip_sheets"] = {
                        item["sheet"] for item in run["sheets"]
                        if not item.get("error") or item.get("empty") or item.get("replace_file")
                    }
                make_job(folder, folder / "raw" / run["digest"], run["filename"], opts,
                         run["digest"], key=run["job"], run=run)

    def import_worker():
        while True:
            import_wake.clear()
            try:
                run_pending_imports()
            except (OSError, sqlite3.Error, ValueError):
                logging.exception("Import queue")
            import_wake.wait(5)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass

        def send(
            self, data=b"", code=200, mime="application/json; charset=utf-8", extra=None
        ):
            if not isinstance(data, bytes):
                data = json.dumps(data, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "same-origin")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; frame-ancestors 'none'; form-action 'self'; base-uri 'none'",
            )
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(data)

        def send_export(self, ident):
            item = exports.read(ident)
            if item["state"] != "ready":
                if item["state"] == "expired":
                    return self.send({"error": "导出已过期，请重新生成。"}, 410)
                return self.send({"error": "导出文件还未准备好。"}, 409)
            try:
                source = exports.archive(ident).open("rb")
            except FileNotFoundError:
                return self.send({"error": "导出已过期，请重新生成。"}, 410)
            with source:
                size = os.fstat(source.fileno()).st_size
                if size != item["size"]:
                    return self.send({"error": "导出文件不完整，请重新生成。"}, 410)
                date = time.strftime("%Y%m%d-%H%M%S", time.localtime(item["created"]))
                prefix = {"backup": APP_NAME + "-整库备份", "transfer": APP_NAME + "-Win11-Mac"}.get(item.get("task"), "行业资料导出")
                return self.send_zip(source, size, prefix + "-" + date + ".zip", '"' + ident + '"')

        def send_zip(self, source, size, name, tag):
            requested = self.headers.get("Range", "") if self.headers.get("If-Range", tag) == tag else ""
            try:
                start, end = byte_range(requested, size) if requested else (0, size - 1)
            except ValueError:
                return self.send(b"", 416, extra={"Content-Range": "bytes */" + str(size)})
            remaining = end - start + 1
            self.send_response(206 if requested else 200)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Length", str(remaining))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("ETag", tag)
            if requested:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.send_header("Content-Disposition", "attachment; filename*=UTF-8''" + urllib.parse.quote(name))
            self.end_headers()
            source.seek(start)
            while remaining:
                content = source.read(min(remaining, 1024**2))
                if not content:
                    break
                self.wfile.write(content)
                remaining -= len(content)

        def authorized(self):
            c = http.cookies.SimpleCookie()
            try:
                c.load(self.headers.get("Cookie", ""))
            except http.cookies.CookieError:
                return False
            if local:
                t = c.get("paper_local")
                return bool(t and secrets.compare_digest(t.value, local_cookie))
            s = c.get("__Host-paper_session")
            return bool(
                s
                and sessions.get(hashlib.sha256(s.value.encode()).hexdigest(), 0)
                > time.time()
            )

        def dispatch(self, method):
            try:
                data = main_data
                target = urllib.parse.urlsplit(self.path)
                url = target.path
                q = dict(urllib.parse.parse_qsl(target.query, keep_blank_values=True))
                h = self.headers.get("Host", "")
                if local and h not in (
                    "127.0.0.1:" + str(self.server.server_port),
                    "localhost:" + str(self.server.server_port),
                ):
                    return self.send({"error": "仅限本机访问。"}, 403)
                if (
                    local
                    and method == "GET"
                    and url == "/open"
                    and launch_ticket[0]
                    and secrets.compare_digest(q.get("ticket", ""), launch_ticket[0])
                ):
                    launch_ticket[0] = ""
                    return self.send(
                        b"",
                        303,
                        extra={
                            "Set-Cookie": "paper_local="
                            + local_cookie
                            + "; HttpOnly; SameSite=Strict; Path=/",
                            "Location": "/",
                        },
                    )
                if (
                    local
                    and method == "GET"
                    and url == "/"
                    and not self.authorized()
                    and hmac.compare_digest(
                        self.headers.get("Authorization", ""), "Bearer " + local_key
                    )
                ):
                    return self.send(
                        (public / "index.html").read_bytes(),
                        mime="text/html; charset=utf-8",
                        extra={
                            "Set-Cookie": "paper_local="
                            + local_cookie
                            + "; HttpOnly; SameSite=Strict; Path=/"
                        },
                    )
                if url == "/api/backup-check-native" and method == "POST":
                    # The desktop picker sends the path directly over loopback.
                    # A browser session cookie never grants access to local paths.
                    if not local or not hmac.compare_digest(
                        self.headers.get("Authorization", "").encode(), ("Bearer " + local_key).encode()
                    ):
                        return self.send({"error": "请在桌面应用中选择备份文件。"}, 403)
                    return self.send(inspect_backup(self.body()["path"]))
                if method == "POST":
                    origin = self.headers.get("Origin", "")
                    u = urllib.parse.urlsplit(origin)
                    if u.netloc != h or u.scheme not in (
                        ("https",) if not local else ("http", "https")
                    ):
                        return self.send({"error": "请在资料库内操作。"}, 403)
                if local and url == "/api/login":
                    return self.send({"error": "请从桌面应用打开本机资料库。"}, 403)
                if url == "/api/login" and method == "POST":
                    p = self.body()
                    pwd = p.get("password", "")
                    with authlock:
                        failed[:] = [t for t in failed if t > time.time() - 600]
                        if len(failed) >= 12:
                            return self.send({"error": "请稍后重试。"}, 429)
                        if not isinstance(pwd, str) or not 1 <= len(pwd) <= 250:
                            raise ValueError("密码长度不正确。")
                        failed.append(time.time())
                        stored = get_setting("password")
                        if not stored:
                            if not authfile.exists() or not hmac.compare_digest(
                                p.get("activation", ""), authfile.read_text().strip()
                            ):
                                raise ValueError("首次启用码不正确。")
                            if len(pwd) < 12 or pwd != p.get("confirm"):
                                raise ValueError(
                                    "请使用至少 12 位密码，两次输入应一致。"
                                )
                            salt = secrets.token_hex(18)
                            hashed = hashlib.pbkdf2_hmac(
                                "sha256", pwd.encode(), salt.encode(), 600000
                            ).hex()
                            with contextlib.closing(dbopen(data)) as db, db:
                                db.execute(
                                    "INSERT INTO settings VALUES(?,?)",
                                    ("password", salt + ":" + hashed),
                                )
                            authfile.unlink(missing_ok=True)
                        else:
                            salt, hashed = stored.split(":")
                            if not hmac.compare_digest(
                                hashlib.pbkdf2_hmac(
                                    "sha256", pwd.encode(), salt.encode(), 600000
                                ).hex(),
                                hashed,
                            ):
                                raise ValueError("密码不正确。")
                        failed.clear()
                        tok = secrets.token_urlsafe(32)
                        sessions[hashlib.sha256(tok.encode()).hexdigest()] = (
                            time.time() + 86400 * 30
                        )
                    return self.send(
                        {"ok": True},
                        extra={
                            "Set-Cookie": "__Host-paper_session="
                            + tok
                            + "; Path=/; HttpOnly; SameSite=Lax; Secure; Max-Age=2592000"
                        },
                    )
                if (
                    url
                    in (
                        "/",
                        "/app.js",
                        "/style.css",
                        "/favicon.svg",
                        "/login.js",
                        "/workspace.js",
                        "/guide.js",
                        "/skillbank.js",
                        "/wiki.js",
                        "/presets.js",
                        "/import_history.js",
                        "/export_queue.js",
                        "/project_search.js",
                    )
                    and method == "GET"
                ):
                    name = (
                        url[1:]
                        if url != "/"
                        else "index.html"
                        if self.authorized()
                        else "login.html"
                    )
                    return self.send(
                        (public / name).read_bytes(),
                        mime=mimetypes.guess_type(name)[0] + "; charset=utf-8",
                    )
                if url == "/api/auth" and method == "GET":
                    return self.send(
                        {
                            "active": self.authorized(),
                            "version": APP_VERSION,
                            "local": local,
                            "startBuildHub": local
                            and os.environ.get("KEYWORD_START_PAGE") == "buildhub",
                            "setup": not local and not bool(get_setting("password")),
                        }
                    )
                if not self.authorized():
                    return self.send({"error": "请刷新页面登录。"}, 401)
                if url == "/api/export-records":
                    if method == "GET":
                        return self.send(exports.list())
                    request = self.body()
                    return self.send(exports.enqueue(request["ids"], request["kinds"], request.get("title", ""),
                                                     request.get("filters")), 202)
                if url == "/api/export-retry" and method == "POST":
                    return self.send(exports.retry(self.body()["id"]), 202)
                if url == "/api/export-backup" and method == "POST":
                    return self.send(exports.enqueue_backup(self.body()["task"]), 202)
                if url == "/api/backup-check" and method == "POST":
                    if not local:
                        return self.send({"error": "请在资料库主机上检查备份文件。"}, 403)
                    self.body()
                    from portable import choose_native_path
                    selected = choose_native_path(backup=True)
                    return self.send(inspect_backup(selected) if selected else {"cancelled": True})
                if url == "/api/export-download" and method == "GET":
                    return self.send_export(q.get("id", ""))
                if url == "/api/program-update" and method == "GET":
                    with tempfile.TemporaryDirectory() as scratch:
                        path = pathlib.Path(scratch) / "program.zip"
                        write_program(path)
                        with path.open("rb") as source:
                            digest = hashlib.sha256()
                            for data_chunk in iter(lambda: source.read(1024**2), b""):
                                digest.update(data_chunk)
                            return self.send_zip(
                                source, os.fstat(source.fileno()).st_size,
                                APP_NAME + "-程序升级-Win11-Mac-v" + APP_VERSION + ".zip",
                                '"' + digest.hexdigest() + '"',
                            )
                if url == "/api/project-search" and method == "GET":
                    return self.send(project_search.search(
                        main_data, q.get("find", ""), q.get("kind", ""), q.get("owner", ""),
                        project_search.search_cursor(q.get("before")),
                    ))
                if url == "/api/gallery-search" and method == "GET":
                    return self.send(gallery.search_industries(main_data, q))
                if url == "/api/saved-presets":
                    if method == "GET":
                        return self.send(presets.list_saved(main_data, q.get("scope", "all"), q.get("industry", 1)))
                    p = self.body()
                    return self.send(presets.save(main_data, p["kind"], q.get("industry", 1), p["payload"], p["name"]))
                if url == "/api/saved-preset-remove" and method == "POST":
                    return self.send(presets.remove(main_data, self.body()["id"]))
                if url.startswith("/api/skillbank-"):
                    op=url.removeprefix("/api/skillbank-")
                    with contextlib.closing(dbopen(main_data)) as db:
                        if method=="GET":
                            page=max(1,int(q.get("page",1)))
                            if op=="list": return self.send(skill_library.cards(db,q.get("query",""),page))
                            if op=="usage": return self.send(site_resources.usage(main_data,q.get("name","")))
                            ident=int(q["id"])
                            c=skill_library.card(db,ident)
                            if op=="detail":
                                return self.send(dict(c,history=site_resources.usage(main_data,c["name"])))
                            if op=="download":
                                row=db.execute("SELECT filename,raw FROM skill_packages WHERE digest=?",(c["package"],)).fetchone()
                                if not row: raise ValueError("此卡片还没有原包。")
                                return self.send(row[1],mime="application/zip",extra={"Content-Disposition":"attachment; filename*=UTF-8''"+urllib.parse.quote(row[0],safe="")})
                        if method=="POST":
                            if op=="prepare":
                                if not local:return self.send({"error":"请在资料库主机准备技能目录。"},403)
                                from skill_cache import prepare
                                return self.send(prepare(main_data,int(self.body()["id"])))
                            if op=="upload":
                                size=int(self.headers.get("Content-Length",0))
                                if not 0<size<=skill_library.MAX_ZIP: raise ValueError("单个 ZIP 最大 48 MB。")
                                raw=self.rfile.read(size)
                                with db:
                                    ids=skill_library.import_zip(db,raw,q.get("filename","skills.zip"))
                                return self.send({"ids":ids})
                            if op=="url": return self.send(skill_library.import_url(db,self.body()))
                            if op=="edit": return self.send(skill_library.edit(db,self.body()))
                        raise ValueError("技能操作不存在。")
                if url == "/api/desk" and method == "GET":
                    return self.send(home_shortcuts(main_data))
                if url == "/api/import-history" and method == "GET":
                    result = import_history.page(
                        main_data, q.get("scope") or q.get("industry") or "1", q.get("find", ""),
                        q.get("status") == "pending", import_history.read_cursor(q.get("before")),
                    )
                    for item in result["items"]:
                        import_history.live_state(item, jobs)
                    return self.send(result)
                if url == "/api/industries" and method == "GET":
                    with contextlib.closing(dbopen(main_data)) as master:
                        return self.send(catalog(master))
                if url == "/api/industry" and method == "POST":
                    return self.send(
                        create_industry(main_data, self.body().get("name", ""))
                    )
                if url == "/api/sections" and method == "GET":
                    with contextlib.closing(dbopen(main_data)) as master:
                        return self.send(sections.listing(master))
                if url in ("/api/section", "/api/subsection") and method == "POST":
                    return self.send(
                        sections.save(
                            main_data, self.body(), url.endswith("subsection")
                        )
                    )
                sid = int(q.get("section") or 2)
                scoped = url.startswith("/api/build-") or url in (
                    "/api/materials",
                    "/api/projects",
                    "/api/home",
                )
                area = None
                if scoped:
                    with contextlib.closing(dbopen(main_data)) as master:
                        area = sections.active_section(master, sid)
                    if not area:
                        raise ValueError("这个一级类目不存在。")
                data = (
                    sections.location(main_data, sid)
                    if scoped and sid >= 3
                    else resolve(main_data, q.get("industry") or "1")
                )
                if url == "/api/build-map-import" and method == "POST":
                    if area["kind"] not in ("build", "store"):
                        raise ValueError("请选择建站项目。")
                    size = int(self.headers.get("Content-Length", 0))
                    if not 0 < size <= 4 * 1024**3:
                        raise ValueError("每个项目文件需要有内容，最大 4 GB。")
                    with tempfile.TemporaryFile() as tmp:
                        remaining = size
                        while remaining:
                            chunk = self.rfile.read(min(remaining, 1024**2))
                            if not chunk:
                                raise ValueError("文件上传中断，请重新选择。")
                            tmp.write(chunk)
                            remaining -= len(chunk)
                        tmp.seek(0)
                        with contextlib.closing(dbopen(data)) as db, db:
                            db.execute("BEGIN IMMEDIATE")
                            result = project_maps.import_file(db, int(q["project"]), pathlib.PureWindowsPath(q["filename"]).name, tmp)
                    return self.send(result)
                if url == "/api/build-page-keywords":
                    if area["kind"] not in ("build", "store"):
                        raise ValueError("请选择建站项目。")
                    import page_bundle

                    fields = q if method == "GET" else self.body()
                    project, key = int(fields["project"]), fields.get("key", "")
                    keyword_folder = resolve(main_data, q.get("industry") or "1")
                    action, term = fields.get("action"), fields.get("term")
                    with contextlib.closing(dbopen(data)) as db, db:
                        writing = method == "POST" and (action != "store" or data == keyword_folder)
                        db.execute("BEGIN IMMEDIATE" if writing else "BEGIN")
                        page = page_bundle.page_details(db, project, key)
                        if method == "POST" and action != "store":
                            if action not in ("add", "remove"):
                                raise ValueError("无法识别这个关键词操作。")
                            result = page_bundle.change_keyword(db, page, project, term, action)
                        else:
                            if method == "POST" and term not in page["terms"]:
                                raise ValueError("请先将这个词关联到本页。")
                            with contextlib.ExitStack() as opened:
                                keyword_db = db
                                if keyword_folder != data:
                                    keyword_db = opened.enter_context(contextlib.closing(dbopen(keyword_folder)))
                                    opened.enter_context(keyword_db)
                                    keyword_db.execute("BEGIN IMMEDIATE" if method == "POST" else "BEGIN")
                                if method == "POST":
                                    result = add_word(keyword_db, {"term": term})
                                else:
                                    result = {"main": page["keyword"], "keywords": page_bundle.keyword_details(keyword_db, page["terms"])}
                    return self.send(result)
                if url == "/api/build-page-bundle" and method == "POST":
                    if area["kind"] not in ("build", "store"):
                        raise ValueError("请选择建站项目。")
                    size = int(self.headers.get("Content-Length") or 0)
                    if not 0 < size <= 4 * 1024 * 1024:
                        raise ValueError("页面资料表单过长或为空。")
                    form = dict(urllib.parse.parse_qsl(
                        self.rfile.read(size).decode("utf-8"), keep_blank_values=True,
                    ))
                    industry_id = int(q.get("industry") or 1)
                    keyword_folder = resolve(main_data, industry_id)
                    with contextlib.closing(dbopen(main_data)) as master:
                        industry = master.execute("SELECT name FROM industry_catalog WHERE id=?", (industry_id,)).fetchone()[0]
                    import page_bundle

                    with tempfile.TemporaryDirectory() as scratch:
                        output = pathlib.Path(scratch) / "page.zip"
                        with contextlib.ExitStack() as opened:
                            project_db = opened.enter_context(contextlib.closing(dbopen(data)))
                            project_db.execute("BEGIN")
                            keyword_db = project_db
                            if keyword_folder != data:
                                keyword_db = opened.enter_context(contextlib.closing(dbopen(keyword_folder)))
                                keyword_db.execute("BEGIN")
                            name = page_bundle.bundle(
                                project_db, keyword_db, output, int(form["project"]),
                                form.get("key", ""), form.get("terms"), industry,
                            )
                        with output.open("rb") as source:
                            return self.send_zip(source, output.stat().st_size, name,
                                                 '"' + uuid.uuid4().hex + '"')
                if method == "GET" and url == "/api/build-wiki-index":
                    find = q.get("find", "").strip()[:400]
                    result = []
                    for industry, section, label, folder in project_archive.folders(main_data):
                        with contextlib.closing(dbopen(folder)) as db:
                            pages = {}
                            for item in knowledge.index(db):
                                pages.setdefault(item["project"], []).append(item)
                            matches = {}
                            if find:
                                for item in knowledge.search_pages(db, find):
                                    matches.setdefault(item["project"], []).append(item)
                            for row in db.execute("""SELECT p.id,p.name,p.site,
                                   (SELECT count(*) FROM wiki_pending_updates w WHERE w.project=p.id) AS pending
                                   FROM build_projects p ORDER BY p.id"""):
                                if not find or find.casefold() in (row["name"] + " " + row["site"] + " " + label).casefold():
                                    selected = pages.get(row["id"], [])
                                elif row["id"] in matches:
                                    selected = matches[row["id"]]
                                else:
                                    continue
                                result.append(dict(row, industry=industry, section=section, label=label, pages=selected))
                    return self.send(result)
                if method == "GET" and url == "/api/build-wiki-project":
                    if area["kind"] not in ("build", "store"):
                        raise ValueError("请选择建站项目。")
                    pid = int(q["project"])
                    with contextlib.closing(dbopen(data)) as db:
                        row = db.execute("SELECT id,name FROM build_projects WHERE id=?", (pid,)).fetchone()
                        if not row:
                            raise ValueError("找不到这个项目。")
                        pages = knowledge.index(db, pid)
                        slug = q.get("slug")
                        return self.send(dict(
                            row, pages=pages, page=knowledge.page(db, pid, slug) if slug else None,
                            updates=[] if slug else knowledge.updates(db, pid),
                            issues=[] if slug else knowledge.check(db, pid),
                            automation=dict(knowledge.auto_status(db, pid), canChooseFolder=local),
                            pending=None if slug else knowledge.pending_updates(db, pid),
                            command=[sys.executable, str(ROOT / "knowledge.py"),
                                     "--data", str(main_data), "--industry", str(q.get("industry", 1)),
                                     "--section", str(sid), "--project", str(pid)] if local else [],
                        ))
                if method == "POST" and url == "/api/build-wiki-automation":
                    if not local:
                        return self.send({"error": "请在建站文件夹所在电脑操作。"}, 403)
                    if area["kind"] not in ("build", "store"):
                        raise ValueError("请选择建站项目。")
                    args = self.body()
                    if not isinstance(args.get("enabled"), bool):
                        raise ValueError("请选择是否启用自动整理。")
                    with contextlib.closing(dbopen(data)) as db:
                        return self.send(project_archive.configure_wiki(db, int(args["project"]), args["enabled"]))
                if url.startswith("/api/build-archive-"):
                    if area["kind"] not in ("build", "store"):
                        raise ValueError("请选择一个建站资料类目。")
                    op = url.split("build-archive-", 1)[1]
                    if op == "overview" and method == "GET":
                        return self.send(project_archive.overview(main_data, prompts_only=q.get("prompts") == "1"))
                    if (
                        op
                        in ("sources", "bind", "pause", "sync", "folder", "stop-folder", "workspaces")
                        and not local
                    ):
                        return self.send(
                            {"error": "请在主机上设置 Codex 自动备份。"}, 403
                        )
                    args = self.body() if method == "POST" else q
                    project = int(args["project"])
                    with contextlib.closing(dbopen(data)) as db:
                        if not db.execute(
                            "SELECT 1 FROM build_projects WHERE id=?", (project,)
                        ).fetchone():
                            raise ValueError("找不到这个项目。")
                        if op == "workspaces":
                            sources = project_archive.local_files()
                            if method == "GET":
                                return self.send(project_archive.workspace_choices(db, project, sources))
                            if method == "POST":
                                source = sources.get(args.get("thread"))
                                if not source or not source["directory"]:
                                    raise ValueError("本机没有找到这个 Codex 文件夹。")
                                for _, _, _, other in project_archive.folders(main_data):
                                    if other == data:
                                        continue
                                    with contextlib.closing(dbopen(other)) as opened:
                                        if opened.execute(
                                            "SELECT 1 FROM chat_folders WHERE directory=? AND enabled=1",
                                            (source["directory"],),
                                        ).fetchone():
                                            raise ValueError("这个文件夹已关联到另一个项目。")
                                return self.send({"folder": project_archive.attach_workspace(
                                    db, project, source["directory"],
                                )})
                        if op == "page-record":
                            if method == "GET":
                                return self.send(project_archive.page_record(db, project, args["key"]))
                            if method == "POST":
                                return self.send(project_archive.update_page_record(db, project, args))
                        if op == "map-work" and method == "GET":
                            return self.send(project_maps.map_work_overview(db, project))
                        if op == "wiki-pending":
                            answer = int(args["answer"])
                            if method == "GET":
                                return self.send(knowledge.pending_updates(db, project, answer))
                            if method == "POST":
                                return self.send(knowledge.file_pending_update(db, project, answer, args))
                        if op == "page-skill" and method == "POST":
                            return self.send(project_archive.change_page_skill(
                                db, project, args.get("key"), args.get("answer"), args.get("name"),
                                remove=args.get("remove") is True,
                            ))
                        if op == "page-issue" and method == "POST":
                            return self.send(project_archive.save_page_issue(db, project, args))
                        if op == "resolve-issue" and method == "POST":
                            return self.send(project_archive.resolve_project_issue(db, project, args))
                        if op == "handoff":
                            import handoff

                            if method == "GET":
                                response = handoff.workspace_options(db, project, local)
                                if args.get("path"):
                                    import ai_reader
                                    import page_bundle
                                    industry = int(q.get("industry") or 1)
                                    folder = resolve(main_data, industry)
                                    page = page_bundle.page_details(db, project, args["path"])
                                    with contextlib.closing(ai_reader.readonly(folder)) as keyword_db:
                                        assets = page_bundle.page_assets(keyword_db, page, industry)
                                    response["pageContext"] = dict(page=page, assets=assets,
                                        record=project_archive.page_record(db, project, page["path"]))
                                else:
                                    response["projectContext"] = dict(
                                        project_archive.project_followup(db, project),
                                        recentTurn=project_archive.latest_archived_turn(db, project),
                                        steps=rows(db, "SELECT id,title,status FROM build_steps WHERE project=? ORDER BY seq,id",
                                                   (project,)),
                                    )
                                return self.send(response)
                            if not local:
                                return self.send({"error": "请在项目文件夹所在电脑打开。"}, 403)
                            return self.send(handoff.open_workspace(db, project, args.get("folder")))
                        if method=="POST" and op=="workcopy":
                            if not local:return self.send({"error":"请在资料库所在电脑准备源码。"},403)
                            import handoff
                            return self.send(handoff.prepare(db,project))
                        if method == "GET":
                            if op == "original":
                                return self.send(project_search.original(
                                    db, project, args["source"], args["id"], args.get("pagePath", ""),
                                ))
                            if op == "workcopy":
                                raise ValueError("请在主机准备工作文件夹。")
                            if op == "prompts":
                                return self.send(
                                    project_archive.prompts(db, project, args)
                                )
                            if op == "prompt-board":
                                return self.send(project_archive.prompt_board(db, project, args))
                            if op == "thread":
                                return self.send(
                                    project_archive.thread_rows(
                                        db,
                                        project,
                                        int(args["id"]),
                                        args.get("find", ""),
                                        args.get("offset", 0),
                                    )
                                )
                            if op == "replies":
                                return self.send(
                                    project_archive.prompt_replies(
                                        db,
                                        project,
                                        int(args["id"]),
                                        args.get("offset", 0),
                                    )
                                )
                            if op == "prompt-text":
                                return self.send(
                                    project_archive.prompt_text(
                                        db, project, args["source"], args["id"]
                                    )
                                )
                            if op == "revision":
                                return self.send(project_archive.revision(db, project))
                            if op == "turns":
                                return self.send(project_archive.archived_turns(
                                    db, project, args.get("before"), answer=args.get("answer") or None,
                                ))
                            if op == "sources":
                                sources = sorted(
                                    project_archive.local_files().values(),
                                    key=lambda x: x["updated"],
                                    reverse=True,
                                )
                                return self.send(
                                    [
                                        {k: r[k] for k in ("id", "title", "workspace")}
                                        for r in sources
                                    ]
                                )
                            if op == "list":
                                journal = project_archive.journal(db, project, args)
                                highlights = []
                                if args.get("dashboard") == "1":
                                    _, current = project_archive.prompt_stage(db, project, journal["nextTaskStep"])
                                    if current:
                                        highlights = project_archive.prompts(db, project, {"step": current}, limit=2)["items"]
                                return self.send(
                                    dict(
                                        journal, promptHighlights=highlights,
                                        hasSource=bool(db.execute("SELECT 1 FROM build_entries e JOIN build_steps s ON s.id=e.step WHERE s.project=? AND e.kind='仓库原件' LIMIT 1",(project,)).fetchone()),
                                        revision=project_archive.revision(db, project),
                                        promptCounts=project_archive.prompt_counts(
                                            db, project
                                        ),
                                        links=project_archive.links(db, project),
                                        folders=[
                                            dict(
                                                id=r["id"],
                                                name=pathlib.Path(r["directory"]).name,
                                            )
                                            for r in db.execute(
                                                "SELECT id,directory FROM chat_folders WHERE project=? AND enabled=1",
                                                (project,),
                                            )
                                        ],
                                        local=local,
                                        recentTurn=project_archive.latest_archived_turn(
                                            db, project
                                        ) if args.get("dashboard") == "1" else None,
                                    )
                                )
                            if op == "text":
                                return self.send(
                                    project_archive.message(
                                        db, project, int(args["id"])
                                    )
                                )
                        if method == "POST" and op == "copy-workflow":
                            dest = int(args["destSection"])
                            industry = int(args["destIndustry"])
                            with contextlib.closing(dbopen(main_data)) as master:
                                a = master.execute(
                                    "SELECT kind FROM top_sections WHERE id=?", (dest,)
                                ).fetchone()
                                if not a or a[0] not in ("build", "store"):
                                    raise ValueError("请选择建站项目所属类目。")
                            folder = (
                                resolve(main_data, industry)
                                if dest == 2
                                else sections.location(main_data, dest)
                            )
                            with contextlib.closing(dbopen(folder)) as target:
                                return self.send(
                                    project_archive.copy_workflow(
                                        db, target, project, args
                                    )
                                )
                        if method == "POST" and op == "folder":
                            return self.send(
                                {
                                    "folder": project_archive.enable_folder(
                                        db,
                                        project,
                                        int(args["id"]),
                                        project_archive.local_files(),
                                    )
                                }
                            )
                        if method == "POST" and op == "stop-folder":
                            with db:
                                db.execute(
                                    "UPDATE chat_folders SET enabled=0 WHERE id=? AND project=?",
                                    (int(args["id"]), project),
                                )
                            return self.send({"ok": True})
                        if method == "POST" and op == "bind":
                            return self.send(
                                {
                                    "added": project_archive.bind(
                                        db,
                                        project,
                                        args["thread"],
                                        args.get("step"),
                                        project_archive.local_files(),
                                    )
                                }
                            )
                        if method == "POST" and op == "pause":
                            with db:
                                db.execute(
                                    "UPDATE project_chats SET enabled=0 WHERE id=? AND project=?",
                                    (int(args["id"]), project),
                                )
                            return self.send({"ok": True})
                        if method == "POST" and op == "sync":
                            sources = project_archive.local_files()
                            added = project_archive.sync_project(db, project, sources)
                            return self.send({"added": added, "recovered": knowledge.retry_pending_updates(db, project)})
                    raise ValueError("未识别的项目记录操作。")
                if url == "/api/build-visit" and method == "POST":
                    if area["kind"] not in ("build", "store"):
                        raise ValueError("请选择建站项目所属类目。")
                    with contextlib.closing(dbopen(data)) as db:
                        item = buildwork.project(db, self.body()["id"])
                    remember_project(
                        main_data,
                        int(q.get("industry") or 1),
                        sid,
                        item["id"],
                    )
                    return self.send(item)
                if url == "/api/selected-brief" and method == "POST":
                    ids = self.body().get("ids")
                    if (
                        not isinstance(ids, list)
                        or not ids
                        or any(type(i) is not int or not 0 < i < 2**63 for i in ids)
                    ):
                        raise ValueError("请先勾选需要的关键词。")
                    ids = list(dict.fromkeys(ids))
                    by_id = {}
                    filters = {"state": "active"}
                    if q.get("market"):
                        filters.update({key: q[key] for key in ("market", "site", "batch", "traffic") if key in q})
                    with contextlib.closing(ai_reader.readonly(data)) as db:
                        db.execute("BEGIN")
                        for offset in range(0, len(ids), 400):
                            chunk = ids[offset : offset + 400]
                            for row in ai_reader.keyword_rows(
                                db, filters, ids=chunk
                            ):
                                by_id[row["id"]] = row
                            if filters.get("market"):
                                continue
                            refs = db.execute(
                                "SELECT r.word,r.url,s.domain,s.url AS site_url FROM refs r LEFT JOIN sites s ON s.id=r.site WHERE r.word IN ("
                                + ",".join("?" for _ in chunk)
                                + ") ORDER BY r.word,r.url",
                                chunk,
                            )
                            for ref in refs:
                                if ref["word"] in by_id:
                                    by_id[ref["word"]].setdefault(
                                        "manual_sources", []
                                    ).append(
                                        {
                                            "url": ref["url"],
                                            "competitor_url": ref["site_url"],
                                        }
                                    )
                    return self.send(
                        {
                            "rows": [by_id[i] for i in ids if i in by_id],
                            "skipped": len(ids) - len(by_id),
                        }
                    )
                if url == "/api/cross-words" and method == "GET":
                    query = q.get("q", "")
                    if not query.strip() or len(query) > 1000:
                        raise ValueError("请输入 1 至 1000 字的关键词。")
                    with contextlib.closing(dbopen(main_data)) as master:
                        industries = catalog(master)
                    result = []
                    for ind in industries:
                        folder = (
                            main_data
                            if ind["id"] == 1
                            else main_data / "industries" / str(ind["id"])
                        )
                        with contextlib.closing(dbopen(folder)) as saved:
                            words = matching_names(saved, query)
                            if words:
                                result.append(
                                    dict(
                                        ind,
                                        rows=[
                                            {"id": w["id"], "term": w["term"]}
                                            for w in words
                                        ],
                                    )
                                )
                    return self.send(result)
                if url == "/api/materials" and method == "GET":
                    if sid >= 3:
                        with contextlib.closing(dbopen(data)) as saved:
                            result = buildwork.material_rows(saved, 1, area["name"], q)
                        return self.send(
                            {"rows": result[:50], "more": len(result) > 50}
                        )
                    with contextlib.closing(dbopen(main_data)) as master:
                        industries = catalog(master)
                    result = []
                    for industry in industries:
                        ident = industry["id"]
                        if q.get("scope") == "current" and ident != int(
                            q.get("industry") or 1
                        ):
                            continue
                        folder = (
                            main_data
                            if ident == 1
                            else main_data / "industries" / str(ident)
                        )
                        with contextlib.closing(dbopen(folder)) as saved:
                            result.extend(
                                buildwork.material_rows(
                                    saved, ident, industry["name"], q
                                )
                            )
                    result.sort(
                        key=lambda r: (r["created"], r["industry"], r["id"]),
                        reverse=True,
                    )
                    return self.send({"rows": result[:50], "more": len(result) > 50})
                if url == "/api/build-file" and method == "POST":
                    size = int(self.headers.get("Content-Length") or 0)
                    if not 0 < size <= 64 * 1024 * 1024:
                        raise ValueError("每个附件需要有内容，最多 64 MB。")
                    content = self.rfile.read(size)
                    if len(content) != size:
                        raise ValueError("上传中断，请重试。")
                    with contextlib.closing(dbopen(data)) as db, db:
                        result = buildwork.attach(
                            db, int(q["entry"]), q["filename"], content
                        )
                        owner = db.execute("SELECT s.project FROM build_entries e JOIN build_steps s ON s.id=e.step WHERE e.id=?",
                                           (int(q["entry"]),)).fetchone()
                        if owner and pathlib.Path(q["filename"]).suffix.lower() in project_maps.FORMATS:
                            db.execute("SAVEPOINT map_attachment")
                            try:
                                result["map"] = project_maps.import_file(db, owner[0], q["filename"], io.BytesIO(content), required=False)
                            except (ValueError, KeyError, IndexError, SyntaxError, OSError, RuntimeError, csv.Error, zipfile.BadZipFile) as err:
                                db.execute("ROLLBACK TO map_attachment")
                                result["mapNotice"] = str(err)
                            finally:
                                db.execute("RELEASE map_attachment")
                        db.commit()
                    return self.send(result)
                if url == "/api/gallery-upload" and method == "POST":
                    size = int(self.headers.get("Content-Length") or 0)
                    thumb_size = int(self.headers.get("X-Thumbnail-Length") or 0)
                    if (
                        not 0 <= thumb_size <= gallery.MAX_THUMB
                        or not 0 < size - thumb_size <= gallery.MAX_IMAGE
                    ):
                        raise ValueError("请选择不超过 32 MB 的图片。")
                    thumb = self.rfile.read(thumb_size)
                    original = self.rfile.read(size - thumb_size)
                    if len(original) + len(thumb) != size:
                        raise ValueError("图片上传中断，请重试。")
                    with contextlib.closing(dbopen(data)) as db, db:
                        result = gallery.store(
                            db, q.get("filename", ""), original, thumb, q.get("word"),
                            q.get("category", ""), q.get("kind", "产品素材")
                        )
                        db.commit()
                    return self.send(result)
                if url == "/api/connect-codex" and method=="POST":
                    if not local:return self.send({"error":"请在资料库主机设置连接。"},403)
                    import codex_link
                    return self.send(codex_link.connect(main_data, switch_from=self.body().get("switchFrom")))
                if url == "/api/codex-status" and method == "GET":
                    if not local:
                        return self.send({"error": "请在资料所在电脑检查本机 Codex 连接。"}, 403)
                    import codex_link
                    return self.send(codex_link.status(main_data))
                if url == "/api/ai-connection" and method == "GET":
                    if not local:
                        return self.send(
                            {
                                "error": "请在资料所在的电脑上打开词库，获取本机连接配置。"
                            },
                            400,
                        )
                    return self.send(ai_reader.config(main_data))
                if url == "/api/bulk-export" and method == "GET":
                    ids = {int(v) for v in q.get("ids", "").split(",") if v}
                    kinds = set(q.get("kinds", "").split(","))
                    with tempfile.TemporaryDirectory() as scratch:
                        archive = pathlib.Path(scratch) / "export.zip"
                        bulk_export.build(main_data, archive, ids, kinds)
                        self.send_response(200)
                        self.send_header("Content-Type", "application/zip")
                        self.send_header("Content-Length", str(archive.stat().st_size))
                        self.send_header("Cache-Control", "no-store")
                        self.send_header(
                            "Content-Disposition",
                            "attachment; filename*=UTF-8''"
                            + urllib.parse.quote("行业资料批量导出.zip"),
                        )
                        self.end_headers()
                        with archive.open("rb") as source:
                            shutil.copyfileobj(source, self.wfile, 1024 * 1024)
                    return
                if url == "/api/gallery-pack" and method == "POST":
                    size = int(self.headers.get("Content-Length") or 0)
                    if not 0 < size <= 4 * 1024 * 1024:
                        raise ValueError("关键词清单过长或为空。")
                    form = dict(
                        urllib.parse.parse_qsl(
                            self.rfile.read(size).decode("utf-8"),
                            keep_blank_values=True,
                        )
                    )
                    terms = (
                        None
                        if form.get("scope") in ("all","gallery")
                        else gallery.terms_from_text(form.get("terms", ""))
                    )
                    with contextlib.closing(dbopen(main_data)) as master:
                        industry = master.execute(
                            "SELECT name FROM industry_catalog WHERE id=?",
                            (int(q.get("industry") or 1),),
                        ).fetchone()[0]
                    with (
                        tempfile.TemporaryDirectory() as scratch,
                        contextlib.closing(dbopen(data)) as db,
                    ):
                        archive = pathlib.Path(scratch) / "assets.zip"
                        if form.get("scope")=="gallery":
                            import gallery_export
                            gallery_export.write(db,archive,industry,form)
                        else:
                            gallery.pack(db, archive, industry, terms)
                        self.send_response(200)
                        self.send_header("Content-Type", "application/zip")
                        self.send_header("Content-Length", str(archive.stat().st_size))
                        self.send_header("Cache-Control", "no-store")
                        self.send_header(
                            "Content-Disposition",
                            "attachment; filename*=UTF-8''"
                            + urllib.parse.quote(industry + ("-产品图库.zip" if form.get("scope") == "gallery" else "-建站配图.zip")),
                        )
                        self.end_headers()
                        with archive.open("rb") as source:
                            shutil.copyfileobj(source, self.wfile, 1024 * 1024)
                    return
                if url in ("/api/stage", "/api/auto-import") and method == "POST":
                    size = int(self.headers.get("Content-Length") or 0)
                    if not 0 < size <= CSV_CAP:
                        raise ValueError("每次支持一个非空文件，最大 4 GiB。")
                    if shutil.disk_usage(data).free < size + 64 * 1024 * 1024:
                        raise ValueError("磁盘剩余空间不足。")
                    key = uuid.uuid4().hex
                    path = data / "incoming" / key
                    sha = hashlib.sha256()
                    name = pathlib.PureWindowsPath(q.get("filename", "导入文件")).name[:300] or "导入文件"
                    try:
                        with path.open("xb") as out:
                            remaining = size
                            while remaining:
                                b = self.rfile.read(min(remaining, 1048576))
                                if not b:
                                    raise ValueError("上传中断，请重新选择文件。")
                                out.write(b)
                                sha.update(b)
                                remaining -= len(b)
                        if url == "/api/auto-import":
                            digest = sha.hexdigest()
                            _, run = autoimport.save_upload(
                                data, path, name, digest, key, q.get("replaces", ""),
                            )
                            import_wake.set()
                            if run["id"] != key:
                                return self.send({"id": run["job"], "run": run["id"], "duplicate": True})
                            return self.send({"id": key})
                        sample = preview(path)
                        sample["siteHeaders"], _ = site_headers(sample["headers"])
                        sample["siteMapping"] = site_mapping(sample["siteHeaders"])
                        path.with_suffix(".meta").write_text(
                            json.dumps([name, sha.hexdigest()])
                        )
                        return self.send({"token": key, "name": name, **sample})
                    except BaseException:
                        path.unlink(missing_ok=True)
                        raise
                if url == "/api/jobs" and method == "GET":
                    job = jobs.get(q.get("id"))
                    if job and job["industry"] == str(data) and (
                        job["status"] != "done" or not job.get("result", {}).get("run")
                    ):
                        return self.send(job)
                    with contextlib.closing(dbopen(data)) as db:
                        row = db.execute("SELECT id FROM import_runs WHERE job=?", (q.get("id"),)).fetchone()
                        if not row:
                            raise ValueError("任务已结束或服务重启，请查看导入记录。")
                        run = autoimport.run_record(db, row["id"])
                    if run["resume_job"] == run["job"] and run["state"] in ("queued", "running"):
                        return self.send(dict(status=run["state"], count=0))
                    status = "done" if run["state"] in ("done", "needs_file", "replaced") else "error"
                    return self.send(dict(status=status, error=run["error"] or (
                        "导入尚未完成，可在导入记录里继续。" if status == "error" else ""
                    ), result={"sheets": run["sheets"], "run": run["id"], "state": run["state"],
                               "replacement_file": run.get("replacement_file")}))
                if url in ("/api/import-review", "/api/import-retry") and method == "POST":
                    p = self.body()
                    with contextlib.closing(dbopen(data)) as db:
                        run = autoimport.run_record(db, p.get("run"))
                        original = data / "raw" / run["digest"]
                        job = jobs.get(run["job"], {})
                        if job.get("status") in ("queued", "running") or (
                            run["resume_job"] == run["job"] and run["state"] in ("queued", "running")
                        ):
                            raise ValueError("这份文件正在导入，请稍后查看。")
                        if not original.is_file():
                            raise ValueError("原文件在这台电脑上找不到。")
                        if run["state"] == "needs_file":
                            raise ValueError(next(item["error"] for item in run["sheets"] if item.get("replace_file")))
                        if run["state"] == "replaced":
                            raise ValueError("这份文件已有补传结果，请在导入记录里查看。")
                        kind = p.get("kind") or "auto"
                        sheet = p.get("sheet", "")
                        skip = int(p.get("skip") or 0)
                        if kind not in ("auto", "words", "sites") or skip < 0:
                            raise ValueError("请检查导入类型和表头行。")
                        if kind != "auto" and not any(
                            row["sheet"] == sheet and row.get("error") and not row.get("empty")
                            and not row.get("replace_file") for row in run["sheets"]
                        ):
                            raise ValueError("这张表已处理，请刷新导入记录。")
                        if url == "/api/import-review":
                            sample = preview(original, sheet, skip)
                            sample["siteHeaders"], _ = site_headers(sample["headers"])
                            sample["siteMapping"] = site_mapping(sample["siteHeaders"])
                            return self.send(dict(sample, name=run["filename"]))
                        key = uuid.uuid4().hex
                        opts = dict(kind=kind, sheet=sheet, skip=skip, review=kind != "auto")
                        if kind != "auto":
                            fields = ("mapping", "domain", "market", "date", "audience", "headerless")
                            opts.update({field: p[field] for field in fields if field in p})
                        autoimport.start_retry(db, run["id"], key, run["job"], opts)
                    import_wake.set()
                    return self.send({"id": key})
                if (
                    url in ("/api/import", "/api/sample", "/api/discard")
                    and method == "POST"
                ):
                    p = self.body()
                    key = str(p.get("token", ""))
                    if len(key) != 32 or any(c not in "0123456789abcdef" for c in key):
                        raise ValueError("文件标识无效。")
                    path = data / "incoming" / key
                    if not path.with_suffix(".meta").exists():
                        raise ValueError("文件已处理或过期。")
                    name, digest = json.loads(path.with_suffix(".meta").read_text())
                    if url == "/api/sample":
                        sample = preview(path, p.get("sheet", ""))
                        sample["siteHeaders"], _ = site_headers(sample["headers"])
                        sample["siteMapping"] = site_mapping(sample["siteHeaders"])
                        return self.send(sample)
                    if url == "/api/discard":
                        path.unlink(missing_ok=True)
                        path.with_suffix(".meta").unlink(missing_ok=True)
                        return self.send({"ok": True})
                    return self.send({"id": make_job(data, path, name, p, digest)})
                with contextlib.closing(dbopen(data)) as db, db:
                    if method == "GET":
                        if url == "/api/build-file":
                            file = db.execute(
                                "SELECT f.filename,b.body FROM build_files f JOIN build_blobs b ON b.digest=f.digest WHERE f.id=?",
                                (int(q["id"]),),
                            ).fetchone()
                            if not file:
                                return self.send({"error": "没有找到附件。"}, 404)
                            return self.send(
                                file[1],
                                mime="application/octet-stream",
                                extra={
                                    "Content-Disposition": "attachment; filename*=UTF-8''"
                                    + urllib.parse.quote(file[0], safe="")
                                },
                            )
                        if url == "/api/projects":
                            projects = buildwork.project_list(db)
                            with contextlib.closing(dbopen(main_data)) as master:
                                recent = master.execute(
                                    "SELECT project FROM recent_project WHERE slot=1 AND industry=? AND section=?",
                                    (int(q.get("industry") or 1), sid),
                                ).fetchone()
                            if recent:
                                for p in projects:
                                    p["recent"] = p["id"] == recent[0]
                            return self.send(projects)
                        if url == "/api/build-project":
                            return self.send(buildwork.project(db, q["id"]))
                        if url == "/api/build-entry":
                            return self.send(buildwork.entry(db, q["id"]))
                        if url == "/api/home":
                            projects = db.execute(
                                "SELECT count(*) FROM build_projects"
                            ).fetchone()[0]
                            images = db.execute(
                                "SELECT count(*) FROM gallery_images"
                            ).fetchone()[0]
                            pages = db.execute(
                                "SELECT count(*) FROM build_pages"
                            ).fetchone()[0]
                            return self.send(
                                {"projects": projects, "images": images, "pages": pages}
                            )
                        if url == "/api/types":
                            return self.send(product_types.overview(db))
                        if url == "/api/type-review":
                            return self.send(product_types.review_groups(db))
                        if url == "/api/type-suggestions":
                            return self.send(product_types.suggest_phrases(db, q))
                        if url == "/api/gallery-filters":
                            return self.send(dict(gallery.filters(db), global_total=gallery_total(main_data)))
                        if url == "/api/gallery":
                            return self.send(gallery.listed(db, q, with_total=True))
                        if url == "/api/gallery-detail":
                            return self.send(gallery.detail(db, q["id"]))
                        if url == "/api/gallery-match":
                            return self.send(gallery.matches(db, q["term"]))
                        if url == "/api/gallery-suggest":
                            return self.send(gallery.suggest(
                                db, q["term"], q.get("category", ""), q.get("query", ""),
                                q.get("offset", 0), q.get("browse") == "1",
                            ))
                        if url == "/api/gallery-link-words":
                            query = q.get("q", "")
                            if not query.strip() or len(query) > 1000:
                                raise ValueError("请输入关键词，最多 1,000 字。")
                            return self.send(matching_names(db, query))
                        if url == "/api/gallery-file":
                            small = q.get("preview") == "1"
                            row = db.execute(
                                "SELECT g.mime,g.filename,"
                                + (
                                    "coalesce(f.thumb,f.original),f.thumb IS NOT NULL"
                                    if small
                                    else "f.original,0"
                                )
                                + " FROM gallery_files f JOIN gallery_images g ON g.id=f.image WHERE f.image=?",
                                (int(q["id"]),),
                            ).fetchone()
                            if not row:
                                return self.send({"error": "没有这张图片。"}, 404)
                            disposition = (
                                {
                                    "Content-Disposition": "attachment; filename*=UTF-8''"
                                    + urllib.parse.quote(row[1], safe="")
                                }
                                if q.get("download")
                                else {}
                            )
                            if not row[2]:
                                original = gallery.external_path(db,int(q["id"]))
                                self.send_response(200)
                                self.send_header("Content-Type", row[0])
                                self.send_header("Content-Length", str(original.stat().st_size))
                                self.send_header("X-Content-Type-Options","nosniff")
                                self.send_header("Cache-Control","private, no-store")
                                for key,value in disposition.items(): self.send_header(key,value)
                                self.end_headers()
                                with original.open("rb") as src: shutil.copyfileobj(src,self.wfile,1024*1024)
                                return
                            return self.send(
                                bytes(row[2]),
                                mime="image/jpeg" if row[3] else row[0],
                                extra=disposition,
                            )
                        if url == "/api/options":
                            return self.send(
                                {
                                    "types": product_types.all_types(db),
                                    "markets": markets(db),
                                    "categories": [
                                        v[0]
                                        for v in db.execute(
                                            "SELECT DISTINCT category FROM words WHERE category<>'' ORDER BY category"
                                        )
                                    ],
                                    "sites": rows(
                                        db,
                                        "SELECT id,domain,name FROM sites ORDER BY domain",
                                    ),
                                }
                            )
                        if url == "/api/transfer":
                            with tempfile.TemporaryDirectory() as scratch:
                                packed = pathlib.Path(scratch) / "transfer.zip"
                                bundle(main_data, packed)
                                self.send_response(200)
                                self.send_header("Content-Type", "application/zip")
                                self.send_header("Cache-Control", "no-store")
                                self.send_header(
                                    "Content-Length", str(packed.stat().st_size)
                                )
                                self.send_header(
                                    "Content-Disposition",
                                    "attachment; filename=keyword-library-Win11-Mac.zip; filename*=UTF-8''"
                                    + urllib.parse.quote(
                                        APP_NAME
                                        + "-Win11-Mac-"
                                        + time.strftime("%Y%m%d")
                                        + ".zip"
                                    ),
                                )
                                self.end_headers()
                                with packed.open("rb") as fp:
                                    shutil.copyfileobj(fp, self.wfile, 1024 * 1024)
                            return
                        if url == "/api/backup":
                            self.send_response(200)
                            self.send_header("Content-Type", "application/zip")
                            self.send_header(
                                "Content-Disposition",
                                "attachment; filename=keyword-library-backup.zip; filename*=UTF-8''"
                                + urllib.parse.quote(
                                    APP_NAME
                                    + "-备份-"
                                    + time.strftime("%Y%m%d")
                                    + ".zip"
                                ),
                            )
                            self.send_header("Cache-Control", "no-store")
                            self.end_headers()
                            backup(main_data, self.wfile)
                            return
                        if url in ("/api/raw", "/api/import-original"):
                            if url == "/api/raw":
                                r = db.execute(
                                    "SELECT a.digest,b.filename FROM archived a JOIN batches b ON b.id=a.batch WHERE batch=?",
                                    (int(q["id"]),),
                                ).fetchone()
                            else:
                                r = db.execute("SELECT digest,filename FROM import_runs WHERE id=?", (q.get("run"),)).fetchone()
                            if not r:
                                raise ValueError("没有找到原文件。")
                            path = data / "raw" / r[0]
                            if not path.is_file():
                                raise ValueError("原文件在这台电脑上找不到。")
                            size = path.stat().st_size
                            self.send_response(200)
                            self.send_header("Content-Type", "application/octet-stream")
                            self.send_header("Content-Length", str(size))
                            self.send_header(
                                "Content-Disposition",
                                "attachment; filename*=UTF-8''"
                                + urllib.parse.quote(r[1], safe=""),
                            )
                            self.end_headers()
                            with path.open("rb") as f:
                                shutil.copyfileobj(f, self.wfile, 1024 * 1024)
                            return
                        if url == "/api/import-history-file":
                            result = import_history.file_details(db, q.get("key", ""))
                            if result["run"]:
                                import_history.live_state(result["run"], jobs)
                            return self.send(result)
                        if url == "/api/stats":
                            return self.send(stats(db))
                        if url == "/api/words":
                            db.execute("BEGIN")
                            return self.send(list_words(db, q))
                        if url == "/api/word":
                            return self.send(detail(db, q))
                        if url == "/api/sites":
                            db.execute("BEGIN")
                            return self.send(sites(db, q))
                        if url == "/api/site":
                            return self.send(site_detail(db, q))
                        if url == "/api/rules":
                            return self.send(
                                rows(db, "SELECT * FROM rules ORDER BY id DESC")
                            )
                        if url == "/api/batches":
                            return self.send(
                                rows(
                                    db,
                                    "SELECT b.*,sb.valid AS site_valid FROM batches b LEFT JOIN site_batches sb ON b.id=sb.batch ORDER BY b.id DESC",
                                    (),
                                )
                            )
                        if url == "/api/import-runs":
                            return self.send(autoimport.recent_runs(
                                db, int(q.get("before") or 2**63 - 1), q.get("scope") == "pending",
                            ))
                        if url == "/api/export":
                            self.send_response(200)
                            self.send_header("Content-Type", "text/csv; charset=utf-8")
                            self.send_header(
                                "Content-Disposition",
                                'attachment; filename="keyword-'
                                + (
                                    "evidence"
                                    if q.get("kind") == "evidence"
                                    else "sites"
                                    if q.get("kind") == "sites"
                                    else "library"
                                )
                                + "-"
                                + time.strftime("%Y%m%d")
                                + '.csv"',
                            )
                            self.send_header("Cache-Control", "no-store")
                            self.end_headers()
                            self.wfile.write(b"\xef\xbb\xbf")
                            out = io.TextIOWrapper(
                                self.wfile,
                                encoding="utf-8",
                                newline="",
                                write_through=False,
                            )
                            try:
                                (
                                    export_sites
                                    if q.get("kind") == "sites"
                                    else write_csv
                                )(db, out, q)
                                out.flush()
                            finally:
                                out.detach()
                            return
                    if method == "POST":
                        p = self.body()
                        if url in (
                            "/api/build-project",
                            "/api/build-project-name",
                            "/api/build-step",
                            "/api/build-skill",
                            "/api/build-page",
                            "/api/build-entry",
                        ):
                            try:
                                if url == "/api/build-entry":
                                    p["subcategory"] = sections.classify(
                                        main_data, sid, p
                                    )
                                elif url == "/api/build-project":
                                    p["store"] = area["kind"] == "store"
                                result = buildwork.save(db, url.split("build-")[1], p)
                                if url == "/api/build-entry":
                                    result["subcategory"] = db.execute(
                                        "SELECT subcategory FROM build_entries WHERE id=?",
                                        (result["id"],),
                                    ).fetchone()[0]
                            except sqlite3.IntegrityError as ex:
                                if url == "/api/build-skill":
                                    raise ValueError(
                                        "请检查所属项目，同一项目内的 Skill 名称需唯一。"
                                    ) from ex
                                if url == "/api/build-project-name":
                                    raise ValueError("这个资料库里已有同名项目，请换一个名称。") from ex
                                raise ValueError(
                                    "项目名称或本项目的页面路径重复，或关联的项目不存在。"
                                ) from ex
                            db.commit()
                            return self.send(result)
                        if url == "/api/type-batch":
                            with db:
                                result = product_types.batch_assign(db, p)
                            return self.send(result)
                        if url == "/api/type-preview":
                            with db:
                                result = product_types.preview_rule(db, p)
                            return self.send(result)
                        if url in ("/api/type-save", "/api/type-assign"):
                            result = (
                                product_types.save
                                if url.endswith("save")
                                else product_types.assign
                            )(db, p)
                            db.commit()
                            return self.send(result)
                        if url == "/api/gallery-classify-batch":
                            return self.send(gallery.classify_selected(db, p.get("ids"), p.get("category")))
                        if url == "/api/gallery-link-preview":
                            return self.send(gallery.preview_bulk_links(db, p.get("selection"), p.get("page", 1)))
                        if url == "/api/gallery-link-batch":
                            return self.send(gallery.apply_bulk_links(db, p.get("selection"), p.get("word"),
                                                                     p.get("revision"), p.get("excluded")))
                        if url == "/api/gallery-classify-preview":
                            _, result = gallery.filtered_classification(db, p.get("filters"), p.get("page", 1))
                            return self.send(result)
                        if url == "/api/gallery-classify-filtered":
                            return self.send(gallery.classify_filtered(
                                db, p.get("filters"), p.get("category"), p.get("revision"), p.get("excluded"),
                            ))
                        if url == "/api/gallery-classify":
                            ident=int(p["id"]);path=str(p["path"])
                            kind=p["kind"];category=str(p["category"]).strip();role=str(p["role"]).strip()
                            if kind not in ("产品素材","同行参考","来源待核实","示例素材","设计源文件","教程参考") or not 0<len(category)<=120 or not 0<len(role)<=180:
                                raise ValueError("请填写分类、来源和用途。")
                            with db:
                                if not path:
                                    if not db.execute("SELECT 1 FROM gallery_images WHERE id=?",(ident,)).fetchone():raise ValueError("图片不存在。")
                                    db.execute("INSERT OR IGNORE INTO gallery_origins VALUES(?,'手动上传',?,?,?)",(ident,category,kind,role))
                                else:
                                    if not db.execute("UPDATE gallery_origins SET kind=?,category=?,role=? WHERE image=? AND path=?",(kind,category,role,ident,path)).rowcount:raise ValueError("找不到图片来源。")
                            return self.send({"ok":True})
                        if url == "/api/gallery-change":
                            result = gallery.change(db, p)
                            db.commit()
                            return self.send(result)
                        if url == "/api/gallery-preview":
                            return self.send(gallery.preview(
                                db, p.get("terms", ""), p.get("offset", 0), p.get("unmatched") is True,
                            ))
                        if url == "/api/gallery-build-link":
                            return self.send(gallery.attach_for_build(
                                db, p.get("term"), p["id"], p.get("cover", False),
                            ))
                        if url == "/api/logout":
                            c = http.cookies.SimpleCookie(
                                self.headers.get("Cookie", "")
                            )
                            s = c.get("__Host-paper_session")
                            if s:
                                sessions.pop(
                                    hashlib.sha256(s.value.encode()).hexdigest(), None
                                )
                            return self.send(
                                {"ok": True},
                                extra={
                                    "Set-Cookie": "__Host-paper_session=; Path=/; HttpOnly; Secure; Max-Age=0"
                                },
                            )
                        if url in ("/api/group-preview", "/api/group-apply"):
                            if url.endswith("apply"):
                                db.execute("BEGIN IMMEDIATE")
                            result = group_state(db, p, url.endswith("apply"))
                            db.commit()
                            return self.send(result)
                        if url in (
                            "/api/state",
                            "/api/word",
                            "/api/site",
                            "/api/rule",
                            "/api/unrule",
                            "/api/edit",
                        ):
                            db.execute("BEGIN IMMEDIATE")
                            if url == "/api/state":
                                result = update_words(db, p)
                            elif url == "/api/word":
                                result = add_word(db, p)
                            elif url == "/api/site":
                                result = add_site(db, p)
                            elif url == "/api/rule":
                                result = apply_rule(db, p)
                            elif url == "/api/unrule":
                                result = remove_rule(db, p)
                            else:
                                db.execute(
                                    "UPDATE words SET category=?,notes=? WHERE id=?",
                                    (
                                        p.get("category", ""),
                                        p.get("notes", ""),
                                        int(p["id"]),
                                    ),
                                )
                                if not db.execute(
                                    "SELECT type_manual FROM words WHERE id=?",
                                    (int(p["id"]),),
                                ).fetchone()[0]:
                                    db.execute(
                                        "UPDATE words SET product_type=? WHERE id=?",
                                        (
                                            product_types.matcher(db)(
                                                *db.execute(
                                                    "SELECT norm,category FROM words WHERE id=?",
                                                    (int(p["id"]),),
                                                ).fetchone()
                                            ),
                                            int(p["id"]),
                                        ),
                                    )
                                result = {"ok": True}
                            db.commit()
                            return self.send(result)
                        if url == "/api/site-channel":
                            val = int(p["audience"])
                            if val not in range(4):
                                raise ValueError("同行类型无效。")
                            db.execute(
                                """INSERT INTO site_channels(site,mask) VALUES(?,?)
                                   ON CONFLICT(site) DO UPDATE SET mask=excluded.mask,inferred=0""",
                                (int(p["id"]), val),
                            )
                            db.commit()
                            return self.send({"ok": True})
                        if url == "/api/rule-preview":
                            return self.send(rule_preview(db, p["phrase"]))
                return self.send({"error": "页面不存在。"}, 404)
            except (BrokenPipeError, ConnectionResetError):
                return
            except (
                ValueError,
                KeyError,
                IndexError,
                TypeError,
                csv.Error,
                sqlite3.IntegrityError,
                zipfile.BadZipFile,
            ) as e:
                self.send({"error": str(e)}, 400)
            except Exception as e:
                logging.exception("request")
                self.send({"error": "操作未完成，请重试。" + str(e)}, 500)

        def body(self):
            n = int(self.headers.get("Content-Length", "0"))
            if not 0 < n <= 1024 * 1024:
                raise ValueError("表单内容过长或为空。")
            return json.loads(self.rfile.read(n))

        def do_GET(self):
            self.dispatch("GET")

        def do_POST(self):
            self.dispatch("POST")

    import zipfile

    srv = ThreadingHTTPServer(("127.0.0.1" if local else host, port), Handler)
    threading.Thread(target=import_worker, name="saved-imports", daemon=True).start()
    if local:
        threading.Thread(
            target=project_archive.auto_sync, args=(main_data,), daemon=True
        ).start()
    print("PORT=" + str(srv.server_port), flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    a = argparse.ArgumentParser()
    a.add_argument("--data", required=True)
    a.add_argument("--port", type=int, default=8787)
    a.add_argument("--host", default="127.0.0.1")
    a.add_argument("--local", action="store_true")
    v = a.parse_args()
    run(v.data, v.port, v.host, v.local)
