import io
import zipfile

from glassx import synth
from glassx.server import create_app


def test_end_to_end_api(tmp_path):
    path = tmp_path / "14002 FM.pdf"
    synth.build_fm_pdf(str(path), synth.reference_project())
    c = create_app().test_client()
    assert c.get("/api/health").json["ok"]
    assert b"MURAFLEX AUTOMATION" in c.get("/").data
    r = c.post("/api/open", data={"file": (open(path, "rb"), "14002 FM.pdf")}, content_type="multipart/form-data").json
    assert len(r["pages"]) == 4
    els = []
    for p in range(4):
        els += c.post("/api/extract", json={"doc_id": r["doc_id"], "page": p}).json["elevations"]
    assert len(els) == 6
    assert c.get(f"/api/page/{r['doc_id']}/1?w=800").status_code == 200
    x = c.post("/api/export", json={"pdf_name": "14002 FM.pdf", "elevations": els})
    assert x.status_code == 200 and "14002 FM.xlsx" in x.headers["Content-Disposition"]
    z = c.post("/api/export_zip", json={"files": [{"pdf_name": "a.pdf", "elevations": els},
                                                   {"pdf_name": "b.pdf", "elevations": els}]})
    assert sorted(zipfile.ZipFile(io.BytesIO(z.data)).namelist()) == ["a.xlsx", "b.xlsx"]
    assert c.post(f"/api/session/{r['doc_id']}", json={"els": els}).json["ok"]
    assert len(c.get(f"/api/session/{r['doc_id']}").json["els"]) == 6


def test_rejects_bad_input():
    c = create_app().test_client()
    assert c.post("/api/extract", json={"doc_id": "../../etc", "page": 0}).status_code == 400
    assert c.post("/api/open", data={"file": (io.BytesIO(b"hello"), "x.pdf")},
                  content_type="multipart/form-data").status_code == 400


def test_office_network_only():
    """Other office PCs may connect (private addresses); anything else is refused."""
    c = create_app().test_client()
    for ip in ("127.0.0.1", "192.168.8.87", "192.168.9.20", "10.4.0.7", "172.20.1.1"):
        assert c.get("/api/health", environ_base={"REMOTE_ADDR": ip}).status_code == 200, ip
    for ip in ("8.8.8.8", "203.0.113.5"):
        assert c.get("/api/health", environ_base={"REMOTE_ADDR": ip}).status_code == 403, ip


def test_netinfo_and_share_urls(monkeypatch):
    from glassx import config, netinfo
    monkeypatch.setattr(config, "HOST", "0.0.0.0")
    monkeypatch.setattr(netinfo, "lan_ips", lambda: ["192.168.8.87"])
    monkeypatch.setattr(netinfo, "host_names", lambda: ["PC-PAVAN", "PC-PAVAN.flatworldlocal.com"])
    j = create_app().test_client().get("/api/netinfo", base_url="http://127.0.0.1:8080").json
    assert j["shared"] and j["urls"] == ["http://192.168.8.87:8080", "http://PC-PAVAN:8080",
                                         "http://PC-PAVAN.flatworldlocal.com:8080"]
    assert netinfo.is_allowed("::ffff:192.168.8.20", netinfo.allowed_networks())
    assert not netinfo.is_allowed("::ffff:8.8.8.8", netinfo.allowed_networks())


def test_public_online_mode(monkeypatch):
    """GLASS_PUBLIC=1 (Render): anyone may use it, nobody can set the API key, the Team link is the site address."""
    from glassx import config
    monkeypatch.setattr(config, "PUBLIC", True)
    c = create_app().test_client()
    hdr = {"X-Forwarded-For": "8.8.8.8", "X-Forwarded-Proto": "https", "X-Forwarded-Host": "muraflex.onrender.com"}
    env = {"REMOTE_ADDR": "10.1.2.3"}
    assert c.get("/api/health", headers=hdr, environ_base=env).status_code == 200
    assert c.get("/", headers=hdr, environ_base=env).status_code == 200
    n = c.get("/api/netinfo", headers=hdr, environ_base=env).json
    assert n["shared"] and n["urls"] == ["https://muraflex.onrender.com"]
    assert c.post("/api/ai/settings", json={"api_key": "sk-x"}, headers=hdr, environ_base=env).status_code == 403
    assert c.post("/api/ai/settings", json={"api_key": "sk-x"}, environ_base={"REMOTE_ADDR": "127.0.0.1"}).status_code == 403
    assert c.get("/api/ai/status", headers=hdr, environ_base=env).json["can_edit"] is False


def test_online_ignores_api_key_unless_switched_on(monkeypatch):
    from glassx import ai, config
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-1234")
    monkeypatch.setattr(config, "PUBLIC", True)
    monkeypatch.setattr(config, "AI_ONLINE", False)
    assert ai.load()["api_key"] == "" and not ai.configured()
    monkeypatch.setattr(config, "AI_ONLINE", True)
    assert ai.load()["api_key"] == "sk-ant-test-1234"
    monkeypatch.setattr(config, "PUBLIC", False)
    assert ai.load()["api_key"] == "sk-ant-test-1234"            # office version unchanged


def test_scanned_page_on_server_without_ocr_says_so(tmp_path, monkeypatch):
    """A tiny online server cannot OCR: the scanned page gets a clear note instead of silently showing nothing."""
    import pymupdf
    from glassx import config, ocr, pipeline
    src = tmp_path / "fm.pdf"
    synth.build_fm_pdf(str(src), synth.reference_project())
    d, out = pymupdf.open(str(src)), pymupdf.open()
    for p in d:
        np_ = out.new_page(width=p.rect.width, height=p.rect.height)
        np_.insert_image(np_.rect, pixmap=p.get_pixmap(dpi=60))
    scan = tmp_path / "scan.pdf"
    out.save(str(scan))
    monkeypatch.setattr(config, "OCR_MODE", "off")
    monkeypatch.setattr(ocr, "_ENGINE", None)
    monkeypatch.setattr(ocr, "_ERR", None)
    assert not ocr.available() and "switched off" in ocr.disabled_reason()
    did = pipeline.store_pdf(scan.read_bytes(), "scan.pdf")
    r = pipeline.extract(did, 1, use_cache=False)
    assert r["elevations"] == [] and r["ocr_off"] and any("Scanned" in n for n in r["notes"])
    monkeypatch.setattr(config, "OCR_MODE", "auto")
    monkeypatch.setattr(ocr, "_limits", lambda: (512 * 1024 * 1024, 0.1))       # Render free plan
    assert "512 MB" in ocr.disabled_reason()
    monkeypatch.setattr(ocr, "_limits", lambda: (16 * 1024 ** 3, 2.0))          # Hugging Face free CPU Space
    assert ocr.disabled_reason() == ""
    monkeypatch.setattr(ocr, "_ERR", None)


def test_sample_pdf_endpoint():
    r = create_app().test_client().get("/api/sample")
    assert r.status_code == 200 and r.data[:4] == b"%PDF" and "Demo" in r.headers["X-Name"]
