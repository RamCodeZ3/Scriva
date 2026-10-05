from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, replace

from domain.entities.source import Source, SourceType
from domain.exceptions import DocumentBuildError
from domain.value_objects.apa_structure import APASection, APASectionType
from domain.value_objects.document_node import (
    HEADING_1,
    MARK_ITALIC,
    PARAGRAPH,
    DocumentNode,
    Mark,
    text_node,
)
from domain.value_objects.source_ref import SourceReference

_CITATION = re.compile(
    r"\[\[cite:(?P<key>[0-9a-fA-F-]{36})"
    r"(?:\|secondary=(?P<secondary>[^\]]+))?\]\]"
)
_LEADING_ARTICLES = {
    "a",
    "an",
    "the",
    "el",
    "la",
    "los",
    "las",
    "un",
    "una",
    "unos",
    "unas",
}


@dataclass(frozen=True)
class CitationResult:
    sections: list[APASection]
    references: list[SourceReference]


def resolve_citations(
    sections: list[APASection],
    sources: list[Source],
    language: str,
    existing_references: list[SourceReference] | None = None,
) -> CitationResult:
    """Resolve model citation keys and construct deterministic references."""
    usable = {
        str(source.id): source for source in sources if source.is_ready()
    }
    cited_keys = _citation_keys(sections)
    unknown = cited_keys - set(usable)
    if unknown:
        raise DocumentBuildError(
            "Generated content cites unknown or unavailable sources: "
            + ", ".join(sorted(unknown))
        )

    cited_sources = _deduplicate([usable[key] for key in cited_keys])
    suffixes = _year_suffixes(cited_sources)
    localized = language.lower().startswith("es")
    resolved = [
        _replace_section(section, usable, suffixes, localized)
        for section in sections
        if section.section_type is not APASectionType.SOURCES
    ]
    references = [
        _reference(source, suffixes.get(str(source.id), ""), localized)
        for source in cited_sources
    ]
    known = {
        (reference.url, reference.author, reference.title)
        for reference in references
    }
    document_text = " ".join(
        node.plain_text() for section in resolved for node in section.nodes
    )
    for reference in existing_references or []:
        identity = (reference.url, reference.author, reference.title)
        if identity not in known and _reference_is_cited(
            reference, document_text
        ):
            references.append(reference)
            known.add(identity)
    references.sort(key=_reference_sort_key)
    resolved.append(_sources_section(references, localized))
    return CitationResult(resolved, references)


def citation_keys(sections: list[APASection]) -> set[str]:
    return _citation_keys(sections)


def _citation_keys(sections: list[APASection]) -> set[str]:
    keys: set[str] = set()
    for section in sections:
        if section.section_type is APASectionType.SOURCES:
            continue
        for node in section.nodes:
            stored_keys = node.metadata.get("citationSourceIds", [])
            if isinstance(stored_keys, list):
                keys.update(key for key in stored_keys if isinstance(key, str))
            for match in _CITATION.finditer(node.plain_text()):
                keys.add(match.group("key"))
    return keys


def _deduplicate(sources: list[Source]) -> list[Source]:
    unique: dict[str, Source] = {}
    for source in sources:
        identity = source.canonical_url or (
            source.raw
            if source.source_type in {SourceType.WEB, SourceType.YOUTUBE}
            else str(source.id)
        )
        unique.setdefault(identity, source)
    return list(unique.values())


def _year_suffixes(sources: list[Source]) -> dict[str, str]:
    grouped: dict[tuple[str, int | None], list[Source]] = defaultdict(list)
    for source in sources:
        grouped[(_citation_author(source).casefold(), _year(source))].append(
            source
        )
    suffixes: dict[str, str] = {}
    for works in grouped.values():
        if len(works) < 2:
            continue
        ordered = sorted(works, key=lambda item: _title_sort_key(_title(item)))
        for index, source in enumerate(ordered):
            suffixes[str(source.id)] = chr(ord("a") + index)
    return suffixes


def _replace_section(
    section: APASection,
    sources: dict[str, Source],
    suffixes: dict[str, str],
    localized: bool,
) -> APASection:
    return replace(
        section,
        heading=_replace_node(section.heading, sources, suffixes, localized),
        body_nodes=tuple(
            _replace_node(node, sources, suffixes, localized)
            for node in section.body_nodes
        ),
    )


def _replace_node(
    node: DocumentNode,
    sources: dict[str, Source],
    suffixes: dict[str, str],
    localized: bool,
) -> DocumentNode:
    if node.text is not None:
        return replace(
            node,
            text=_CITATION.sub(
                lambda match: _in_text(
                    sources[match.group("key")],
                    suffixes.get(match.group("key"), ""),
                    localized,
                    match.group("secondary"),
                ),
                node.text,
            ),
        )
    matches = tuple(_CITATION.finditer(node.plain_text()))
    metadata = dict(node.metadata)
    if matches:
        metadata["citationSourceIds"] = list(
            dict.fromkeys(match.group("key") for match in matches)
        )
    return replace(
        node,
        children=tuple(
            _replace_node(child, sources, suffixes, localized)
            for child in node.children
        ),
        metadata=metadata,
    )


