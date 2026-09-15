from __future__ import annotations

import itertools
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from domain.exceptions import DocumentBuildError

HEADING_1 = "heading-1"
HEADING_2 = "heading-2"
HEADING_3 = "heading-3"
HEADING_4 = "heading-4"
HEADING_5 = "heading-5"
PARAGRAPH = "paragraph"
BLOCK_QUOTE = "block-quote"
BULLETED_LIST = "bulleted-list"
NUMBERED_LIST = "numbered-list"
LIST_ITEM = "list-item"
IMAGE = "image"
PAGE_BREAK = "page-break"
SECTION_BREAK = "section-break"
TABLE = "table"
TABLE_ROW = "table-row"
TABLE_CELL = "table-cell"
TABLE_OF_CONTENTS = "table-of-contents"
FIELD = "field"
FOOTNOTE = "footnote"
ENDNOTE = "endnote"
HYPERLINK = "hyperlink"
BOOKMARK = "bookmark"
REFERENCE_MARK = "reference-mark"
REFERENCE_ENTRY = "reference-entry"
TAB = "tab"
IMAGE_INLINE = "image-inline"

HEADING_TYPES = frozenset(
    {HEADING_1, HEADING_2, HEADING_3, HEADING_4, HEADING_5}
)
LIST_TYPES = frozenset({BULLETED_LIST, NUMBERED_LIST})
TABLE_TYPES = frozenset({TABLE, TABLE_ROW, TABLE_CELL})
NOTE_TYPES = frozenset({FOOTNOTE, ENDNOTE})
ATOMIC_BLOCK_TYPES = frozenset(
    {
        IMAGE,
        IMAGE_INLINE,
        PAGE_BREAK,
        SECTION_BREAK,
        TABLE_OF_CONTENTS,
        FIELD,
        TAB,
    }
)
CONTAINER_BLOCK_TYPES = (
    HEADING_TYPES
    | LIST_TYPES
    | TABLE_TYPES
    | NOTE_TYPES
    | {
        PARAGRAPH,
        BLOCK_QUOTE,
        LIST_ITEM,
        HYPERLINK,
        BOOKMARK,
        REFERENCE_MARK,
        REFERENCE_ENTRY,
    }
)
BLOCK_TYPES = CONTAINER_BLOCK_TYPES | ATOMIC_BLOCK_TYPES
INLINE_BLOCK_TYPES = frozenset(
    {
        FIELD,
        FOOTNOTE,
        ENDNOTE,
        HYPERLINK,
        BOOKMARK,
        REFERENCE_MARK,
        TAB,
        IMAGE_INLINE,
    }
)
INLINE_ATOMIC_TYPES = frozenset({FIELD, TAB, IMAGE_INLINE})

PAGE_NUMBER_POSITIONS = frozenset(
    {"top-right", "bottom-center", "bottom-right"}
)

MARK_BOLD = "bold"
MARK_ITALIC = "italic"
MARK_UNDERLINE = "underline"
MARK_STRIKETHROUGH = "strikethrough"
MARK_HIGHLIGHT = "highlight"
MARK_BACKGROUND_SHADING = "backgroundShading"
MARK_COLOR = "color"
MARK_FONT_FAMILY = "fontFamily"
MARK_FONT_SIZE = "fontSize"
MARK_SCRIPT = "script"
MARK_LINK = "link"
MARK_CODE = "code"

_VALID_MARK_TYPES = frozenset(
    {
        MARK_BOLD,
        MARK_ITALIC,
        MARK_UNDERLINE,
        MARK_STRIKETHROUGH,
        MARK_HIGHLIGHT,
        MARK_BACKGROUND_SHADING,
        MARK_COLOR,
        MARK_FONT_FAMILY,
        MARK_FONT_SIZE,
        MARK_SCRIPT,
        MARK_LINK,
        MARK_CODE,
    }
)
_MARKS_REQUIRING_VALUE = frozenset(
    {
        MARK_HIGHLIGHT,
        MARK_BACKGROUND_SHADING,
        MARK_COLOR,
        MARK_FONT_FAMILY,
        MARK_FONT_SIZE,
        MARK_SCRIPT,
        MARK_LINK,
    }
)
_SCRIPT_VALUES = frozenset({"none", "superscript", "subscript"})
_HIGHLIGHT_VALUES = frozenset(
    {
        "yellow",
        "green",
        "cyan",
        "magenta",
        "blue",
        "red",
        "darkBlue",
        "darkCyan",
        "darkGreen",
        "darkMagenta",
        "darkRed",
        "darkYellow",
        "darkGray",
        "lightGray",
        "black",
        "white",
        "none",
    }
)
_TEXT_ALIGNMENTS = frozenset({"left", "center", "right", "justify"})
_ORIENTATIONS = frozenset({"portrait", "landscape"})
_auto_id = itertools.count(1)


