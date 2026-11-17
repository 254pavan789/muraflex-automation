"""AI reading with Claude - tested with a fake API client that answers like the model would (no network, no key).

The fake answers from a known truth in PDF points and converts it to the pixel coordinates of the exact image the
app sent, so box mapping, the team rules, OCR cross-check, doors and the fallbacks are all checked end to end."""
import threading
from types import SimpleNamespace

import pytest

from glassx import ai, pipeline
from glassx.server import create_app

_T = threading.local()

# truth in PDF points (the picture sheet built by tests/test_ocr._picture_fm_pdf)
E1 = {"number": "1", "title": "ELEVATION / PRIVATE OFFICE 1308", "title_box": [168, 554, 400, 567],
      "drawing_box": [125, 290, 410, 570],
      "edges": [(150, ("54¼", [132, 325, 168, 342]), ('49½"', [128, 455, 180, 472])),
                (240, None, None),                                           # nothing written at this edge
                (320, None, ('49⅝"', [298, 455, 350, 472])),
                (400, None, ('50"', [378, 455, 412, 472]))],
      "panels": [(0, 1, "GSD-12", "1308", "door", [180, 388, 210, 405]),
                 (1, 2, "OGL-12", "1308-B", "glass", [265, 388, 295, 405]),
                 (2, 3, "OGL-12", "1308-C", "glass", [345, 388, 375, 405])],
      "doors": [{"panel": 0, "type": "sliding", "hinge": "unknown", "swing_45": None, "swing_90": None,
                 "closed": None}]}
E2 = {"number": "2", "title": "ELEVATION / PRIVATE OFFICE 1306", "title_box": [668, 554, 900, 567],
      "drawing_box": [625, 290, 910, 570],
      "edges": [(650, ("54 1/4", [632, 325, 668, 342]), ('50"', [628, 455, 662, 472])),
                (740, ("54 1/4", [722, 325, 758, 342]), ('49¾"', [718, 455, 770, 472])),
                (820, ("54 1/4", [802, 325, 838, 342]), ('50⅛"', [798, 455, 850, 472])),
                (900, ("54 1/4", [882, 325, 918, 342]), ('50 3/8"', [878, 455, 930, 472]))],   # OCR reads 50 1/4
      "panels": [(0, 1, "FPD-OGL", "1306", "door", [680, 388, 710, 405]),
                 (1, 2, "OGL-12", "1306-B", "by_others", [765, 388, 795, 405]),
                 (2, 3, "OGL-12", "1306-C", "glass", [845, 388, 875, 405])],
      "doors": [{"panel": 0, "type": "pivot", "hinge": "right",
                 "swing_45": ("50 1/8 (S)", [700, 200, 740, 212]), "swing_90": ("50 1/4(S)", [730, 180, 770, 192]),
                 "closed": ("49 3/4", [660, 230, 700, 242])}]}


class FakeMessages:
    def __init__(self, fail=None):
        self.fail = fail
        self.calls = []

    def create(self, **kw):
        self.calls.append(kw)
        if self.fail:
            raise RuntimeError(self.fail)
        z, x0, y0 = _T.tf
        px = lambda b: [(b[0] - x0) * z, (b[1] - y0) * z, (b[2] - x0) * z, (b[3] - y0) * z]  # noqa: E731
        tool = kw["tool_choice"]["name"]
        assert kw["tools"][0]["name"] == tool and kw["model"].startswith("claude-")
        img = kw["messages"][0]["content"][0]
        assert img["type"] == "image" and img["source"]["media_type"] == "image/png"
        if tool == "report_elevations":
            out = {"elevations": [{"number": e["number"], "title": e["title"], "title_box": px(e["title_box"]),
                                   "drawing_box": px(e["drawing_box"])} for e in (E1, E2)]}
        else:
            text = kw["messages"][0]["content"][1]["text"]
            e = E1 if "1308" in text else E2
            v = lambda t: None if not t else {"text": t[0], "box": px(t[1])}  # noqa: E731
            out = {"edges": [{"x": (x - x0) * z, "upper": v(u), "lower": v(lo)} for x, u, lo in e["edges"]],
                   "panels": [{"left_edge": a, "right_edge": b, "code": c, "tag": t, "kind": k, "tag_box": px(tb)}
                              for a, b, c, t, k, tb in e["panels"]],
                   "doors": [dict(d, **{n: v(d[n]) for n in ("swing_45", "swing_90", "closed")}) for d in e["doors"]],
                   "notes": [], "unclear": ["1308 door tag partly hidden"] if e is E1 else []}
        return SimpleNamespace(content=[SimpleNamespace(type="tool_use", input=out)],
                               usage=SimpleNamespace(input_tokens=4800, output_tokens=900))


