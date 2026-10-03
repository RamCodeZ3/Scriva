from dataclasses import dataclass


@dataclass(frozen=True)
class SourceReference:
    """Bibliographic reference formatted for APA 7."""

    author: str
    title: str
    year: int | None = None
    url: str | None = None
    publisher: str | None = None
    source_type: str | None = None
    month: int | None = None
    day: int | None = None
    year_suffix: str = ""
    language: str = "en"

    def to_apa_string(self) -> str:
        """Returns the reference as a formatted APA 7 string."""
        return "".join(self.to_apa_parts())

    def to_apa_parts(self) -> tuple[str, str, str]:
        missing = "s. f." if self.language.startswith("es") else "n.d."
        year = f"{self.year}{self.year_suffix}" if self.year else missing
        if self.year is None and self.year_suffix:
            year = f"{missing}-{self.year_suffix}"
        date = year
        if self.year and self.month and self.day:
            date = f"{year}, {self.month:02d} {self.day:02d}"
        if self.author:
            prefix = f"{self.author}. ({date}). "
            title_suffix = ""
        else:
            prefix = ""
            title_suffix = f". ({date})"
        kind = ""
        if self.source_type == "youtube":
            kind = " [Video]"
        elif self.source_type == "file":
            kind = " [File]"
        publisher = f". {self.publisher}" if self.publisher else ""
        url = f". {self.url}" if self.url else ""
        return prefix, self.title, f"{title_suffix}{kind}{publisher}{url}"
