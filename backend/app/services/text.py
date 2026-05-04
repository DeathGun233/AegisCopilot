from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
import re

from .logistics_metadata import extract_logistics_metadata


CHINESE_NUMERAL = "一二三四五六七八九十百千万"


@dataclass(frozen=True)
class StructuredTextChunk:
    text: str
    metadata: dict[str, Any]


@dataclass
class _Section:
    title: str
    marker: str
    level: int
    ordinal: int
    parent: "_Section | None" = None
    content_lines: list[str] = field(default_factory=list)
    children: list["_Section"] = field(default_factory=list)

    @property
    def path_titles(self) -> list[str]:
        if self.parent is None or self.parent.level == 0:
            return [self.title] if self.title else []
        return [*self.parent.path_titles, self.title]

    def render(self, include_children: bool = True) -> str:
        lines: list[str] = []
        if self.marker or self.title:
            lines.append(f"{self.marker}{self.title}".strip())
        lines.extend(self.content_lines)
        if include_children:
            for child in self.children:
                child_text = child.render(include_children=True)
                if child_text:
                    if lines and lines[-1] != "":
                        lines.append("")
                    lines.extend(child_text.splitlines())
        return normalize_text("\n".join(lines))


def normalize_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    for token in re.findall(r"[\w\u4e00-\u9fff]+", text):
        normalized = token.lower()
        if re.fullmatch(r"[\u4e00-\u9fff]+", normalized):
            tokens.extend(list(normalized))
            if len(normalized) > 1:
                tokens.extend(normalized[index : index + 2] for index in range(len(normalized) - 1))
        else:
            tokens.append(normalized)
    return tokens


def split_into_chunks(text: str, chunk_size: int = 900, overlap: int = 120) -> list[str]:
    normalized = normalize_text(text)
    if len(normalized) <= chunk_size:
        return [normalized]
    chunks: list[str] = []
    start = 0
    while start < len(normalized):
        hard_end = min(len(normalized), start + chunk_size)
        end = _find_chunk_boundary(normalized, start, hard_end, chunk_size)
        chunks.append(normalized[start:end].strip())
        if end >= len(normalized):
            break
        start = max(end - overlap, start + 1)
    return [chunk for chunk in chunks if chunk]


def split_into_structured_chunks(text: str, chunk_size: int = 900, overlap: int = 120) -> list[StructuredTextChunk]:
    normalized = normalize_text(text)
    if not normalized:
        return []

    root = _parse_sections(normalized)
    if not root.children:
        return [
            StructuredTextChunk(text=chunk, metadata=_fallback_metadata(index))
            for index, chunk in enumerate(split_into_chunks(normalized, chunk_size, overlap), start=1)
        ]

    chunks: list[StructuredTextChunk] = []
    if normalize_text("\n".join(root.content_lines)):
        chunks.extend(
            _chunk_section_text(
                text=normalize_text("\n".join(root.content_lines)),
                metadata=_fallback_metadata(0),
                chunk_size=chunk_size,
                overlap=overlap,
            )
        )

    for section in root.children:
        chunks.extend(_section_to_chunks(section, chunk_size=chunk_size, overlap=overlap))

    return [chunk for chunk in chunks if chunk.text]


def _parse_sections(text: str) -> _Section:
    root = _Section(title="", marker="", level=0, ordinal=0)
    current = root
    ordinal = 0

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            current.content_lines.append("")
            continue

        heading = _match_section_heading(line)
        if heading is None:
            current.content_lines.append(line)
            continue

        level, marker, title = heading
        ordinal += 1
        while current.parent is not None and current.level >= level:
            current = current.parent
        section = _Section(
            title=title,
            marker=marker,
            level=level,
            ordinal=ordinal,
            parent=current,
        )
        current.children.append(section)
        current = section

    return root


def _match_section_heading(line: str) -> tuple[int, str, str] | None:
    if len(line) > 120:
        return None

    markdown_heading = re.match(r"^(?P<marker>#{1,6})\s+(?P<title>.+?)\s*#*$", line)
    if markdown_heading:
        title = markdown_heading.group("title").strip()
        if title:
            return len(markdown_heading.group("marker")), "", title

    patterns: list[tuple[int, str]] = [
        (1, rf"^(?P<marker>[{CHINESE_NUMERAL}]+[、.．])\s*(?P<title>.+)$"),
        (1, rf"^(?P<marker>第[0-9{CHINESE_NUMERAL}]+条)\s*(?P<title>.+)$"),
        (2, rf"^(?P<marker>[（(][{CHINESE_NUMERAL}]+[）)])\s*(?P<title>.+)$"),
        (3, r"^(?P<marker>\d+[.．、])\s*(?P<title>.+)$"),
        (4, r"^(?P<marker>[（(]\d+[）)])\s*(?P<title>.+)$"),
    ]
    for level, pattern in patterns:
        matched = re.match(pattern, line)
        if not matched:
            continue
        title = matched.group("title").strip()
        if not title:
            return None
        marker = matched.group("marker")
        if marker.startswith("第") and marker.endswith("条"):
            return level, "", f"{marker} {title}"
        return level, marker, title
    return None


