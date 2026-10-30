import getpass

from domain.value_objects.bib_metadata import BibMetadata

from infrastructure.metadata.common import clean, file_title, put, set_date


def read_office(meta: BibMetadata, path: str) -> None:
    if meta.source_type == "docx":
        from docx import Document

        props = Document(path).core_properties
    else:
        from pptx import Presentation

        props = Presentation(path).core_properties
    put(meta, "title", props.title, "doc_properties")
    generic = {
        "python-docx",
        "python-pptx",
        "administrator",
        "user",
        "microsoft office user",
        getpass.getuser().casefold(),
    }
    author = clean(props.author)
    if author and author.casefold() not in generic:
        put(meta, "author", author, "doc_properties")
    set_date(meta, props.created or props.modified, "doc_properties")
    file_title(meta, path)
    meta.needs_review = True
