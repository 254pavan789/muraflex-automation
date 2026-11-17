"""Command line:  python app.py [--batch PATH ...] [--out DIR] [--selftest] [--port N] [--no-browser]"""
from __future__ import annotations

import argparse
import glob
import logging
import os
import random
import sys
import tempfile
import threading
import time
import webbrowser

from . import __version__, config


def _batch(paths, out_dir):
    from . import pipeline
    files = []
    for p in paths:
        files += sorted(glob.glob(os.path.join(p, "*.pdf"))) if os.path.isdir(p) else [p]
    if not files:
        print("No PDF files found.")
        return 1
    print(f"MURAFLEX AUTOMATION {__version__} - batch: {len(files)} PDF(s)\n")
    total_p = total_e = total_d = 0
    t0 = time.perf_counter()
    for f in files:
        t = time.perf_counter()
        try:
            r = pipeline.process_pdf(f)
            panels = sum(1 for e in r["elevations"] for p in e["panels"] if p["export"] and p["kind"] != "Door")
            od = out_dir or os.path.dirname(os.path.abspath(f))
            doors = [d for d in r.get("doors", []) if d.get("export", True)]
            out = pipeline.export_to(r["elevations"], r["name"], od, doors)        # one workbook: GLASS + DOOR tabs
            flags = sum(1 for e in r["elevations"] if e["notes"])
            total_p += panels; total_e += len(r["elevations"])
            total_d += len(doors)
            dflags = sum(1 for d in doors if d["notes"])
            print(f"  OK   {os.path.basename(f)}\n       {r['pages']} page(s), {len(r['elevations'])} elevation(s), "
                  f"{panels} panel(s){f', {flags} elevation(s) to check' if flags else ''}"
                  f"  ->  {out}  ({time.perf_counter() - t:.1f}s)")
            if doors:
                print(f"       {len(doors)} door(s){f', {dflags} to check' if dflags else ''}  ->  DOOR tab")
        except Exception as e:  # keep going with the next file
            print(f"  FAIL {os.path.basename(f)}: {e}")
    print(f"\nDone: {total_e} elevations, {total_p} glass panels, {total_d} doors in {time.perf_counter() - t0:.1f}s")
    return 0


