"""
Source code parser for C/C++ doc comments.

Handles two parsing backends:
  - libclang (accurate types, signatures, member info)
  - regex fallback (works without clang installed, less precise)

Also includes the IGT GPU Tools test metadata parser, reST-to-Markdown
conversion, and gtk-doc markup translation.
"""

from __future__ import annotations

import os
import re
import textwrap
from dataclasses import dataclass, field
from enum import Enum, auto

try:
    from clang.cindex import (
        CursorKind,
        Index,
        TranslationUnit,
        TranslationUnitLoadError,
    )

    CLANG_AVAILABLE = True
except ImportError:
    CLANG_AVAILABLE = False


class SymbolKind(Enum):
    FUNCTION = auto()
    VARIABLE = auto()
    TYPEDEF = auto()
    MACRO = auto()
    MACRO_FUNCTION = auto()
    STRUCT = auto()
    UNION = auto()
    ENUM = auto()
    ENUM_CONSTANT = auto()
    CLASS = auto()
    FIELD = auto()
    GENERIC = auto()
    TEST = auto()
    SUBTEST = auto()
    FILE = auto()


@dataclass
class DocComment:
    name: str
    kind: SymbolKind
    comment: str
    signature: str = ""
    filename: str = ""
    line: int = 0
    members: list[DocComment] = field(default_factory=list)
    return_type: str = ""
    params: list[tuple[str, str]] = field(default_factory=list)


_COMMENT_LINE_RE = re.compile(r"^\s*///\s?", re.MULTILINE)


def _clean_block_comment(raw):
    text = raw
    if text.startswith("/**"):
        text = text[3:]
    elif text.startswith("/*"):
        text = text[2:]
    if text.endswith("*/"):
        text = text[:-2]

    lines = text.split("\n")
    cleaned = []
    for line in lines:
        s = line.lstrip()
        if s.startswith("* "):
            cleaned.append(s[2:])
        elif s.startswith("*"):
            cleaned.append(s[1:])
        else:
            cleaned.append(line)

    # Trim trailing junk: empty lines, stray comment closing markers
    _JUNK = {"", "*/", "**/", "/**", "*", "/", "="}
    while cleaned and (
        cleaned[-1].strip() in _JUNK
        or cleaned[-1].strip().startswith("==")
        and set(cleaned[-1].strip()) <= {"="}
    ):
        cleaned.pop()
    while cleaned and (
        cleaned[0].strip() in _JUNK
        or cleaned[0].strip().startswith("==")
        and set(cleaned[0].strip()) <= {"="}
    ):
        cleaned.pop(0)

    # Drop interior lines that are just leftover comment decorations
    cleaned = [ln for ln in cleaned if ln.strip() not in ("/**", "**/")]

    return textwrap.dedent("\n".join(cleaned)).strip()


def clean_comment(raw):
    if raw.lstrip().startswith("///"):
        return _COMMENT_LINE_RE.sub("", raw).strip()
    return _clean_block_comment(raw)


# ── gtk-doc → reST conversion ──

_GTKDOC_FUNC_RE = re.compile(r"(?<![`\\#@%\w])(\w+)\(\)(?!`)")
_GTKDOC_TYPE_RE = re.compile(r"(?<!\\)#(\w+)\.(\w+)|(?<!\\)#(\w+)")
_GTKDOC_CONST_RE = re.compile(r"%(\w+)")
_GTKDOC_PARAM_TEXT_RE = re.compile(r"@(\w+)")
_GTKDOC_PARAM_DOC_RE = re.compile(r"^@(\w+):\s*(.+)$", re.MULTILINE)
_GTKDOC_RETURNS_RE = re.compile(r"^(?:Returns?|Return value):\s*(.+)$", re.MULTILINE)
_GTKDOC_SINCE_RE = re.compile(r"^Since:\s*(.+)$", re.MULTILINE)
_GTKDOC_DEPRECATED_RE = re.compile(r"^Deprecated:\s*(.+)$", re.MULTILINE)
_GTKDOC_CODEBLOCK_RE = re.compile(
    r'\|\[(?:\s*<!--\s*language="(\w+)"\s*-->)?\s*\n?(.*?)\]\|', re.DOTALL
)
_GTKDOC_LITERAL_RE = re.compile(r"<literal>(.+?)</literal>")
_GTKDOC_EMPHASIS_RE = re.compile(r"<emphasis>(.+?)</emphasis>")


def gtkdoc_to_rst(text):
    protected = {}
    counter = [0]

    def _protect(m):
        key = f"\x00PROT{counter[0]}\x00"
        protected[key] = m.group(0)
        counter[0] += 1
        return key

    # 1. Protect Example:, HowTo:, Notes/Note sections (including any |[...]| blocks)
    #    before any gtk-doc conversion runs
    _example_section_re = re.compile(
        r"(^(?:Example(?:s| usage)?|HowTo|How\s*To|Notes?):?\s*$)"
        r"(.*?)"
        r"(?=^(?:@\w+\s*:|Returns?:|Since:|Deprecated:"
        r"|Example(?:s| usage)?:|HowTo:|How\s*To:|Notes?:)|\Z)",
        re.MULTILINE | re.DOTALL | re.IGNORECASE,
    )

    def _protect_example(m):
        header = m.group(1)
        body = m.group(2)
        # Convert |[...]| inside the example body to fenced blocks
        body = _GTKDOC_CODEBLOCK_RE.sub(_replace_codeblock, body)
        key = f"\x00PROT{counter[0]}\x00"
        protected[key] = header + body
        counter[0] += 1
        return key

    text = _example_section_re.sub(_protect_example, text)

    # 2. Convert remaining |[...]| blocks to fenced code blocks
    text = _GTKDOC_CODEBLOCK_RE.sub(_replace_codeblock, text)

    # 3. Protect remaining fenced code blocks
    _fence_re = re.compile(r"```\w*\n.*?```", re.DOTALL)
    text = _fence_re.sub(_protect, text)

    # 4. Run all gtk-doc conversions on unprotected text
    text = _GTKDOC_LITERAL_RE.sub(r"``\1``", text)
    text = _GTKDOC_EMPHASIS_RE.sub(r"*\1*", text)

    text = _GTKDOC_PARAM_DOC_RE.sub(r":param \1: \2", text)
    text = _GTKDOC_RETURNS_RE.sub(r":returns: \1", text)
    text = _GTKDOC_SINCE_RE.sub(r"Since: \1", text)
    text = _GTKDOC_DEPRECATED_RE.sub(r"Deprecated: \1", text)

    text = _GTKDOC_TYPE_RE.sub(_replace_type_ref, text)
    text = _GTKDOC_CONST_RE.sub(r":const:`\1`", text)
    text = _GTKDOC_FUNC_RE.sub(r":func:`\1`", text)
    text = _GTKDOC_PARAM_TEXT_RE.sub(r"``\1``", text)

    # 5. Restore all protected blocks
    for key, val in protected.items():
        text = text.replace(key, val)

    return text


