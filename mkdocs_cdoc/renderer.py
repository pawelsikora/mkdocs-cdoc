"""
Markdown renderer for parsed doc comments.

Takes DocComment objects from the parser and turns them into Markdown with
headings, parameter tables, anchor IDs, and side-by-side example layouts.
"""

from __future__ import annotations
import re
from .parser import SymbolKind, rst_to_markdown

_KIND_LABELS = {
    SymbolKind.FUNCTION: "Function",
    SymbolKind.VARIABLE: "Variable",
    SymbolKind.TYPEDEF: "Type",
    SymbolKind.MACRO: "Macro",
    SymbolKind.MACRO_FUNCTION: "Macro",
    SymbolKind.STRUCT: "Struct",
    SymbolKind.UNION: "Union",
    SymbolKind.ENUM: "Enum",
    SymbolKind.ENUM_CONSTANT: "Enumerator",
    SymbolKind.CLASS: "Class",
    SymbolKind.FIELD: "Field",
    SymbolKind.GENERIC: "",
    SymbolKind.TEST: "Test",
    SymbolKind.SUBTEST: "Subtest",
    SymbolKind.FILE: "File",
}

_KIND_ANCHOR_PREFIX = {
    SymbolKind.FUNCTION: "func",
    SymbolKind.VARIABLE: "var",
    SymbolKind.TYPEDEF: "type",
    SymbolKind.MACRO: "macro",
    SymbolKind.MACRO_FUNCTION: "macro",
    SymbolKind.STRUCT: "struct",
    SymbolKind.UNION: "union",
    SymbolKind.ENUM: "enum",
    SymbolKind.ENUM_CONSTANT: "enumval",
    SymbolKind.CLASS: "class",
    SymbolKind.FIELD: "field",
    SymbolKind.GENERIC: "sym",
    SymbolKind.TEST: "test",
    SymbolKind.SUBTEST: "subtest",
    SymbolKind.FILE: "file",
}


def anchor_id(doc):
    prefix = _KIND_ANCHOR_PREFIX.get(doc.kind, "sym")
    return f"{prefix}-{doc.name}"


class RenderConfig:
    def __init__(
        self,
        *,
        heading_level=3,
        show_source_link=False,
        source_uri="",
        members=True,
        signature_style="code",
        convert_rst=True,
        language="c",
    ):
        self.heading_level = heading_level
        self.show_source_link = show_source_link
        self.source_uri = source_uri
        self.members = members
        self.signature_style = signature_style
        self.convert_rst = convert_rst
        self.language = language


def _heading(text, level):
    return f"{'#' * level} {text}"


def _source_link(doc, cfg):
    if not cfg.show_source_link or not cfg.source_uri:
        return ""
    uri = cfg.source_uri.format(filename=doc.filename, line=doc.line)
    return f" [[source]({uri})]"


