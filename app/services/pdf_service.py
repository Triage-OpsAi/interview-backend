import textwrap
from typing import Iterable, List


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _sanitize(text: str) -> str:
    return text.encode("latin-1", errors="replace").decode("latin-1")


def _wrap_lines(lines: Iterable[str], width: int = 92) -> List[str]:
    wrapped: List[str] = []
    for line in lines:
        line = _sanitize(str(line))
        if not line:
            wrapped.append("")
            continue
        wrapped.extend(textwrap.wrap(line, width=width) or [""])
    return wrapped


def build_report_pdf(lines: Iterable[str]) -> bytes:
    wrapped = _wrap_lines(lines)
    pages = [wrapped[i : i + 52] for i in range(0, len(wrapped), 52)] or [[]]

    objects: List[bytes] = []
    page_object_numbers = []

    def add_object(payload: bytes) -> int:
        objects.append(payload)
        return len(objects)

    catalog_num = add_object(b"<< /Type /Catalog /Pages 2 0 R >>")
    pages_num = add_object(b"")
    font_num = add_object(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    for page_lines in pages:
        content_lines = ["BT", "/F1 10 Tf", "13 TL", "50 790 Td"]
        for line in page_lines:
            content_lines.append(f"({_escape(line)}) Tj")
            content_lines.append("T*")
        content_lines.append("ET")
        content = "\n".join(content_lines).encode("latin-1")
        content_num = add_object(b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream")
        page_num = add_object(
            f"<< /Type /Page /Parent {pages_num} 0 R /MediaBox [0 0 612 842] "
            f"/Resources << /Font << /F1 {font_num} 0 R >> >> /Contents {content_num} 0 R >>".encode()
        )
        page_object_numbers.append(page_num)

    kids = " ".join(f"{num} 0 R" for num in page_object_numbers)
    objects[pages_num - 1] = f"<< /Type /Pages /Kids [{kids}] /Count {len(page_object_numbers)} >>".encode()
    objects[catalog_num - 1] = b"<< /Type /Catalog /Pages 2 0 R >>"

    output = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, payload in enumerate(objects, start=1):
        offsets.append(len(output))
        output.extend(f"{index} 0 obj\n".encode())
        output.extend(payload)
        output.extend(b"\nendobj\n")

    xref_offset = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n".encode())
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode())
    output.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n".encode()
    )
    return bytes(output)
