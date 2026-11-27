import re

from domain.value_objects.bib_metadata import BibMetadata
from pypdf import PdfReader

from infrastructure.metadata.common import file_title, put, set_date

DOI = re.compile(r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+")


def read_pdf(meta: BibMetadata, path: str) -> None:
    reader = PdfReader(path)
    for page in reader.pages[:2]:
        match = DOI.search(page.extract_text() or "")
        if match:
            doi = match.group().rstrip(".,;")
            while doi.endswith(")") and doi.count(")") > doi.count("("):
                doi = doi[:-1]
            put(meta, "doi", doi, "pdf_info")
            break
    info = reader.metadata
    if info:
        put(meta, "title", info.title, "pdf_info")
        put(meta, "author", info.author, "pdf_info")
        try:
            set_date(meta, info.creation_date, "pdf_info")
        except (ValueError, TypeError):
            pass
    file_title(meta, path)
    meta.needs_review = True
