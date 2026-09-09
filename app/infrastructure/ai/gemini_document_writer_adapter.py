from __future__ import annotations

import json
import re
from dataclasses import replace as _with_replaced
from typing import Any

from application.ports.document_writer_port import DocumentWriterPort
from domain.exceptions import DocumentBuildError
from domain.services.table_of_contents_builder import build_index_section
from domain.value_objects.apa_structure import APASection, APASectionType
from domain.value_objects.document_node import (
    BLOCK_QUOTE,
    BULLETED_LIST,
    HEADING_1,
    HEADING_2,
    IMAGE,
    LIST_ITEM,
    NUMBERED_LIST,
    PAGE_BREAK,
    PARAGRAPH,
    TABLE,
    TABLE_CELL,
    TABLE_OF_CONTENTS,
    TABLE_ROW,
    DocumentNode,
    page_break_node,
    text_node,
)
from domain.value_objects.document_type import DocumentType
from domain.value_objects.presentation_info import PresentationInfo
from domain.value_objects.source_ref import SourceReference
from google import genai
from google.genai import types

# Full canonical APA 7 order (used for sorting the final section list —
# 'index' is never requested from the AI, see _AI_SECTION_ORDER below).
_SECTION_ORDER = [
    APASectionType.PRESENTATION,
    APASectionType.INDEX,
    APASectionType.INTRODUCTION,
    APASectionType.BODY,
    APASectionType.CONCLUSION,
    APASectionType.SOURCES,
]

# The subset of sections the AI is actually asked to write. 'index' is
# deliberately excluded: it is synthesized by build_index_section() from
# the real heading-1/heading-2 nodes the AI produced elsewhere, after the
# response is parsed — never authored (or narrated) by the AI itself.
_AI_SECTION_ORDER = [
    s for s in _SECTION_ORDER if s is not APASectionType.INDEX
]

_GLOBAL_STYLE_KEYS = frozenset(
    {
        "fontFamily",
        "fontSize",
        "color",
        "backgroundColor",
        "pageMargin",
        "pageSize",
        "orientation",
        "lineHeight",
        "showPageNumbers",
        "pageNumberPosition",
    }
)


def _ensure_trailing_page_break(section: APASection) -> APASection:
    if section.body_nodes and section.body_nodes[-1].type == PAGE_BREAK:
        return section
    return _with_replaced(
        section,
        body_nodes=section.body_nodes
        + (page_break_node(section_type=section.section_type.value),),
    )


