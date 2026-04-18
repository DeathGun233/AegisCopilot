from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence


DEFAULT_TARGETS = (
    Path("backend/app"),
    Path("backend/tests"),
    Path("frontend/src"),
)
TEXT_SUFFIXES = {".py", ".js", ".jsx", ".ts", ".tsx", ".json", ".md", ".css", ".html"}
PLACEHOLDER_PATTERN = re.compile(r"\?{3,}")
REPLACEMENT_CHARACTER = "\ufffd"


@dataclass(frozen=True)
class Finding:
    path: Path
    line_number: int
    line: str


def _contains_cjk(text: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in text)


def _looks_like_gbk_decoded_utf8(line: str) -> bool:
    if not any(ord(char) > 127 for char in line):
        return False

    try:
        repaired = line.encode("gbk").decode("utf-8")
    except UnicodeError:
        return False

    return repaired != line and _contains_cjk(repaired)


def _iter_files(paths: Sequence[Path]) -> Iterable[Path]:
    for path in paths:
        if path.is_dir():
            for child in sorted(path.rglob("*")):
                if child.is_file() and "__pycache__" not in child.parts and child.suffix in TEXT_SUFFIXES:
                    yield child
            continue
        if path.is_file():
            yield path


def scan_paths(paths: Sequence[Path]) -> list[Finding]:
    findings: list[Finding] = []
    for path in _iter_files(paths):
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for line_number, line in enumerate(content.splitlines(), start=1):
            if (
                PLACEHOLDER_PATTERN.search(line)
                or REPLACEMENT_CHARACTER in line
                or _looks_like_gbk_decoded_utf8(line)
            ):
                findings.append(Finding(path=path, line_number=line_number, line=line.strip()))
    return findings


def main(argv: Sequence[str] | None = None) -> int:
    raw_paths = [Path(item) for item in argv] if argv else list(DEFAULT_TARGETS)
    resolved_paths = [
        path if path.is_absolute() else Path.cwd() / path
        for path in raw_paths
    ]
    findings = scan_paths(resolved_paths)
    if not findings:
        print("No placeholder corruption found.")
        return 0

    for finding in findings:
        display_path = finding.path.relative_to(Path.cwd()) if finding.path.is_relative_to(Path.cwd()) else finding.path
        print(f"{display_path}:{finding.line_number}: {finding.line}")
    print(f"Found {len(findings)} placeholder-corruption line(s).")
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