def _replace_codeblock(m):
    lang = m.group(1) or "c"
    code = m.group(2).rstrip()
    return f"\n```{lang.lower()}\n{code}\n```\n"


def _replace_type_ref(m):
    if m.group(1) and m.group(2):
        return f":member:`{m.group(1)}.{m.group(2)}`"
    return f":type:`{m.group(3)}`"


# ── reST → Markdown conversion ──

_RST_PARAM_RE = re.compile(r":param\s+(\w+):\s*(.+)")
_RST_TYPE_RE = re.compile(r":type\s+(\w+):\s*(.+)")
_RST_RETURN_RE = re.compile(r":returns?:\s*(.+)")
_RST_RTYPE_RE = re.compile(r":rtype:\s*(.+)")
_RST_REF_RE = re.compile(
    r":(?:c(?:pp)?:)?(?:func|macro|type|const|var|struct|union|enum|member|data|class):`([^`]+)`"
)
_RST_LITERAL_RE = re.compile(r"``([^`]+)``")
_NAME_COLON_RE = re.compile(r"^\w[\w_]*\s*:\s*$")


_EXAMPLE_HEADER_RE = re.compile(
    r"^(?:example|examples|example usage|usage example|sample|sample usage)s?\s*:?\s*$",
    re.IGNORECASE,
)
_EXAMPLE_INLINE_RE = re.compile(
    r"(?:Example|EXAMPLE|Examples|EXAMPLES|Sample|SAMPLE)s?\s*:\s*$", re.IGNORECASE
)
_HOWTO_RE = re.compile(r"^(?:howto|how\s*to)\s*:\s*$", re.IGNORECASE)
_HOWTO_INLINE_RE = re.compile(r"(?:HowTo|HOWTO|How\s*To|how\s*to)\s*:\s*$", re.IGNORECASE)
_NOTES_RE = re.compile(r"^(?:notes?)\s*:\s*$", re.IGNORECASE)
_NOTES_INLINE_RE = re.compile(r"(?:Notes?|NOTES?)\s*:\s*$", re.IGNORECASE)


def _detect_code_lang(lines):
    """Detect language from code content. $ suggests bash."""
    for line in lines:
        s = line.strip()
        if s.startswith("$") or s.startswith("# $"):
            return "bash"
    return "c"