_NODE_SCHEMA_RULES = (
    "CRITICAL OUTPUT RULES — the renderer understands ONLY a small, "
    "specific tree of JSON node objects. NO Markdown anywhere. Each "
    "section's 'nodes' array is a list of BLOCK nodes. Each block node is "
    "one of:\n"
    f'  - {{"type": "{PARAGRAPH}", "children": [ TEXT, ... ]}} — normal '
    "academic prose, one idea per paragraph.\n"
    f'  - {{"type": "{HEADING_2}", "children": [ TEXT ]}} — a subtopic '
    "heading, used sparingly and mostly inside 'body' for genuine subtopic "
    f"breaks. Never inside 'presentation' or 'index'. Deeper levels "
    f'("heading-3", "heading-4", "heading-5") exist for genuinely nested '
    "subtopics but are rarely needed — do not use them just to vary "
    "appearance.\n"
    f'  - {{"type": "{BLOCK_QUOTE}", "children": [ PARAGRAPH-like TEXT '
    "children ]}} — ONLY for a direct quotation of 40+ words per APA 7 "
    "(shorter quotes stay inline inside a normal paragraph, in quotation "
    "marks).\n"
    f'  - {{"type": "{BULLETED_LIST}", "children": [ LIST_ITEM, ... ]}} — '
    "use ONLY when items have no meaningful order (parallel examples, "
    "equivalent characteristics).\n"
    f'  - {{"type": "{NUMBERED_LIST}", "children": [ LIST_ITEM, ... ]}} — '
    "use when items are steps, a chronology, or a ranked hierarchy.\n"
    f'  A LIST_ITEM is {{"type": "{LIST_ITEM}", "children": [ TEXT, ... ]}}.\n'
    f'  - {{"type": "{TABLE}", "children": [ TABLE_ROW, ... ]}} — use ONLY '
    "for genuinely tabular data (rows of comparable fields/numbers). Do "
    "not use a table to lay out things that are really a list or plain "
    f'prose. A TABLE_ROW is {{"type": "{TABLE_ROW}", "children": [ '
    f'TABLE_CELL, ... ]}}. A TABLE_CELL is {{"type": "{TABLE_CELL}", '
    '"children": [ PARAGRAPH, ... ]}} — a cell\'s children are block '
    "nodes (usually a single 'paragraph'), never bare text nodes. Every "
    "row in a table must have the same number of cells, and the first "
    "row is normally the header row (its cells' paragraph text in bold).\n"
    '  A TEXT node is a leaf: {"text": "..."} or, when a mark is genuinely '
    'useful, {"text": "...", "marks": [ MARK, ... ]}. Each MARK is an '
    'object {"type": "bold"} or {"type": "color", "value": "#d93025"}. '
    "Valid mark types: 'bold', 'italic', 'underline', 'strikethrough' (no "
    'value needed); \'script\' (value: "superscript" or "subscript"); '
    "'color' / 'highlight' (value: a hex color string); 'link' (value: "
    '{"url": "..."}) — only when the source material names a URL to '
    "cite inline. Use marks sparingly, never on whole sentences, never "
    "invented decoration.\n"
    "  EVERY block node ('paragraph', 'heading-N', 'block-quote', "
    "'bulleted-list', 'numbered-list', 'list-item') MUST include a "
    "'styles' object with 'textAlign' set explicitly — never omit it, "
    "never leave it to be inferred. Use APA 7's own convention per type: "
    "'paragraph' and 'block-quote' -> \"justify\"; 'heading-1' -> "
    "\"center\"; 'heading-2' through 'heading-5' -> \"left\"; "
    "'list-item' -> \"left\". Only deviate from these defaults if the "
    "user's additional notes explicitly ask for different alignment on "
    "specific content. Besides 'textAlign', 'styles' may also carry "
    "textIndent, spaceBefore, marginBottom/Left/Right, lineHeight, "
    "backgroundColor, borderLeft, etc. — but add those ONLY when the "
    "user's additional notes explicitly ask for that particular visual "
    "formatting.\n"
    f'  A standalone {{"type": "{PAGE_BREAK}"}} node forces a new page at '
    "that point, and never has 'children' or 'styles'. The exporter "
    "renders EXACTLY the tree you return — it never invents page breaks "
    "of its own — so the ones APA 7 always requires must be present in "
    "your JSON:\n"
    f"    - The 'presentation' section's 'nodes' MUST end with a "
    f'{{"type": "{PAGE_BREAK}"}} node (the cover page always starts the '
    "table of contents on a fresh page).\n"
    f"    - The 'conclusion' section's 'nodes' MUST end with a "
    f'{{"type": "{PAGE_BREAK}"}} node (the body always starts the '
    "references on a fresh page).\n"
    "    - Do NOT add a page-break node anywhere else — not between "
    "'introduction' and 'body', not between subtopics ('heading-2' "
    "already separates those visually), and not as decoration — unless "
    "the user's additional notes explicitly ask for one extra, specific "
    "pagination break somewhere in the body.\n"
    "    - (The 'index' section's own trailing page break is added by "
    "the application, since you never write that section — see the "
    "'index' rule below.)\n"
    '  NEVER output a node with "type": "image". You have no way to '
    "produce a real, working file URL, so an invented 'src' would be a "
    "broken link — images are inserted by the application separately, "
    "after your text is generated.\n"
    f'  NEVER output a node with "type": "{TABLE_OF_CONTENTS}". That node '
    "is built entirely by the application from your real headings — see "
    "the 'index' rule below.\n"
    "  NEVER type a page number into paragraph text anywhere in the "
    'document (no "Página 1", no "[page X]", no manual folio). The '
    "application draws real page numbers itself from "
    "'global_style.showPageNumbers' / 'pageNumberPosition'.\n"
    "Rules that still apply regardless of node type:\n"
    "- Lists are the exception, not the default: most content must be "
    "'paragraph' nodes. Every item in a list must be grammatically "
    "parallel with the others (all full sentences, or all short "
    "fragments — not mixed).\n"
    "- Keep paragraphs short and centered on a single idea; never merge "
    "several distinct ideas into one 'paragraph' node — split them into "
    "separate paragraph nodes instead.\n"
    "- Titles (document title and every section title) must be short, "
    "original, in your own words, in the source's language, NEVER a URL, "
    "NEVER copied verbatim from source text, at most ~12 words."
)

