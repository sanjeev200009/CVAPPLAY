from __future__ import annotations

import os

from .convex_api import ConvexClient
from .config import settings


def extract_cv_text(pdf_path: str) -> str:
    import pdfplumber

    text_parts: list[str] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            extracted = page.extract_text()
            if extracted:
                text_parts.append(extracted)
    return "\n\n".join(text_parts).strip()


def load_cv() -> str:
    """Returns the parsed CV text, cached in .cache/cv.txt."""
    cache = os.path.join(os.path.dirname(__file__), "..", ".cache", "cv.txt")
    cache = os.path.normpath(cache)
    if os.path.exists(cache):
        with open(cache, "r", encoding="utf-8") as fh:
            return fh.read()
    text = extract_cv_text(settings.cv_pdf_path)
    os.makedirs(os.path.dirname(cache), exist_ok=True)
    with open(cache, "w", encoding="utf-8") as fh:
        fh.write(text)
    return text


def register_cv_version(client: ConvexClient) -> str:
    """Stores the parsed CV in Convex resume_versions; returns the CV text."""
    text = load_cv()
    client.mutation(
        "mutations:insertResumeVersion",
        {
            "version_label": settings.cv_version_label,
            "content_text": text[:20000],
            "active": True,
        },
    )
    return text