def _section_to_chunks(section: _Section, *, chunk_size: int, overlap: int) -> list[StructuredTextChunk]:
    if section.level == 1 and section.children:
        chunks = [
            StructuredTextChunk(
                text=section.render(include_children=False),
                metadata=_section_metadata(section),
            )
        ]
        for child in section.children:
            chunks.extend(_section_to_chunks(child, chunk_size=chunk_size, overlap=overlap))
        return chunks

    if section.children and not section.marker and not normalize_text("\n".join(section.content_lines)):
        chunks: list[StructuredTextChunk] = []
        for child in section.children:
            chunks.extend(_section_to_chunks(child, chunk_size=chunk_size, overlap=overlap))
        return chunks

    block_chunks = _section_content_block_chunks(section, chunk_size=chunk_size, overlap=overlap)
    if block_chunks:
        if section.children:
            for child in section.children:
                block_chunks.extend(_section_to_chunks(child, chunk_size=chunk_size, overlap=overlap))
        return block_chunks

    section_text = _section_text_with_context(section)
    return _chunk_section_text(
        text=section_text,
        metadata=_section_metadata(section),
        chunk_size=chunk_size,
        overlap=overlap,
    )


def _section_content_block_chunks(section: _Section, *, chunk_size: int, overlap: int) -> list[StructuredTextChunk]:
    metadata = _section_metadata(section)
    lines = list(section.content_lines)
    chunks: list[StructuredTextChunk] = []
    paragraph: list[str] = []
    index = 0
    table_count = 0

    def flush_paragraph() -> None:
        paragraph_text = normalize_text("\n".join(paragraph))
        if not paragraph_text:
            paragraph.clear()
            return
        chunks.extend(
            _chunk_section_text(
                text=normalize_text(f"{_section_path(section)}\n{paragraph_text}"),
                metadata={**metadata, "block_type": "paragraph"},
                chunk_size=chunk_size,
                overlap=overlap,
            )
        )
        paragraph.clear()

    while index < len(lines):
        line = lines[index].strip()
        if _is_markdown_table_row(line):
            flush_paragraph()
            table_lines: list[str] = []
            while index < len(lines) and _is_markdown_table_row(lines[index].strip()):
                table_lines.append(lines[index].strip())
                index += 1
            table_count += 1
            chunks.extend(_markdown_table_to_chunks(table_lines, section, metadata, table_count))
            continue
        if _is_markdown_list_item(line):
            flush_paragraph()
            list_lines: list[str] = []
            while index < len(lines) and _is_markdown_list_item(lines[index].strip()):
                list_lines.append(lines[index].strip())
                index += 1
            list_text = normalize_text(f"{_section_path(section)}\n" + "\n".join(list_lines))
            chunks.append(
                StructuredTextChunk(
                    text=list_text,
                    metadata={**metadata, "block_type": "list"},
                )
            )
            continue
        paragraph.append(lines[index])
        index += 1

    flush_paragraph()
    return chunks


def _markdown_table_to_chunks(
    table_lines: list[str],
    section: _Section,
    metadata: dict[str, Any],
    table_index: int,
) -> list[StructuredTextChunk]:
    if len(table_lines) < 2:
        return []
    headers = _markdown_table_cells(table_lines[0])
    row_lines = table_lines[1:]
    if row_lines and _is_markdown_table_separator(row_lines[0]):
        row_lines = row_lines[1:]
    table_name = section.title or _section_path(section) or f"table-{table_index}"
    chunks: list[StructuredTextChunk] = []
    for row_index, row_line in enumerate(row_lines, start=1):
        cells = _markdown_table_cells(row_line)
        if not cells:
            continue
        row_pairs = [
            f"{header}：{cells[cell_index]}"
            for cell_index, header in enumerate(headers)
            if header and cell_index < len(cells) and cells[cell_index]
        ]
        row_id = _stable_table_row_id(section, table_name, row_pairs, row_index)
        text = normalize_text(
            "\n".join(
                [
                    f"章节：{_section_path(section)}",
                    f"表格：{table_name}",
                    *row_pairs,
                ]
            )
        )
        chunks.append(
            StructuredTextChunk(
                text=text,
                metadata={
                    **metadata,
                    "block_type": "table_row",
                    "table_name": table_name,
                    "row_id": row_id,
                    "table_row_index": row_index,
                },
            )
        )
    return chunks


