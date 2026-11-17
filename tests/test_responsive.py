"""v4.9 responsive web app: static checks of the page + (optional) real-browser checks on phone / tablet / desktop sizes.

The browser part needs Playwright + Chrome/Chromium (pip install playwright; playwright install chromium) and is skipped
otherwise. It drives the real app: open a PDF, edit a cell, fill a cell from the drawing, switch views, export."""
import os
import re
import threading

import pytest

from glassx import synth
from glassx.server import create_app

WEB = os.path.join(os.path.dirname(__file__), "..", "glassx", "web", "index.html")


def _html():
    return create_app().test_client().get("/").data.decode("utf-8")


def test_viewport_and_breakpoints():
    h = _html()
    assert 'name="viewport"' in h and "width=device-width" in h and "viewport-fit=cover" in h
    for bp in ("max-width:1100px", "max-width:899px", "orientation:landscape", "max-width:599px", "pointer:coarse",
               "min-width:2200px", "@container rp"):
        assert bp in h, bp
    for el in ('id="vnav"', 'id="gut"', 'id="bMore"', 'id="mmenu"', 'id="pickbar"', 'id="rMin"'):
        assert el in h, el


def test_every_id_used_by_the_script_exists():
    h = open(WEB, encoding="utf-8").read()
    markup, script = h.split("<script>", 1)
    ids = set(re.findall(r'id="([\w-]+)"', markup))
    used = set(re.findall(r"\$\('#([\w-]+)['\s.]", script))
    missing = {u for u in used if u not in ids and u not in ("rsY", "rsN", "dAddAny", "rdr")}   # created by the script
    assert not missing, missing


# ---------------------------------------------------------------- real browser (optional)
def _browser():
    pw = pytest.importorskip("playwright.sync_api")
    p = pw.sync_playwright().start()
    for kw in ({}, {"channel": "chrome"}, {"executable_path": "/usr/bin/google-chrome"}):
        try:
            return p, p.chromium.launch(args=["--no-sandbox"], **kw)
        except Exception:
            continue
    p.stop()
    pytest.skip("no Chrome / Chromium for Playwright")


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    from werkzeug.serving import make_server
    srv = make_server("127.0.0.1", 0, create_app(), threaded=True)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    pdf = tmp_path_factory.mktemp("r") / "14002 FM.pdf"
    synth.build_fm_pdf(str(pdf), synth.reference_project())
    yield f"http://127.0.0.1:{srv.server_port}", str(pdf)
    srv.shutdown()


@pytest.mark.parametrize("w,h,touch", [(375, 667, True), (844, 390, True), (768, 1024, True), (1024, 768, True),
                                       (1366, 1024, True), (1280, 720, False), (1920, 1080, False)])
def test_app_works_on_every_screen(server, w, h, touch):
    base, pdf = server
    p, b = _browser()
    try:
        ctx = b.new_context(viewport={"width": w, "height": h}, has_touch=touch, is_mobile=touch and w < 900,
                            accept_downloads=True, reduced_motion="reduce")
        pg = ctx.new_page()
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.goto(base)
        pg.evaluate("enter('glass')")
        pg.set_input_files("#file", pdf)
        pg.wait_for_function("F() && !F().busy && !document.querySelector('#bExport').disabled", timeout=60000)
        pg.wait_for_timeout(2600)                                         # reading summary closes
        narrow = pg.evaluate("NARROW.matches")
        if narrow:
            pg.evaluate("setView('split')")
        assert pg.evaluate("document.documentElement.scrollWidth<=innerWidth"), "page scrolls sideways"
        for sel in ("#bExport", "#swG", "#swD", "#bOpen", "#bMore" if narrow else "#bHelp"):
            assert pg.evaluate(f"(()=>{{const r=document.querySelector('{sel}').getBoundingClientRect();"
                               f"return r.width>0&&r.right<=innerWidth+1&&r.bottom<=innerHeight+1}})()"), sel
        # edit a value -> stored as a fraction, total follows
        cell = pg.locator("#list input[data-f='L.u']").first
        cell.fill("50 1/4")
        cell.press("Enter")
        pg.wait_for_timeout(200)
        assert pg.evaluate("gEls(F())[0].panels.find(p=>p.kind!=='Door').L.u") == "50 1/4"
        # click / tap a value on the drawing fills the focused cell
        pg.locator("#list input[data-f='L.l']").first.focus()
        box = pg.evaluate("""(()=>{const v=document.querySelector('#viewer').getBoundingClientRect();
          const o=[...document.querySelectorAll('#ovs .ov.cand,#ovs .ov.l,#ovs .ov.u')].find(o=>{const r=o.getBoundingClientRect();
          return r.width&&r.top>v.top&&r.bottom<v.bottom&&r.left>v.left&&r.right<v.right});
          if(!o)return null;const r=o.getBoundingClientRect();return [r.x+r.width/2,r.y+r.height/2,o.dataset.v]})()""")
        assert box, "no value box visible on the drawing"
        (pg.touchscreen.tap if touch else pg.mouse.click)(box[0], box[1])
        pg.wait_for_timeout(200)
        assert pg.evaluate("gEls(F())[0].panels.find(p=>p.kind!=='Door').L.l") == box[2]
        pg.evaluate("setFill(null)")
        if narrow:                                                        # Drawing / Sheet views
            pg.evaluate("setView('sheet')")
            assert pg.evaluate("document.querySelector('#viewer').offsetWidth") == 0
            pg.evaluate("setView('draw')")
            assert pg.evaluate("document.querySelector('#right').offsetWidth") == 0
            pg.evaluate("setView('split')")
        pg.evaluate("setMode('door')")
        pg.wait_for_timeout(200)
        assert pg.evaluate("document.documentElement.scrollWidth<=innerWidth"), "DOOR: page scrolls sideways"
        with pg.expect_download() as d:
            pg.locator("#bExport").click()
        assert d.value.suggested_filename == "14002 FM.xlsx"
        assert not errs, errs
        ctx.close()
    finally:
        b.close()
        p.stop()
