"""Turn an uploaded document into text, with a confidence figure.

Tesseract does the reading; PDFs are rasterised with poppler's `pdftoppm`,
which ships with the same Homebrew/apt package the OCR service already needs.
Both are optional at import time: without them the API returns a clear
"OCR unavailable" instead of failing at startup.

A born-digital PDF (one with a real text layer) is read directly, which is
both faster and far more accurate than rasterising it first.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

MAX_PAGES = 8
DPI = 200


@dataclass
class OcrResult:
    text: str
    confidence: float | None       # 0-1, Tesseract's mean word confidence
    pages: int
    engine: str
    warnings: list[str] = field(default_factory=list)


def available() -> tuple[bool, str]:
    if shutil.which("tesseract") is None:
        return False, "Tesseract is not installed (brew install tesseract / apt install tesseract-ocr)"
    try:
        import pytesseract  # noqa: F401
    except ImportError:
        return False, "The pytesseract package is not installed"
    return True, "ready"


def _pdf_text_layer(path: Path) -> str:
    """Text already inside the PDF, if any — no OCR needed."""
    if shutil.which("pdftotext") is None:
        return ""
    try:
        out = subprocess.run(
            ["pdftotext", "-l", str(MAX_PAGES), str(path), "-"],
            capture_output=True, timeout=60, check=False,
        )
        return out.stdout.decode("utf-8", errors="replace")
    except (subprocess.SubprocessError, OSError):
        return ""


def _pdf_to_images(path: Path, out_dir: Path) -> list[Path]:
    if shutil.which("pdftoppm") is None:
        raise RuntimeError("poppler's pdftoppm is not installed, so PDFs cannot be rasterised")
    subprocess.run(
        ["pdftoppm", "-png", "-r", str(DPI), "-l", str(MAX_PAGES), str(path), str(out_dir / "page")],
        capture_output=True, timeout=180, check=True,
    )
    return sorted(out_dir.glob("page*.png"))


def _ocr_image(path: Path) -> tuple[str, float | None]:
    import pytesseract
    from PIL import Image

    with Image.open(path) as img:
        img = img.convert("L")  # greyscale: better contrast for scans
        text = pytesseract.image_to_string(img)
        try:
            data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)
            scores = [int(c) for c in data.get("conf", []) if str(c).lstrip("-").isdigit() and int(c) >= 0]
            confidence = (sum(scores) / len(scores) / 100) if scores else None
        except (pytesseract.TesseractError, ValueError):
            confidence = None
    return text, confidence


def read(path: Path) -> OcrResult:
    """Extract text from a PDF or image."""
    ok, why = available()
    suffix = path.suffix.lower()
    warnings: list[str] = []

    if suffix == ".pdf":
        embedded = _pdf_text_layer(path)
        if len(re.sub(r"\s", "", embedded)) > 200:
            pages = embedded.count("\f") or 1
            return OcrResult(embedded, 0.99, min(pages, MAX_PAGES), "pdf text layer")
        if not ok:
            raise RuntimeError(why)
        with tempfile.TemporaryDirectory() as tmp:
            images = _pdf_to_images(path, Path(tmp))
            if not images:
                raise RuntimeError("That PDF has no readable pages")
            texts, confs = [], []
            for image in images[:MAX_PAGES]:
                text, conf = _ocr_image(image)
                texts.append(text)
                if conf is not None:
                    confs.append(conf)
            if len(images) > MAX_PAGES:
                warnings.append(f"Only the first {MAX_PAGES} pages were read")
            return OcrResult("\n\f\n".join(texts), (sum(confs) / len(confs)) if confs else None,
                             min(len(images), MAX_PAGES), "tesseract", warnings)

    if not ok:
        raise RuntimeError(why)
    text, conf = _ocr_image(path)
    return OcrResult(text, conf, 1, "tesseract", warnings)