_SYSTEM_INSTRUCTION = (
    "You are an academic writing assistant. You write complete, well "
    "structured documents strictly following APA 7 formatting rules, in "
    "the same language as the source content, as a JSON node tree instead "
    "of Markdown.\n\n"
    f"{_NODE_SCHEMA_RULES}\n"
    "7. If the user's additional notes contain a questionnaire (a list of "
    "questions to answer), address every question explicitly and "
    "completely inside 'body', while still producing all five required "
    "sections normally.\n"
    "8. The 'presentation' section is REQUIRED and must exist, but it is "
    "NOT a summary or abstract of the document's topic. Its 'nodes' must "
    "restate ONLY the structured presentation data given to you below — "
    "student name, institution, subject/course, professor, student ID (if "
    "provided), and today's date — as separate 'paragraph' nodes (one "
    "field per paragraph), in the source's language, exactly as given. "
    "Each paragraph must contain ONLY the field's plain value, with NO "
    'label or prefix of any kind — write "Aram Musset", never "Nombre: '
    'Aram Musset" or "Student: Aram Musset"; write "Universidad XYZ", '
    'never "Institución: Universidad XYZ". Do NOT add a summary of what '
    "the document is about, do NOT add a field that wasn't provided to "
    "you, and do NOT omit any field that was. Its LAST node must be a "
    '{"type": "page-break"} node — see the page-break rule above.\n'
    '9. NEVER produce a section with "section_type": "index" — omit it '
    "completely from your JSON response. The application builds the "
    "table of contents itself, after you respond, from the real "
    "'heading-1' and 'heading-2' nodes you wrote in the other sections — "
    "it is not something you write or narrate. Your required sections "
    "are therefore exactly these five, in order: presentation, "
    "introduction, body, conclusion, sources.\n"
    "10. The 'introduction' section's \"title\" must be a specific, "
    "content-descriptive heading you write in your own words — e.g. "
    '"El Problema del Acoplamiento en el Software Moderno", not the '
    'generic word "Introducción"/"Introduction" (nor a literal '
    "translation of it, nor any other section-label placeholder). A "
    "reader should learn something about THIS document's actual topic "
    "just from that heading. The literal 'section_type' value is a "
    "machine identifier, not a suggested visible title: NEVER copy or "
    "translate it into the 'title' field. This title IS rendered and "
    "must remain present in the response.\n"
    "11. The 'body' section's \"title\" is used ONLY for internal "
    "bookkeeping and is NEVER rendered as a heading in the final "
    'document — do not write generic labels like "Desarrollo"/"Body"/'
    '"Cuerpo" expecting them to appear on the page; pick any short '
    "internal label (it truly doesn't matter, e.g. the document's main "
    "topic). What DOES appear on the page is 'body'.'nodes' directly: "
    "it must begin IMMEDIATELY with a 'heading-2' node for its first "
    "subtopic — never prefix it with a generic top-level heading of "
    "your own. 'body' should read as a sequence of specific topics and "
    "subtopics, each with its own descriptive 'heading-2' (and, if truly "
    "needed, nested 'heading-3'), never as a single undifferentiated "
    "block under one generic label.\n"
    "12. If the user's additional notes explicitly request custom "
    "visual formatting (a specific color, alignment, emphasis, a "
    "highlighted term, a quote box, etc.), honor it using 'styles' on the "
    "relevant block node(s) and/or 'marks' on the relevant text — but "
    "only for what was actually requested, nothing more.\n"
    "13. The 'conclusion' section's LAST node must be a "
    '{"type": "page-break"} node — see the page-break rule above.\n'
    "14. Return 'global_style' as an empty object unless the user's "
    "additional notes explicitly request a document-wide format change. "
    "When explicitly requested, include only the keys that must change; "
    "never repeat defaults there. Node-specific formatting still belongs "
    "in node 'styles' or text 'marks'.\n"
    "You always answer with a single JSON object and nothing else — no "
    "markdown fences, no commentary, no preamble."
)