def _next_id() -> str:
    return f"node-{next(_auto_id)}"


def _copy_mapping(value: Mapping[str, Any] | None) -> dict[str, Any]:
    return dict(value or {})


def _validate_span(name: str, value: Any) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise DocumentBuildError(
            f"'{name}' must be a positive integer, got: {value!r}"
        )


def _validate_styles(styles: dict[str, Any]) -> None:
    """Validate known styles while retaining unknown OOXML properties."""
    if "marginTop" in styles:
        raise DocumentBuildError(
            "'marginTop' is deprecated; use 'spaceBefore'."
        )
    if "columnWidths" in styles:
        raise DocumentBuildError(
            "'columnWidths' is not part of v2; use table-cell.style.width."
        )
    text_align = styles.get("textAlign")
    if text_align is not None and text_align not in _TEXT_ALIGNMENTS:
        raise DocumentBuildError(
            f"'textAlign' must be one of {sorted(_TEXT_ALIGNMENTS)}, "
            f"got: {text_align!r}"
        )

    orientation = styles.get("orientation")
    if orientation is not None and orientation not in _ORIENTATIONS:
        raise DocumentBuildError(
            f"'orientation' must be one of {sorted(_ORIENTATIONS)}, "
            f"got: {orientation!r}"
        )

    margins = styles.get("margins")
    if margins is not None and not isinstance(margins, dict):
        raise DocumentBuildError("'margins' must be a JSON object.")

    borders = styles.get("borders")
    if borders is not None and not isinstance(borders, dict):
        raise DocumentBuildError("'borders' must be a JSON object.")

    list_level = styles.get("listLevel")
    if list_level is not None and (
        not isinstance(list_level, int)
        or isinstance(list_level, bool)
        or list_level < 0
    ):
        raise DocumentBuildError(
            f"'listLevel' must be a non-negative integer, got: {list_level!r}"
        )

    highlight = styles.get("highlight")
    if highlight is not None and highlight not in _HIGHLIGHT_VALUES:
        raise DocumentBuildError(
            f"'highlight' must be one of {sorted(_HIGHLIGHT_VALUES)}, "
            f"got: {highlight!r}"
        )

    for span in ("colSpan", "rowSpan"):
        if span in styles:
            _validate_span(span, styles[span])


