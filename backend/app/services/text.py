from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
import re


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

    section_text = _section_text_with_context(section)
    return _chunk_section_text(
        text=section_text,
        metadata=_section_metadata(section),
        chunk_size=chunk_size,
        overlap=overlap,
    )


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