@pytest.fixture
def fake(monkeypatch):
    msgs = FakeMessages()
    monkeypatch.setattr(ai, "CLIENT_FACTORY", lambda: SimpleNamespace(messages=msgs))
    real = ai.render

    def render(page, rect, cap=8.0):
        out = real(page, rect, cap)
        _T.tf = (out[1], out[2], out[3])
        return out
    monkeypatch.setattr(ai, "render", render)
    ai.save(model="claude-sonnet-5-5", mode="pictures", api_key="sk-ant-test-key-1234")
    return msgs


def test_fit_size_matches_the_vision_docs():
    assert ai.fit_size(1075, 1520, 1568, 1568) == (924, 1307)                    # standard tier example
    assert ai.fit_size(3840, 2160) == (2576, 1449)                                # high-resolution tier example
    assert ai.fit_size(1000, 1000) == (1000, 1000)
    w, h = ai.fit_size(9792, 6336)                                                # an FM sheet at 8x
    assert -(-w // 28) * -(-h // 28) <= 4784 and max(w, h) <= 2576


def _pdf(tmp_path):
    from tests.test_ocr import _picture_fm_pdf
    path = str(tmp_path / "raster.pdf")
    _picture_fm_pdf(path)
    return path


def test_raster_page_read_by_ai_with_team_rules(tmp_path, fake):
    r = pipeline.process_pdf(_pdf(tmp_path), use_cache=False)
    els = {e["elev"]: e for e in r["elevations"]}
    assert set(els) == {"1", "2"} and all(e.get("ai") for e in els.values())
    e1 = els["1"]
    assert [p["u"] for p in e1["points"]] == ["54 1/4"] * 4                       # one upper -> every edge
    assert [p["l"] for p in e1["points"]] == ["49 1/2", "49 9/16", "49 5/8", "50"]  # blank edge = floored average
    assert e1["name"] == "PRIVATE OFFICE 1308" and e1["room"] == "1308"
    assert [(p["tag"], p["kind"], p["export"]) for p in e1["panels"]] == [
        ("1308", "Door", False), ("1308-B", "Fixed", True), ("1308-C", "Fixed", True)]
    notes = " | ".join(e1["notes"])
    assert "Read by AI" in notes and "used at every edge" in notes and "REQUIRES HUMAN REVIEW (AI unsure)" in notes
    # boxes come back in PDF points on the right spot
    assert abs(e1["points"][0]["ubox"][0] - 132) < 1.5 and abs(e1["points"][3]["lbox"][3] - 472) < 1.5
    e2 = els["2"]
    assert [p["kind"] for p in e2["panels"]] == ["Door", "By others", "Fixed"]
    assert any("AI 50 3/8 / OCR 50 1/4" in n for n in e2["notes"])               # cross-check caught the difference
    dd = {d["tag"]: d for d in r["doors"]}
    assert dd["1308"]["type"] == "Sliding"
    p = dd["1306"]
    assert p["type"] == "Pivot" and p["hinge"] == "R"
    assert (p["pts"]["A"]["l"], p["pts"]["B"]["l"]) == ("49 3/4", "50")            # hinge right -> A = right edge
    assert (p["pts"]["C1"]["u"], p["pts"]["C1"]["l"], p["pts"]["C2"]["u"], p["pts"]["C2"]["l"]) == \
        ("54 1/4", "50 1/8", "54 1/4", "50 1/4")
    assert p["closed"]["l"] == "49 3/4"
    st = ai.status()
    assert st["usage"]["calls"] >= 3 and st["usage"]["pages"] >= 1


def test_ai_failure_keeps_the_ocr_read(tmp_path, fake):
    fake.fail = "Error code: 401 - authentication_error invalid x-api-key"
    r = pipeline.extract(pipeline.store_pdf(open(_pdf(tmp_path), "rb").read(), "raster.pdf"), 0, use_cache=False)
    assert r["method"] != "ai" and r["elevations"]                                  # OCR result still there
    assert "API key was refused" in r["ai_error"]


def test_text_pages_do_not_call_ai(tmp_path, fake):
    from glassx import synth
    path = str(tmp_path / "text.pdf")
    synth.build_fm_pdf(path, synth.reference_project())
    r = pipeline.process_pdf(path, use_cache=False)
    assert not fake.calls and all(not e.get("ai") for e in r["elevations"])


def test_ai_button_without_key(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    did = pipeline.store_pdf(open(_pdf(tmp_path), "rb").read(), "raster.pdf")
    r = pipeline.extract(did, 0, use_cache=False, ai_mode="force")
    assert r["ai_error"] == "AI reading is not set up"


def test_ai_settings_api_host_only_and_key_never_returned(fake):
    c = create_app().test_client()
    st = c.get("/api/ai/status").json
    assert st["on"] and st["key_hint"] == "…1234" and "sk-ant" not in str(st)
    other = {"REMOTE_ADDR": "192.168.9.44"}
    assert c.post("/api/ai/settings", json={"mode": "off"}, environ_base=other).status_code == 403
    assert c.post("/api/ai/test", json={}, environ_base=other).status_code == 403
    assert c.get("/api/ai/status", environ_base=other).json["can_edit"] is False
    j = c.post("/api/ai/settings", json={"api_key": "", "model": "claude-opus-5-5", "mode": "button"}).json
    assert j["key_hint"] == "…1234" and j["model"] == "claude-opus-5-5" and j["mode"] == "button"   # empty = keep
    assert c.post("/api/ai/test", json={}).json["ok"]
    assert not c.post("/api/ai/settings", json={"clear_key": True}).json["configured"]


def test_ai_button_route(tmp_path, fake):
    c = create_app().test_client()
    did = pipeline.store_pdf(open(_pdf(tmp_path), "rb").read(), "raster.pdf")
    ai.save(mode="button")                                         # not automatic: only the button calls AI
    r = c.post("/api/extract", json={"doc_id": did, "page": 0}).json
    assert r["method"] != "ai" and not fake.calls
    r = c.post("/api/extract", json={"doc_id": did, "page": 0, "ai": True}).json
    assert r["method"] == "ai" and len(r["elevations"]) == 2


def test_key_txt_in_app_folder_turns_ai_on(tmp_path, monkeypatch):
    """Drop key.txt next to run_app.bat -> AI is on; the key itself never reaches the browser."""
    from glassx import config
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(config, "BASE_DIR", str(tmp_path))
    monkeypatch.setattr(ai, "CLIENT_FACTORY", lambda: None)
    assert not ai.status()["on"]
    (tmp_path / "Key.txt").write_text("# Anthropic key for MURAFLEX\nANTHROPIC_API_KEY = sk-ant-api03-ABCDEFGHIJKLMNOPQRST-wxyz\n")
    st = ai.status()
    assert st["on"] and st["key_source"] == "Key.txt" and st["key_file"] and st["key_hint"] == "…wxyz"
    assert ai.load()["api_key"] == "sk-ant-api03-ABCDEFGHIJKLMNOPQRST-wxyz"
    ai.save(api_key="sk-ant-other-settings-key-0000")                  # the file still wins
    assert ai.status()["key_hint"] == "…wxyz"
    j = create_app().test_client().get("/api/ai/status").json
    assert j["on"] and "ABCDEFGH" not in str(j)
    (tmp_path / "Key.txt").write_text("")                              # empty file -> back to the saved key
    assert ai.status()["key_hint"] == "…0000"


def test_vector_page_gaps_filled_by_ai_without_touching_text_values():
    res = {"elevations": [{"elev": "1", "title_box": [100, 500, 300, 512], "notes": [], "points": [
        {"x": 100, "u": "48", "l": "57"}, {"x": 200, "u": "48", "l": ""}, {"x": 300, "u": "", "l": "57 1/4"}],
        "panels": [{"pts": [0, 1], "L": {"u": "48", "l": "57"}, "R": {"u": "48", "l": ""}},
                   {"pts": [1, 2], "L": {"u": "48", "l": ""}, "R": {"u": "", "l": "57 1/4"}}]}]}
    assert ai.weak(res)
    out = {"elevations": [{"elev": "1", "title_box": [100, 500, 300, 512], "points": [
        {"x": 101, "u": "48", "l": "60", "lbox": [1, 1, 2, 2]},                     # text has 57: must stay 57
        {"x": 203, "u": "48", "l": "57 1/8", "lbox": [190, 400, 220, 410], "l_raw": "57 1/8 in"},
        {"x": 298, "u": "48 1/16", "l": "57 1/4", "ubox": [290, 300, 310, 310]}]}]}
    assert ai.fill_gaps(res, out) == 2
    e = res["elevations"][0]
    assert [(p["u"], p["l"]) for p in e["points"]] == [("48", "57"), ("48", "57 1/8"), ("48 1/16", "57 1/4")]
    assert e["panels"][0]["R"] == {"u": "48", "l": "57 1/8"} and e["panels"][1]["R"]["u"] == "48 1/16"
    assert "Read by AI where the text had no value (2): L2 57 1/8, U3 48 1/16" in e["notes"][0]
    assert not ai.weak({"elevations": [{"points": [{"u": "48", "l": "57"}] * 6}]})