_AUGMENT_SYSTEM_INSTRUCTION = (
    "You are an academic writing assistant. You update an EXISTING APA 7 "
    "document (stored as a JSON node tree, not Markdown) with new source "
    "material, deciding per-section whether it needs to change.\n\n"
    f"{_NODE_SCHEMA_RULES}\n"
    "7. For every section, decide: if the new material doesn't affect it, "
    'return it with "unchanged": true and nothing else — do NOT repeat '
    "its old nodes, that wastes tokens. If it does, return the FULL "
    "updated 'title' and 'nodes' for that section.\n"
    "8. If the new material is a genuinely new subtopic not covered yet in "
    "'body', add it as a new 'heading-2' block followed by its 'paragraph' "
    "node(s), appended at a sensible point — don't just tack it onto an "
    "unrelated paragraph. 'body'.'nodes' must still begin IMMEDIATELY with "
    "a 'heading-2' — never introduce a generic top-level heading like "
    '"Desarrollo"/"Body" of your own; its "title" field is internal '
    "bookkeeping only and is never rendered (see the equivalent rule in "
    "the initial-write instructions).\n"
    "9. If the new material complements or extends a topic already present "
    "in 'body', merge it into that existing paragraph/subtopic's node(s) "
    "instead of duplicating it as a separate block.\n"
    '10. NEVER return a section with "section_type": "index" — not as '
    'a full section, not even as {"unchanged": true}. Omit it entirely, '
    "in every response, always. The application rebuilds the table of "
    "contents itself after merging your sections, from whatever "
    "'heading-1'/'heading-2' nodes end up in the final document — it is "
    "never something you write.\n"
    '11. NEVER return a section with "section_type": "presentation". '
    "The cover is user-editable content owned by the application and is "
    "not included in this request.\n"
    "12. Update 'sources' and 'conclusion' if the new content changes "
    "what they should say; otherwise mark them unchanged. If you DO "
    "regenerate 'conclusion', its LAST node must still be a "
    '{"type": "page-break"} node, exactly as before. '
    "'introduction' is almost never affected by new material — mark it "
    "unchanged unless the new content truly changes the document's "
    'overall scope. If you DO regenerate it, its "title" must remain a '
    "specific, content-descriptive heading in your own words — never the "
    'generic word "Introducción"/"Introduction" and never a translation '
    "of the machine-only 'section_type' identifier. The introduction "
    "title remains visible and must not be omitted.\n"
    "13. Preserve any existing 'styles' or 'marks' you see on nodes you "
    "keep or lightly edit — don't strip formatting the user (or a previous "
    "request) explicitly asked for. Only add new 'styles'/'marks' if the "
    "current additional notes explicitly request them, and never invent "
    "'image' nodes yourself.\n"
    "14. Return 'global_style' as an empty object unless the CURRENT "
    "additional notes explicitly request a document-wide format change. "
    "If requested, return only changed keys. Do not echo or reset the "
    "existing global styles supplied in the prompt.\n"
    "You always answer with a single JSON object and nothing else — no "
    "markdown fences, no commentary, no preamble."
)

_URL_PATTERN = re.compile(r"https?://", re.IGNORECASE)
_GENERIC_INTRODUCTION_TITLES = frozenset(
    {
        "intro",
        "introduction",
        "introduccion",
        "introducción",
        "introducao",
        "introdução",
        "introduzione",
        "einleitung",
        "inleiding",
        "wprowadzenie",
        "введение",
        "序論",
        "はじめに",
    }
)

_RESPONSE_SHAPE_HINT = """
{
  "title": "A short, original academic title you write yourself",
  "global_style": {},
  "sections": [
    {"section_type": "presentation", "title": "...", "nodes": [ BLOCK, ... ]},
    {"section_type": "introduction",
     "title": "El impacto de la automatización en el aprendizaje",
     "nodes": [ BLOCK, ... ]},
    {"section_type": "body", "title": "internal label only",
     "nodes": [ {"type": "heading-2", ...}, BLOCK, ... ]},
    {"section_type": "conclusion", "title": "...", "nodes": [ BLOCK, ... ]},
    {"section_type": "sources", "title": "...", "nodes": [ BLOCK, ... ]}
  ],
  "references": [
    {"author": "...", "year": "...", "title": "...", "url": "..."}
  ]
}
""".strip()