def _selftest():
    """End-to-end check on generated FM sheets with known answers (run after installing on a new PC)."""
    from . import excel, pipeline, synth
    tmp = tempfile.mkdtemp(prefix="glassx_selftest_")
    config.set_data_dir(tmp)
    ok = True
    t0 = time.perf_counter()
    cases = [("reference project", synth.reference_project(), {"doors": True}),
             ("PDF mark-up annotations", synth.reference_project(), {"use_annots": True, "doors": True}),
             ("two rows of elevations", synth.reference_project(), {"rows_per_page": 2, "doors": True})]
    rng = random.Random(11)
    for i in range(5):
        pages = [[synth.random_spec(rng, j + 1 + 4 * pg, str(rng.randint(10, 99)), rng.randint(1, 3),
                                    door_first=rng.random() < .3) for j in range(4)] for pg in range(2)]
        cases.append((f"random sheet {i + 1}", pages, {"seed": i}))
    for i in range(4):                                              # 14005 Gibson Dunn style sheets
        cases.append((f"Gibson-style sheet {i + 1}", synth.random_project_gd(random.Random(100 + i), 2),
                      {"seed": i, "use_annots": i % 2 == 1, "gd": True}))
    for i in range(3):                                              # pivot doors: hinge side, 45 / 90 deg readings
        cases.append((f"door sheet {i + 1}", synth.random_door_project(random.Random(300 + i), 2),
                      {"seed": i, "rows_per_page": 1 + i % 2, "doors": "fuzz"}))
    for i, st in enumerate(["oc", "oc", "admin", "admin"]):          # 14092 style / ADMIN style (also rotated)
        cases.append((f"{'Orange County' if st == 'oc' else 'ADMIN'}-style sheet {i % 2 + 1}",
                      synth.random_project_family(random.Random(200 + i), st, 2), {"fam": st, "rotate": 90 * (i % 2)}))
    for name, specs, kw in cases:
        path = os.path.join(tmp, f"case_{abs(hash(name)) % 10**6}.pdf")
        fam = kw.pop("fam", None)
        door_check = kw.pop("doors", False)
        if fam:
            synth.build_fm_pdf_family(path, specs, fam, rotate=kw.get("rotate", 0))
        elif kw.pop("gd", False):
            synth.build_fm_pdf_gd(path, specs, **kw)
        else:
            synth.build_fm_pdf(path, specs, **kw)
        r = pipeline.process_pdf(path, use_cache=False)
        if fam:
            exp = synth.expected_family(specs, fam)
            got = sorted((e["elev"], p["tag"], p["L"]["u"], p["L"]["l"], p["R"]["u"], p["R"]["l"], p["kind"])
                         for e in r["elevations"] for p in e["panels"] if p["kind"] != "No tag")
            wrong = [x for x in exp if x not in got] + [x for x in got if x not in exp]
        else:
            exp = synth.expected(specs)
            got = {(e["elev"], p["tag"]): (p["L"]["u"], p["L"]["l"], p["R"]["u"], p["R"]["l"], p["kind"])
                   for e in r["elevations"] for p in e["panels"] if p["kind"] != "No tag"}
            wrong = [k for k in exp if got.get(k) != exp[k]]
        data = excel.export_bytes(r["elevations"])
        status = "PASS" if not wrong and data[:2] == b"PK" else "FAIL"
        ok &= status == "PASS"
        print(f"  {status}  {name:<26} {len(exp):>3} panels" + (f"  wrong: {wrong[:3]}" if wrong else ""))
        if door_check:                                              # DOOR module: A / B / C1 / C2 of every pivot door
            dexp = synth.expected_doors(specs)
            if door_check == "fuzz":
                flat = [sp for pg in specs for sp in pg]
                dexp = [x for x, sp in zip(dexp, flat) if synth.door_determinable(sp)]
            dgot = [(d["elev"], d["tag"], *((d["pts"][k]["u"], d["pts"][k]["l"]) for k in ("A", "B", "C1", "C2")))
                    for d in r["doors"]]
            dwrong = [x for x in dexp if x not in dgot]
            dstat = "PASS" if not dwrong and excel.export_bytes(r["elevations"], r["doors"])[:2] == b"PK" else "FAIL"
            ok &= dstat == "PASS"
            print(f"  {dstat}  {name + ' (doors)':<26} {len(dexp):>3} doors" + (f"  wrong: {dwrong[:2]}" if dwrong else ""))
    print(f"\nSelf-test {'PASSED' if ok else 'FAILED'} in {time.perf_counter() - t0:.1f}s")
    return 0 if ok else 1


def main(argv=None):
    ap = argparse.ArgumentParser(prog="app.py", description="MURAFLEX AUTOMATION - FM PDF to GLASS and DOOR sheets")
    ap.add_argument("--batch", nargs="+", metavar="PDF_OR_FOLDER", help="process PDFs without the UI")
    ap.add_argument("--out", default=None, help="output folder for --batch (default: next to each PDF)")
    ap.add_argument("--selftest", action="store_true", help="run the built-in end-to-end test")
    ap.add_argument("--port", type=int, default=config.PORT)
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--host", default=None, help="address to listen on (default 0.0.0.0 = office network)")
    ap.add_argument("--local", action="store_true", help="this PC only (127.0.0.1), not shared on the network")
    ap.add_argument("--ai-check", metavar="PDF", help="read every page of a PDF with Claude AI and print the result")
    ap.add_argument("--version", action="version", version=__version__)
    a = ap.parse_args(argv)
    if a.ai_check:
        return _ai_check(a.ai_check)
    if a.selftest:
        return _selftest()
    log = config.setup_logging()
    if a.batch:
        return _batch(a.batch, a.out)
    return _serve(a, log)


def _ai_check(path):
    """Command-line check of AI reading on one PDF (uses the key and model saved in AI settings)."""
    from . import ai, pipeline
    st = ai.status()
    if not st["configured"]:
        print("AI reading is not set up: start the app, click  AI  in the header and save the Anthropic API key.")
        return 1
    print(f"AI check with {st['model']} on {os.path.basename(path)}")
    t = test = ai.test_connection()
    if not test["ok"]:
        print("  Connection failed:", t["error"])
        return 1
    did = pipeline.store_pdf(open(path, "rb").read(), os.path.basename(path))
    for p in range(len(pipeline.page_sizes(did))):
        r = pipeline.extract(did, p, use_cache=False, ai_mode="force")
        print(f"\n--- page {p + 1}: {r['method']}  {len(r['elevations'])} elevation(s)" +
              (f"   ! {r['ai_error']}" if r.get("ai_error") else ""))
        for e in r["elevations"]:
            print(f"  ELEV {e['elev'] or '?'}  {e['name']}")
            for q in e["panels"]:
                print(f"    {q['tag'] or q['code'] or '-':<14} {q['kind']:<9} L {q['L']['u']:>8} / {q['L']['l']:<8}"
                      f"  R {q['R']['u']:>8} / {q['R']['l']:<8}")
            for n in e["notes"]:
                print("      note:", n)
        for d in r.get("doors", []):
            print(f"  DOOR {d['tag']} {d['type']} hinge {d.get('hinge') or '?'}: " +
                  "  ".join(f"{k} {v['u']}/{v['l']}" for k, v in d["pts"].items()))
    u = ai.status()["usage"]
    print(f"\nTokens: {u['input_tokens']} input, {u['output_tokens']} output, {u['calls']} calls")
    return 0


