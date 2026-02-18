"""
MkDocs plugin for generating API documentation from C/C++ source comments.

This is the main plugin module. It hooks into MkDocs' build lifecycle to
discover source files, parse doc comments, build a cross-reference registry,
and render everything as Markdown pages. Also handles IGT GPU Tools test
catalog generation when configured.
"""

from __future__ import annotations

import fnmatch
import logging
import os
import re
from dataclasses import dataclass, field
from mkdocs.config import config_options
from mkdocs.config.base import Config as MkDocsConfig
from mkdocs.plugins import BasePlugin
from mkdocs.structure.files import File

from .parser import (
    SymbolKind,
    parse_file,
    parse_file_regex,
    CLANG_AVAILABLE,
    gtkdoc_to_rst,
    IGTTestMeta,
    parse_igt_test_file,
)
from .renderer import (
    RenderConfig,
    render_autodoc,
    render_doc,
    render_docs,
    render_single,
    anchor_id,
)

log = logging.getLogger("mkdocs.plugins.cdoc")

_DIRECTIVE_RE = re.compile(
    r"^(?P<indent>[ \t]*):::[ \t]+(?P<domain>c|cpp):"
    r"(?P<directive>autodoc|autofunction|autostruct|autounion|autoenum|automacro|autovar|autotype)\s*\n"
    r"(?P<body>(?:(?P=indent)[ \t]+:\w+:.*\n)*)",
    re.MULTILINE,
)
_OPTION_RE = re.compile(r"^\s+:(\w+):\s*(.+)$", re.MULTILINE)

_DIRECTIVE_KIND_MAP = {
    "autofunction": SymbolKind.FUNCTION,
    "autostruct": SymbolKind.STRUCT,
    "autounion": SymbolKind.UNION,
    "autoenum": SymbolKind.ENUM,
    "automacro": SymbolKind.MACRO,
    "autovar": SymbolKind.VARIABLE,
    "autotype": SymbolKind.TYPEDEF,
}

_CPP_EXTS = frozenset({".cpp", ".hpp", ".cc", ".hh", ".cxx", ".hxx"})


def _render_steps_html(steps):
    """Render a list of step items (strings or if-tuples) to HTML."""
    parts = ["<ol>"]
    for item in steps:
        if isinstance(item, tuple) and item[0] == "if":
            _, condition, children = item
            if condition == "otherwise":
                parts.append("</ol><p><em>Otherwise, do following steps:</em></p><ol>")
            else:
                parts.append(
                    f"</ol><p><em>If condition (<code>{condition}</code>) is met, "
                    f"do following steps:</em></p><ol>"
                )
            for child in children:
                if isinstance(child, tuple) and child[0] == "if":
                    parts.append(_render_steps_html([child]))
                else:
                    parts.append(f"<li>{child}</li>")
        else:
            parts.append(f"<li>{item}</li>")
    parts.append("</ol>")
    return "".join(parts)


_VERSION_RE = re.compile(
    r"""['"]?(?:version|VERSION|Version)['"]?\s*[:=]\s*['"]?(\d+\.\d+(?:\.\d+)?)['"]?"""
)


def _read_version(filepath):
    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                m = _VERSION_RE.search(line)
                if m:
                    return m.group(1)
    except OSError as exc:
        log.warning("cdoc: cannot read version file %s: %s", filepath, exc)
    return None


_RST_XREF_RE = re.compile(
    r":(?:c(?:pp)?:)?(?:func|macro|type|const|var|struct|union|enum|member|data|class|test|subtest|file):`([^`]+)`"
)
_BACKTICK_FUNC_RE = re.compile(r"(?<!\[)`(\w+)\(\)`(?!\])")
_BACKTICK_IDENT_RE = re.compile(r"(?<!\[)`(\w[\w-]*)`(?!\])")
_BACKTICK_FILE_RE = re.compile(
    r"(?<!\[)`([\w][\w.-]*/[\w][\w.-]*\.[\w]+|[\w][\w.-]*\.(?:c|h|cpp|hpp|cc|hh|cxx|hxx))`(?!\])"
)


@dataclass
class SymbolEntry:
    name: str
    kind: SymbolKind
    page_uri: str
    anchor: str
    group_title: str = ""


@dataclass
class SourceGroup:
    root: str
    nav_title: str = "API Reference"
    output_dir: str = "api"
    extensions: list[str] = field(default_factory=lambda: [".c", ".h"])
    exclude: list[str] = field(default_factory=list)
    clang_args: list[str] = field(default_factory=list)
    generate_index: bool = True
    pages: list[dict] = field(default_factory=list)
    # IGT test options
    test_mode: str = ""
    test_group_by: list[str] = field(default_factory=list)
    test_fields: list[str] = field(default_factory=list)
    extract_test_steps: bool = False
    # Runtime state
    discovered: list[str] = field(default_factory=list)
    generated_pages: dict[str, str] = field(default_factory=dict)
    test_metas: dict[str, IGTTestMeta] = field(default_factory=dict)


class CdocConfig(MkDocsConfig):
    source_root = config_options.Type(str, default="")
    clang_args = config_options.Type(list, default=[])
    sources = config_options.Type(list, default=[])
    heading_level = config_options.Type(int, default=2)
    show_source_link = config_options.Type(bool, default=False)
    source_uri = config_options.Type(str, default="")
    members = config_options.Type(bool, default=True)
    signature_style = config_options.Type(str, default="code")
    convert_rst = config_options.Type(bool, default=True)
    convert_gtkdoc = config_options.Type(bool, default=False)
    auto_xref = config_options.Type(bool, default=True)
    language = config_options.Type(str, default="c")
    fallback_parser = config_options.Type(bool, default=True)
    autodoc = config_options.Type(bool, default=True)
    autodoc_output_dir = config_options.Type(str, default="api_reference")
    autodoc_nav_title = config_options.Type(str, default="API Reference")
    autodoc_extensions = config_options.Type(list, default=[".c", ".h"])
    autodoc_exclude = config_options.Type(list, default=[])
    autodoc_index = config_options.Type(bool, default=True)
    autodoc_pages = config_options.Type(list, default=[])
    project_name = config_options.Type(str, default="")
    version_file = config_options.Type(str, default="")
    test_mode = config_options.Type(str, default="")
    test_group_by = config_options.Type(list, default=[])
    test_fields = config_options.Type(list, default=[])
    appendix_code_usages = config_options.Type(bool, default=False)
    extract_test_steps = config_options.Type(bool, default=False)


def _discover_sources(root, extensions, exclude):
    out = []
    exts = [e if e.startswith(".") else f".{e}" for e in extensions]
    for dirpath, _, fnames in os.walk(root):
        for fn in sorted(fnames):
            _, ext = os.path.splitext(fn)
            if ext.lower() not in exts:
                continue
            rel = os.path.relpath(os.path.join(dirpath, fn), root)
            if any(fnmatch.fnmatch(fn, p) or fnmatch.fnmatch(rel, p) for p in exclude):
                continue
            out.append(rel)
    return out