def rst_to_markdown(text, *, doc=None):
    result_lines = []
    params = {}  # name -> description
    param_types = {}  # name -> type (from :type: or doc.params)
    returns = None
    # Collected examples: (label, code lines, paragraph position)
    example_blocks = []
    current_example = None  # (label, [lines]) or None
    example_counter = 0
    current_paragraph_start = 0
    # HowTo and Notes prose sections
    howto_lines = []
    notes_lines = []
    current_section = None  # None, "example", "howto", "notes"

    # Grab parameter types from the function signature when we have them
    if doc and doc.params:
        for ptype, pname in doc.params:
            if pname and ptype:
                param_types[pname] = ptype

    def _finalize_section():
        """Finalize the current section before switching to a new one."""
        nonlocal current_example, current_section
        if current_section == "example" and current_example is not None:
            example_blocks.append((*current_example, max(0, current_paragraph_start)))
            current_example = None
        current_section = None

    for line in text.split("\n"):
        stripped = line.strip()

        # Strip "funcname:" header lines (redundant with heading)
        if not result_lines and current_section is None and _NAME_COLON_RE.match(stripped):
            continue
        if (
            doc
            and not result_lines
            and current_section is None
            and stripped.rstrip(":") == doc.name
        ):
            continue

        # Track paragraph boundaries
        if not stripped and current_section is None:
            current_paragraph_start = len(result_lines) + 1

        # --- Detect section headers ---

        # HowTo: (standalone or inline)
        is_howto = _HOWTO_RE.match(stripped)
        howto_inline = None
        if not is_howto and current_section != "howto":
            howto_inline = _HOWTO_INLINE_RE.search(stripped)

        # Notes: (standalone or inline)
        is_notes = _NOTES_RE.match(stripped)
        notes_inline = None
        if not is_notes and current_section != "notes":
            notes_inline = _NOTES_INLINE_RE.search(stripped)

        # Example: (standalone or inline)
        is_standalone_example = _EXAMPLE_HEADER_RE.match(stripped)
        if not is_standalone_example and stripped.startswith(".. code-block::"):
            is_standalone_example = True
        inline_match = None
        if not is_standalone_example and current_section != "example":
            inline_match = _EXAMPLE_INLINE_RE.search(stripped)

        # --- Handle section transitions ---

        if is_howto or howto_inline:
            _finalize_section()
            if howto_inline and not is_howto:
                before = stripped[: howto_inline.start()].rstrip()
                if before:
                    line_p = _RST_REF_RE.sub(r"`\1`", before)
                    line_p = _RST_LITERAL_RE.sub(r"`\1`", line_p)
                    result_lines.append(line_p)
            current_section = "howto"
            continue

        if is_notes or notes_inline:
            _finalize_section()
            if notes_inline and not is_notes:
                before = stripped[: notes_inline.start()].rstrip()
                if before:
                    line_p = _RST_REF_RE.sub(r"`\1`", before)
                    line_p = _RST_LITERAL_RE.sub(r"`\1`", line_p)
                    result_lines.append(line_p)
            current_section = "notes"
            continue

        if is_standalone_example or inline_match:
            _finalize_section()
            example_counter += 1
            label = f"Example {example_counter}" if example_counter > 1 else "Example"
            if inline_match and not is_standalone_example:
                before = stripped[: inline_match.start()].rstrip()
                if before:
                    line_p = _RST_REF_RE.sub(r"`\1`", before)
                    line_p = _RST_LITERAL_RE.sub(r"`\1`", line_p)
                    result_lines.append(line_p)
            current_example = (label, [])
            current_section = "example"
            continue

        # --- Collect lines for current section ---

        if current_section == "howto":
            # End howto on reST field markers
            if (
                _RST_PARAM_RE.match(stripped)
                or _RST_RETURN_RE.match(stripped)
                or _RST_TYPE_RE.match(stripped)
                or _RST_RTYPE_RE.match(stripped)
            ):
                _finalize_section()
                # Fall through
            else:
                howto_lines.append(line)
                continue

        if current_section == "notes":
            if (
                _RST_PARAM_RE.match(stripped)
                or _RST_RETURN_RE.match(stripped)
                or _RST_TYPE_RE.match(stripped)
                or _RST_RTYPE_RE.match(stripped)
            ):
                _finalize_section()
            else:
                notes_lines.append(line)
                continue

        if current_section == "example":
            if (
                _RST_PARAM_RE.match(stripped)
                or _RST_RETURN_RE.match(stripped)
                or _RST_TYPE_RE.match(stripped)
                or _RST_RTYPE_RE.match(stripped)
            ):
                _finalize_section()
            else:
                ex_lines = current_example[1]
                has_code = any(ln.strip() for ln in ex_lines)
                in_fence = (
                    any(ln.strip().startswith("```") for ln in ex_lines)
                    and sum(1 for ln in ex_lines if ln.strip().startswith("```")) % 2 == 1
                )
                if (
                    has_code
                    and not in_fence
                    and stripped
                    and not line.startswith((" ", "\t"))
                    and not stripped.startswith("```")
                ):
                    _finalize_section()
                    current_paragraph_start = len(result_lines)
                    # Re-check for HowTo/Notes/Example on this line
                    re_howto = _HOWTO_RE.match(stripped) or _HOWTO_INLINE_RE.search(stripped)
                    re_notes = _NOTES_RE.match(stripped) or _NOTES_INLINE_RE.search(stripped)
                    re_ex_s = _EXAMPLE_HEADER_RE.match(stripped)
                    re_ex_i = _EXAMPLE_INLINE_RE.search(stripped)
                    if re_howto:
                        current_section = "howto"
                        if not _HOWTO_RE.match(stripped):
                            m = _HOWTO_INLINE_RE.search(stripped)
                            before = stripped[: m.start()].rstrip()
                            if before:
                                result_lines.append(
                                    _RST_LITERAL_RE.sub(r"`\1`", _RST_REF_RE.sub(r"`\1`", before))
                                )
                        continue
                    elif re_notes:
                        current_section = "notes"
                        if not _NOTES_RE.match(stripped):
                            m = _NOTES_INLINE_RE.search(stripped)
                            before = stripped[: m.start()].rstrip()
                            if before:
                                result_lines.append(
                                    _RST_LITERAL_RE.sub(r"`\1`", _RST_REF_RE.sub(r"`\1`", before))
                                )
                        continue
                    elif re_ex_s or re_ex_i:
                        example_counter += 1
                        label = f"Example {example_counter}" if example_counter > 1 else "Example"
                        if re_ex_i and not re_ex_s:
                            m = re_ex_i
                            before = stripped[: m.start()].rstrip()
                            if before:
                                result_lines.append(
                                    _RST_LITERAL_RE.sub(r"`\1`", _RST_REF_RE.sub(r"`\1`", before))
                                )
                        current_example = (label, [])
                        current_section = "example"
                        continue
                    # Fall through to normal processing
                else:
                    ex_lines.append(line)
                    continue

        # --- Normal line processing ---
        m = _RST_PARAM_RE.match(stripped)
        if m:
            params[m.group(1)] = m.group(2)
            continue
        m = _RST_TYPE_RE.match(stripped)
        if m:
            param_types[m.group(1)] = m.group(2)
            continue
        m = _RST_RETURN_RE.match(stripped)
        if m:
            returns = m.group(1)
            continue
        if _RST_RTYPE_RE.match(stripped):
            continue

        line = _RST_REF_RE.sub(r"`\1`", line)
        line = _RST_LITERAL_RE.sub(r"`\1`", line)
        result_lines.append(line)

    # Finalize last section
    _finalize_section()

    # Strip trailing empty lines from body
    while result_lines and not result_lines[-1].strip():
        result_lines.pop()

    # Build return info from signature if not in doc comment
    # Skip for macros (#define) — they don't have a meaningful return type
    if (
        not returns
        and doc
        and doc.return_type
        and doc.kind not in (SymbolKind.MACRO, SymbolKind.MACRO_FUNCTION)
    ):
        rt = doc.return_type.strip()
        rt = doc.return_type.strip()
        if rt and rt != "void":
            if "*" in rt:
                # "char *" -> "Pointer to char"
                base = rt.replace("*", "").strip()
                stars = rt.count("*")
                ptr = "Pointer to pointer to" if stars > 1 else "Pointer to"
                returns = f"{ptr} `{base}`" if base else f"{ptr} void"
            else:
                returns = f"`{rt}`"

    # Build parameter table with Type column
    if params:
        has_types = any(pname in param_types for pname in params)
        result_lines += ["", "**Parameters:**", ""]
        if has_types:
            result_lines.append("| Name | Type | Description |")
            result_lines.append("|------|------|-------------|")
        else:
            result_lines.append("| Name | Description |")
            result_lines.append("|------|-------------|")
        for pname, pdesc in params.items():
            ptype = param_types.get(pname, "")
            if ptype:
                type_display = f"`{ptype}`"
                result_lines.append(f"| `{pname}` | {type_display} | {pdesc} |")
            else:
                if has_types:
                    result_lines.append(f"| `{pname}` | | {pdesc} |")
                else:
                    result_lines.append(f"| `{pname}` | {pdesc} |")

    if returns:
        result_lines += ["", f"**Returns:** {returns}"]

    # Insert example blocks at their associated paragraph positions
    # Process in reverse order so insertions don't shift later indices
    for label, ex_lines, para_idx in reversed(example_blocks):
        # Strip leading/trailing blank lines
        while ex_lines and not ex_lines[0].strip():
            ex_lines.pop(0)
        while ex_lines and not ex_lines[-1].strip():
            ex_lines.pop()
        if not ex_lines:
            continue
        has_fence = any(ln.strip().startswith("```") for ln in ex_lines)
        marker_lines = [f"<!-- EXAMPLE_START:{label} -->"]
        if has_fence:
            marker_lines.extend(ex_lines)
        else:
            joined = "\n".join(ex_lines)
            lang = _detect_code_lang(ex_lines)
            marker_lines.append(f"```{lang}")
            marker_lines.extend(textwrap.dedent(joined).split("\n"))
            marker_lines.append("```")
        marker_lines.append("<!-- EXAMPLE_END -->")

        # Insert at the paragraph start so the card floats beside the paragraph
        insert_at = min(para_idx, len(result_lines))
        for j, ml in enumerate(marker_lines):
            result_lines.insert(insert_at + j, ml)

    # Emit HowTo and Notes as markers for the renderer
    _howto_text = "\n".join(howto_lines).strip()
    _notes_text = "\n".join(notes_lines).strip()
    if _howto_text or _notes_text:
        result_lines += ["", "<!-- APPENDIX_START -->"]
        if _howto_text:
            result_lines += ["<!-- HOWTO_START -->", _howto_text, "<!-- HOWTO_END -->"]
        if _notes_text:
            result_lines += ["<!-- NOTES_START -->", _notes_text, "<!-- NOTES_END -->"]
        result_lines.append("<!-- APPENDIX_END -->")

    return "\n".join(result_lines)


