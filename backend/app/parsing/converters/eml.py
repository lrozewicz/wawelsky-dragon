"""Konwerter EML (kontrakt C8c) — e-mail → HTML: temat, nagłówki, treść, załączniki."""

from __future__ import annotations

import dataclasses
import email
import email.policy
import tempfile
from pathlib import Path

from app.parsing.converters.common import finish, read_bytes
from app.parsing.converters.html_in import clean_html_document
from app.parsing.errors import ConversionFailed
from app.parsing.html import esc, paragraphs_html
from app.parsing.types import ConvertedDocument, ConvertOptions

_HEADERS = ("From", "To", "Cc", "Date")


def convert_eml(path: Path, opts: ConvertOptions) -> ConvertedDocument:
    """E-mail → `<h1>` z tematem, lista nagłówków, treść (html/plain), załączniki rejestrem."""
    msg = email.message_from_bytes(read_bytes(path), policy=email.policy.default)
    subject = msg.get("Subject")
    subject_text = str(subject) if subject is not None else ""
    parts: list[str] = [f"<h1>{esc(subject_text)}</h1>"]

    items: list[str] = []
    for header in _HEADERS:
        value = msg.get(header)
        if value is not None:
            items.append(f"<li><strong>{header}</strong>: {esc(str(value))}</li>")
    if items:
        parts.append(f"<ul>{''.join(items)}</ul>")

    body = msg.get_body(preferencelist=("html", "plain"))
    if body is not None:
        content = body.get_content()
        if body.get_content_type() == "text/html":
            parts.append(clean_html_document(content)[0])
        else:
            parts.append(paragraphs_html(content))

    # import lokalny — registry importuje convert_eml na poziomie modułu (cykl importu)
    from app.parsing.registry import convert, detect_format  # noqa: PLC0415

    warnings: list[str] = []
    for part in msg.iter_attachments():
        filename = part.get_filename()
        if not filename:
            continue  # załącznik bez nazwy — pomijany
        safe_name = Path(filename).name  # tylko nazwa pliku — ochrona przed `../`
        raw = part.get_payload(decode=True)
        payload = raw if isinstance(raw, bytes) else b""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp) / safe_name
            tmp_path.write_bytes(payload)
            try:
                fmt = detect_format(tmp_path, tmp_path.suffix)
                converted = convert(
                    tmp_path,
                    fmt,
                    dataclasses.replace(opts, vision_available=False, ocr_available=False),
                )
            except ConversionFailed as exc:
                warnings.append(f"attachment '{safe_name}' skipped: {exc}")
                continue
        parts.append(f"<h2>Attachment: {esc(safe_name)}</h2>{converted.html}")

    metadata: dict[str, str] = {}
    if subject_text:
        metadata["title"] = subject_text
    sender = msg.get("From")
    if sender is not None and str(sender):
        metadata["author"] = str(sender)
    return finish(
        "".join(parts), diagnosis="e-mail has no text", metadata=metadata, warnings=warnings
    )
