from dataclasses import dataclass


@dataclass(frozen=True)
class PresentationInfo:
    """
    Metadata shown on the document cover page (APA 7 title page).
    Only student_name is required. Missing secondary metadata is represented
    by editable placeholders on the generated cover page.
    """

    student_name: str
    professor: str | None = None
    subject: str | None = None
    student_id: str | None = None
    institution: str | None = None

    def __post_init__(self) -> None:
        if not self.student_name.strip():
            raise ValueError("student_name cannot be empty.")
        if self.subject is not None and not self.subject.strip():
            raise ValueError("subject cannot be blank if provided.")
        for field_name in ("professor", "student_id", "institution"):
            value = getattr(self, field_name)
            normalized = (
                value.strip()
                if isinstance(value, str) and value.strip()
                else f"<{field_name}>"
            )
            object.__setattr__(self, field_name, normalized)

    def display_institution(self) -> str:
        return self.institution or "<institution>"

    def display_student_id(self) -> str:
        return self.student_id or "<student_id>"

    def display_subject(self) -> str:
        return self.subject or "Subject not specified"
