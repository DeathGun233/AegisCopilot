from __future__ import annotations

from io import BytesIO
from pathlib import Path

from .text import normalize_text

try:
    from pypdf import PdfReader
except ModuleNotFoundError:  # pragma: no cover - depends on local environment
    PdfReader = None

try:
    from docx import Document as DocxDocument
except ModuleNotFoundError:  # pragma: no cover - depends on local environment
    DocxDocument = None


class ExtractionError(ValueError):
    pass


class ExtractionService:
    def extract(self, filename: str, content: bytes) -> str:
        suffix = Path(filename).suffix.lower()
        if suffix in {".txt", ".md", ".markdown"}:
            return self._decode_text(content)
        if suffix == ".pdf":
            return self._extract_pdf(content)
        if suffix == ".docx":
            return self._extract_docx(content)
        raise ExtractionError(f"暂不支持的文件类型：{suffix or '未知类型'}")

    @staticmethod
    def _decode_text(content: bytes) -> str:
        for encoding in ("utf-8", "utf-8-sig", "gb18030", "gbk"):
            try:
                return normalize_text(content.decode(encoding))
            except UnicodeDecodeError:
                continue
        raise ExtractionError("无法解码文本文件内容")

    @staticmethod
    def _extract_pdf(content: bytes) -> str:
        if PdfReader is None:
            raise ExtractionError("处理 PDF 需要先安装 pypdf")
        reader = PdfReader(BytesIO(content))
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
        if not text.strip():
            raise ExtractionError("PDF 文本提取结果为空")
        return normalize_text(text)

    @staticmethod
    def _extract_docx(content: bytes) -> str:
        if DocxDocument is None:
            raise ExtractionError("处理 DOCX 需要先安装 python-docx")
        document = DocxDocument(BytesIO(content))
        text = "\n".join(paragraph.text for paragraph in document.paragraphs if paragraph.text.strip())
        if not text.strip():
            raise ExtractionError("DOCX 文本提取结果为空")
        return normalize_text(text)