def _in_text(
    source: Source,
    suffix: str,
    localized: bool,
    secondary: str | None,
) -> str:
    year = _display_year(source, suffix, localized)
    consulted = f"{_citation_author(source)}, {year}"
    if secondary:
        connector = "citado en" if localized else "as cited in"
        return f"({secondary.strip()}, {connector} {consulted})"
    return f"({consulted})"


def _reference(
    source: Source, suffix: str, localized: bool
) -> SourceReference:
    return SourceReference(
        author=_reference_author(source),
        title=_title(source, localized),
        year=_year(source),
        url=_source_url(source),
        publisher=source.site_name,
        source_type=source.source_type.value,
        month=source.published_at.month if source.published_at else None,
        day=source.published_at.day if source.published_at else None,
        year_suffix=suffix,
        language="es" if localized else "en",
    )


def _sources_section(
    references: list[SourceReference], localized: bool
) -> APASection:
    title = "Referencias" if localized else "References"
    body = tuple(_reference_node(reference) for reference in references)
    if not body:
        raise DocumentBuildError(
            "Generated document contains no valid source citations."
        )
    return APASection(
        APASectionType.SOURCES,
        DocumentNode(type=HEADING_1, children=(text_node(title),)),
        body,
    )


def _reference_node(reference: SourceReference) -> DocumentNode:
    prefix, title, suffix = reference.to_apa_parts()
    return DocumentNode(
        type=PARAGRAPH,
        styles={"leftIndent": "0.5in", "firstLineIndent": "-0.5in"},
        metadata={"generatedReference": True},
        children=(
            text_node(prefix),
            text_node(title, marks=(Mark(MARK_ITALIC),)),
            text_node(suffix),
        ),
    )


def _reference_author(source: Source) -> str:
    author = (source.author or "").strip()
    if not author:
        return ""
    if "," in author or _is_group_author(author):
        return author
    parts = author.split()
    if len(parts) == 1:
        return author
    if len(parts) >= 3:
        return f"{' '.join(parts[-2:])}, {parts[0][0]}."
    return f"{parts[-1]}, {parts[0][0]}."


def _citation_author(source: Source) -> str:
    author = (source.author or "").strip()
    if not author:
        return _title(source)
    if "," in author:
        return author.split(",", 1)[0]
    if _is_group_author(author):
        return author
    parts = author.split()
    return " ".join(parts[-2:] if len(parts) >= 3 else parts[-1:])


def _is_group_author(author: str) -> bool:
    words = author.split()
    return len(words) > 3 or any(
        word.casefold() in {"staff", "team", "university", "institute"}
        for word in words
    )


def _title(source: Source, localized: bool = False) -> str:
    if source.title:
        return source.title.strip()
    if source.label:
        return source.label.strip()
    defaults = {
        SourceType.TEXT: (
            "Texto proporcionado por el usuario"
            if localized
            else "User-provided text"
        ),
        SourceType.WEB: "Página web" if localized else "Web page",
        SourceType.YOUTUBE: (
            "Video de YouTube" if localized else "YouTube video"
        ),
        SourceType.FILE: (
            "Archivo proporcionado" if localized else "Provided file"
        ),
    }
    return defaults[source.source_type]


def _year(source: Source) -> int | None:
    return source.published_at.year if source.published_at else None


def _display_year(source: Source, suffix: str, localized: bool) -> str:
    if source.published_at:
        return f"{source.published_at.year}{suffix}"
    missing = "s. f." if localized else "n.d."
    return f"{missing}-{suffix}" if suffix else missing


def _source_url(source: Source) -> str | None:
    if source.source_type not in {SourceType.WEB, SourceType.YOUTUBE}:
        return None
    return source.canonical_url or source.raw


def _reference_sort_key(reference: SourceReference) -> tuple[str, str]:
    return (
        _normalize(reference.author or reference.title),
        _title_sort_key(reference.title),
    )


def _title_sort_key(title: str) -> str:
    words = _normalize(title).split()
    if words and words[0] in _LEADING_ARTICLES:
        words = words[1:]
    return " ".join(words)


def _normalize(value: str) -> str:
    return "".join(
        character
        for character in unicodedata.normalize("NFKD", value.casefold())
        if not unicodedata.combining(character)
    )


def _reference_is_cited(reference: SourceReference, text: str) -> bool:
    missing = "s. f." if reference.language.startswith("es") else "n.d."
    year = (
        f"{reference.year}{reference.year_suffix}"
        if reference.year
        else missing
    )
    if reference.year is None and reference.year_suffix:
        year = f"{missing}-{reference.year_suffix}"
    author = reference.author or reference.title
    if reference.author and "," in reference.author:
        author = reference.author.split(",", 1)[0]
    return f"{author}, {year}" in text or f"{author} ({year})" in text