# -- clang parser --

_KIND_MAP = {}

if CLANG_AVAILABLE:
    _KIND_MAP = {
        CursorKind.FUNCTION_DECL: SymbolKind.FUNCTION,
        CursorKind.VAR_DECL: SymbolKind.VARIABLE,
        CursorKind.TYPEDEF_DECL: SymbolKind.TYPEDEF,
        CursorKind.MACRO_DEFINITION: SymbolKind.MACRO,
        CursorKind.STRUCT_DECL: SymbolKind.STRUCT,
        CursorKind.UNION_DECL: SymbolKind.UNION,
        CursorKind.ENUM_DECL: SymbolKind.ENUM,
        CursorKind.ENUM_CONSTANT_DECL: SymbolKind.ENUM_CONSTANT,
        CursorKind.CLASS_DECL: SymbolKind.CLASS,
        CursorKind.CXX_METHOD: SymbolKind.FUNCTION,
        CursorKind.FIELD_DECL: SymbolKind.FIELD,
    }


def _get_signature(cursor):
    kind = _KIND_MAP.get(cursor.kind, SymbolKind.GENERIC)
    name = cursor.spelling or cursor.displayname
    if kind == SymbolKind.FUNCTION:
        rtype = cursor.result_type.spelling if cursor.result_type else "void"
        params = []
        for ch in cursor.get_children():
            if ch.kind == CursorKind.PARM_DECL:
                params.append(f"{ch.type.spelling} {ch.spelling}".strip())
        return f"{rtype} {name}({', '.join(params)})"
    elif kind == SymbolKind.VARIABLE:
        return f"{cursor.type.spelling} {name}"
    elif kind == SymbolKind.TYPEDEF:
        return f"typedef {cursor.underlying_typedef_type.spelling} {name}"
    elif kind in (SymbolKind.STRUCT, SymbolKind.UNION, SymbolKind.CLASS):
        kw = {SymbolKind.STRUCT: "struct", SymbolKind.UNION: "union", SymbolKind.CLASS: "class"}[
            kind
        ]
        return f"{kw} {name}"
    elif kind == SymbolKind.ENUM:
        return f"enum {name}"
    elif kind == SymbolKind.FIELD:
        return f"{cursor.type.spelling} {name}"
    return name


def _get_params(cursor):
    if not CLANG_AVAILABLE:
        return []
    return [
        (ch.type.spelling, ch.spelling or "")
        for ch in cursor.get_children()
        if ch.kind == CursorKind.PARM_DECL
    ]


def _parse_cursor(cursor, filename):
    raw = cursor.raw_comment
    if not raw:
        return None

    kind = _KIND_MAP.get(cursor.kind, SymbolKind.GENERIC)
    name = cursor.spelling or cursor.displayname or ""

    if kind == SymbolKind.MACRO and cursor.kind == CursorKind.MACRO_DEFINITION:
        tokens = list(cursor.get_tokens())
        if len(tokens) >= 2 and tokens[1].spelling == "(":
            kind = SymbolKind.MACRO_FUNCTION

    doc = DocComment(
        name=name,
        kind=kind,
        comment=clean_comment(raw),
        signature=_get_signature(cursor),
        filename=filename,
        line=cursor.location.line if cursor.location else 0,
        return_type=(
            cursor.result_type.spelling
            if hasattr(cursor, "result_type") and cursor.result_type
            else ""
        ),
        params=_get_params(cursor),
    )

    if kind in (SymbolKind.STRUCT, SymbolKind.UNION, SymbolKind.CLASS, SymbolKind.ENUM):
        for ch in cursor.get_children():
            child_doc = _parse_cursor(ch, filename)
            if child_doc:
                doc.members.append(child_doc)
    return doc