_AUGMENT_RESPONSE_SHAPE_HINT = """
{
  "title": "usually the same title as before, unless it must change",
  "global_style": {},
  "sections": [
    {"section_type": "introduction", "unchanged": true},
    {"section_type": "body", "title": "...", "nodes": [ BLOCK, ... ]},
    {"section_type": "conclusion", "title": "...", "nodes": [ BLOCK, ... ]},
    {"section_type": "sources", "title": "...", "nodes": [ BLOCK, ... ]}
  ],
  "references": [
    {"author": "...", "year": "...", "title": "...", "url": "..."}
  ]
}
""".strip()


class GeminiDocumentWriterAdapter(DocumentWriterPort):
    def __init__(
        self, api_key: str, model_name: str = "gemini-3.5-flash"
    ) -> None:
        self._client = genai.Client(api_key=api_key)
        self._model_name = model_name

    async def write(
        self,
        *,
        source_content: str,
        title: str,
        document_type: DocumentType,
        presentation: PresentationInfo,
        additional_notes: str | None = None,
    ) -> tuple[str, list[APASection], list[SourceReference], dict[str, Any]]:
        prompt = self._build_prompt(
            source_content=source_content,
            title=title,
            document_type=document_type,
            presentation=presentation,
            additional_notes=additional_notes,
        )
        raw_text = await self._generate(
            prompt, system_instruction=_SYSTEM_INSTRUCTION
        )
        title_out, sections, references, global_style = self._parse_response(
            raw_text
        )
        return (
            title_out,
            self._finalize_sections(sections),
            references,
            global_style,
        )

    async def augment(
        self,
        *,
        existing_sections: list[APASection],
        existing_references: list[SourceReference],
        new_content: str,
        document_type: DocumentType,
        existing_global_style: dict[str, Any],
        additional_notes: str | None = None,
    ) -> tuple[str, list[APASection], list[SourceReference], dict[str, Any]]:
        prompt = self._build_augment_prompt(
            existing_sections=existing_sections,
            existing_references=existing_references,
            new_content=new_content,
            document_type=document_type,
            existing_global_style=existing_global_style,
            additional_notes=additional_notes,
        )
        raw_text = await self._generate(
            prompt, system_instruction=_AUGMENT_SYSTEM_INSTRUCTION
        )
        title_out, sections, references, global_style = (
            self._parse_augment_response(
                raw_text, existing_sections=existing_sections
            )
        )
        return (
            title_out,
            self._finalize_sections(sections),
            references,
            global_style,
        )

    def _finalize_sections(
        self, sections: list[APASection]
    ) -> list[APASection]:
        """Drops any 'index' section the model produced despite being told
        not to (defensive — see rule 9 / rule 10 in the system prompts),
        rebuilds it from scratch (build_index_section() is a pure
        placeholder — see that module's docstring for why it needs no
        input), guarantees the mandatory APA 7 page breaks are actually
        present in the tree (defensive — see the page-break rule in
        _NODE_SCHEMA_RULES), and returns the full section list in
        canonical APA 7 order.

        Doing this here — on the persisted node tree itself, not as an
        export-time side effect — is what keeps the WYSIWYG editor and the
        PDF export in sync: both read the very same nodes.
        """
        without_index = [
            s for s in sections if s.section_type is not APASectionType.INDEX
        ]
        without_index = [
            _ensure_trailing_page_break(s)
            if s.section_type
            in (APASectionType.PRESENTATION, APASectionType.CONCLUSION)
            else s
            for s in without_index
        ]
        index_section = _ensure_trailing_page_break(build_index_section())
        finalized = without_index + [index_section]
        finalized.sort(key=lambda s: s.section_type.order)
        return finalized

    async def _generate(self, prompt: str, *, system_instruction: str) -> str:
        try:
            response = await self._client.aio.models.generate_content(
                model=self._model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    response_mime_type="application/json",
                    temperature=0.3,
                ),
            )
            return response.text
        except Exception as exc:
            raise DocumentBuildError(f"Gemini request failed: {exc}") from exc

    def _build_prompt(
        self,
        *,
        source_content: str,
        title: str,
        document_type: DocumentType,
        presentation: PresentationInfo,
        additional_notes: str | None,
    ) -> str:
        section_names = ", ".join(s.value for s in _AI_SECTION_ORDER)
        notes = _clean_notes(additional_notes)
        return f"""
Write a "{document_type.value}" document, following APA 7 rules, based
exclusively on the source material below.

Topic / working title given by the user (use this only as a hint about the
subject — do NOT copy it verbatim, and especially never use it if it is a
URL): "{title}"

Additional notes from the user (extraction guidance, tone, focus, a
questionnaire to answer inside "body", or explicit formatting requests to
honor via 'styles'/'marks'): {notes}

Required sections, in this exact order: {section_names}.

Presentation/cover page data — the 'presentation' section's nodes must
restate exactly these fields, one per paragraph, and nothing else:
{presentation}

Respond with a single JSON object shaped exactly like this:
{_RESPONSE_SHAPE_HINT}

--- SOURCE MATERIAL START ---
{source_content}
--- SOURCE MATERIAL END ---
""".strip()

    def _build_augment_prompt(
        self,
        *,
        existing_sections: list[APASection],
        existing_references: list[SourceReference],
        new_content: str,
        document_type: DocumentType,
        existing_global_style: dict[str, Any] | None = None,
        additional_notes: str | None = None,
    ) -> str:
        notes = _clean_notes(additional_notes)
        existing_sections_json = json.dumps(
            [
                {
                    "section_type": s.section_type.value,
                    "title": s.title,
                    "nodes": [n.to_dict() for n in s.body_nodes],
                }
                for s in existing_sections
                if s.section_type is not APASectionType.PRESENTATION
                and s.section_type is not APASectionType.INDEX
            ],
            ensure_ascii=False,
        )
        existing_refs_json = json.dumps(
            [
                {
                    "author": r.author,
                    "year": r.year,
                    "title": r.title,
                    "url": r.url,
                }
                for r in existing_references
            ],
            ensure_ascii=False,
        )
        return f"""
This is an existing "{document_type.value}" APA 7 document you must update
with new source material — not rewrite from scratch.

Existing sections (JSON, one entry per section_type): {existing_sections_json}

Existing references (JSON): {existing_refs_json}

Existing global styles (preserve every value unless the current additional
notes explicitly request a document-wide formatting change):
{json.dumps(existing_global_style or {}, ensure_ascii=False)}

User's additional notes for this update: {notes}

New source material to incorporate:
--- NEW MATERIAL START ---
{new_content}
--- NEW MATERIAL END ---

Respond with a single JSON object shaped exactly like this:
{_AUGMENT_RESPONSE_SHAPE_HINT}

Every section_type shown in the existing sections must appear exactly once,
either as "unchanged": true or with full "title"/"nodes". Do not return
"presentation" or "index". "references" must be the complete,
de-duplicated list (old entries plus any genuinely new ones).
""".strip()

    def _parse_response(
        self, raw_text: str
    ) -> tuple[str, list[APASection], list[SourceReference], dict[str, Any]]:
        data = _decode_json(raw_text)
        title = self._validate_title(data.get("title"), field="title")

        raw_sections = data.get("sections")
        if not raw_sections:
            raise DocumentBuildError("Gemini response has no 'sections'.")

        sections = [
            self._build_section(s, introduction_fallback=title)
            for s in raw_sections
        ]
        references = self._parse_references(data)
        return title, sections, references, _parse_global_style(data)

    def _parse_augment_response(
        self, raw_text: str, *, existing_sections: list[APASection]
    ) -> tuple[str, list[APASection], list[SourceReference], dict[str, Any]]:
        data = _decode_json(raw_text)
        title = self._validate_title(data.get("title"), field="title")

        raw_sections = data.get("sections")
        if not raw_sections:
            raise DocumentBuildError("Gemini response has no 'sections'.")

        existing_by_type = {s.section_type: s for s in existing_sections}
        sections: list[APASection] = []
        for s in raw_sections:
            try:
                section_type = APASectionType(s["section_type"])
            except (KeyError, ValueError) as exc:
                raise DocumentBuildError(
                    f"Malformed section in Gemini response: {exc}"
                ) from exc

            if s.get("unchanged"):
                existing = existing_by_type.get(section_type)
                if existing is None:
                    raise DocumentBuildError(
                        "Gemini marked "
                        f"'{section_type.value}' unchanged but no "
                        "prior version exists."
                    )
                sections.append(existing)
                continue

            sections.append(
                self._build_section(s, introduction_fallback=title)
            )

        references = self._parse_references(data)
        return title, sections, references, _parse_global_style(data)

    def _build_section(
        self, raw: dict, *, introduction_fallback: str | None = None
    ) -> APASection:
        try:
            section_type = APASectionType(raw["section_type"])
            title = self._validate_title(raw["title"], field="section title")
            title = self._resolve_section_title(
                section_type,
                title,
                introduction_fallback=introduction_fallback,
            )
            raw_nodes = raw["nodes"]
        except (KeyError, ValueError) as exc:
            raise DocumentBuildError(
                f"Malformed section in Gemini response: {exc}"
            ) from exc

        if not raw_nodes:
            raise DocumentBuildError(
                f"Section '{section_type.value}' has no 'nodes'."
            )

        try:
            body_nodes = tuple(
                self._reject_image(
                    _with_replaced(
                        DocumentNode.from_dict(n),
                        section_type=section_type.value,
                    )
                )
                for n in raw_nodes
            )
        except DocumentBuildError as exc:
            raise DocumentBuildError(
                f"Malformed node in section '{section_type.value}': {exc}"
            ) from exc

        heading = DocumentNode(
            type=HEADING_1,
            section_type=section_type.value,
            children=(text_node(title),),
        )

        return APASection(
            section_type=section_type, heading=heading, body_nodes=body_nodes
        )

    def _resolve_section_title(
        self,
        section_type: APASectionType,
        title: str,
        *,
        introduction_fallback: str | None,
    ) -> str:
        if section_type is APASectionType.PRESENTATION:
            if introduction_fallback is None:
                raise DocumentBuildError(
                    "The presentation page requires the document title."
                )
            return self._validate_title(
                introduction_fallback,
                field="presentation title",
            )
        if section_type is not APASectionType.INTRODUCTION:
            return title
        if not _is_generic_introduction_title(title):
            return title
        if introduction_fallback is not None:
            fallback = self._validate_title(
                introduction_fallback,
                field="introduction fallback title",
            )
            if not _is_generic_introduction_title(fallback):
                return fallback
        raise DocumentBuildError(
            "Gemini returned a generic introduction title and no "
            "content-specific fallback title is available."
        )

    def _reject_image(self, node: DocumentNode) -> DocumentNode:
        if node.type == IMAGE:
            raise DocumentBuildError(
                "Gemini generated an 'image' node, which isn't allowed — "
                "images are inserted by the application, not the writer."
            )
        return node

    def _parse_references(self, data: dict) -> list[SourceReference]:
        try:
            return [
                SourceReference(
                    author=r.get("author", ""),
                    year=r.get("year", ""),
                    title=r.get("title", ""),
                    url=r.get("url"),
                )
                for r in data.get("references", [])
            ]
        except (KeyError, TypeError) as exc:
            raise DocumentBuildError(
                f"Malformed reference in Gemini response: {exc}"
            ) from exc

    def _validate_title(self, value: object, *, field: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise DocumentBuildError(f"Gemini response has an empty {field}.")
        candidate = value.strip()
        if _URL_PATTERN.search(candidate):
            raise DocumentBuildError(
                f"Gemini returned a {field} that looks like a URL: "
                f"{candidate!r}"
            )
        if len(candidate) > 200:
            raise DocumentBuildError(
                f"Gemini returned an implausibly long {field} "
                f"({len(candidate)} chars) — looks like copied source text."
            )
        return candidate


def _clean_notes(additional_notes: str | None) -> str:
    return (
        additional_notes.strip()
        if additional_notes and additional_notes.strip()
        else "None"
    )


def _parse_global_style(data: dict) -> dict[str, Any]:
    raw = data.get("global_style") or {}
    if not isinstance(raw, dict):
        raise DocumentBuildError("'global_style' must be a JSON object.")
    unknown = set(raw) - _GLOBAL_STYLE_KEYS
    if unknown:
        names = ", ".join(sorted(unknown))
        raise DocumentBuildError(f"Unknown global style fields: {names}.")
    return dict(raw)


def _is_generic_introduction_title(title: str) -> bool:
    normalized = re.sub(r"[^\w\s]", "", title.casefold()).strip()
    return normalized in _GENERIC_INTRODUCTION_TITLES


def _decode_json(raw_text: str) -> dict:
    text = raw_text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        data, _ = json.JSONDecoder().raw_decode(text)
    except json.JSONDecodeError as exc:
        raise DocumentBuildError(
            f"Gemini did not return valid JSON: {exc}"
        ) from exc
    return data