def _source_rel_to_md_uri(rel, output_dir):
    return f"{output_dir}/{rel.replace(os.sep, '/')}.md"


class CdocPlugin(BasePlugin[CdocConfig]):

    def __init__(self):
        super().__init__()
        self._cache = {}
        self._groups = []
        self._pages = {}
        self._tmpfiles = []
        self._symbols = {}
        self._symbol_names = set()
        self._ambiguous_files = set()
        self._use_dir_urls = True
        self._version = None

    # ── Symbol registry ──

    def _register_symbols(self, docs, page_uri, group=None):
        gtitle = group.nav_title if group else ""
        for doc in docs:
            aid = anchor_id(doc)
            entry = SymbolEntry(
                name=doc.name, kind=doc.kind, page_uri=page_uri, anchor=aid, group_title=gtitle
            )
            if doc.name not in self._symbols:
                self._symbols[doc.name] = entry
                self._symbol_names.add(doc.name)
            for member in doc.members:
                maid = anchor_id(member)
                mentry = SymbolEntry(
                    name=member.name,
                    kind=member.kind,
                    page_uri=page_uri,
                    anchor=maid,
                    group_title=gtitle,
                )
                qualified = f"{doc.name}.{member.name}"
                if member.name not in self._symbols:
                    self._symbols[member.name] = mentry
                    self._symbol_names.add(member.name)
                self._symbols[qualified] = mentry
                self._symbol_names.add(qualified)

    def _resolve_xref(self, name, current_page_uri=None):
        clean = name.strip()
        if clean.endswith("()"):
            clean = clean[:-2]

        entry = self._symbols.get(clean)
        if not entry:
            return None

        target = entry.page_uri
        anchor = entry.anchor
        if current_page_uri and target == current_page_uri:
            return f"#{anchor}" if anchor else ""

        if current_page_uri:
            # When use_directory_urls is true, pages are served as
            # foo/bar.c.md -> foo/bar.c/index.html
            # So we need to compute relative paths between directory URLs
            if self._use_dir_urls:
                # Convert .md paths to directory paths for relpath calculation
                # "api/lib/igt_aux.c.md" -> "api/lib/igt_aux.c/"
                target_dir = target.removesuffix(".md") + "/"
                current_dir = current_page_uri.removesuffix(".md") + "/"
                from_dir = current_dir  # we're "inside" this directory
                rel = (
                    os.path.relpath(target_dir.rstrip("/"), from_dir.rstrip("/")).replace(
                        os.sep, "/"
                    )
                    + "/"
                )
            else:
                from_dir = os.path.dirname(current_page_uri)
                rel = os.path.relpath(target, from_dir).replace(os.sep, "/")
        else:
            rel = target

        # Build the final URL with ?h= highlight parameter and anchor
        if anchor:
            return f"{rel}?h={clean}#{anchor}"
        return rel

    def _apply_xrefs(self, markdown, current_page_uri=None):
        # Keep example cards safe from cross-reference rewriting
        _EXAMPLE_CARD_RE = re.compile(r'<div class="hm-example">.*?</div>', re.DOTALL)
        protected = {}
        counter = [0]

        def _protect(m):
            key = f"\x00HMEX{counter[0]}\x00"
            protected[key] = m.group(0)
            counter[0] += 1
            return key

        text = _EXAMPLE_CARD_RE.sub(_protect, markdown)

        def replace_rst_ref(m):
            name = m.group(1)
            url = self._resolve_xref(name, current_page_uri)
            display = name.rstrip("()")
            if url:
                return f"[`{display}`]({url})"
            return f"`{display}`"

        text = _RST_XREF_RE.sub(replace_rst_ref, text)

        if self.config["auto_xref"]:
            text = self._auto_xref_backticks(text, current_page_uri)

        # Put the example cards back
        for key, val in protected.items():
            text = text.replace(key, val)

        # MkDocs skips markdown inside raw HTML, so we convert
        # links and backtick spans to proper HTML ourselves
        text = self._md_links_in_html(text)

        # Clean up any leftover C comment artifacts (stray /** or */ lines)
        text = self._sanitize_output(text)

        return text

    # Match markdown links: [text](url)
    _MD_LINK_RE = re.compile(r"\[`?([^]]+?)`?\]\(([^)]+)\)")

    def _md_links_in_html(self, text):
        """Convert markdown links and backtick spans to HTML inside HTML blocks."""
        result = []
        in_html = False
        for line in text.split("\n"):
            stripped = line.strip()
            # Track HTML block context
            if stripped.startswith(
                ("<table", "<thead", "<tbody", "<tr", "<td", "<th", "<div", "<ol", "<ul", "<li")
            ):
                in_html = True
            if stripped.startswith(("</table", "</tbody", "</div>")):
                in_html = True  # still process closing line

            if in_html:
                # Convert [`text`](url) and [text](url) → <a href><code>text</code></a>
                if self._MD_LINK_RE.search(line):
                    line = self._MD_LINK_RE.sub(
                        lambda m: f'<a href="{m.group(2)}"><code>{m.group(1)}</code></a>', line
                    )
                # Convert remaining `text` backtick spans → <code>text</code>
                line = re.sub(r"`([^`]+)`", r"<code>\1</code>", line)

            if stripped.startswith(("</table", "</div>")):
                in_html = False

            result.append(line)
        return "\n".join(result)

    # Regex for lines that are just comment artifacts (not inside code blocks)
    _ARTIFACT_LINE_RE = re.compile(r"^\s*(?:/\*\*|\*\*/|/\*|\*/)\s*$")

    def _sanitize_output(self, text):
        """Remove stray C comment artifacts from rendered markdown."""
        lines = text.split("\n")
        result = []
        in_code = False
        in_html_pre = False
        for line in lines:
            # Leave fenced code blocks alone
            stripped = line.strip()
            if stripped.startswith("```"):
                in_code = not in_code
            if "<pre>" in line or "<code" in line:
                in_html_pre = True
            if "</pre>" in line or "</code>" in line:
                in_html_pre = False

            if not in_code and not in_html_pre:
                # Remove lines that are just /** or **/ or /* or */
                if self._ARTIFACT_LINE_RE.match(line):
                    continue
                # Remove leading /** or **/ at the start of a line that has other content
                line = re.sub(r"^\s*/\*\*\s*$", "", line)
                line = re.sub(r"^\s*\*\*/\s*$", "", line)
            result.append(line)
        return "\n".join(result)

    def _auto_xref_backticks(self, text, current_page_uri=None):
        def replace_file(m):
            name = m.group(1)
            if name not in self._symbol_names:
                return m.group(0)
            url = self._resolve_xref(name, current_page_uri)
            if url:
                return f"[`{name}`]({url})"
            return m.group(0)

        def replace_func(m):
            name = m.group(1)
            url = self._resolve_xref(name, current_page_uri)
            if url:
                return f"[`{name}()`]({url})"
            return m.group(0)

        def replace_ident(m):
            name = m.group(1)
            if name not in self._symbol_names:
                return m.group(0)
            url = self._resolve_xref(name, current_page_uri)
            if url:
                return f"[`{name}`]({url})"
            return m.group(0)

        text = _BACKTICK_FILE_RE.sub(replace_file, text)
        text = _BACKTICK_FUNC_RE.sub(replace_func, text)
        text = _BACKTICK_IDENT_RE.sub(replace_ident, text)
        return text

    # ── Appendix: "Referenced by" code examples ──

    def _extract_code_usages(self, func_name, group, max_results=3):
        """Find up to max_results call sites of func_name across all source groups."""
        usages = []
        call_pat = re.compile(r"\b" + re.escape(func_name) + r"\s*\(")
        for g in self._groups:
            for rel in g.discovered:
                abspath = os.path.join(g.root, rel)
                try:
                    with open(abspath, "r", encoding="utf-8", errors="replace") as f:
                        lines = f.readlines()
                except OSError:
                    continue

                for i, line in enumerate(lines):
                    if not call_pat.search(line):
                        continue
                    stripped = line.strip()

                    # Skip doc comments and comment lines
                    if stripped.startswith(("*", "/*", "//", "/**")):
                        continue
                    # Skip lines inside block comments
                    in_comment = False
                    for j in range(max(0, i - 5), i):
                        lj = lines[j].strip()
                        if "/*" in lj:
                            in_comment = True
                        if "*/" in lj:
                            in_comment = False
                    if in_comment:
                        continue

                    # Skip function declarations/definitions (the function itself)
                    if re.match(
                        r"^\s*(?:static\s+|extern\s+|inline\s+|__\w+\s+)*"
                        r"(?:(?:const|unsigned|signed|long|short|struct|enum|union)\s+)*"
                        r"\w[\w\s*]+\b" + re.escape(func_name) + r"\s*\(",
                        stripped,
                    ):
                        continue
                    # Skip #define lines (macro definitions)
                    if stripped.startswith("#"):
                        continue

                    snippet_lines, start_line = self._extract_snippet(lines, i)
                    if snippet_lines:
                        usages.append((rel, start_line + 1, snippet_lines))
                        if len(usages) >= max_results:
                            return usages
        return usages

    def _extract_snippet(self, lines, call_idx, context=12):
        """Extract a code snippet around a function call, bounded by the enclosing block."""
        total = len(lines)

        # Walk backwards to find enclosing function/block start
        start = call_idx
        brace_depth = 0
        for j in range(call_idx, max(-1, call_idx - 80), -1):
            s = lines[j]
            brace_depth += s.count("}") - s.count("{")
            if brace_depth < 0:
                # Found opening brace of enclosing block
                # Look one more line back for the function signature
                if (
                    j > 0
                    and lines[j - 1].strip()
                    and not lines[j - 1].strip().startswith(("/*", "*", "//", "#"))
                ):
                    start = j - 1
                else:
                    start = j
                break
        else:
            start = max(0, call_idx - context)

        # Walk forwards to find end of the statement/block
        end = call_idx
        brace_depth = 0
        for j in range(start, min(total, call_idx + 80)):
            s = lines[j]
            brace_depth += s.count("{") - s.count("}")
            if j > call_idx and brace_depth <= 0:
                end = j
                break
        else:
            end = min(total - 1, call_idx + context)

        # Clamp to reasonable size
        if end - start > 30:
            # Show call_idx in center with context
            start = max(start, call_idx - 15)
            end = min(end, call_idx + 15)

        snippet = [ln.rstrip("\n") for ln in lines[start : end + 1]]
        # Dedent
        if snippet:
            import textwrap

            snippet = textwrap.dedent("\n".join(snippet)).split("\n")
        # Strip leading/trailing blank lines
        while snippet and not snippet[0].strip():
            snippet.pop(0)
            start += 1
        while snippet and not snippet[-1].strip():
            snippet.pop()

        return snippet, start

    def _render_appendix(self, doc_name, group):
        """Build the 'Example usage in code' appendix for a function."""
        code_usages = self._extract_code_usages(doc_name, group) if group else []
        if not code_usages:
            return ""

        parts = ["", "#### Example usage in code", "", '<div class="hm-appendix">', ""]
        for rel, line_no, snippet in code_usages:
            code_text = "\n".join(snippet)
            code_text = code_text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            label_text = f"{rel}:{line_no}"
            card = (
                f'<div class="hm-example">'
                f'<span class="hm-example-label">{label_text}</span>'
                f'<pre><code class="language-c">{code_text}</code></pre>'
                f"</div>"
            )
            parts += [card, ""]
        parts += ["</div>", ""]
        return "\n".join(parts)

    # ── gtk-doc comment conversion ──

    def _convert_comments(self, docs):
        if not self.config["convert_gtkdoc"]:
            return
        for doc in docs:
            doc.comment = gtkdoc_to_rst(doc.comment)
            for member in doc.members:
                member.comment = gtkdoc_to_rst(member.comment)

    # ── Source group configuration ──

    def _build_groups(self, config_dir):
        raw = self.config.get("sources", [])
        if not raw:
            root = self.config.get("source_root", "") or "."
            if not os.path.isabs(root):
                root = os.path.normpath(os.path.join(config_dir, root))
            return [
                SourceGroup(
                    root=root,
                    nav_title=self.config["autodoc_nav_title"],
                    output_dir=self.config["autodoc_output_dir"],
                    extensions=self.config["autodoc_extensions"],
                    exclude=self.config["autodoc_exclude"],
                    clang_args=list(self.config["clang_args"]),
                    generate_index=self.config["autodoc_index"],
                    pages=list(self.config.get("autodoc_pages", [])),
                    test_mode=self.config.get("test_mode", ""),
                    test_group_by=list(self.config.get("test_group_by", [])),
                    test_fields=list(self.config.get("test_fields", [])),
                    extract_test_steps=self.config.get("extract_test_steps", False),
                )
            ]

        groups = []
        global_clang = self.config.get("clang_args", [])
        for i, entry in enumerate(raw):
            if isinstance(entry, str):
                entry = {"root": entry}
            if not isinstance(entry, dict) or "root" not in entry:
                log.error("cdoc: bad sources[%d], skipping", i)
                continue
            root = entry["root"]
            if not os.path.isabs(root):
                root = os.path.normpath(os.path.join(config_dir, root))
            extra = entry.get("clang_args")
            merged = list(global_clang) + (list(extra) if extra else [])
            basename = os.path.basename(root.rstrip("/").rstrip(os.sep)) or "src"

            # IGT config: support both nested "igt:" and flat "test_*" keys
            igt = entry.get("igt", {})
            if igt:
                test_mode = "igt"
            else:
                test_mode = entry.get("test_mode", "")

            igt_group_by = list(igt.get("group_by", entry.get("test_group_by", [])))
            igt_fields = list(igt.get("fields", entry.get("test_fields", [])))
            # Default fields to group_by if not specified
            if not igt_fields and igt_group_by:
                igt_fields = list(igt_group_by)

            groups.append(
                SourceGroup(
                    root=root,
                    nav_title=entry.get("nav_title", f"API ({basename})"),
                    output_dir=entry.get("output_dir", f"api_reference/{basename}"),
                    extensions=entry.get("extensions", self.config["autodoc_extensions"]),
                    exclude=entry.get("exclude", self.config["autodoc_exclude"]),
                    clang_args=merged,
                    generate_index=entry.get("index", self.config["autodoc_index"]),
                    pages=list(entry.get("pages", [])),
                    test_mode=test_mode,
                    test_group_by=igt_group_by,
                    test_fields=igt_fields,
                    extract_test_steps=igt.get(
                        "extract_steps",
                        entry.get(
                            "extract_test_steps", self.config.get("extract_test_steps", False)
                        ),
                    ),
                )
            )
        return groups

    def _discover_and_register(self, group):
        group.discovered = []
        group.generated_pages = {}
        if not os.path.isdir(group.root):
            log.error("cdoc: source root missing: %s", group.root)
            return
        group.discovered = _discover_sources(group.root, group.extensions, group.exclude)
        log.info("cdoc: [%s] %d files in %s", group.nav_title, len(group.discovered), group.root)

        for rel in group.discovered:
            uri = _source_rel_to_md_uri(rel, group.output_dir)
            abspath = os.path.normpath(os.path.join(group.root, rel))
            group.generated_pages[uri] = abspath
            self._pages[uri] = (abspath, group)

            docs = self._parse(abspath, group)
            self._register_symbols(docs, uri, group)
            self._register_file_symbol(rel, uri, group)

            if group.test_mode == "igt":
                tmeta = parse_igt_test_file(abspath, extract_steps=group.extract_test_steps)
                group.test_metas[rel] = tmeta
                self._register_test_symbols(tmeta, uri, group)

        if group.generate_index and group.discovered:
            idx = f"{group.output_dir}/index.md"
            group.generated_pages[idx] = "__INDEX__"
            self._pages[idx] = ("__INDEX__", group)

        if group.test_mode == "igt" and group.test_group_by:
            for field_name in group.test_group_by:
                slug = field_name.lower().replace(" ", "_").replace("-", "_")
                guri = f"{group.output_dir}/by-{slug}.md"
                group.generated_pages[guri] = f"__GROUP__{field_name}"
                self._pages[guri] = (f"__GROUP__{field_name}", group)

    def _register_test_symbols(self, tmeta, page_uri, group):
        gtitle = group.nav_title if group else ""
        tanchor = f"test-{tmeta.name}"
        tentry = SymbolEntry(
            name=tmeta.name,
            kind=SymbolKind.TEST,
            page_uri=page_uri,
            anchor=tanchor,
            group_title=gtitle,
        )
        if tmeta.name not in self._symbols:
            self._symbols[tmeta.name] = tentry
            self._symbol_names.add(tmeta.name)

        for sub in tmeta.subtests:
            sanchor = f"subtest-{sub.name}"
            qualified = f"{tmeta.name}@{sub.name}"
            sentry = SymbolEntry(
                name=sub.name,
                kind=SymbolKind.SUBTEST,
                page_uri=page_uri,
                anchor=sanchor,
                group_title=gtitle,
            )
            self._symbols[qualified] = sentry
            self._symbol_names.add(qualified)
            if sub.name not in self._symbols:
                self._symbols[sub.name] = sentry
                self._symbol_names.add(sub.name)

    def _register_file_symbol(self, rel, page_uri, group):
        gtitle = group.nav_title if group else ""
        basename = os.path.basename(rel)
        # Qualified form: group_output_dir_basename/filename e.g. "core/engine.h"
        # Use the last component of output_dir as the group qualifier
        group_slug = os.path.basename(group.output_dir.rstrip("/"))
        qualified = f"{group_slug}/{basename}"
        entry = SymbolEntry(
            name=basename, kind=SymbolKind.FILE, page_uri=page_uri, anchor="", group_title=gtitle
        )
        # Always register qualified form
        self._symbols[qualified] = entry
        self._symbol_names.add(qualified)
        # Register bare name only if unique and not already ambiguous
        if basename in self._ambiguous_files:
            pass
        elif basename not in self._symbols:
            self._symbols[basename] = entry
            self._symbol_names.add(basename)
        else:
            existing = self._symbols[basename]
            if existing.kind == SymbolKind.FILE and existing.page_uri != page_uri:
                # Ambiguous — remove bare name so only qualified works
                del self._symbols[basename]
                self._symbol_names.discard(basename)
                # Mark as ambiguous so we don't re-add later
                self._ambiguous_files.add(basename)

    def _build_nav_tree(self, group):
        nav = []
        if group.generate_index:
            nav.append({"Overview": f"{group.output_dir}/index.md"})
        if group.test_mode == "igt" and group.test_group_by:
            for field_name in group.test_group_by:
                slug = field_name.lower().replace(" ", "_").replace("-", "_")
                label = field_name.replace("_", " ").title()
                nav.append({f"By {label}": f"{group.output_dir}/by-{slug}.md"})
        for page_entry in group.pages:
            if isinstance(page_entry, dict):
                nav.append(page_entry)
            elif isinstance(page_entry, str):
                nav.append(page_entry)
        return nav

    def _inject_nav(self, config):
        top_title = self.config["autodoc_nav_title"]
        out_dir = self.config["autodoc_output_dir"]

        if len(self._groups) == 1:
            g = self._groups[0]
            if not g.discovered:
                return
            tree = self._build_nav_tree(g)
            if self._version or self.config.get("project_name"):
                tree.insert(0, {"Overview": f"{out_dir}/index.md"})
            section = {top_title: tree}
        else:
            children = [{"Overview": f"{out_dir}/index.md"}]
            for g in self._groups:
                if not g.discovered:
                    continue
                children.append({g.nav_title: self._build_nav_tree(g)})
            if len(children) <= 1:
                return
            section = {top_title: children}

        nav = config.get("nav")
        if nav is None:
            config["nav"] = [section]
            return
        for i, item in enumerate(nav):
            if isinstance(item, dict) and top_title in item:
                nav[i] = section
                return
        nav.append(section)

    # ── MkDocs lifecycle hooks ──

    def on_config(self, config, **kwargs):
        config_dir = os.path.dirname(config.get("config_file_path", "")) or os.getcwd()
        if not CLANG_AVAILABLE and self.config["fallback_parser"]:
            log.warning("cdoc: clang not found, falling back to regex parser")

        self._cache.clear()
        self._pages.clear()
        self._tmpfiles.clear()
        self._symbols.clear()
        self._symbol_names.clear()
        self._ambiguous_files.clear()
        self._groups = self._build_groups(config_dir)

        self._use_dir_urls = config.get("use_directory_urls", True)

        # Our cross-reference links use directory-style URLs that MkDocs
        # cannot validate against .md source files, so we silence those
        try:
            config["validation"]["links"]["unrecognized_links"] = 0
        except (KeyError, TypeError):
            pass

        self._version = None
        vf = self.config.get("version_file", "")
        if vf:
            if not os.path.isabs(vf):
                vf = os.path.normpath(os.path.join(config_dir, vf))
            self._version = _read_version(vf)
            if self._version:
                log.info("cdoc: project version %s (from %s)", self._version, vf)

        if not self.config["autodoc"]:
            return config

        for g in self._groups:
            self._discover_and_register(g)

        if len(self._groups) > 1:
            top_uri = f"{self.config['autodoc_output_dir']}/index.md"
            self._pages[top_uri] = ("__TOP_INDEX__", None)

        self._inject_nav(config)

        nsym = len(self._symbols)
        if nsym:
            log.info("cdoc: symbol registry built, %d symbols indexed", nsym)

        return config

    def on_files(self, files, *, config, **kwargs):
        for uri in sorted(self._pages):
            try:
                f = File.generated(config, uri, content="")
            except (AttributeError, TypeError):
                f = File(
                    uri,
                    config["docs_dir"],
                    config["site_dir"],
                    config.get("use_directory_urls", True),
                )
                dest = os.path.join(config["docs_dir"], uri)
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                open(dest, "w").close()
                self._tmpfiles.append(dest)
            f.edit_uri = None
            files.append(f)
        return files

    def on_page_markdown(self, markdown, *, page, config, files, **kwargs):
        src_uri = getattr(page.file, "src_uri", None) or page.file.src_path

        if src_uri in self._pages:
            target, group = self._pages[src_uri]
            if target == "__TOP_INDEX__":
                md = self._mk_top_index()
                return self._apply_xrefs(md, src_uri)
            if target == "__INDEX__":
                md = self._mk_index(group)
                return self._apply_xrefs(md, src_uri)
            if isinstance(target, str) and target.startswith("__GROUP__"):
                field_name = target[len("__GROUP__") :]
                md = self._mk_group_page(group, field_name, src_uri)
                return self._apply_xrefs(md, src_uri)
            if group.test_mode == "igt":
                rel = os.path.relpath(target, group.root)
                tmeta = group.test_metas.get(rel)
                md = self._mk_test_page(target, group, tmeta)
            else:
                md = self._mk_page(target, group)
            return self._apply_xrefs(md, src_uri)

        md = _DIRECTIVE_RE.sub(lambda m: self._handle_directive(m, page), markdown)
        return self._apply_xrefs(md, src_uri)

    def on_post_build(self, *, config, **kwargs):
        docs_dir = config["docs_dir"]
        for p in self._tmpfiles:
            try:
                os.remove(p)
            except OSError:
                pass
            d = os.path.dirname(p)
            while d != docs_dir:
                try:
                    os.rmdir(d)
                except OSError:
                    break
                d = os.path.dirname(d)

    # ── A–Z navigation bar ──

    _AZ_CSS = """<style>
.hm-idx{position:sticky;top:var(--md-header-height,0);z-index:2;
background:var(--md-default-bg-color,#fff);border-bottom:1px solid rgba(128,128,128,.2);
padding:8px .8rem;margin:0 -.8rem 16px;text-align:center;
font-family:ui-monospace,SFMono-Regular,monospace;font-size:13px;letter-spacing:1px}
.hm-idx a{display:inline-block;min-width:28px;height:28px;line-height:28px;
text-align:center;text-decoration:none;border-radius:4px;
color:var(--md-typeset-a-color,#1a73e8);transition:background .15s}
.hm-idx a:hover{background:rgba(128,128,128,.12)}
.hm-idx .x{display:inline-block;min-width:28px;height:28px;line-height:28px;
text-align:center;opacity:.2}
.hm-example{position:relative;
background:var(--md-code-bg-color,#f5f5f5);
border:1px solid rgba(128,128,128,.2);border-radius:6px;
margin:0 0 16px;overflow:hidden}
.hm-example-label{display:block;padding:6px 12px;
font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.5px;
color:var(--md-default-fg-color--light,#666);
border-bottom:1px solid rgba(128,128,128,.15);
background:rgba(128,128,128,.06)}
.hm-example pre{margin:0!important;border:0!important;border-radius:0!important;
background:transparent!important}
.hm-example code{font-size:12.5px!important;line-height:1.5!important}
.hm-appendix .hm-example{float:none;width:100%;margin:0 0 12px}
@media(min-width:960px){
.hm-example{float:right;clear:right;width:45%;margin:0 0 16px 24px}
}
@media(max-width:959px){
.hm-example{width:100%}
}
.hm-tc-table{width:100%;border-collapse:collapse;margin:16px 0}
.hm-tc-table th{background:var(--md-default-fg-color--lightest,#f0f0f0);
padding:10px 14px;text-align:left;font-size:13px;font-weight:600;
text-transform:uppercase;letter-spacing:.5px;
border-bottom:2px solid var(--md-typeset-a-color,#1a73e8)}
.hm-tc-table td{padding:10px 14px;border-bottom:1px solid rgba(128,128,128,.15);
vertical-align:top;font-size:13.5px;line-height:1.6}
.hm-tc-table tr:hover td{background:rgba(128,128,128,.04)}
.hm-tc-table td:first-child{width:30%;white-space:nowrap}
.hm-tc-table ol{margin:0;padding-left:1.4em}
.hm-tc-table ol li{margin:2px 0}
.hm-tc-table code{font-size:12px;padding:1px 4px;
background:var(--md-code-bg-color,#f5f5f5);border-radius:3px}
.hm-tc-table strong{color:var(--md-typeset-a-color,#1a73e8)}
</style>"""

    def _group_symbols(self, group):
        return {n: e for n, e in self._symbols.items() if e.group_title == group.nav_title}

    def _active_letters(self, group):
        syms = self._group_symbols(group)
        letters = set()
        for n, e in syms.items():
            if not n or "@" in n or "/" in n or e.kind == SymbolKind.FILE:
                continue
            sort_name = n.lstrip("_")
            if sort_name and sort_name[0].isalpha():
                letters.add(sort_name[0].upper())
        return letters

    def _az_bar(self, group, index_uri=None, current_uri=None, use_directory_urls=True):
        active = self._active_letters(group)
        parts = []
        for ch in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
            if ch in active:
                if index_uri and current_uri and current_uri != index_uri:
                    if use_directory_urls:
                        cur_html_dir = os.path.dirname(current_uri).replace(os.sep, "/")
                        cur_html_dir += "/" + os.path.splitext(os.path.basename(current_uri))[0]
                        idx_html_dir = os.path.dirname(index_uri).replace(os.sep, "/")
                        rel = os.path.relpath(idx_html_dir, cur_html_dir).replace(os.sep, "/")
                        if not rel.endswith("/"):
                            rel += "/"
                    else:
                        target_html = index_uri.replace(".md", ".html")
                        cur_dir = os.path.dirname(current_uri)
                        rel = os.path.relpath(target_html, cur_dir).replace(os.sep, "/")
                    parts.append(f'<a href="{rel}#{ch}">{ch}</a>')
                else:
                    parts.append(f'<a href="#{ch}">{ch}</a>')
            else:
                parts.append(f'<span class="x">{ch}</span>')
        return self._AZ_CSS + '\n<div class="hm-idx">\n' + "\n".join(parts) + "\n</div>\n\n"

    # ── Page rendering ──

    def _rcfg(self, domain="c"):
        return RenderConfig(
            heading_level=self.config["heading_level"],
            show_source_link=self.config["show_source_link"],
            source_uri=self.config["source_uri"],
            members=self.config["members"],
            signature_style=self.config["signature_style"],
            convert_rst=self.config["convert_rst"],
            language="cpp" if domain == "cpp" else "c",
        )

    def _mk_page(self, abspath, group):
        rel = os.path.relpath(abspath, group.root)
        docs = self._parse(abspath, group)
        ext = os.path.splitext(abspath)[1]
        cfg = self._rcfg("cpp" if ext.lower() in _CPP_EXTS else "c")
        cfg.heading_level = 2

        page_uri = None
        for uri, (path, _) in self._pages.items():
            if path == abspath:
                page_uri = uri
                break
        index_uri = f"{group.output_dir}/index.md"
        bar = self._az_bar(
            group, index_uri=index_uri, current_uri=page_uri, use_directory_urls=self._use_dir_urls
        )

        header = f"# {os.path.basename(rel)}\n\nSource file: `{rel.replace(os.sep, '/')}`\n\n"
        if not docs:
            return header + bar + "---\n\n_No documented symbols found in this file._"

        # Render each doc with optional appendix
        rendered_parts = []
        for doc in docs:
            rendered = render_doc(doc, cfg)
            if doc.kind in (SymbolKind.FUNCTION, SymbolKind.MACRO_FUNCTION):
                # Check if renderer already emitted HowTo/Notes from comment
                has_comment_appendix = "<!-- APPENDIX_RENDER_START -->" in rendered
                code_appendix = ""
                if self.config["appendix_code_usages"]:
                    code_appendix = self._render_appendix(doc.name, group)

                if has_comment_appendix or code_appendix:
                    # Build unified Appendix heading
                    appendix_parts = ["", "### Appendix", ""]

                    # Extract HowTo/Notes from rendered markdown
                    if has_comment_appendix:
                        _, _, rest = rendered.partition("<!-- APPENDIX_RENDER_START -->")
                        comment_appendix, _, after = rest.partition("<!-- APPENDIX_RENDER_END -->")
                        # Remove markers from rendered
                        rendered = (
                            rendered[: rendered.index("<!-- APPENDIX_RENDER_START -->")] + after
                        )
                        appendix_parts.append(comment_appendix.strip())
                        appendix_parts.append("")

                    # Add code usages between HowTo and Notes if both exist
                    if code_appendix:
                        appendix_parts.append(code_appendix)

                    rendered += "\n".join(appendix_parts)

            rendered_parts.append(rendered)

        return header + bar + "---\n\n" + "\n---\n\n".join(rendered_parts)

    def _mk_top_index(self):
        top_title = self.config["autodoc_nav_title"]
        proj = self.config.get("project_name", "") or top_title
        lines = [f"# API Reference for {proj}", ""]

        if self._version:
            lines += [
                '<div style="padding:12px 16px;border-left:4px solid var(--md-typeset-a-color,#1a73e8);'
                "background:var(--md-admonition-bg-color,rgba(68,138,255,.1));"
                'border-radius:4px;margin-bottom:16px">',
                f"<strong>Version {self._version}</strong>",
                "</div>",
                "",
            ]

        nsym = len(self._symbols)
        ngroups = sum(1 for g in self._groups if g.discovered)
        lines += [
            f"This reference covers {nsym} documented symbols "
            f"across {ngroups} source {'group' if ngroups == 1 else 'groups'}.",
            "",
        ]

        lines += ["## Sources", ""]
        for g in self._groups:
            if not g.discovered:
                continue
            nfiles = len(g.discovered)
            idx_uri = f"{g.output_dir}/index.md"
            top_uri = f"{self.config['autodoc_output_dir']}/index.md"
            link = os.path.relpath(idx_uri, os.path.dirname(top_uri)).replace(os.sep, "/")
            desc = ""
            if g.test_mode == "igt":
                ntests = len(g.test_metas)
                nsubs = sum(len(t.subtests) for t in g.test_metas.values())
                desc = f" — {ntests} tests, {nsubs} subtests"
            else:
                syms = {n: e for n, e in self._symbols.items() if e.group_title == g.nav_title}
                desc = f" — {len(syms)} symbols"
            lines.append(f"- **[{g.nav_title}]({link})** — {nfiles} files{desc}")
        lines.append("")

        return "\n".join(lines)

    def _mk_index(self, group):
        index_uri = f"{group.output_dir}/index.md"
        bar = self._az_bar(
            group, index_uri=index_uri, current_uri=index_uri, use_directory_urls=self._use_dir_urls
        )

        lines = [f"# {group.nav_title}", ""]

        if self._version:
            lines += [
                '<div style="padding:12px 16px;border-left:4px solid var(--md-typeset-a-color,#1a73e8);'
                "background:var(--md-admonition-bg-color,rgba(68,138,255,.1));"
                'border-radius:4px;margin-bottom:16px">',
                f"<strong>Version {self._version}</strong>",
                "</div>",
                "",
            ]

        if group.test_mode == "igt":
            total_tests = len(group.test_metas)
            total_subs = sum(len(t.subtests) for t in group.test_metas.values())
            lines += [
                f"Test documentation generated from C/C++ sources. "
                f"{total_tests} tests, {total_subs} subtests.",
                "",
            ]
        else:
            nfiles = len(group.discovered)
            syms = self._group_symbols(group)
            nsym = len({n for n in syms if "@" not in n})
            lines += [f"{nfiles} source files, {nsym} documented symbols.", ""]

        lines.append(bar)

        by_dir = {}
        for rel in sorted(group.discovered):
            d = os.path.dirname(rel).replace(os.sep, "/") or ""
            by_dir.setdefault(d, []).append(rel)
        lines += ["## Source Files", ""]
        for d in sorted(by_dir):
            if d:
                lines += [f"### {d}/", ""]
            if group.test_mode == "igt":
                lines.append("| File | Test | Subtests | Description |")
                lines.append("|------|------|----------|-------------|")
            else:
                lines.append("| File | Symbols |")
                lines.append("|------|---------|")
            for rel in by_dir[d]:
                uri = _source_rel_to_md_uri(rel, group.output_dir)
                link = uri[len(group.output_dir) + 1 :]
                fn = os.path.basename(rel)
                if group.test_mode == "igt":
                    tmeta = group.test_metas.get(rel)
                    tname = tmeta.name if tmeta else fn
                    nsubs = len(tmeta.subtests) if tmeta else 0
                    desc = tmeta.fields.get("description", "") if tmeta else ""
                    if len(desc) > 50:
                        desc = desc[:47] + "..."
                    lines.append(f"| [{fn}]({link}) | {tname} | {nsubs} | {desc} |")
                else:
                    abssrc = os.path.normpath(os.path.join(group.root, rel))
                    n = len(self._parse(abssrc, group))
                    lines.append(
                        f"| [{fn}]({link}) | {n} documented symbol{'s' if n != 1 else ''} |"
                    )
            lines.append("")

        lines += ["---", "", "## Symbol Index", ""]
        syms = self._group_symbols(group)
        by_letter = {}
        for name, entry in sorted(syms.items()):
            if not name:
                continue
            if "@" in name or "/" in name:
                continue
            if entry.kind == SymbolKind.FILE:
                continue
            # Sort key: strip leading underscores to determine letter
            sort_name = name.lstrip("_")
            if not sort_name or not sort_name[0].isalpha():
                continue
            letter = sort_name[0].upper()
            by_letter.setdefault(letter, []).append((name, entry))

        from .renderer import _KIND_LABELS

        for ch in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
            entries = by_letter.get(ch, [])
            lines.append(f'<a id="{ch}"></a>')
            lines.append("")
            lines.append(f"### {ch}")
            lines.append("")
            if not entries:
                lines += ["*No symbols.*", ""]
                continue
            for name, entry in sorted(entries, key=lambda x: x[0].lstrip("_").lower()):
                kind_label = _KIND_LABELS.get(entry.kind, "")
                page_link = entry.page_uri[len(group.output_dir) + 1 :]
                display = (
                    f"{name}()"
                    if entry.kind in (SymbolKind.FUNCTION, SymbolKind.MACRO_FUNCTION)
                    else name
                )
                lines.append(f"- [`{display}`]({page_link}#{entry.anchor}) — {kind_label}")
            lines.append("")

        return "\n".join(lines)

    def _mk_test_page(self, abspath, group, tmeta):
        rel = os.path.relpath(abspath, group.root)
        docs = self._parse(abspath, group)
        ext = os.path.splitext(abspath)[1]
        cfg = self._rcfg("cpp" if ext.lower() in _CPP_EXTS else "c")
        cfg.heading_level = 3

        page_uri = None
        for uri, (path, _) in self._pages.items():
            if path == abspath:
                page_uri = uri
                break
        index_uri = f"{group.output_dir}/index.md"
        bar = self._az_bar(
            group, index_uri=index_uri, current_uri=page_uri, use_directory_urls=self._use_dir_urls
        )

        lines = []

        if tmeta:
            lines.append(f'<a id="test-{tmeta.name}"></a>')
            lines.append("")
            lines.append(f"# {tmeta.name}")
            lines.append("")
            desc = tmeta.fields.get("description", "")
            if desc:
                lines += [desc, ""]

            show_fields = group.test_fields or [k for k in tmeta.fields if k != "description"]
            if show_fields:
                lines.append("| Field | Value |")
                lines.append("|-------|-------|")
                for fk in show_fields:
                    fv = self._get_field(tmeta.fields, fk, "")
                    if fv and fk != "description":
                        label = fk.replace("_", " ").title()
                        lines.append(f"| {label} | {fv} |")
                lines.append("")

            lines.append(f"Source file: `{rel.replace(os.sep, '/')}`")
            lines.append("")
            lines.append(bar)
            lines.append("---")
            lines.append("")

            if tmeta.subtests:
                lines.append(f"## Subtests ({len(tmeta.subtests)})")
                lines.append("")
                show_steps = group.extract_test_steps
                # Build HTML table
                lines.append('<table class="hm-tc-table">')
                col2_header = "Steps" if show_steps else "Description"
                lines.append(
                    "<thead><tr>" "<th>TC (Subtest)</th>" f"<th>{col2_header}</th>" "</tr></thead>"
                )
                lines.append("<tbody>")
                for sub in sorted(tmeta.subtests, key=lambda s: s.name.lower()):
                    sdesc = sub.fields.get("description", "")
                    is_dynamic = sub.fields.get("dynamic") == "true"
                    extra = {
                        k: v for k, v in sub.fields.items() if k not in ("description", "dynamic")
                    }

                    # TC cell: name + extra fields
                    tc_parts = [f'<a id="subtest-{sub.name}"></a>', f"<strong>{sub.name}</strong>"]
                    if not show_steps and sdesc:
                        # Description goes in col2, not in TC cell
                        pass
                    elif sdesc:
                        tc_parts.append(f"<br><em>{sdesc}</em>")
                    for k, v in extra.items():
                        label = k.replace("_", " ").title()
                        tc_parts.append(f"<br><small><strong>{label}:</strong> {v}</small>")
                    if is_dynamic:
                        tc_parts.append(
                            "<br><small><em>Dynamic subtest — names generated at runtime.</em></small>"
                        )
                    tc_html = "".join(tc_parts)

                    # Col2 cell: steps or description
                    if show_steps:
                        if sub.steps:
                            col2_html = _render_steps_html(sub.steps)
                        elif sdesc:
                            col2_html = f"<ol><li>{sdesc}</li></ol>"
                        else:
                            col2_html = "<em>No steps extracted.</em>"
                    else:
                        col2_html = sdesc if sdesc else "<em>No description.</em>"

                    lines.append(f"<tr><td>{tc_html}</td><td>{col2_html}</td></tr>")

                lines.append("</tbody></table>")
                lines.append("")
                lines.append("")
        else:
            lines.append(f"# {os.path.basename(rel)}")
            lines.append("")
            lines.append(f"Source file: `{rel.replace(os.sep, '/')}`")
            lines.append("")
            lines.append(bar)
            lines.append("---")
            lines.append("")

        if docs and not tmeta:
            lines.append("## Functions & Symbols")
            lines.append("")
            lines.append(render_docs(docs, cfg))

        return "\n".join(lines)

    def _mk_group_page(self, group, field_name, current_uri):
        index_uri = f"{group.output_dir}/index.md"
        bar = self._az_bar(
            group,
            index_uri=index_uri,
            current_uri=current_uri,
            use_directory_urls=self._use_dir_urls,
        )

        label = field_name.replace("_", " ").title()
        lines = [f"# {group.nav_title} — By {label}", ""]
        lines.append(bar)

        # Check if this field exists at test level or subtest level
        is_subtest_field = self._is_subtest_field(group, field_name)

        if is_subtest_field:
            lines += self._render_subtest_group_page(group, field_name)
        else:
            lines += self._render_test_group_page(group, field_name)

        return "\n".join(lines)

    @staticmethod
    def _get_field(fields, name, default=None):
        """Look up a field with flexible name matching (underscore/hyphen/space)."""
        if name in fields:
            return fields[name]
        # Try alternate forms: sub_category <-> sub-category <-> Sub category
        alt_hyphen = name.replace("_", "-")
        if alt_hyphen in fields:
            return fields[alt_hyphen]
        alt_under = name.replace("-", "_")
        if alt_under in fields:
            return fields[alt_under]
        alt_space = name.replace("_", " ")
        if alt_space in fields:
            return fields[alt_space]
        alt_space2 = name.replace("-", " ")
        if alt_space2 in fields:
            return fields[alt_space2]
        return default

    def _is_subtest_field(self, group, field_name):
        """Check if field_name is primarily a subtest-level field."""
        test_hits = 0
        sub_hits = 0
        for rel, tmeta in group.test_metas.items():
            if self._get_field(tmeta.fields, field_name) is not None:
                test_hits += 1
            for sub in tmeta.subtests:
                if self._get_field(sub.fields, field_name) is not None:
                    sub_hits += 1
        return sub_hits > test_hits

    def _render_test_group_page(self, group, field_name):
        """Group page where field is at the test level (category, mega_feature, etc.)."""
        lines = []
        grouped = {}
        total_tests = 0
        total_subs = 0
        for rel, tmeta in group.test_metas.items():
            value = self._get_field(tmeta.fields, field_name, "Uncategorized")
            grouped.setdefault(value, []).append((rel, tmeta))
            total_tests += 1
            total_subs += len(tmeta.subtests)

        lines += [f"{total_tests} tests, {total_subs} subtests.", "", "---", ""]

        for value in sorted(grouped.keys()):
            entries = grouped[value]
            sub_count = sum(len(t.subtests) for _, t in entries)
            lines.append(f"## {value}")
            lines.append("")
            lines.append(f"*{len(entries)} tests, {sub_count} subtests*")
            lines.append("")
            for rel, tmeta in sorted(entries, key=lambda x: x[1].name.lower()):
                uri = _source_rel_to_md_uri(rel, group.output_dir)
                link = uri[len(group.output_dir) + 1 :]
                test_desc = self._get_field(tmeta.fields, "description", "")
                lines.append(f"### [{tmeta.name}]({link}#test-{tmeta.name})")
                lines.append("")
                if test_desc:
                    lines.append(f"*{test_desc}*")
                    lines.append("")
                if tmeta.subtests:
                    lines.append("| Subtest | Description |")
                    lines.append("|---------|-------------|")
                    for sub in sorted(tmeta.subtests, key=lambda s: s.name.lower()):
                        sdesc = sub.fields.get("description", "")
                        if len(sdesc) > 80:
                            sdesc = sdesc[:77] + "..."
                        lines.append(f"| [{sub.name}]({link}#subtest-{sub.name})" f" | {sdesc} |")
                    lines.append("")
                else:
                    lines.append("*No subtests.*")
                    lines.append("")

        return lines

    def _render_subtest_group_page(self, group, field_name):
        """Group page where field is at the subtest level (functionality, etc.)."""
        lines = []
        grouped = {}
        total_subs = 0
        for rel, tmeta in group.test_metas.items():
            for sub in tmeta.subtests:
                value = self._get_field(sub.fields, field_name, "Uncategorized")
                grouped.setdefault(value, []).append((rel, tmeta, sub))
                total_subs += 1

        total_groups = len(grouped)
        lines += [f"{total_groups} groups, {total_subs} subtests.", "", "---", ""]

        for value in sorted(grouped.keys()):
            entries = grouped[value]
            lines.append(f"## {value}")
            lines.append("")
            lines.append(f"*{len(entries)} subtests*")
            lines.append("")
            # Group entries by test
            by_test = {}
            for rel, tmeta, sub in entries:
                by_test.setdefault((rel, tmeta.name), (tmeta, []))[1].append(sub)
            for (rel, tname), (tmeta, subs) in sorted(
                by_test.items(), key=lambda x: x[0][1].lower()
            ):
                uri = _source_rel_to_md_uri(rel, group.output_dir)
                link = uri[len(group.output_dir) + 1 :]
                lines.append(f"### [{tmeta.name}]({link}#test-{tmeta.name})")
                lines.append("")
                lines.append("| Subtest | Description |")
                lines.append("|---------|-------------|")
                for sub in sorted(subs, key=lambda s: s.name.lower()):
                    desc = sub.fields.get("description", "")
                    if len(desc) > 80:
                        desc = desc[:77] + "..."
                    lines.append(f"| [{sub.name}]({link}#subtest-{sub.name})" f" | {desc} |")
                lines.append("")

        return lines

    def _parse(self, filepath, group=None):
        abspath = os.path.normpath(filepath)
        if abspath in self._cache:
            return self._cache[abspath]
        if not os.path.isfile(abspath):
            log.error("cdoc: file not found: %s", abspath)
            return []

        clang_args = group.clang_args if group else self.config["clang_args"]
        docs = []
        need_fallback = not CLANG_AVAILABLE

        if CLANG_AVAILABLE:
            try:
                docs = parse_file(abspath, clang_args=clang_args)
            except Exception as exc:
                if self.config["fallback_parser"]:
                    log.debug("cdoc: clang failed on %s (%s), trying regex", abspath, exc)
                    need_fallback = True
                else:
                    log.error("cdoc: parse error %s: %s", abspath, exc)

        if need_fallback and self.config["fallback_parser"]:
            try:
                docs = parse_file_regex(abspath)
            except Exception as exc:
                log.error("cdoc: regex fallback failed for %s: %s", abspath, exc)
                docs = []

        self._convert_comments(docs)
        self._cache[abspath] = docs
        return docs

    def _resolve_file(self, path):
        if os.path.isabs(path):
            return path
        for g in self._groups:
            full = os.path.normpath(os.path.join(g.root, path))
            if os.path.isfile(full):
                return full
        if self._groups:
            return os.path.normpath(os.path.join(self._groups[0].root, path))
        return os.path.normpath(path)

    def _handle_directive(self, match, page):
        domain = match.group("domain")
        directive = match.group("directive")
        opts = {}
        for m in _OPTION_RE.finditer(match.group("body")):
            opts[m.group(1)] = m.group(2).strip()
        fpath = opts.get("file", "")
        if not fpath:
            return f"<!-- cdoc: missing :file: for {domain}:{directive} -->\n"
        docs = self._parse(self._resolve_file(fpath))
        cfg = self._rcfg(domain)
        if "heading_level" in opts:
            try:
                cfg.heading_level = int(opts["heading_level"])
            except ValueError:
                pass
        if "members" in opts:
            cfg.members = opts["members"].lower() in ("true", "yes", "1")
        if directive == "autodoc":
            return render_autodoc(docs, cfg, title=opts.get("title"))
        name = opts.get("name", "")
        if not name:
            return f"<!-- cdoc: missing :name: for {domain}:{directive} -->\n"
        return render_single(docs, name, kind=_DIRECTIVE_KIND_MAP.get(directive), cfg=cfg)