def _already_running(port):
    import json
    import urllib.request
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=1.5) as r:
            return json.loads(r.read().decode()).get("app") == "MURAFLEX AUTOMATION"
    except Exception:
        return False


def _serve(a, log):
    from . import netinfo, ocr
    from .server import create_app
    host = "127.0.0.1" if a.local else (a.host or config.HOST)
    config.HOST = host
    port = a.port
    if not netinfo.port_free(host, port):
        if _already_running(port):                              # double-clicked twice: just open the running app
            print(f"\n  MURAFLEX AUTOMATION is already running on port {port} - opening it.\n")
            if not a.no_browser:
                webbrowser.open(f"http://127.0.0.1:{port}")
            return 0
        free = next((p for p in range(port + 1, port + 30) if netinfo.port_free(host, p)), None)
        if free is None:
            print(f"  Port {port} is in use and no free port was found nearby. Close the other program or use --port.")
            return 1
        print(f"  Port {port} is used by another program - using port {free} instead.")
        port = free
    app = create_app()
    local = f"http://127.0.0.1:{port}"
    shared = host not in ("127.0.0.1", "localhost", "::1")
    urls = netinfo.share_urls(port) if shared else []
    line = "=" * 64
    print(f"\n  {line}\n  MURAFLEX AUTOMATION {__version__}\n  {line}")
    print(f"  This PC          : {local}")
    if shared:
        if urls:
            print(f"  Other office PCs : {urls[0]}      <- share this link")
            for u in urls[1:]:
                print(f"                     {u}")
        else:
            print("  Other office PCs : no office network found (check the network cable / Wi-Fi)")
        fw = netinfo.firewall_rule_ok(port)
        if fw is False:
            print(f"\n  ! Windows Firewall may block the other PCs. Run  allow_network_access.bat  once")
            print(f"    (right-click > Run as administrator) - it opens port {port} on the office network only.")
            print("    (Run it again if you ran it for an older version - the port changed from 5050 to 8080.)")
    else:
        print("  Shared           : no (this PC only - started with --local)")
    print(f"  Data folder      : {config.DATA_DIR}")
    print(f"  OCR              : {'ready' if ocr.available() else 'not installed (only needed for scanned PDFs)'}")
    print(f"  {line}\n  Keep this window open while people use the app. Close it to stop.\n")
    try:
        with open(os.path.join(config.DATA_DIR, "TEAM_LINK.txt"), "w", encoding="utf-8") as fh:
            fh.write("MURAFLEX AUTOMATION - open one of these links in a browser on any office PC:\n\n" +
                     "\n".join(urls or [local]) + "\n")
    except OSError:
        pass
    log.info("start %s on %s:%s (share: %s)", __version__, host, port, ", ".join(urls) or "-")
    if not a.no_browser:
        threading.Timer(1.2, lambda: webbrowser.open(local)).start()
    try:
        from waitress import serve                              # production server: many users at once, Windows-friendly
        logging.getLogger("waitress").setLevel(logging.ERROR)
        proxy = dict(trusted_proxy="*", trusted_proxy_count=1, clear_untrusted_proxy_headers=True,
                     trusted_proxy_headers={"x-forwarded-for", "x-forwarded-proto", "x-forwarded-host"}) if config.PUBLIC else {}
        serve(app, host=host, port=port, threads=16, channel_timeout=600, connection_limit=200,
              max_request_body_size=450 * 1024 * 1024, ident="MURAFLEX AUTOMATION", **proxy)   # online: trust the HTTPS proxy
    except ImportError:
        logging.getLogger("werkzeug").setLevel(logging.WARNING)
        app.run(host=host, port=port, debug=False, threaded=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