@dataclass(frozen=True)
class Mark:
    type: str
    value: Any = None

    def __post_init__(self) -> None:
        if self.type not in _VALID_MARK_TYPES:
            raise DocumentBuildError(f"Unknown mark type: {self.type!r}")
        if self.type in _MARKS_REQUIRING_VALUE and self.value is None:
            raise DocumentBuildError(f"Mark '{self.type}' requires a 'value'.")
        if self.type == MARK_SCRIPT and self.value not in _SCRIPT_VALUES:
            raise DocumentBuildError(
                "'script' mark value must be one of "
                f"{sorted(_SCRIPT_VALUES)}, "
                f"got: {self.value!r}"
            )
        if self.type == MARK_LINK and not (
            isinstance(self.value, dict) and self.value.get("url")
        ):
            raise DocumentBuildError(
                "'link' mark value must be an object with a non-empty "
                f"'url', got: {self.value!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"type": self.type}
        if self.value is not None:
            result["value"] = self.value
        return result

    @classmethod
    def from_dict(cls, data: Any) -> Mark:
        if isinstance(data, str):
            return cls(type=data)
        if not isinstance(data, dict) or "type" not in data:
            raise DocumentBuildError(f"Malformed mark: {data!r}")
        return cls(type=data["type"], value=data.get("value"))


def _marks_to_style(marks: tuple[Mark, ...]) -> dict[str, Any]:
    style: dict[str, Any] = {}
    for mark in marks:
        if mark.type == MARK_LINK:
            continue
        if (
            mark.type == MARK_HIGHLIGHT
            and isinstance(mark.value, str)
            and mark.value.startswith("#")
        ):
            style[MARK_BACKGROUND_SHADING] = mark.value
            continue
        style[mark.type] = True if mark.value is None else mark.value
    return style


def _style_to_marks(style: Mapping[str, Any]) -> tuple[Mark, ...]:
    marks: list[Mark] = []
    for name, value in style.items():
        if name not in _VALID_MARK_TYPES or name == MARK_LINK:
            continue
        if name in {
            MARK_BOLD,
            MARK_ITALIC,
            MARK_UNDERLINE,
            MARK_STRIKETHROUGH,
            MARK_CODE,
        }:
            if value:
                marks.append(Mark(name))
            continue
        if (
            name == MARK_HIGHLIGHT
            and isinstance(value, str)
            and value.startswith("#")
        ):
            marks.append(Mark(MARK_BACKGROUND_SHADING, value))
            continue
        marks.append(Mark(name, value))
    return tuple(marks)


@dataclass(frozen=True)
class DocumentNode:
    type: str | None = None
    text: str | None = None
    id: str | None = None
    section_type: str | None = None
    marks: tuple[Mark, ...] = ()
    children: tuple[DocumentNode, ...] = ()
    styles: dict[str, Any] = field(default_factory=dict)
    src: str | None = None
    alt: str | None = None
    caption: str | None = None
    col_span: int | None = None
    row_span: int | None = None
    field_type: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        is_leaf = self.text is not None
        is_block = self.type is not None
        if is_leaf == is_block:
            raise DocumentBuildError(
                "A document node must be either a leaf text node ('text') "
                "or a block node ('type'), never both or neither."
            )
        if not isinstance(self.styles, dict):
            raise DocumentBuildError("'styles' must be a JSON object.")
        if not isinstance(self.metadata, dict):
            raise DocumentBuildError("'metadata' must be a JSON object.")

        if is_leaf:
            self._validate_text_leaf()
            return
        if self.id is None:
            object.__setattr__(self, "id", _next_id())
        if self.type not in BLOCK_TYPES | {IMAGE_INLINE}:
            raise DocumentBuildError(f"Unknown node type: {self.type!r}")
        if self.marks:
            raise DocumentBuildError("Only leaf text nodes may carry 'marks'.")
        _validate_styles(self.styles)
        self._validate_block_payload()
        self._validate_children()

    def _validate_text_leaf(self) -> None:
        if self.children:
            raise DocumentBuildError(
                "A leaf text node cannot have 'children'."
            )
        if self.styles:
            raise DocumentBuildError(
                "A leaf text node cannot have 'styles' — use 'marks'."
            )
        block_properties = (
            self.src,
            self.alt,
            self.caption,
            self.col_span,
            self.row_span,
            self.field_type,
        )
        if (
            any(value is not None for value in block_properties)
            or self.metadata
        ):
            raise DocumentBuildError(
                "A leaf text node cannot carry block-node properties."
            )

    def _validate_block_payload(self) -> None:
        if self.type in {IMAGE, IMAGE_INLINE}:
            if not self.src:
                raise DocumentBuildError("An 'image' node requires 'src'.")
        elif self.src is not None or self.alt is not None:
            raise DocumentBuildError("'src'/'alt' only apply to image nodes.")

        if self.caption is not None and self.type not in {IMAGE, TABLE}:
            raise DocumentBuildError(
                "'caption' only applies to 'image' and 'table' nodes."
            )

        if self.col_span is not None:
            _validate_span("colSpan", self.col_span)
        if self.row_span is not None:
            _validate_span("rowSpan", self.row_span)
        if (self.col_span is not None or self.row_span is not None) and (
            self.type != TABLE_CELL
        ):
            raise DocumentBuildError(
                "'colSpan'/'rowSpan' only apply to 'table-cell' nodes."
            )

        if self.type == FIELD:
            if (
                not isinstance(self.field_type, str)
                or not self.field_type.strip()
            ):
                raise DocumentBuildError(
                    "A 'field' node requires a non-empty 'field_type'."
                )
        elif self.field_type is not None:
            raise DocumentBuildError(
                "'field_type' only applies to 'field' nodes."
            )

    def _validate_children(self) -> None:
        if self.type in ATOMIC_BLOCK_TYPES:
            if self.children:
                raise DocumentBuildError(
                    f"A '{self.type}' node cannot have 'children'."
                )
            return

        if not self.children and self.type not in {BOOKMARK, REFERENCE_MARK}:
            raise DocumentBuildError(
                f"Block node '{self.type}' must have at least one child."
            )
        if self.type in LIST_TYPES and any(
            child.type != LIST_ITEM for child in self.children
        ):
            raise DocumentBuildError(
                f"'{self.type}' children must all be '{LIST_ITEM}' nodes."
            )
        if self.type == TABLE and any(
            child.type != TABLE_ROW for child in self.children
        ):
            raise DocumentBuildError(
                f"'{TABLE}' children must all be '{TABLE_ROW}' nodes."
            )
        if self.type == TABLE_ROW and any(
            child.type != TABLE_CELL for child in self.children
        ):
            raise DocumentBuildError(
                f"'{TABLE_ROW}' children must all be '{TABLE_CELL}' nodes."
            )
        if self.type == TABLE_CELL and any(
            child.text is not None or child.type not in _CELL_BLOCK_TYPES
            for child in self.children
        ):
            raise DocumentBuildError(
                f"'{TABLE_CELL}' children must be content block nodes, "
                "not bare text or inline-only nodes."
            )
        hyperlink_children = INLINE_ATOMIC_TYPES | {BOOKMARK}
        if self.type == HYPERLINK and any(
            child.text is None and child.type not in hyperlink_children
            for child in self.children
        ):
            raise DocumentBuildError(
                "A 'hyperlink' may contain text, fields, tabs, or bookmarks."
            )
        if self.type == BOOKMARK and any(
            child.text is None and child.type not in INLINE_ATOMIC_TYPES
            for child in self.children
        ):
            raise DocumentBuildError(
                "A 'bookmark' may contain only text, fields, or tabs."
            )
        if self.type == REFERENCE_MARK and any(
            child.text is None and child.type not in INLINE_ATOMIC_TYPES
            for child in self.children
        ):
            raise DocumentBuildError(
                "A 'reference-mark' may contain only text, fields, or tabs."
            )

    def plain_text(self) -> str:
        if self.text is not None:
            return self.text
        if self.type == IMAGE:
            return self.caption or self.alt or ""
        if self.type in ATOMIC_BLOCK_TYPES:
            return ""
        return "".join(child.plain_text() for child in self.children)

    def to_dict(self) -> dict[str, Any]:
        if self.text is not None:
            result: dict[str, Any] = {"text": self.text}
            if self.marks:
                result["style"] = _marks_to_style(self.marks)
            return result

        result = {"type": self.type}
        if self.id:
            result["id"] = self.id
        if self.section_type:
            result["section_type"] = self.section_type
        if self.styles:
            result["style"] = dict(self.styles)
        if self.src is not None:
            result["src"] = self.src
        if self.alt is not None:
            result["alt"] = self.alt
        if self.caption is not None:
            result["caption"] = self.caption
        if self.col_span is not None:
            result["colSpan"] = self.col_span
        if self.row_span is not None:
            result["rowSpan"] = self.row_span
        if self.field_type is not None:
            result["field_type"] = self.field_type
        if self.metadata:
            result["metadata"] = dict(self.metadata)
        if self.type not in ATOMIC_BLOCK_TYPES:
            result["children"] = _children_to_dict(self.children)
        return result

    @classmethod
    def from_dict(cls, data: Any, *, assign_ids: bool = True) -> DocumentNode:
        if not isinstance(data, dict):
            raise DocumentBuildError(
                f"Node must be a JSON object, got: {data!r}"
            )
        if "text" in data:
            if "type" in data:
                raise DocumentBuildError(
                    "A node cannot contain both 'text' and 'type'."
                )
            text = data["text"]
            if not isinstance(text, str):
                raise DocumentBuildError(
                    f"Leaf 'text' must be a string, got: {text!r}"
                )
            raw_marks = data.get("marks") or ()
            if not isinstance(raw_marks, (list, tuple)):
                raise DocumentBuildError("'marks' must be a JSON array.")
            style = data.get("style") or {}
            if not isinstance(style, dict):
                raise DocumentBuildError("'style' must be a JSON object.")
            return cls(
                text=text,
                marks=(
                    _style_to_marks(style)
                    if style
                    else tuple(Mark.from_dict(mark) for mark in raw_marks)
                ),
            )

        styles = data.get("style") or data.get("styles") or {}
        metadata = data.get("metadata") or {}
        raw_children = data.get("children") or ()
        if not isinstance(styles, dict):
            raise DocumentBuildError("'style' must be a JSON object.")
        if not isinstance(metadata, dict):
            raise DocumentBuildError("'metadata' must be a JSON object.")
        if not isinstance(raw_children, (list, tuple)):
            raise DocumentBuildError("'children' must be a JSON array.")

        if data.get("type") == HYPERLINK:
            raw_children = _flatten_legacy_hyperlink_children(
                metadata, raw_children
            )

        normalized_styles = dict(styles)
        if "marginTop" in normalized_styles:
            normalized_styles["spaceBefore"] = normalized_styles.pop(
                "marginTop"
            )
        normalized_styles.pop("columnWidths", None)

        return cls(
            type=data.get("type"),
            id=data.get("id") or (_next_id() if assign_ids else None),
            section_type=data.get("section_type"),
            styles=normalized_styles,
            children=tuple(
                cls.from_dict(child, assign_ids=assign_ids)
                for child in raw_children
            ),
            src=data.get("src"),
            alt=data.get("alt"),
            caption=data.get("caption"),
            col_span=data.get("colSpan", data.get("col_span")),
            row_span=data.get("rowSpan", data.get("row_span")),
            field_type=data.get("field_type", data.get("fieldType")),
            metadata=dict(metadata),
        )


def _flatten_legacy_hyperlink_children(
    metadata: Mapping[str, Any], raw_children: Sequence[Any]
) -> tuple[Any, ...]:
    """Repair persisted duplicate hyperlinks while rejecting new ones."""
    flattened: list[Any] = []
    parent_url = metadata.get("url")
    for child in raw_children:
        if not isinstance(child, dict) or child.get("type") != HYPERLINK:
            flattened.append(child)
            continue
        child_metadata = child.get("metadata") or {}
        if child_metadata.get("url") != parent_url:
            flattened.append(child)
            continue
        flattened.extend(child.get("children") or ())
    return tuple(flattened)


def _children_to_dict(
    children: tuple[DocumentNode, ...],
) -> list[dict[str, Any]]:
    """Serialize legacy link marks as the single v2 hyperlink shape."""
    result: list[dict[str, Any]] = []
    index = 0
    while index < len(children):
        child = children[index]
        link = next(
            (mark for mark in child.marks if mark.type == MARK_LINK), None
        )
        if child.text is None or link is None:
            result.append(child.to_dict())
            index += 1
            continue

        link_value = link.value if isinstance(link.value, dict) else {}
        url = link_value.get("url")
        linked_children: list[dict[str, Any]] = []
        while index < len(children):
            candidate = children[index]
            candidate_link = next(
                (mark for mark in candidate.marks if mark.type == MARK_LINK),
                None,
            )
            if (
                candidate.text is None
                or candidate_link is None
                or candidate_link.value != link.value
            ):
                break
            linked_children.append(candidate.to_dict())
            index += 1
        result.append(
            {
                "id": _next_id(),
                "type": HYPERLINK,
                "metadata": {
                    key: value
                    for key, value in link_value.items()
                    if key != "url"
                }
                | {"url": url},
                "children": linked_children,
            }
        )
    return result


_CELL_BLOCK_TYPES = (
    HEADING_TYPES
    | LIST_TYPES
    | NOTE_TYPES
    | {
        PARAGRAPH,
        BLOCK_QUOTE,
        TABLE,
        PAGE_BREAK,
        SECTION_BREAK,
        TABLE_OF_CONTENTS,
        IMAGE,
    }
)


def text_node(
    text: str, *, marks: Sequence[Mark | str] | None = None
) -> DocumentNode:
    resolved = tuple(
        mark if isinstance(mark, Mark) else Mark(type=mark)
        for mark in (marks or ())
    )
    return DocumentNode(text=text, marks=resolved)


def block_node(
    node_type: str,
    children: Sequence[DocumentNode],
    *,
    section_type: str | None = None,
    node_id: str | None = None,
    styles: Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> DocumentNode:
    return DocumentNode(
        type=node_type,
        children=tuple(children),
        section_type=section_type,
        id=node_id or _next_id(),
        styles=_copy_mapping(styles),
        metadata=_copy_mapping(metadata),
    )


def image_node(
    src: str,
    *,
    alt: str | None = None,
    caption: str | None = None,
    section_type: str | None = None,
    node_id: str | None = None,
    styles: Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> DocumentNode:
    return DocumentNode(
        type=IMAGE,
        id=node_id or _next_id(),
        section_type=section_type,
        styles=_copy_mapping(styles),
        src=src,
        alt=alt,
        caption=caption,
        metadata=_copy_mapping(metadata),
    )


def page_break_node(
    *,
    section_type: str | None = None,
    node_id: str | None = None,
    styles: Mapping[str, Any] | None = None,
) -> DocumentNode:
    return DocumentNode(
        type=PAGE_BREAK,
        id=node_id or _next_id(),
        section_type=section_type,
        styles=_copy_mapping(styles),
    )


def section_break_node(
    *,
    break_type: str = "next-page",
    section_type: str | None = None,
    node_id: str | None = None,
    styles: Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> DocumentNode:
    node_metadata = {"breakType": break_type, **_copy_mapping(metadata)}
    return DocumentNode(
        type=SECTION_BREAK,
        id=node_id or _next_id(),
        section_type=section_type,
        styles=_copy_mapping(styles),
        metadata=node_metadata,
    )


def field_node(
    field_type: str,
    *,
    node_id: str | None = None,
    styles: Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> DocumentNode:
    return DocumentNode(
        type=FIELD,
        id=node_id or _next_id(),
        field_type=field_type,
        styles=_copy_mapping(styles),
        metadata=_copy_mapping(metadata),
    )


def tab_node(
    *,
    node_id: str | None = None,
    styles: Mapping[str, Any] | None = None,
) -> DocumentNode:
    return DocumentNode(
        type=TAB,
        id=node_id or _next_id(),
        styles=_copy_mapping(styles),
    )


def hyperlink_node(
    children: Sequence[DocumentNode],
    url: str,
    *,
    node_id: str | None = None,
    styles: Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> DocumentNode:
    if not url:
        raise DocumentBuildError("A 'hyperlink' node requires a URL.")
    node_metadata = {"url": url, **_copy_mapping(metadata)}
    return DocumentNode(
        type=HYPERLINK,
        id=node_id or _next_id(),
        children=tuple(children),
        styles=_copy_mapping(styles),
        metadata=node_metadata,
    )


def bookmark_node(
    name: str,
    children: Sequence[DocumentNode] = (),
    *,
    node_id: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> DocumentNode:
    if not name:
        raise DocumentBuildError("A 'bookmark' node requires a name.")
    node_metadata = {"name": name, **_copy_mapping(metadata)}
    return DocumentNode(
        type=BOOKMARK,
        id=node_id or _next_id(),
        children=tuple(children),
        metadata=node_metadata,
    )


def footnote_node(
    children: Sequence[DocumentNode],
    *,
    note_id: str | None = None,
    node_id: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> DocumentNode:
    return _note_node(FOOTNOTE, children, note_id, node_id, metadata)


def endnote_node(
    children: Sequence[DocumentNode],
    *,
    note_id: str | None = None,
    node_id: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> DocumentNode:
    return _note_node(ENDNOTE, children, note_id, node_id, metadata)


def _note_node(
    node_type: str,
    children: Sequence[DocumentNode],
    note_id: str | None,
    node_id: str | None,
    metadata: Mapping[str, Any] | None,
) -> DocumentNode:
    node_metadata = _copy_mapping(metadata)
    if note_id is not None:
        node_metadata["noteId"] = note_id
    return DocumentNode(
        type=node_type,
        id=node_id or _next_id(),
        children=tuple(children),
        metadata=node_metadata,
    )


def table_node(
    rows: Sequence[DocumentNode],
    *,
    caption: str | None = None,
    section_type: str | None = None,
    node_id: str | None = None,
    styles: Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> DocumentNode:
    return DocumentNode(
        type=TABLE,
        children=tuple(rows),
        section_type=section_type,
        id=node_id or _next_id(),
        styles=_copy_mapping(styles),
        caption=caption,
        metadata=_copy_mapping(metadata),
    )


def table_row_node(
    cells: Sequence[DocumentNode],
    *,
    node_id: str | None = None,
    styles: Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> DocumentNode:
    return DocumentNode(
        type=TABLE_ROW,
        children=tuple(cells),
        id=node_id or _next_id(),
        styles=_copy_mapping(styles),
        metadata=_copy_mapping(metadata),
    )


def table_cell_node(
    children: Sequence[DocumentNode],
    *,
    col_span: int | None = None,
    row_span: int | None = None,
    node_id: str | None = None,
    styles: Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> DocumentNode:
    return DocumentNode(
        type=TABLE_CELL,
        children=tuple(children),
        id=node_id or _next_id(),
        styles=_copy_mapping(styles),
        col_span=col_span,
        row_span=row_span,
        metadata=_copy_mapping(metadata),
    )


def table_of_contents_node(
    *,
    section_type: str | None = None,
    node_id: str | None = None,
    styles: Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> DocumentNode:
    return DocumentNode(
        type=TABLE_OF_CONTENTS,
        id=node_id or _next_id(),
        section_type=section_type,
        styles=_copy_mapping(styles),
        metadata=_copy_mapping(metadata),
    )
