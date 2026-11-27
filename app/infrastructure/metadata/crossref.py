from urllib.parse import quote

from domain.value_objects.bib_metadata import BibMetadata

from infrastructure.metadata.common import logger, put, set_date
from infrastructure.metadata.http import MetadataHTTPClient


async def enrich_crossref(meta: BibMetadata, http: MetadataHTTPClient) -> bool:
    if not meta.doi:
        return False
    try:
        data = await http.get_json(
            "https://api.crossref.org/works/" + quote(meta.doi, safe="")
        )
        work = data["message"]
        verified = BibMetadata(source_type=meta.source_type)
        titles = work.get("title") or []
        put(verified, "title", titles[0] if titles else None, "crossref")
        authors = []
        for author in work.get("author") or []:
            family, given = author.get("family"), author.get("given")
            if family and given:
                initials = " ".join(f"{part[0]}." for part in given.split())
                authors.append(f"{family}, {initials}")
            elif family or author.get("name"):
                authors.append(family or author["name"])
        put(verified, "author", "; ".join(authors) or None, "crossref")
        parts = (work.get("issued", {}).get("date-parts") or [[]])[0]
        if len(parts) >= 3:
            set_date(
                verified,
                f"{parts[0]:04}-{parts[1]:02}-{parts[2]:02}",
                "crossref",
            )
        elif parts:
            set_date(verified, str(parts[0]), "crossref")
        containers = work.get("container-title") or []
        put(
            verified,
            "site_name",
            containers[0] if containers else None,
            "crossref",
        )
        put(verified, "publisher", work.get("publisher"), "crossref")
        put(verified, "url", work.get("URL"), "crossref")
        # Crossref takes priority, but never erases fields absent in its reply.
        if verified.published_at or verified.published_year:
            meta.published_at = None
            meta.published_year = None
            meta.origins.pop("published_at", None)
            meta.origins.pop("published_year", None)
        for field, origin in verified.origins.items():
            setattr(meta, field, getattr(verified, field))
            meta.origins[field] = origin
        return bool(verified.title)
    except Exception:
        logger.info("Crossref metadata unavailable; retaining local values.")
        return False
