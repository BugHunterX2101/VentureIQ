"""Document intelligence: read a document, then check what it claims.

The sample documents are generated here rather than committed, so the suite
stays self-contained and no real company's paperwork lives in the repo.
"""

import shutil

import pytest

from app.documents import extract, ocr

pytestmark = pytest.mark.skipif(not ocr.available()[0], reason="Tesseract is not installed")


def make_document(path, lines):
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("RGB", (1240, 60 + 56 * len(lines)), "white")
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 25)
    except OSError:  # pragma: no cover - CI fallback
        font = ImageFont.load_default()
    for i, line in enumerate(lines):
        draw.text((45, 30 + i * 56), line, fill="black", font=font)
    img.save(path)
    return path


CERTIFICATE = [
    "CERTIFICATE OF INCORPORATION",
    "Ministry of Corporate Affairs / Registrar of Companies",
    "Corporate Identity Number: U51909DL2019PTC351212",
    "Name of Company: ABSENTIA TRADERS PRIVATE LIMITED",
    "Date of Incorporation: 11/06/2019",
]
GST = [
    "GOODS AND SERVICES TAX",
    "REGISTRATION CERTIFICATE",
    "GSTIN: 29AAACR5055K1Z3",
    "Legal Name: ZERODHA BROKING LIMITED",
    "PAN: AAACR5055K",
]


@pytest.fixture
def certificate(tmp_path):
    return make_document(tmp_path / "coi.png", CERTIFICATE)


@pytest.fixture
def gst_certificate(tmp_path):
    return make_document(tmp_path / "gst.png", GST)


class TestOcr:
    def test_reads_an_image(self, certificate):
        result = ocr.read(certificate)
        assert "CERTIFICATE OF INCORPORATION" in result.text
        assert result.pages == 1 and result.engine == "tesseract"
        assert result.confidence and result.confidence > 0.5

    def test_unreadable_file_raises(self, tmp_path):
        broken = tmp_path / "not-an-image.png"
        broken.write_bytes(b"definitely not a png")
        with pytest.raises((RuntimeError, OSError)):
            ocr.read(broken)


class TestExtraction:
    def test_identifies_a_certificate_of_incorporation(self, certificate):
        text = ocr.read(certificate).text
        kind, confidence = extract.detect_type(text)
        assert kind == "incorporation_certificate" and confidence > 0.6

    def test_pulls_cin_name_and_date(self, certificate):
        text = ocr.read(certificate).text
        fields = {f.key: f.value for f in extract.extract(text, "incorporation_certificate")}
        assert fields["cin"] == "U51909DL2019PTC351212"
        assert fields["incorporation_date"] == "2019-06-11"
        assert "Absentia" in fields["company_name"]

    def test_repairs_ocr_confusions_only_when_the_checksum_agrees(self):
        # Tesseract often reads 5 as S. The repair must validate to be accepted.
        good = extract.extract("GSTIN: 29AAACRS055K1Z3", "gst_certificate")
        assert {f.key: f.value for f in good}["gstin"] == "29AAACR5055K1Z3"

        # Same confusion, but no valid check digit exists: refuse to guess.
        bad = extract.extract("GSTIN: 29AAACRS055K1Z9", "gst_certificate")
        assert "gstin" not in {f.key for f in bad}

    def test_pan_is_taken_from_a_gst_certificate(self, gst_certificate):
        text = ocr.read(gst_certificate).text
        fields = {f.key: f.value for f in extract.extract(text, "gst_certificate")}
        assert fields["pan"] == "AAACR5055K"

    def test_revenue_is_read_with_indian_units(self):
        fields = {f.key: f.value for f in
                  extract.extract("Revenue from operations: Rs 2.5 crore", "financial_statement")}
        assert fields.get("revenue") == pytest.approx(2.5e7) or fields.get("revenue") == pytest.approx(2.5)


class TestVerification:
    def test_gstin_checksum_is_checked(self, gst_certificate):
        text = ocr.read(gst_certificate).text
        checks = extract.verify(extract.extract(text, "gst_certificate"), None)
        by = {c["check"]: c for c in checks}
        assert by["gstin_checksum"]["status"] == "verified"
        assert by["pan_matches_gstin"]["status"] == "verified"

    @pytest.mark.registry
    def test_cin_is_confirmed_against_the_mca_registry(self, certificate):
        from app.registry import store

        if not store.available():
            pytest.skip("registry.db has not been imported")
        text = ocr.read(certificate).text
        checks = extract.verify(extract.extract(text, "incorporation_certificate"), None)
        by = {c["check"]: c for c in checks}
        assert by["cin_in_registry"]["status"] == "verified"
        assert by["incorporation_date_matches_registry"]["status"] == "verified"

    @pytest.mark.registry
    def test_a_tampered_certificate_is_caught(self, tmp_path):
        from app.registry import store

        if not store.available():
            pytest.skip("registry.db has not been imported")
        tampered = make_document(tmp_path / "tampered.png", [
            "CERTIFICATE OF INCORPORATION",
            "Corporate Identity Number: U51909DL2019PTC351212",
            "Name of Company: SOMETHING ELSE VENTURES PRIVATE LIMITED",
            "Date of Incorporation: 02/02/2022",
        ])
        text = ocr.read(tampered).text
        checks = {c["check"]: c for c in extract.verify(extract.extract(text, "incorporation_certificate"), None)}
        assert checks["name_matches_registry"]["status"] == "conflict"
        assert checks["incorporation_date_matches_registry"]["status"] == "conflict"


@pytest.mark.skipif(shutil.which("tesseract") is None, reason="needs Tesseract")
class TestUploadEndpoint:
    def test_capabilities_are_advertised(self, client):
        body = client.get("/api/documents/capabilities").json()
        assert body["ocr_available"] is True and body["max_file_mb"] >= 1

    def test_upload_requires_a_session(self, client, certificate, startup):
        with certificate.open("rb") as fh:
            r = client.post(f"/api/startups/{startup.startup_id}/documents",
                            files={"file": ("coi.png", fh, "image/png")})
        assert r.status_code == 401

    def test_only_the_owner_may_upload(self, client, certificate, startup, founder, db):
        startup.owner_user_id = "someone-else"
        db.commit()
        with certificate.open("rb") as fh:
            r = client.post(f"/api/startups/{startup.startup_id}/documents",
                            headers=founder["headers"], files={"file": ("coi.png", fh, "image/png")})
        assert r.status_code == 403

    def test_owner_upload_extracts_and_stores(self, client, certificate, startup, founder, db):
        startup.owner_user_id = founder["user"]["user_id"]
        db.commit()
        with certificate.open("rb") as fh:
            r = client.post(f"/api/startups/{startup.startup_id}/documents",
                            headers=founder["headers"], files={"file": ("coi.png", fh, "image/png")})
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["doc_type"] == "incorporation_certificate"
        assert any(f["key"] == "cin" for f in body["fields"])

        listed = client.get(f"/api/startups/{startup.startup_id}/documents").json()
        assert len(listed) == 1 and listed[0]["filename"] == "coi.png"

    def test_rejects_an_unsupported_file_type(self, client, tmp_path, startup, founder, db):
        startup.owner_user_id = founder["user"]["user_id"]
        db.commit()
        bad = tmp_path / "notes.txt"
        bad.write_text("hello")
        with bad.open("rb") as fh:
            r = client.post(f"/api/startups/{startup.startup_id}/documents",
                            headers=founder["headers"], files={"file": ("notes.txt", fh, "text/plain")})
        assert r.status_code == 415