def parse_file(filepath, clang_args=None):
    if not CLANG_AVAILABLE:
        raise RuntimeError("clang bindings not available, pip install clang")

    idx = Index.create()
    args = list(clang_args or []) + ["-detailed-preprocessing-record"]

    try:
        tu = idx.parse(
            filepath, args=args, options=TranslationUnit.PARSE_DETAILED_PROCESSING_RECORD
        )
    except TranslationUnitLoadError as exc:
        raise RuntimeError(f"Failed to parse {filepath}: {exc}") from exc

    docs = []
    fname = os.path.basename(filepath)
    abspath = os.path.abspath(filepath)
    for cursor in tu.cursor.get_children():
        if cursor.location and cursor.location.file:
            if os.path.abspath(cursor.location.file.name) != abspath:
                continue
        doc = _parse_cursor(cursor, fname)
        if doc:
            docs.append(doc)
    return docs


# -- regex fallback --


def parse_file_regex(filepath):
    with open(filepath, "r", encoding="utf-8", errors="replace") as f:
        source = f.read()

    docs = []
    fname = os.path.basename(filepath)
    # Match /** comment */ followed by a C declaration
    pat = re.compile(r"/\*\*(.+?)\*/\s*\n\s*(.+?)(?:\n|;|\{)", re.DOTALL)

    for m in pat.finditer(source):
        comment = clean_comment("/**" + m.group(1) + "*/")
        decl = m.group(2).strip()

        # Skip if "declaration" is actually another comment or empty
        if not decl or decl.startswith("/*") or decl.startswith("//"):
            continue

        kind = SymbolKind.GENERIC
        name = decl.split("(")[0].split()[-1] if decl else "unknown"
        return_type = ""
        params_list = []

        if "(" in decl:
            kind = SymbolKind.FUNCTION
            # Extract return type and name from pre-paren part
            pre_paren = decl.split("(")[0].strip()
            tokens = pre_paren.split()
            if tokens:
                raw_name = tokens[-1]
                rtype_parts = tokens[:-1]
                # Handle pointer returns: char *func -> name=func, return=char *
                if raw_name.startswith("*"):
                    name = raw_name.lstrip("*")
                    stars = "*" * (len(raw_name) - len(name))
                    return_type = " ".join(rtype_parts) + " " + stars if rtype_parts else stars
                else:
                    name = raw_name
                    return_type = " ".join(rtype_parts) if rtype_parts else ""
                return_type = return_type.strip()
            # Extract params from parenthesized portion
            paren_match = re.search(r"\(([^)]*)\)", decl)
            if paren_match:
                param_str = paren_match.group(1).strip()
                if param_str and param_str != "void":
                    for p in param_str.split(","):
                        p = p.strip()
                        if not p:
                            continue
                        ptokens = p.split()
                        if len(ptokens) >= 2:
                            pname = ptokens[-1].lstrip("*")
                            ptype = " ".join(ptokens[:-1])
                            if ptokens[-1].startswith("*"):
                                ptype += " " + "*" * (len(ptokens[-1]) - len(pname))
                                ptype = ptype.strip()
                            params_list.append((ptype, pname))
                        elif ptokens:
                            params_list.append(("", ptokens[0]))
        elif decl.startswith("struct "):
            kind = SymbolKind.STRUCT
        elif decl.startswith("union "):
            kind = SymbolKind.UNION
        elif decl.startswith("enum "):
            kind = SymbolKind.ENUM
        elif decl.startswith("typedef "):
            kind = SymbolKind.TYPEDEF
        elif decl.startswith("#define"):
            kind = SymbolKind.MACRO
            parts = decl.split()
            name = parts[1].split("(")[0] if len(parts) > 1 else "unknown"

        # Strip leading * from name (pointer returns)
        name = name.lstrip("*")

        # Clean signature for display
        sig = decl.rstrip("{").rstrip().rstrip(";").strip()

        docs.append(
            DocComment(
                name=name,
                kind=kind,
                comment=comment,
                signature=sig,
                filename=fname,
                return_type=return_type,
                params=params_list,
            )
        )
    return docs


# -- IGT test metadata parsing --


@dataclass
class SubtestMeta:
    name: str
    fields: dict = field(default_factory=dict)
    line: int = 0
    steps: list[str] = field(default_factory=list)


@dataclass
class IGTTestMeta:
    name: str
    filename: str
    fields: dict = field(default_factory=dict)
    subtests: list[SubtestMeta] = field(default_factory=list)


_IGT_TEST_BLOCK_RE = re.compile(r"/\*\*(.+?)\*/", re.DOTALL)
_IGT_SUBTEST_CALL_RE = re.compile(
    r'igt_subtest\s*\(\s*"([^"]+)"\s*\)|' r'igt_subtest_f\s*\(\s*"([^"]+)"',
    re.MULTILINE,
)
_IGT_DESCRIBE_RE = re.compile(r'igt_describe\s*\(\s*"([^"]+)"\s*\)')
_IGT_DYNAMIC_RE = re.compile(
    r'igt_subtest_with_dynamic\s*\(\s*"([^"]+)"\s*\)|'
    r'igt_subtest_with_dynamic_f\s*\(\s*"([^"]+)"',
)


def _parse_structured_comment(text):
    lines = text.split("\n")
    cleaned = []
    for line in lines:
        s = line.lstrip()
        if s.startswith("* "):
            cleaned.append(s[2:])
        elif s.startswith("*"):
            cleaned.append(s[1:])
        else:
            cleaned.append(s)
    return "\n".join(cleaned).strip()


