"""Web app (Flask). Runs on one office PC; colleagues open it in their browser over the office network.
Only this PC and private office networks may connect (GLASS_ALLOW); nothing goes to the internet."""
from __future__ import annotations

import io
import json
import logging
import os
import sys
import time
import traceback
import zipfile

from flask import Flask, Response, abort, jsonify, request, send_file

from . import __version__, ENGINE_VERSION, ai, config, excel, netinfo, ocr, pdfdoc, pipeline

log = logging.getLogger("glassx.server")


def _web_dir():
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return os.path.join(base, "glassx", "web")
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")


def create_app() -> Flask:
    config.ensure_dirs()
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 400 * 1024 * 1024
    nets = netinfo.allowed_networks()
    if config.PUBLIC:                                    # online copy (Render etc.): behind an HTTPS proxy, open to everyone
        from werkzeug.middleware.proxy_fix import ProxyFix
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
        nets = netinfo.allowed_networks("*")

    @app.before_request
    def _office_only():
        if not netinfo.is_allowed(request.remote_addr, nets):
            log.warning("refused %s (not on the office network)", request.remote_addr)
            abort(403, "MURAFLEX AUTOMATION is only available on the office network")

    def need_id(doc_id):
        if not pipeline.valid_id(doc_id):
            abort(400, "bad document id")
        if not os.path.exists(pipeline.pdf_path(doc_id)):
            abort(404, "PDF not found - open it again")

    @app.errorhandler(Exception)
    def _err(e):
        code = getattr(e, "code", 500)
        if code == 500:
            log.error("unhandled: %s", traceback.format_exc())
        return jsonify({"error": getattr(e, "description", None) or str(e)}), code

    @app.get("/")
    def index():
        with open(os.path.join(_web_dir(), "index.html"), encoding="utf-8") as fh:
            html = fh.read().replace("{{VERSION}}", __version__)
        r = Response(html, mimetype="text/html")
        r.headers["Cache-Control"] = "no-store"
        return r

    @app.get("/api/health")
    def health():
        return jsonify({"ok": True, "app": "MURAFLEX AUTOMATION", "version": __version__, "engine": ENGINE_VERSION,
                        "ocr": ocr.available()})

    @app.get("/api/netinfo")
    def api_netinfo():
        port = request.host.rsplit(":", 1)[-1] if ":" in request.host else "80"
        port = int(port) if port.isdigit() else config.PORT
        lan = config.HOST not in ("127.0.0.1", "localhost", "::1")
        if config.PUBLIC:                                # the link to share is this site's own address
            return jsonify({"shared": True, "urls": [request.host_url.rstrip("/")], "port": port, "host": [], "you": ""})
        return jsonify({"shared": lan, "urls": netinfo.share_urls(port) if lan else [], "port": port,
                        "host": netinfo.host_names()[:1], "you": request.remote_addr})

    @app.post("/api/open")
    def api_open():
        f = request.files.get("file")
        if not f:
            abort(400, "no file")
        data = f.read()
        if not data.startswith(b"%PDF"):
            abort(400, f"{f.filename} is not a PDF")
        did = pipeline.store_pdf(data, f.filename)
        try:
            pages = pipeline.page_sizes(did)
        except Exception as e:
            abort(400, f"cannot open PDF: {e}")
        log.info("opened %s (%s, %d pages)", f.filename, did, len(pages))
        return jsonify({"doc_id": did, "name": f.filename, "pages": pages})

    @app.get("/api/page/<doc_id>/<int:pno>")
    def api_page(doc_id, pno):
        need_id(doc_id)
        w = max(400, min(int(request.args.get("w", 1600)), 6000))
        w = int(round(w / 200.0) * 200)
        cp = os.path.join(config.CACHE_DIR, f"{doc_id}_{pno}_{w}.png")
        if not os.path.exists(cp):
            d = pipeline.get_doc(doc_id)
            if not 0 <= pno < len(d):
                abort(404)
            pdfdoc.render_png(d, pno, w, cp)
        r = send_file(cp, mimetype="image/png")
        r.headers["Cache-Control"] = "public, max-age=86400"
        return r

    @app.post("/api/extract")
    def api_extract():
        j = request.get_json(force=True)
        need_id(j.get("doc_id"))
        if j.get("ai"):                                   # the "AI read page" button
            return jsonify(pipeline.extract(j["doc_id"], int(j["page"]), use_cache=False, ai_mode="force"))
        return jsonify(pipeline.extract(j["doc_id"], int(j["page"]), use_cache=not j.get("fresh")))

    # ---------------------------------------------------------------- AI (Claude) settings - host PC only
    def _host_only():
        if config.PUBLIC:                                # nobody on the internet may set or test the owner's API key
            abort(403, "AI settings are switched off on the online version (the owner sets the key on the server)")
        ra = (request.remote_addr or "").split("%")[0]
        if ra.startswith("::ffff:"):
            ra = ra[7:]
        if ra not in ("127.0.0.1", "::1") and ra not in netinfo.lan_ips():
            abort(403, "AI settings can only be changed on the PC that runs MURAFLEX AUTOMATION")

    @app.get("/api/ai/status")
    def api_ai_status():
        st = ai.status()
        ra = (request.remote_addr or "").replace("::ffff:", "")
        st["can_edit"] = not config.PUBLIC and (ra in ("127.0.0.1", "::1") or ra in netinfo.lan_ips())
        return jsonify(st)

    @app.post("/api/ai/settings")
    def api_ai_settings():
        _host_only()
        j = request.get_json(force=True) or {}
        key = j.get("api_key")
        if j.get("clear_key"):
            key = ""
        elif key is not None and not str(key).strip():
            key = None                                     # empty box = keep the saved key
        st = ai.save(model=j.get("model"), mode=j.get("mode"), api_key=key)
        log.info("AI settings changed: model=%s mode=%s key=%s", st["model"], st["mode"], "set" if st["key_hint"] else "none")
        return jsonify(st)

    @app.post("/api/ai/test")
    def api_ai_test():
        _host_only()
        if not ai.status()["configured"]:
            return jsonify({"ok": False, "error": "No API key saved yet"})
        return jsonify(ai.test_connection())

    @app.route("/api/session/<doc_id>", methods=["GET", "POST"])
    def api_session(doc_id):
        need_id(doc_id)
        p = os.path.join(config.SESS_DIR, doc_id + ".json")
        if request.method == "GET":
            if not os.path.exists(p):
                return jsonify({})
            with open(p, encoding="utf-8") as fh:
                sv = json.load(fh)
            sv["stale"] = sv.get("engine") != ENGINE_VERSION          # edits made on an older reader's results
            return jsonify(sv)
        j = request.get_json(force=True)
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"saved": time.strftime("%Y-%m-%d %H:%M"), "engine": ENGINE_VERSION, **j}, fh)
        os.replace(tmp, p)
        return jsonify({"ok": True})

    @app.post("/api/export")
    def api_export():
        j = request.get_json(force=True)
        data = excel.export_bytes(j.get("elevations") or [], j.get("doors") or [])     # tabs GLASS + DOOR
        name = excel.xlsx_name(j.get("pdf_name"))
        try:
            with open(os.path.join(config.EXPORT_DIR, name), "wb") as fh:
                fh.write(data)
        except OSError:
            pass
        log.info("exported %s", name)
        return send_file(io.BytesIO(data), as_attachment=True, download_name=name,
                         mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    @app.post("/api/export_zip")
    def api_export_zip():
        j = request.get_json(force=True)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for f in j.get("files") or []:
                z.writestr(excel.xlsx_name(f.get("pdf_name")),
                           excel.export_bytes(f.get("elevations") or [], f.get("doors") or []))
        buf.seek(0)
        return send_file(buf, as_attachment=True, download_name=f"MURAFLEX_sheets_{time.strftime('%Y%m%d_%H%M')}.zip",
                         mimetype="application/zip")

    @app.post("/api/export_doors")
    def api_export_doors():
        j = request.get_json(force=True)
        data = excel.export_bytes(j.get("elevations") or [], j.get("doors") or [])     # same one workbook
        name = excel.xlsx_name(j.get("pdf_name"))
        try:
            with open(os.path.join(config.EXPORT_DIR, name), "wb") as fh:
                fh.write(data)
        except OSError:
            pass
        log.info("exported %s", name)
        return send_file(io.BytesIO(data), as_attachment=True, download_name=name,
                         mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    @app.post("/api/export_doors_zip")
    def api_export_doors_zip():
        j = request.get_json(force=True)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for f in j.get("files") or []:
                z.writestr(excel.xlsx_name(f.get("pdf_name")),
                           excel.export_bytes(f.get("elevations") or [], f.get("doors") or []))
        buf.seek(0)
        return send_file(buf, as_attachment=True, download_name=f"MURAFLEX_sheets_{time.strftime('%Y%m%d_%H%M')}.zip",
                         mimetype="application/zip")

    return app