def _is_markdown_table_row(line: str) -> bool:
    return line.startswith("|") and line.endswith("|") and line.count("|") >= 2


def _is_markdown_table_separator(line: str) -> bool:
    cells = _markdown_table_cells(line)
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell.strip()) for cell in cells)


def _markdown_table_cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _is_markdown_list_item(line: str) -> bool:
    return bool(re.match(r"^([-*+]|\d+[.)])\s+\S", line))


def _stable_table_row_id(section: _Section, table_name: str, row_pairs: list[str], row_index: int) -> str:
    row_text = "\n".join([_section_path(section), table_name, *row_pairs])
    metadata = extract_logistics_metadata(row_text)
    parts: list[str] = []
    country = str(metadata.get("country", "")).strip().lower()
    if country:
        parts.append(country)
    elif metadata.get("region"):
        parts.append(_slug_text(str(metadata["region"])))

    incoterm = str(metadata.get("incoterm", "")).strip().lower()
    channel = str(metadata.get("channel", "")).strip().lower()
    if incoterm:
        parts.append(incoterm)
    elif channel:
        parts.append(_slug_text(channel))

    category = str(metadata.get("product_category", ""))
    fee_slug = _fee_slug(row_text)
    if category:
        parts.append(_category_slug(category))
    elif fee_slug:
        parts.append(fee_slug)

    if len(parts) >= 2:
        return "row-" + "-".join(item for item in parts if item)
    return f"table-{_slug_text(table_name) or 'table'}-row-{row_index}"


def _category_slug(category: str) -> str:
    mapping = {
        "带电": "battery",
        "纯电池": "battery",
        "液体": "liquid",
        "粉末": "powder",
        "食品": "food",
        "化妆品": "cosmetics",
        "纺织品": "textile",
        "普货": "general",
    }
    return mapping.get(category, _slug_text(category))


def _fee_slug(text: str) -> str:
    if "偏远附加费" in text or "偏远" in text:
        return "remote-fee"
    if "燃油" in text:
        return "fuel-fee"
    if "超重" in text:
        return "overweight-fee"
    return ""


def _slug_text(text: str) -> str:
    ascii_text = re.sub(r"[^a-zA-Z0-9]+", "-", text.lower()).strip("-")
    if ascii_text:
        return ascii_text
    mapping = {
        "欧盟": "eu",
        "欧洲": "eu",
        "北美": "north-america",
    }
    for key, value in mapping.items():
        if key in text:
            return value
    return ""


def _section_text_with_context(section: _Section) -> str:
    rendered = section.render(include_children=True)
    path = _section_path(section)
    if path and path not in rendered:
        return normalize_text(f"{path}\n{rendered}")
    return rendered


def _chunk_section_text(
    *,
    text: str,
    metadata: dict[str, Any],
    chunk_size: int,
    overlap: int,
) -> list[StructuredTextChunk]:
    normalized = normalize_text(text)
    soft_limit = max(chunk_size, int(chunk_size * 1.4))
    if len(normalized) <= soft_limit:
        return [StructuredTextChunk(text=normalized, metadata=metadata)]

    parts = split_into_chunks(normalized, chunk_size=chunk_size, overlap=overlap)
    total = len(parts)
    return [
        StructuredTextChunk(
            text=part,
            metadata={**metadata, "chunk_part_index": index, "chunk_part_count": total},
        )
        for index, part in enumerate(parts, start=1)
    ]


def _section_metadata(section: _Section) -> dict[str, Any]:
    path_titles = section.path_titles
    parent_path = " > ".join(path_titles[:-1])
    return {
        "section_path": " > ".join(path_titles),
        "section_path_parts": path_titles,
        "section_title": section.title,
        "section_level": section.level,
        "section_index": section.ordinal,
        "section_marker": section.marker,
        "section_parent_path": parent_path,
        "section_root_title": path_titles[0] if path_titles else section.title,
    }


def _fallback_metadata(index: int) -> dict[str, Any]:
    return {
        "section_path": "",
        "section_path_parts": [],
        "section_title": "",
        "section_level": 0,
        "section_index": index,
    }


def _section_path(section: _Section) -> str:
    return " > ".join(section.path_titles)


def _find_chunk_boundary(text: str, start: int, hard_end: int, chunk_size: int) -> int:
    if hard_end >= len(text):
        return hard_end

    min_end = min(hard_end, start + max(int(chunk_size * 0.65), 1))
    boundary_candidates = [
        text.rfind("\n\n", min_end, hard_end),
        text.rfind("\n", min_end, hard_end),
        text.rfind("。", min_end, hard_end),
        text.rfind("；", min_end, hard_end),
    ]
    boundary = max(boundary_candidates)
    if boundary >= min_end:
        return boundary + 1
    return hard_end