def _parse_test_comment(comment_text):
    text = _parse_structured_comment(comment_text)
    if "TEST:" not in text:
        return None

    test = IGTTestMeta(name="", filename="")
    current_subtest = None
    current_key = None  # Track which field is being accumulated
    current_target = None  # test.fields or current_subtest.fields

    for line in text.split("\n"):
        stripped = line.strip()

        if stripped.startswith("SUBTEST:"):
            _flush_multiline(current_target, current_key)
            current_key = None
            name = stripped[len("SUBTEST:") :].strip()
            # Skip format-string subtests
            if "%s" in name or "%d" in name or "%u" in name:
                current_subtest = None
                current_target = None
                continue
            current_subtest = SubtestMeta(name=name)
            current_target = current_subtest.fields
            test.subtests.append(current_subtest)
            continue

        if stripped.startswith("TEST:"):
            _flush_multiline(current_target, current_key)
            current_key = None
            test.name = stripped[len("TEST:") :].strip()
            current_subtest = None
            current_target = test.fields
            continue

        if ":" in stripped:
            key, _, val = stripped.partition(":")
            key_raw = key.strip()
            key_clean = key_raw.lower().replace(" ", "_")
            val = val.strip()
            # Only treat as a field if key looks like a field name:
            # - up to 3 words (e.g. "Mega feature", "Sub category")
            # - no punctuation other than hyphens/underscores
            word_count = len(key_raw.split())
            looks_like_field = key_clean and word_count <= 3 and re.match(r"^[\w\s-]+$", key_raw)
            if looks_like_field:
                _flush_multiline(current_target, current_key)
                target = current_subtest.fields if current_subtest else test.fields
                current_target = target
                if val:
                    target[key_clean] = val
                    current_key = None
                else:
                    # Value on next line(s)
                    target[key_clean] = ""
                    current_key = key_clean
                continue

        # Continuation line for multi-line value
        if stripped and current_key and current_target is not None:
            existing = current_target.get(current_key, "")
            if existing:
                current_target[current_key] = existing + " " + stripped
            else:
                current_target[current_key] = stripped
            continue

        # Blank line — stop accumulating
        if not stripped:
            if current_key:
                _flush_multiline(current_target, current_key)
                current_key = None

    _flush_multiline(current_target, current_key)
    return test if test.name else None


def _flush_multiline(target, key):
    """Clean up a multi-line field value."""
    if target and key and key in target:
        target[key] = target[key].strip()


def _extract_brace_body(source, open_pos):
    """Extract the content between { and matching } starting at open_pos."""
    depth = 0
    i = open_pos
    while i < len(source):
        if source[i] == "{":
            depth += 1
        elif source[i] == "}":
            depth -= 1
            if depth == 0:
                return source[open_pos + 1 : i]
        i += 1
    return ""


# Patterns for recognising meaningful steps in subtest bodies
_STEP_COMMENT_RE = re.compile(r"/\*\s*(.+?)\s*\*/", re.DOTALL)
_STEP_LINE_COMMENT_RE = re.compile(r"//\s*(.+)")
_STEP_ASSERT_RE = re.compile(r"igt_assert(?:_eq|_neq|_lt|_lte|_f|_fd)?\s*\((.+)")
_STEP_REQUIRE_RE = re.compile(r"igt_require\s*\((.+)")
_STEP_SKIP_RE = re.compile(r"igt_skip\s*\((.+)")
_STEP_IGT_CALL_RE = re.compile(r"(igt_\w+|gem_\w+|kms_\w+|drmIoctl|drm_\w+|do_ioctl\w*)\s*\(")
_STEP_FUNC_CALL_RE = re.compile(r"(\w+)\s*\(")
_STEP_ASSIGN_RE = re.compile(r"(\w[\w\.\->]*)\s*=\s*(.+)")

# Ignored patterns — boilerplate that should not become steps
_STEP_IGNORE = {
    "close",
    "free",
    "munmap",
    "memset",
    "memcpy",
    "errno",
    "return",
    "break",
    "continue",
}


def _parse_subtest_steps(body):
    """Extract human-readable steps from a subtest body.

    Returns a list of step items.  Each item is either:
      - a string  (normal numbered step)
      - a tuple   ("if", condition_text, [child_step_strings])
    """
    raw = _collect_raw_steps(body.split("\n"), 0, len(body.split("\n")))

    # Post-process: deduplicate comment + code step pairs
    deduped = []
    i = 0
    while i < len(raw):
        item = raw[i]
        if isinstance(item, str):
            is_comment = (
                not item.startswith("Assert ")
                and not item.startswith("Call ")
                and not item.startswith("Require ")
                and not item.startswith("Set ")
                and not item.startswith("Skip ")
            )
            if is_comment and i + 1 < len(raw) and isinstance(raw[i + 1], str):
                nxt = raw[i + 1]
                if nxt.startswith("Assert ") or nxt.startswith("Call ") or nxt.startswith("Set "):
                    deduped.append(item)
                    i += 2
                    continue
        deduped.append(item)
        i += 1

    return deduped


# Regex to match if/else if lines and capture the condition
_IF_RE = re.compile(r"^(?:}\s*)?(?:else\s+)?if\s*\((.+?)\)\s*\{?\s*$")
_ELSE_RE = re.compile(r"^}\s*else\s*\{?\s*$")


