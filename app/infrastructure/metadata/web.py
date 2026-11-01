from __future__ import annotations

import json
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from domain.value_objects.bib_metadata import BibMetadata

from infrastructure.metadata.common import clean, logger, put, set_date


def _objects(value: object):
    if isinstance(value, list):
        for item in value:
            yield from _objects(item)
    elif isinstance(value, dict):
        yield value
        yield from _objects(value.get("@graph"))


def _names(value: object) -> str | None:
    if isinstance(value, list):
        return (
            "; ".join(filter(None, (_names(item) for item in value))) or None
        )
    if isinstance(value, dict):
        return clean(value.get("name"))
    return clean(value)


def read_web(meta: BibMetadata, html: str, url: str) -> None:
    soup = BeautifulSoup(html, "html.parser")

    def tag(name: str) -> str | None:
        found = soup.find("meta", attrs={"name": name}) or soup.find(
            "meta", attrs={"property": name}
        )
        return clean(found.get("content")) if found else None

    put(meta, "title", tag("og:title"), "html_meta")
    put(meta, "author", tag("author"), "html_meta")
    set_date(meta, tag("article:published_time"), "html_meta")
    put(meta, "site_name", tag("og:site_name"), "html_meta")
    canonical = soup.find("link", rel="canonical")
    put(
        meta,
        "url",
        urljoin(url, canonical.get("href") or url) if canonical else url,
        "html_meta",
    )
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            objects = _objects(json.loads(script.string or script.get_text()))
            for item in objects:
                # Ignore navigation and organization-only objects.
                if not (
                    item.get("headline")
                    or item.get("datePublished")
                    or item.get("@type")
                    in (
                        "Article",
                        "NewsArticle",
                        "ScholarlyArticle",
                        "BlogPosting",
                        "WebPage",
                    )
                ):
                    continue
                put(
                    meta,
                    "title",
                    item.get("headline") or item.get("name"),
                    "json_ld",
                )
                put(meta, "author", _names(item.get("author")), "json_ld")
                set_date(meta, item.get("datePublished"), "json_ld")
                publisher = _names(item.get("publisher"))
                put(meta, "site_name", publisher, "json_ld")
                put(meta, "publisher", publisher, "json_ld")
        except (ValueError, TypeError, AttributeError):
            logger.info("Ignoring malformed web structured metadata.")
    for field, names in {
        "title": ("citation_title", "DC.title", "dc.title"),
        "author": ("citation_author", "DC.creator", "dc.creator"),
        "doi": ("citation_doi", "DC.identifier", "dc.identifier"),
    }.items():
        for name in names:
            values = [
                clean(item.get("content"))
                for item in soup.find_all("meta", attrs={"name": name})
            ]
            value = "; ".join(filter(None, values)) or None
            if field == "doi" and value:
                from infrastructure.metadata.pdf import DOI

                match = DOI.search(value)
                value = match.group().rstrip(".,;") if match else None
            put(meta, field, value, "html_meta")
    for name in ("citation_publication_date", "DC.date", "dc.date"):
        set_date(meta, tag(name), "html_meta")
    # Browser document.title is the final title fallback, after article data.
    put(
        meta,
        "title",
        soup.title.get_text() if soup.title else None,
        "html_meta",
    )
    if not meta.published_at and not meta.published_year:
        try:
            from htmldate import find_date

            # Only inspect the supplied HTML; never fetch a URL here.
            found = find_date(
                html,
                url=url,
                original_date=True,
                extensive_search=False,
                deferred_url_extractor=False,
            )
            if found:
                set_date(meta, found, "ninguno")
                meta.needs_review = True
        except Exception:
            logger.info("Web date heuristic unavailable.")