def render_doc(doc, cfg=None):
    if cfg is None:
        cfg = RenderConfig()

    parts = []
    label = _KIND_LABELS.get(doc.kind, "")
    htxt = f"`{doc.name}`" if doc.name else "Documentation"
    if label:
        htxt = f"{label}: {htxt}"
    htxt += _source_link(doc, cfg)

    aid = anchor_id(doc)
    parts.append(f'<a id="{aid}"></a>')
    parts.append("")
    parts.append(_heading(htxt, cfg.heading_level))
    parts.append("")

    if doc.signature and cfg.signature_style == "code":
        parts += [f"```{cfg.language}", doc.signature, "```", ""]

    comment = doc.comment
    if cfg.convert_rst:
        comment = rst_to_markdown(comment, doc=doc)
    if comment:
        # Extract appendix section (HowTo / Notes) before other processing
        appendix_md = ""
        if "<!-- APPENDIX_START -->" in comment:
            before_appendix, _, appendix_rest = comment.partition("<!-- APPENDIX_START -->")
            appendix_block, _, _ = appendix_rest.partition("<!-- APPENDIX_END -->")
            comment = before_appendix.rstrip()

            howto_text = ""
            notes_text = ""
            if "<!-- HOWTO_START -->" in appendix_block:
                _, _, rest = appendix_block.partition("<!-- HOWTO_START -->")
                howto_text, _, appendix_block = rest.partition("<!-- HOWTO_END -->")
                howto_text = howto_text.strip()
            if "<!-- NOTES_START -->" in appendix_block:
                _, _, rest = appendix_block.partition("<!-- NOTES_START -->")
                notes_text, _, _ = rest.partition("<!-- NOTES_END -->")
                notes_text = notes_text.strip()

            if howto_text or notes_text:
                ap_parts = ["", "<!-- APPENDIX_RENDER_START -->"]
                if howto_text:
                    ap_parts += ["**How To:**", "", howto_text, ""]
                if notes_text:
                    # Render as MkDocs Material warning admonition
                    ap_parts.append("")
                    ap_parts.append('!!! warning "Note"')
                    for nline in notes_text.split("\n"):
                        ap_parts.append(f"    {nline}")
                    ap_parts.append("")
                ap_parts.append("<!-- APPENDIX_RENDER_END -->")
                appendix_md = "\n".join(ap_parts)

        # Extract all example blocks and render as cards
        if "<!-- EXAMPLE_START" in comment:
            _EX_SPLIT_RE = re.compile(
                r"<!-- EXAMPLE_START(?::([^>]*))? -->(.*?)<!-- EXAMPLE_END -->", re.DOTALL
            )
            examples = []
            last_end = 0
            body_parts = []
            for m in _EX_SPLIT_RE.finditer(comment):
                before = comment[last_end : m.start()].strip()
                if before:
                    body_parts.append(before)
                label = m.group(1) or "Example"
                ex_text = m.group(2).strip()
                examples.append((label, ex_text))
                last_end = m.end()
            trailing = comment[last_end:].strip()
            if trailing:
                body_parts.append(trailing)

            example_cards = []
            for label, ex_text in examples:
                code_lines = []
                in_fence = False
                fence_lang = "c"
                for line in ex_text.split("\n"):
                    if line.strip().startswith("```") and not in_fence:
                        in_fence = True
                        fence_lang = line.strip()[3:].strip() or "c"
                        continue
                    if line.strip().startswith("```") and in_fence:
                        in_fence = False
                        continue
                    if in_fence:
                        code_lines.append(line)
                code_text = "\n".join(code_lines)
                code_text = (
                    code_text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                )
                card = (
                    f'<div class="hm-example">'
                    f'<span class="hm-example-label">{label}</span>'
                    f'<pre><code class="language-{fence_lang}">{code_text}</code></pre>'
                    f"</div>"
                )
                example_cards.append(card)

            for card in example_cards:
                parts += [card, ""]
            for bp in body_parts:
                parts += [bp, ""]
        else:
            parts += [comment, ""]

        # Append the appendix (HowTo / Notes) after the main content
        if appendix_md:
            parts.append(appendix_md)

    if cfg.members and doc.members:
        mcfg = RenderConfig(
            heading_level=cfg.heading_level + 1,
            show_source_link=cfg.show_source_link,
            source_uri=cfg.source_uri,
            members=True,
            signature_style=cfg.signature_style,
            convert_rst=cfg.convert_rst,
            language=cfg.language,
        )
        for member in doc.members:
            parts.append(render_doc(member, mcfg))

    return "\n".join(parts)


def render_docs(docs, cfg=None):
    if cfg is None:
        cfg = RenderConfig()
    return "\n---\n\n".join(render_doc(d, cfg) for d in docs)


def render_autodoc(docs, cfg=None, *, title=None):
    if cfg is None:
        cfg = RenderConfig()
    parts = []
    if title:
        parts += [_heading(title, max(1, cfg.heading_level - 1)), ""]
    parts.append(render_docs(docs, cfg))
    return "\n".join(parts)


def render_single(docs, name, kind=None, cfg=None):
    if cfg is None:
        cfg = RenderConfig()
    for doc in docs:
        if doc.name == name and (kind is None or doc.kind == kind):
            return render_doc(doc, cfg)
        for member in doc.members:
            if member.name == name and (kind is None or member.kind == kind):
                return render_doc(member, cfg)
    return f"<!-- cdoc: symbol '{name}' not found -->\n"