def _collect_raw_steps(lines, start, end):
    """Recursively collect steps, handling if-blocks."""
    steps = []
    i = start
    while i < end:
        line = lines[i].strip()
        i += 1

        if not line or line == "{" or line == "}":
            continue

        # Detect if (...) { block
        m_if = _IF_RE.match(line)
        if m_if:
            condition = m_if.group(1).strip()
            # Find the matching closing brace
            block_end = _find_block_end(lines, i, end)
            # Recursively collect steps inside the if-body
            child_steps = _collect_raw_steps(lines, i, block_end)
            if child_steps:
                steps.append(("if", condition, child_steps))
            i = block_end + 1  # skip past the closing }

            # Check for } else { or } else if on the closing brace line
            closing_line = lines[block_end].strip() if block_end < end else ""
            while True:
                m_eic = _ELSE_IF_COMBINED_RE.match(closing_line)
                m_ec = _ELSE_COMBINED_RE.match(closing_line)
                if m_eic:
                    cond2 = m_eic.group(1).strip()
                    block_end2 = _find_block_end(lines, i, end)
                    child2 = _collect_raw_steps(lines, i, block_end2)
                    if child2:
                        steps.append(("if", cond2, child2))
                    closing_line = lines[block_end2].strip() if block_end2 < end else ""
                    i = block_end2 + 1
                elif m_ec:
                    block_end2 = _find_block_end(lines, i, end)
                    child2 = _collect_raw_steps(lines, i, block_end2)
                    if child2:
                        steps.append(("if", "otherwise", child2))
                    i = block_end2 + 1
                    break
                else:
                    # Also check the next non-empty line for standalone else
                    next_i = i
                    while next_i < end and not lines[next_i].strip():
                        next_i += 1
                    if next_i < end:
                        nl = lines[next_i].strip()
                        m_eic2 = _IF_RE.match(nl)
                        m_ec2 = _ELSE_RE.match(nl)
                        if m_eic2 and "else" in nl:
                            i = next_i
                            # Let the loop re-check
                            closing_line = nl
                            # Rewrite as combined form to reuse logic
                            if _ELSE_IF_COMBINED_RE.match(closing_line):
                                continue
                        elif m_ec2:
                            i = next_i + 1
                            block_end2 = _find_block_end(lines, i, end)
                            child2 = _collect_raw_steps(lines, i, block_end2)
                            if child2:
                                steps.append(("if", "otherwise", child2))
                            i = block_end2 + 1
                    break
            continue

        # Detect else-if or else at top level (without leading })
        m_else = _ELSE_RE.match(line)
        if m_else:
            block_end = _find_block_end(lines, i, end)
            child_steps = _collect_raw_steps(lines, i, block_end)
            if child_steps:
                steps.append(("if", "otherwise", child_steps))
            i = block_end + 1
            continue

        # --- Regular step extraction (same as before) ---

        # Block comments: /* ... */
        mc = _STEP_COMMENT_RE.search(line)
        if mc and not line.startswith("/*<") and "language=" not in line:
            comment_text = mc.group(1).strip()
            comment_text = re.sub(r"\s*\n\s*\*?\s*", " ", comment_text)
            if comment_text and len(comment_text) > 2:
                steps.append(comment_text.rstrip(".") + ".")
            continue

        # Line comments: // ...
        mlc = _STEP_LINE_COMMENT_RE.match(line)
        if mlc:
            comment_text = mlc.group(1).strip()
            if comment_text and len(comment_text) > 2:
                steps.append(comment_text.rstrip(".") + ".")
            continue

        # igt_skip
        msk = _STEP_SKIP_RE.search(line)
        if msk:
            steps.append("Skip if preconditions not met.")
            continue

        # igt_require
        mreq = _STEP_REQUIRE_RE.search(line)
        if mreq:
            cond = mreq.group(1).rstrip(");").strip()
            steps.append(f"Require `{cond}`.")
            continue

        # igt_assert variants
        ma = _STEP_ASSERT_RE.search(line)
        if ma:
            cond = ma.group(1).rstrip(");").strip()
            if len(cond) > 80:
                cond = cond[:77] + "..."
            steps.append(f"Assert `{cond}`.")
            continue

        # igt_* / gem_* / kms_* / drm* calls
        migt = _STEP_IGT_CALL_RE.search(line)
        if migt:
            func = migt.group(1)
            steps.append(f"Call `{func}()`.")
            continue

        # Variable assignment with function call
        masn = _STEP_ASSIGN_RE.match(line)
        if masn:
            var = masn.group(1)
            rhs = masn.group(2).strip().rstrip(";")
            mf = _STEP_FUNC_CALL_RE.match(rhs)
            if mf:
                func = mf.group(1)
                if func not in _STEP_IGNORE:
                    steps.append(f"Set `{var}` from `{func}()`.")
                    continue

        # Generic function call
        mfc = _STEP_FUNC_CALL_RE.match(line)
        if mfc:
            func = mfc.group(1)
            if func not in _STEP_IGNORE and not func.startswith("__"):
                steps.append(f"Call `{func}()`.")
                continue

    return steps


def _find_block_end(lines, start, end):
    """Find the index of the line containing the closing } for the block.

    Stops at '} else {' or '} else if (...) {' treating them as the
    end of the current block (the else/else-if opens a new block).
    """
    depth = 1
    i = start
    while i < end:
        line = lines[i].strip()
        # Check for } else { or } else if — these close the current block
        if depth == 1 and (_ELSE_COMBINED_RE.match(line) or _ELSE_IF_COMBINED_RE.match(line)):
            return i
        depth += line.count("{") - line.count("}")
        if depth <= 0:
            return i
        i += 1
    return end - 1


# Match } else { or } else if (...) { on the SAME line as closing brace
_ELSE_IF_COMBINED_RE = re.compile(r"}\s*else\s+if\s*\((.+?)\)\s*\{?\s*$")
_ELSE_COMBINED_RE = re.compile(r"}\s*else\s*\{?\s*$")


def _extract_subtest_bodies(source):
    """Find all igt_subtest("name") { ... } blocks and return {name: body}."""
    bodies = {}
    # Match igt_subtest("name"), igt_subtest_f("name"...),
    # and igt_subtest_with_dynamic("name")
    pat = re.compile(
        r'igt_subtest(?:_f|_with_dynamic(?:_f)?)?\s*\(\s*"([^"]+)"[^)]*\)\s*\{',
    )
    for m in pat.finditer(source):
        name = m.group(1)
        brace_pos = m.end() - 1  # position of the opening {
        body = _extract_brace_body(source, brace_pos)
        bodies[name] = body
    return bodies


def parse_igt_test_file(filepath, extract_steps=True):
    with open(filepath, "r", encoding="utf-8", errors="replace") as f:
        source = f.read()

    fname = os.path.basename(filepath)
    test = None

    for m in _IGT_TEST_BLOCK_RE.finditer(source):
        parsed = _parse_test_comment(m.group(1))
        if parsed:
            test = parsed
            test.filename = fname
            break

    if test is None:
        stem = os.path.splitext(fname)[0]
        test = IGTTestMeta(name=stem, filename=fname)

    comment_subtests = {s.name for s in test.subtests}

    # Scan all /** ... */ comment blocks for standalone SUBTEST: entries
    # These may contain descriptions and fields not in the main TEST block
    _standalone_subtests = {}  # name -> fields dict
    for m in _IGT_TEST_BLOCK_RE.finditer(source):
        block_text = _parse_structured_comment(m.group(1))
        if re.search(r"(?<!\bSUB)TEST:", block_text):
            continue  # Skip the main TEST block, already parsed
        if "SUBTEST:" not in block_text:
            continue
        # Parse this standalone SUBTEST block
        current_name = None
        current_key = None
        current_fields = None
        for bline in block_text.split("\n"):
            stripped = bline.strip()
            if stripped.startswith("SUBTEST:"):
                if current_name and current_fields:
                    _flush_multiline(current_fields, current_key)
                    _standalone_subtests[current_name] = current_fields
                current_name = stripped[len("SUBTEST:") :].strip()
                if "%s" in current_name or "%d" in current_name or "%u" in current_name:
                    current_name = None
                    current_fields = None
                    current_key = None
                    continue
                current_fields = {}
                current_key = None
                continue
            if current_fields is None:
                continue
            if ":" in stripped:
                key, _, val = stripped.partition(":")
                key_raw = key.strip()
                key_clean = key_raw.lower().replace(" ", "_")
                word_count = len(key_raw.split())
                if key_clean and word_count <= 3 and re.match(r"^[\w\s-]+$", key_raw):
                    _flush_multiline(current_fields, current_key)
                    val = val.strip()
                    if val:
                        current_fields[key_clean] = val
                        current_key = None
                    else:
                        current_fields[key_clean] = ""
                        current_key = key_clean
                    continue
            # Continuation line
            if stripped and current_key and current_fields is not None:
                existing = current_fields.get(current_key, "")
                current_fields[current_key] = (existing + " " + stripped).strip()
                continue
            if not stripped and current_key:
                _flush_multiline(current_fields, current_key)
                current_key = None
        if current_name and current_fields:
            _flush_multiline(current_fields, current_key)
            _standalone_subtests[current_name] = current_fields

    lines = source.split("\n")
    pending_desc = None
    pending_describe_buf = None  # For multi-line igt_describe
    for i, line in enumerate(lines):
        # Handle multi-line igt_describe accumulation
        if pending_describe_buf is not None:
            pending_describe_buf += " " + line.strip()
            # Check if the line completes the igt_describe call
            if ")" in line and '"' in pending_describe_buf:
                # Extract all quoted strings and join them
                parts = re.findall(r'"([^"]*)"', pending_describe_buf)
                if parts:
                    pending_desc = "".join(parts)
                pending_describe_buf = None
            continue

        dm = _IGT_DESCRIBE_RE.search(line)
        if dm:
            pending_desc = dm.group(1)
            continue

        # Detect start of multi-line igt_describe (opening paren + quote but no closing)
        dm_start = re.search(r'igt_describe\s*\(\s*"([^"]*)"?\s*$', line)
        if dm_start:
            pending_describe_buf = line.strip()
            continue

        sm = _IGT_SUBTEST_CALL_RE.search(line)
        if sm:
            name = sm.group(1) or sm.group(2)
            # Skip format-string subtests like "%s" or names containing %s
            if "%s" in name or "%d" in name or "%u" in name:
                pending_desc = None
                continue
            if name not in comment_subtests:
                sub = SubtestMeta(name=name, line=i + 1)
                if pending_desc:
                    sub.fields["description"] = pending_desc
                test.subtests.append(sub)
                comment_subtests.add(name)
            elif pending_desc:
                for s in test.subtests:
                    if s.name == name and "description" not in s.fields:
                        s.fields["description"] = pending_desc
                        s.line = i + 1
                        break
            pending_desc = None
            continue

        dyn = _IGT_DYNAMIC_RE.search(line)
        if dyn:
            name = dyn.group(1) or dyn.group(2)
            # Skip format-string dynamic subtests
            if "%s" in name or "%d" in name or "%u" in name:
                pending_desc = None
                continue
            if name not in comment_subtests:
                sub = SubtestMeta(name=name, line=i + 1)
                sub.fields["dynamic"] = "true"
                if pending_desc:
                    sub.fields["description"] = pending_desc
                test.subtests.append(sub)
                comment_subtests.add(name)
            pending_desc = None
            continue

        # Only clear pending_desc on lines that are clearly NOT part of
        # the igt_describe -> igt_subtest sequence.
        # Keep it across: blank lines, comments, braces, igt_ calls
        if stripped_line := line.strip():
            if not stripped_line.startswith(
                ("//", "/*", "*", "{", "}")
            ) and not stripped_line.startswith("igt_"):
                pending_desc = None

    # Merge fields from standalone SUBTEST comment blocks
    # These fill in missing fields (especially description) for subtests
    # that were discovered from code or the main TEST block
    if _standalone_subtests:
        for sub in test.subtests:
            standalone = _standalone_subtests.get(sub.name)
            if not standalone:
                continue
            for key, val in standalone.items():
                if key not in sub.fields or not sub.fields[key]:
                    sub.fields[key] = val
        # Also create subtests that only exist in standalone comments
        for name, fields in _standalone_subtests.items():
            if name not in comment_subtests:
                sub = SubtestMeta(name=name)
                sub.fields.update(fields)
                test.subtests.append(sub)
                comment_subtests.add(name)

    # Extract subtest bodies and parse steps (only if enabled)
    if extract_steps:
        bodies = _extract_subtest_bodies(source)
        for sub in test.subtests:
            body = bodies.get(sub.name, "")
            if body:
                sub.steps = _parse_subtest_steps(body)

    return test
