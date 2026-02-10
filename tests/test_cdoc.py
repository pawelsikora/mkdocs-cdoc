import os
import textwrap
import pytest

from mkdocs_cdoc.parser import (
    DocComment,
    SymbolKind,
    clean_comment,
    parse_file_regex,
    rst_to_markdown,
    gtkdoc_to_rst,
)
from mkdocs_cdoc.renderer import RenderConfig, render_doc, render_single, render_docs, anchor_id
from mkdocs_cdoc.plugin import (
    SourceGroup,
    SymbolEntry,
    _discover_sources,
    _source_rel_to_md_uri,
    _DIRECTIVE_RE,
    CdocPlugin,
)

# -- comment cleaning --


class TestCleanComment:
    def test_block_simple(self):
        assert clean_comment("/** Brief. */") == "Brief."

    def test_block_multiline(self):
        raw = "/**\n * Line one.\n *\n * Line two.\n */"
        result = clean_comment(raw)
        assert "Line one." in result and "Line two." in result

    def test_line_comment(self):
        assert clean_comment("/// Brief.") == "Brief."

    def test_no_leading_asterisk(self):
        assert clean_comment("/** Just text */") == "Just text"


# -- gtk-doc to reST --


class TestGtkdocToRst:
    def test_function_ref(self):
        assert ":func:`foo`" in gtkdoc_to_rst("call foo() here")

    def test_function_ref_preserves_word_boundary(self):
        result = gtkdoc_to_rst("call foo() and bar()")
        assert ":func:`foo`" in result
        assert ":func:`bar`" in result

    def test_type_ref(self):
        assert ":type:`MyStruct`" in gtkdoc_to_rst("use #MyStruct")

    def test_member_ref(self):
        assert ":member:`Foo.bar`" in gtkdoc_to_rst("see #Foo.bar")

    def test_const_ref(self):
        assert ":const:`TRUE`" in gtkdoc_to_rst("returns %TRUE")

    def test_param_doc(self):
        result = gtkdoc_to_rst("@count: number of items")
        assert ":param count: number of items" in result

    def test_param_in_text(self):
        result = gtkdoc_to_rst("uses the @count value")
        assert "``count``" in result

    def test_returns(self):
        result = gtkdoc_to_rst("Returns: the value")
        assert ":returns: the value" in result

    def test_return_value(self):
        result = gtkdoc_to_rst("Return value: the value")
        assert ":returns: the value" in result

    def test_codeblock(self):
        result = gtkdoc_to_rst("|[\nint x = 0;\n]|")
        assert "```c" in result
        assert "int x = 0;" in result

    def test_codeblock_with_language(self):
        result = gtkdoc_to_rst('|[<!-- language="Python" -->\nprint("hi")\n]|')
        assert "```python" in result

    def test_literal(self):
        assert "``NULL``" in gtkdoc_to_rst("<literal>NULL</literal>")

    def test_emphasis(self):
        assert "*important*" in gtkdoc_to_rst("<emphasis>important</emphasis>")

    def test_since_passthrough(self):
        result = gtkdoc_to_rst("Since: 2.4")
        assert "Since: 2.4" in result

    def test_combined(self):
        text = "@buf: the #GBuffer\nReturns: %TRUE on success"
        result = gtkdoc_to_rst(text)
        assert ":param buf:" in result
        assert ":type:`GBuffer`" in result
        assert ":returns:" in result
        assert ":const:`TRUE`" in result

    def test_no_false_positive_in_backticks(self):
        result = gtkdoc_to_rst("`already_code()`")
        assert ":func:" not in result

    def test_no_false_positive_hash_in_comment(self):
        result = gtkdoc_to_rst("use \\#ifdef for conditional")
        assert ":type:" not in result


# -- reST to Markdown --


class TestRstToMarkdown:
    def test_param(self):
        assert "| `foo` | desc. |" in rst_to_markdown(":param foo: desc.")

    def test_returns(self):
        assert "**Returns:** val." in rst_to_markdown(":returns: val.")

    def test_cross_ref(self):
        result = rst_to_markdown("see :c:func:`other`")
        assert "`other`" in result and ":c:func:" not in result

    def test_double_backticks(self):
        result = rst_to_markdown("use ``NULL``")
        assert "`NULL`" in result and "``" not in result

    def test_multiple_params(self):
        result = rst_to_markdown(":param a: first.\n:param b: second.")
        assert "| `a` |" in result and "| `b` |" in result

    def test_plain_passthrough(self):
        assert rst_to_markdown("just text.") == "just text."

    def test_type_role(self):
        result = rst_to_markdown("the :type:`my_type` value")
        assert "`my_type`" in result and ":type:" not in result

    def test_const_role(self):
        result = rst_to_markdown("returns :const:`MAX_VAL`")
        assert "`MAX_VAL`" in result and ":const:" not in result

    def test_member_role(self):
        result = rst_to_markdown(":member:`Config.debug`")
        assert "`Config.debug`" in result


# -- regex parser --


class TestRegexParser:
    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        self.source = tmp_path / "test.c"
        self.source.write_text(textwrap.dedent("""\
            /**
             * Add two numbers.
             * :param a: First.
             * :param b: Second.
             * :returns: Sum.
             */
            int add(int a, int b);

            /** A struct. */
            struct foo {
                /** Value. */
                int val;
            };
        """))

    def test_finds_function(self):
        assert "add" in [d.name for d in parse_file_regex(str(self.source))]

    def test_finds_struct(self):
        structs = [d for d in parse_file_regex(str(self.source)) if d.kind == SymbolKind.STRUCT]
        assert any("foo" in s.name for s in structs)

    def test_comment_text(self):
        docs = [d for d in parse_file_regex(str(self.source)) if d.name == "add"]
        assert len(docs) == 1 and "Add two" in docs[0].comment


# -- renderer --


class TestRenderer:
    def test_function(self):
        doc = DocComment(
            name="foobar",
            kind=SymbolKind.FUNCTION,
            comment="Get foo.\n\n:param bar: Name.",
            signature="void foobar(const char *bar)",
        )
        result = render_doc(doc, RenderConfig(heading_level=3, convert_rst=True))
        assert "### Function: `foobar`" in result
        assert "```c" in result
        assert "| `bar` | Name. |" in result

    def test_struct_members(self):
        doc = DocComment(
            name="point",
            kind=SymbolKind.STRUCT,
            comment="2D.",
            signature="struct point",
            members=[
                DocComment(name="x", kind=SymbolKind.FIELD, comment="X.", signature="int x"),
                DocComment(name="y", kind=SymbolKind.FIELD, comment="Y.", signature="int y"),
            ],
        )
        result = render_doc(doc, RenderConfig(heading_level=3, members=True))
        assert "### Struct: `point`" in result
        assert "#### Field: `x`" in result

    def test_no_members(self):
        doc = DocComment(
            name="s",
            kind=SymbolKind.STRUCT,
            comment="S.",
            members=[DocComment(name="x", kind=SymbolKind.FIELD, comment="F.")],
        )
        assert "Field:" not in render_doc(doc, RenderConfig(members=False))

    def test_single_found(self):
        docs = [
            DocComment(name="a", kind=SymbolKind.FUNCTION, comment="A."),
            DocComment(name="b", kind=SymbolKind.FUNCTION, comment="B."),
        ]
        assert "`b`" in render_single(docs, "b")

    def test_single_not_found(self):
        assert "not found" in render_single(
            [DocComment(name="a", kind=SymbolKind.FUNCTION, comment=".")], "z"
        )

    def test_source_link(self):
        doc = DocComment(name="foo", kind=SymbolKind.FUNCTION, comment=".", filename="t.c", line=42)
        cfg = RenderConfig(show_source_link=True, source_uri="https://gh.com/{filename}#L{line}")
        assert "https://gh.com/t.c#L42" in render_doc(doc, cfg)

    def test_separator(self):
        docs = [
            DocComment(name="a", kind=SymbolKind.FUNCTION, comment="A."),
            DocComment(name="b", kind=SymbolKind.FUNCTION, comment="B."),
        ]
        assert "---" in render_docs(docs)

    def test_anchor_id(self):
        doc = DocComment(name="init", kind=SymbolKind.FUNCTION, comment=".")
        assert anchor_id(doc) == "func-init"

    def test_anchor_in_output(self):
        doc = DocComment(name="init", kind=SymbolKind.FUNCTION, comment=".")
        result = render_doc(doc)
        assert '<a id="func-init"></a>' in result


# -- directive regex --


class TestDirectiveRegex:
    def test_autodoc(self):
        m = _DIRECTIVE_RE.search("::: c:autodoc\n    :file: test.c\n")
        assert m and m.group("directive") == "autodoc"

    def test_cpp(self):
        m = _DIRECTIVE_RE.search("::: cpp:autofunction\n    :file: t.cpp\n    :name: f\n")
        assert m and m.group("domain") == "cpp"

    def test_no_match(self):
        assert _DIRECTIVE_RE.search("plain text\n") is None


# -- source discovery --


class TestDiscoverSources:
    def _tree(self, tmp_path):
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.c").write_text("")
        (tmp_path / "src" / "test_foo.c").write_text("")
        (tmp_path / "src" / "notes.txt").write_text("")
        (tmp_path / "src" / "lib").mkdir()
        (tmp_path / "src" / "lib" / "core.c").write_text("")
        (tmp_path / "src" / "lib" / "core.h").write_text("")
        return str(tmp_path / "src")

    def test_finds_c_h(self, tmp_path):
        found = _discover_sources(self._tree(tmp_path), [".c", ".h"], [])
        names = {os.path.basename(f) for f in found}
        assert "main.c" in names and "core.h" in names and "notes.txt" not in names

    def test_exclude(self, tmp_path):
        found = _discover_sources(self._tree(tmp_path), [".c", ".h"], ["test_*"])
        assert "test_foo.c" not in {os.path.basename(f) for f in found}

    def test_empty(self, tmp_path):
        (tmp_path / "empty").mkdir()
        assert _discover_sources(str(tmp_path / "empty"), [".c"], []) == []


# -- URI mapping --


class TestUriMapping:
    def test_simple(self):
        assert _source_rel_to_md_uri("main.c", "api") == "api/main.c.md"

    def test_nested(self):
        assert _source_rel_to_md_uri("lib/core.c", "api") == "api/lib/core.c.md"


# -- helpers --


def _rcfg():
    return {
        "clang_args": [],
        "heading_level": 2,
        "show_source_link": False,
        "source_uri": "",
        "members": True,
        "signature_style": "code",
        "convert_rst": True,
        "convert_gtkdoc": False,
        "auto_xref": True,
        "language": "c",
        "fallback_parser": True,
        "appendix_code_usages": False,
        "extract_test_steps": False,
    }


def _mk_single(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.c").write_text("/**\n * doc\n */\nvoid f();\n")
    (tmp_path / "src" / "lib").mkdir()
    (tmp_path / "src" / "lib" / "utils.c").write_text("/**\n * doc\n */\nint g();\n")
    (tmp_path / "src" / "lib" / "utils.h").write_text("/**\n * doc\n */\nint g();\n")
    plugin = CdocPlugin()
    plugin.config = {
        "source_root": str(tmp_path / "src"),
        "sources": [],
        "autodoc": True,
        "autodoc_output_dir": "api",
        "autodoc_nav_title": "API Reference",
        "autodoc_extensions": [".c", ".h"],
        "autodoc_exclude": [],
        "autodoc_index": True,
        "autodoc_pages": [],
        "autodoc_pages": [],
        **_rcfg(),
    }
    plugin._groups = plugin._build_groups(str(tmp_path))
    g = plugin._groups[0]
    g.discovered = _discover_sources(g.root, g.extensions, g.exclude)
    for rel in g.discovered:
        uri = _source_rel_to_md_uri(rel, g.output_dir)
        abspath = os.path.normpath(os.path.join(g.root, rel))
        g.generated_pages[uri] = abspath
        plugin._pages[uri] = (abspath, g)
        docs = plugin._parse(abspath, g)
        plugin._register_symbols(docs, uri, g)
    g.generated_pages["api/index.md"] = "__INDEX__"
    plugin._pages["api/index.md"] = ("__INDEX__", g)
    return plugin


def _mk_multi(tmp_path):
    (tmp_path / "core").mkdir()
    (tmp_path / "core" / "engine.c").write_text("/**\n * Core engine.\n */\nvoid engine_init();\n")
    (tmp_path / "core" / "engine.h").write_text("/**\n * Header.\n */\nvoid engine_init();\n")
    (tmp_path / "drivers").mkdir()
    (tmp_path / "drivers" / "uart.c").write_text("/**\n * UART.\n */\nvoid uart_send();\n")
    (tmp_path / "drivers" / "spi.c").write_text("/**\n * SPI.\n */\nvoid spi_transfer();\n")
    plugin = CdocPlugin()
    plugin.config = {
        "source_root": "",
        "sources": [
            {
                "root": str(tmp_path / "core"),
                "nav_title": "Core API",
                "output_dir": "api/core",
                "extensions": [".c", ".h"],
                "exclude": [],
                "clang_args": ["-DCORE"],
            },
            {
                "root": str(tmp_path / "drivers"),
                "nav_title": "Driver API",
                "output_dir": "api/drivers",
                "extensions": [".c"],
                "exclude": [],
                "clang_args": ["-DDRIVER"],
            },
        ],
        "autodoc": True,
        "autodoc_output_dir": "api",
        "autodoc_nav_title": "API Reference",
        "autodoc_extensions": [".c", ".h"],
        "autodoc_exclude": [],
        "autodoc_index": True,
        "autodoc_pages": [],
        "autodoc_pages": [],
        **_rcfg(),
    }
    plugin._groups = plugin._build_groups(str(tmp_path))
    for g in plugin._groups:
        g.discovered = _discover_sources(g.root, g.extensions, g.exclude)
        for rel in g.discovered:
            uri = _source_rel_to_md_uri(rel, g.output_dir)
            abspath = os.path.normpath(os.path.join(g.root, rel))
            g.generated_pages[uri] = abspath
            plugin._pages[uri] = (abspath, g)
            docs = plugin._parse(abspath, g)
            plugin._register_symbols(docs, uri, g)
        if g.generate_index and g.discovered:
            idx = f"{g.output_dir}/index.md"
            g.generated_pages[idx] = "__INDEX__"
            plugin._pages[idx] = ("__INDEX__", g)
    return plugin


def _uris(items):
    out = []
    for item in items:
        if isinstance(item, dict):
            for v in item.values():
                if isinstance(v, str):
                    out.append(v)
                elif isinstance(v, list):
                    out.extend(_uris(v))
    return out


def _nav_section(nav, title):
    for item in nav:
        if isinstance(item, dict) and title in item:
            return item[title]
    return None


# -- nav injection --


class TestNavSingle:
    def test_empty_nav(self, tmp_path):
        p = _mk_single(tmp_path)
        cfg = {"nav": None}
        p._inject_nav(cfg)
        assert cfg["nav"] and "API Reference" in cfg["nav"][0]

    def test_appends(self, tmp_path):
        p = _mk_single(tmp_path)
        cfg = {"nav": [{"Home": "index.md"}]}
        p._inject_nav(cfg)
        assert len(cfg["nav"]) == 2

    def test_replaces(self, tmp_path):
        p = _mk_single(tmp_path)
        cfg = {"nav": [{"Home": "index.md"}, {"API Reference": []}]}
        p._inject_nav(cfg)
        assert len(cfg["nav"]) == 2 and len(cfg["nav"][1]["API Reference"]) > 0

    def test_has_overview(self, tmp_path):
        p = _mk_single(tmp_path)
        cfg = {"nav": []}
        p._inject_nav(cfg)
        items = cfg["nav"][0]["API Reference"]
        assert items[0] == {"Overview": "api/index.md"}

    def test_no_source_files_in_nav(self, tmp_path):
        p = _mk_single(tmp_path)
        cfg = {"nav": []}
        p._inject_nav(cfg)
        uris = _uris(cfg["nav"][0]["API Reference"])
        assert not any("main.c.md" in u for u in uris)

    def test_nav_only_overview(self, tmp_path):
        p = _mk_single(tmp_path)
        cfg = {"nav": []}
        p._inject_nav(cfg)
        items = cfg["nav"][0]["API Reference"]
        assert len(items) == 1 and "Overview" in items[0]

    def test_nav_with_pages(self, tmp_path):
        p = _mk_single(tmp_path)
        p._groups[0].pages = [{"Getting Started": "docs/intro.md"}]
        cfg = {"nav": []}
        p._inject_nav(cfg)
        items = cfg["nav"][0]["API Reference"]
        assert len(items) == 2
        assert items[1] == {"Getting Started": "docs/intro.md"}


class TestNavMulti:
    def test_single_top_level(self, tmp_path):
        p = _mk_multi(tmp_path)
        cfg = {"nav": [{"Home": "index.md"}]}
        p._inject_nav(cfg)
        top_titles = [list(item.keys())[0] for item in cfg["nav"] if isinstance(item, dict)]
        assert "API Reference" in top_titles
        assert "Core API" not in top_titles
        assert "Driver API" not in top_titles

    def test_groups_nested(self, tmp_path):
        p = _mk_multi(tmp_path)
        cfg = {"nav": []}
        p._inject_nav(cfg)
        children = cfg["nav"][0]["API Reference"]
        child_titles = []
        for item in children:
            if isinstance(item, dict):
                child_titles.extend(item.keys())
        assert "Core API" in child_titles and "Driver API" in child_titles

    def test_each_group_has_overview(self, tmp_path):
        p = _mk_multi(tmp_path)
        cfg = {"nav": []}
        p._inject_nav(cfg)
        children = cfg["nav"][0]["API Reference"]
        for item in children:
            if isinstance(item, dict):
                for title, sub in item.items():
                    if isinstance(sub, list):
                        assert any("index.md" in str(e) for e in sub)

    def test_no_source_files_in_nav(self, tmp_path):
        p = _mk_multi(tmp_path)
        cfg = {"nav": []}
        p._inject_nav(cfg)
        all_uris = _uris(cfg["nav"])
        assert not any("engine.c.md" in u for u in all_uris)
        assert not any("uart.c.md" in u for u in all_uris)

    def test_separate_indexes(self, tmp_path):
        p = _mk_multi(tmp_path)
        cfg = {"nav": []}
        p._inject_nav(cfg)
        all_uris = _uris(cfg["nav"])
        assert "api/core/index.md" in all_uris
        assert "api/drivers/index.md" in all_uris

    def test_multi_with_pages(self, tmp_path):
        p = _mk_multi(tmp_path)
        p._groups[0].pages = [{"Intro": "docs/core-intro.md"}]
        cfg = {"nav": []}
        p._inject_nav(cfg)
        children = cfg["nav"][0]["API Reference"]
        core_section = None
        for item in children:
            if isinstance(item, dict) and "Core API" in item:
                core_section = item["Core API"]
        assert core_section is not None
        assert len(core_section) == 2
        assert core_section[1] == {"Intro": "docs/core-intro.md"}


# -- symbol registry --


class TestSymbolRegistry:
    def test_symbols_indexed(self, tmp_path):
        p = _mk_single(tmp_path)
        assert "f" in p._symbols or "g" in p._symbols

    def test_resolve_known(self, tmp_path):
        p = _mk_single(tmp_path)
        for name in p._symbols:
            url = p._resolve_xref(name)
            assert url is not None
            assert "#" in url
            break

    def test_resolve_unknown(self, tmp_path):
        p = _mk_single(tmp_path)
        assert p._resolve_xref("nonexistent_symbol_xyz") is None

    def test_resolve_with_parens(self, tmp_path):
        p = _mk_single(tmp_path)
        for name in p._symbols:
            url = p._resolve_xref(name + "()")
            assert url is not None
            break

    def test_multi_group_symbols(self, tmp_path):
        p = _mk_multi(tmp_path)
        has_core = any("engine" in n for n in p._symbols)
        has_driver = any("uart" in n or "spi" in n for n in p._symbols)
        assert has_core and has_driver

    def test_same_page_anchor(self, tmp_path):
        p = _mk_single(tmp_path)
        for name, entry in p._symbols.items():
            url = p._resolve_xref(name, entry.page_uri)
            assert url.startswith("#")
            break


# -- cross-reference resolution --


class TestXrefResolution:
    def test_rst_role_resolved(self, tmp_path):
        p = _mk_single(tmp_path)
        names = list(p._symbols.keys())
        if not names:
            pytest.skip("no symbols found")
        name = names[0]
        md = f"see :func:`{name}` for details"
        result = p._apply_xrefs(md)
        assert f"[`{name}`](" in result
        assert ":func:" not in result

    def test_rst_role_unresolved(self, tmp_path):
        p = _mk_single(tmp_path)
        md = "see :func:`totally_unknown_xyz`"
        result = p._apply_xrefs(md)
        assert "`totally_unknown_xyz`" in result
        assert "[" not in result or "totally_unknown_xyz" in result

    def test_auto_xref_backtick_func(self, tmp_path):
        p = _mk_single(tmp_path)
        names = list(p._symbols.keys())
        if not names:
            pytest.skip("no symbols")
        name = names[0]
        md = f"call `{name}()` to start"
        result = p._apply_xrefs(md)
        assert f"[`{name}()`](" in result

    def test_auto_xref_backtick_ident(self, tmp_path):
        p = _mk_single(tmp_path)
        names = list(p._symbols.keys())
        if not names:
            pytest.skip("no symbols")
        name = names[0]
        md = f"the `{name}` function"
        result = p._apply_xrefs(md)
        assert f"[`{name}`](" in result

    def test_auto_xref_unknown_not_linked(self, tmp_path):
        p = _mk_single(tmp_path)
        md = "use `some_random_thing` here"
        result = p._apply_xrefs(md)
        assert "`some_random_thing`" in result
        assert "[`some_random_thing`](" not in result

    def test_auto_xref_disabled(self, tmp_path):
        p = _mk_single(tmp_path)
        p.config["auto_xref"] = False
        names = list(p._symbols.keys())
        if not names:
            pytest.skip("no symbols")
        name = names[0]
        md = f"call `{name}()` here"
        result = p._apply_xrefs(md)
        assert f"[`{name}()`](" not in result


# -- gtk-doc runtime conversion --


class TestGtkdocRuntime:
    def test_converts_when_enabled(self, tmp_path):
        src = tmp_path / "test.c"
        src.write_text("/**\n * Call foo() on #MyStruct\n */\nvoid bar();\n")
        plugin = CdocPlugin()
        plugin.config = {
            "source_root": str(tmp_path),
            "sources": [],
            "autodoc": True,
            "autodoc_output_dir": "api",
            "autodoc_nav_title": "API",
            "autodoc_extensions": [".c", ".h"],
            "autodoc_exclude": [],
            "autodoc_index": True,
            "autodoc_pages": [],
            **_rcfg(),
        }
        plugin.config["convert_gtkdoc"] = True
        plugin._groups = plugin._build_groups(str(tmp_path))
        docs = plugin._parse(str(src))
        assert any(":func:`foo`" in d.comment for d in docs)
        assert any(":type:`MyStruct`" in d.comment for d in docs)

    def test_skips_when_disabled(self, tmp_path):
        src = tmp_path / "test.c"
        src.write_text("/**\n * Call foo() on #MyStruct\n */\nvoid bar();\n")
        plugin = CdocPlugin()
        plugin.config = {
            "source_root": str(tmp_path),
            "sources": [],
            "autodoc": True,
            "autodoc_output_dir": "api",
            "autodoc_nav_title": "API",
            "autodoc_extensions": [".c", ".h"],
            "autodoc_exclude": [],
            "autodoc_index": True,
            "autodoc_pages": [],
            **_rcfg(),
        }
        plugin.config["convert_gtkdoc"] = False
        plugin._groups = plugin._build_groups(str(tmp_path))
        docs = plugin._parse(str(src))
        assert not any(":func:`foo`" in d.comment for d in docs)


# -- build groups --


class TestBuildGroups:
    def test_single_root(self, tmp_path):
        plugin = CdocPlugin()
        plugin.config = {
            "source_root": "src",
            "sources": [],
            "clang_args": ["-DFOO"],
            "autodoc_nav_title": "My API",
            "autodoc_output_dir": "ref",
            "autodoc_extensions": [".c"],
            "autodoc_exclude": ["test_*"],
            "autodoc_index": True,
            "autodoc_pages": [],
        }
        groups = plugin._build_groups(str(tmp_path))
        assert len(groups) == 1
        assert groups[0].nav_title == "My API"

    def test_multi_sources(self, tmp_path):
        (tmp_path / "a").mkdir()
        (tmp_path / "b").mkdir()
        plugin = CdocPlugin()
        plugin.config = {
            "source_root": "",
            "sources": [
                {"root": "a", "nav_title": "A", "output_dir": "api/a"},
                {"root": "b", "nav_title": "B", "output_dir": "api/b"},
            ],
            "clang_args": [],
            "autodoc_extensions": [".c", ".h"],
            "autodoc_exclude": [],
            "autodoc_index": True,
            "autodoc_pages": [],
        }
        groups = plugin._build_groups(str(tmp_path))
        assert len(groups) == 2 and groups[0].nav_title == "A"

    def test_clang_args_merge(self, tmp_path):
        (tmp_path / "a").mkdir()
        plugin = CdocPlugin()
        plugin.config = {
            "source_root": "",
            "sources": [{"root": "a", "clang_args": ["-DLOCAL"]}],
            "clang_args": ["-DGLOBAL"],
            "autodoc_extensions": [".c"],
            "autodoc_exclude": [],
            "autodoc_index": True,
            "autodoc_pages": [],
            "autodoc_nav_title": "API",
        }
        groups = plugin._build_groups(str(tmp_path))
        assert "-DGLOBAL" in groups[0].clang_args and "-DLOCAL" in groups[0].clang_args

    def test_bare_string(self, tmp_path):
        (tmp_path / "mydir").mkdir()
        plugin = CdocPlugin()
        plugin.config = {
            "source_root": "",
            "sources": ["mydir"],
            "clang_args": [],
            "autodoc_extensions": [".c"],
            "autodoc_exclude": [],
            "autodoc_index": True,
            "autodoc_pages": [],
            "autodoc_nav_title": "API",
        }
        groups = plugin._build_groups(str(tmp_path))
        assert len(groups) == 1


# -- page rendering --


class TestRendering:
    def test_source_page(self, tmp_path):
        src = tmp_path / "test.c"
        src.write_text("/**\n * Do stuff.\n * :param x: Val.\n */\nint do_stuff(int x);\n")
        plugin = CdocPlugin()
        plugin.config = {"source_root": str(tmp_path), **_rcfg()}
        g = SourceGroup(root=str(tmp_path))
        result = plugin._mk_page(str(src), g)
        assert "# test.c" in result and "do_stuff" in result

    def test_empty_page(self, tmp_path):
        src = tmp_path / "empty.c"
        src.write_text("int x;\n")
        plugin = CdocPlugin()
        plugin.config = {"source_root": str(tmp_path), **_rcfg()}
        result = plugin._mk_page(str(src), SourceGroup(root=str(tmp_path)))
        assert "No documented symbols" in result

    def test_index_page(self, tmp_path):
        src = tmp_path / "test.c"
        src.write_text("/**\n * Func.\n */\nvoid f();\n")
        plugin = CdocPlugin()
        plugin.config = {
            "source_root": str(tmp_path),
            "autodoc_output_dir": "api",
            "autodoc_nav_title": "API Reference",
            **_rcfg(),
        }
        g = SourceGroup(root=str(tmp_path), nav_title="My API", output_dir="api")
        g.discovered = ["test.c"]
        g.generated_pages = {"api/test.c.md": str(src), "api/index.md": "__INDEX__"}
        result = plugin._mk_index(g)
        assert "# My API" in result and "test.c" in result


# -- alphabet bar --


class TestAlphabetBar:
    def test_index_has_bar(self, tmp_path):
        p = _mk_single(tmp_path)
        g = p._groups[0]
        result = p._mk_index(g)
        assert 'class="hm-idx"' in result

    def test_index_has_symbol_index(self, tmp_path):
        p = _mk_single(tmp_path)
        result = p._mk_index(p._groups[0])
        assert "## Symbol Index" in result

    def test_index_has_letter_anchors(self, tmp_path):
        p = _mk_single(tmp_path)
        result = p._mk_index(p._groups[0])
        assert '<a id="F"></a>' in result or '<a id="G"></a>' in result

    def test_source_page_has_bar(self, tmp_path):
        p = _mk_single(tmp_path)
        g = p._groups[0]
        abspath = list(g.generated_pages.values())[0]
        if abspath == "__INDEX__":
            abspath = list(g.generated_pages.values())[1]
        result = p._mk_page(abspath, g)
        assert 'class="hm-idx"' in result

    def test_active_letters(self, tmp_path):
        p = _mk_single(tmp_path)
        g = p._groups[0]
        active = p._active_letters(g)
        assert len(active) > 0
        assert all(c.isupper() and len(c) == 1 for c in active)

    def test_inactive_letters_dimmed(self, tmp_path):
        p = _mk_single(tmp_path)
        g = p._groups[0]
        bar = p._az_bar(g, index_uri="api/index.md", current_uri="api/index.md")
        assert 'class="x"' in bar

    def test_source_page_bar_links_to_index(self, tmp_path):
        p = _mk_multi(tmp_path)
        g = p._groups[0]
        src_uri = None
        for uri, (path, grp) in p._pages.items():
            if path != "__INDEX__" and grp == g:
                src_uri = uri
                break
        if not src_uri:
            pytest.skip("no source pages")
        idx_uri = f"{g.output_dir}/index.md"
        bar = p._az_bar(g, index_uri=idx_uri, current_uri=src_uri, use_directory_urls=True)
        assert "../#" in bar or 'href="#' in bar

    def test_index_bar_uses_inpage_anchors(self, tmp_path):
        p = _mk_single(tmp_path)
        g = p._groups[0]
        idx = f"{g.output_dir}/index.md"
        bar = p._az_bar(g, index_uri=idx, current_uri=idx)
        import re

        links = re.findall(r'href="([^"]+)"', bar)
        for link in links:
            assert link.startswith("#")

    def test_multi_groups_separate_bars(self, tmp_path):
        p = _mk_multi(tmp_path)
        core_active = p._active_letters(p._groups[0])
        driver_active = p._active_letters(p._groups[1])
        assert core_active != driver_active


# -- IGT test mode --

from mkdocs_cdoc.parser import (
    parse_igt_test_file,
    IGTTestMeta,
    SubtestMeta,
    SymbolKind as SK,
)


class TestIGTParser:
    def test_parse_test_comment(self, tmp_path):
        src = tmp_path / "kms_foo.c"
        src.write_text(
            "/**\n * TEST: kms_foo\n * Category: Display\n * Description: Foo tests\n *\n * SUBTEST: basic\n * Description: Basic test\n */\n"
        )
        tm = parse_igt_test_file(str(src))
        assert tm.name == "kms_foo"
        assert tm.fields["category"] == "Display"
        assert len(tm.subtests) == 1
        assert tm.subtests[0].name == "basic"

    def test_parse_igt_subtest_calls(self, tmp_path):
        src = tmp_path / "test_bar.c"
        src.write_text(
            '/**\n * TEST: test_bar\n * Category: Core\n */\n\nigt_describe("Does something.");\nigt_subtest("do-thing") {\n}\n'
        )
        tm = parse_igt_test_file(str(src))
        assert tm.name == "test_bar"
        assert any(s.name == "do-thing" for s in tm.subtests)
        sub = [s for s in tm.subtests if s.name == "do-thing"][0]
        assert sub.fields.get("description") == "Does something."

    def test_parse_dynamic_subtest(self, tmp_path):
        src = tmp_path / "dyn.c"
        src.write_text(
            '/**\n * TEST: dyn\n * Category: Core\n */\n\nigt_subtest_with_dynamic("pipe-tests") {\n}\n'
        )
        tm = parse_igt_test_file(str(src))
        sub = [s for s in tm.subtests if s.name == "pipe-tests"][0]
        assert sub.fields.get("dynamic") == "true"

    def test_no_test_comment_uses_filename(self, tmp_path):
        src = tmp_path / "plain.c"
        src.write_text('igt_subtest("alpha") {}\n')
        tm = parse_igt_test_file(str(src))
        assert tm.name == "plain"
        assert any(s.name == "alpha" for s in tm.subtests)

    def test_subtest_fields(self, tmp_path):
        src = tmp_path / "fields.c"
        src.write_text(
            "/**\n * TEST: fields\n * Category: Core\n *\n * SUBTEST: sub1\n * Description: Sub one\n * Functionality: gem\n */\n"
        )
        tm = parse_igt_test_file(str(src))
        sub = tm.subtests[0]
        assert sub.fields["functionality"] == "gem"

    def test_comment_subtests_merged_with_code(self, tmp_path):
        src = tmp_path / "merge.c"
        src.write_text(
            '/**\n * TEST: merge\n * Category: Core\n *\n * SUBTEST: from-comment\n * Description: Declared in comment\n */\n\nigt_describe("From code");\nigt_subtest("from-code") {}\n'
        )
        tm = parse_igt_test_file(str(src))
        names = {s.name for s in tm.subtests}
        assert "from-comment" in names
        assert "from-code" in names


class TestIGTPlugin:
    def _mk_igt(self, tmp_path):
        tdir = tmp_path / "tests"
        tdir.mkdir()
        (tdir / "kms_test.c").write_text(
            "/**\n * TEST: kms_test\n * Category: Display\n * Mega feature: KMS\n * Description: Test KMS.\n *\n"
            " * SUBTEST: basic\n * Description: Basic check.\n */\n\n"
            'igt_describe("Basic check.");\nigt_subtest("basic") {}\n'
        )
        (tdir / "gem_test.c").write_text(
            "/**\n * TEST: gem_test\n * Category: Core\n * Mega feature: GEM\n * Description: Test GEM.\n *\n"
            " * SUBTEST: alloc\n * Description: Allocate buffer.\n */\n"
        )
        plugin = CdocPlugin()
        plugin.config = {
            "source_root": "",
            "sources": [
                {
                    "root": str(tdir),
                    "nav_title": "Test API",
                    "output_dir": "api/tests",
                    "extensions": [".c"],
                    "exclude": [],
                    "test_mode": "igt",
                    "test_group_by": ["category", "mega_feature"],
                    "test_fields": ["category", "mega_feature"],
                },
            ],
            "autodoc": True,
            "autodoc_output_dir": "api",
            "autodoc_nav_title": "API Reference",
            "autodoc_extensions": [".c", ".h"],
            "autodoc_exclude": [],
            "autodoc_index": True,
            "autodoc_pages": [],
            "test_mode": "",
            "test_group_by": [],
            "test_fields": [],
            **_rcfg(),
        }
        plugin._groups = plugin._build_groups(str(tmp_path))
        g = plugin._groups[0]
        g.discovered = _discover_sources(g.root, g.extensions, g.exclude)
        for rel in g.discovered:
            uri = _source_rel_to_md_uri(rel, g.output_dir)
            abspath = os.path.normpath(os.path.join(g.root, rel))
            g.generated_pages[uri] = abspath
            plugin._pages[uri] = (abspath, g)
            docs = plugin._parse(abspath, g)
            plugin._register_symbols(docs, uri, g)
            tmeta = parse_igt_test_file(abspath)
            g.test_metas[rel] = tmeta
            plugin._register_test_symbols(tmeta, uri, g)
        idx = f"{g.output_dir}/index.md"
        g.generated_pages[idx] = "__INDEX__"
        plugin._pages[idx] = ("__INDEX__", g)
        for field_name in g.test_group_by:
            slug = field_name.lower().replace(" ", "_")
            guri = f"{g.output_dir}/by-{slug}.md"
            g.generated_pages[guri] = f"__GROUP__{field_name}"
            plugin._pages[guri] = (f"__GROUP__{field_name}", g)
        return plugin

    def test_test_symbols_registered(self, tmp_path):
        p = self._mk_igt(tmp_path)
        assert "kms_test" in p._symbols
        assert p._symbols["kms_test"].kind == SK.TEST

    def test_subtest_symbols_registered(self, tmp_path):
        p = self._mk_igt(tmp_path)
        assert "kms_test@basic" in p._symbols
        assert p._symbols["kms_test@basic"].kind == SK.SUBTEST

    def test_index_has_test_stats(self, tmp_path):
        p = self._mk_igt(tmp_path)
        idx = p._mk_index(p._groups[0])
        assert "2 tests" in idx
        assert "subtests" in idx

    def test_index_has_test_table(self, tmp_path):
        p = self._mk_igt(tmp_path)
        idx = p._mk_index(p._groups[0])
        assert "kms_test" in idx
        assert "gem_test" in idx

    def test_test_page_has_metadata(self, tmp_path):
        p = self._mk_igt(tmp_path)
        g = p._groups[0]
        abspath = os.path.normpath(os.path.join(g.root, "kms_test.c"))
        tmeta = g.test_metas.get("kms_test.c")
        page = p._mk_test_page(abspath, g, tmeta)
        assert "test-kms_test" in page
        assert "Category" in page
        assert "Display" in page

    def test_test_page_has_subtests(self, tmp_path):
        p = self._mk_igt(tmp_path)
        g = p._groups[0]
        abspath = os.path.normpath(os.path.join(g.root, "kms_test.c"))
        tmeta = g.test_metas.get("kms_test.c")
        page = p._mk_test_page(abspath, g, tmeta)
        assert "subtest-basic" in page
        assert "Subtests" in page

    def test_group_page_by_category(self, tmp_path):
        p = self._mk_igt(tmp_path)
        g = p._groups[0]
        page = p._mk_group_page(g, "category", "api/tests/by-category.md")
        assert "Display" in page
        assert "Core" in page
        assert "kms_test" in page
        assert "gem_test" in page

    def test_group_page_by_feature(self, tmp_path):
        p = self._mk_igt(tmp_path)
        g = p._groups[0]
        page = p._mk_group_page(g, "mega_feature", "api/tests/by-mega_feature.md")
        assert "KMS" in page
        assert "GEM" in page

    def test_nav_includes_group_pages(self, tmp_path):
        p = self._mk_igt(tmp_path)
        g = p._groups[0]
        nav = p._build_nav_tree(g)
        labels = []
        for item in nav:
            if isinstance(item, dict):
                labels.extend(item.keys())
        assert "By Category" in labels
        assert "By Mega Feature" in labels

    def test_xref_test(self, tmp_path):
        p = self._mk_igt(tmp_path)
        md = ":test:`kms_test`"
        result = p._apply_xrefs(md, "api/tests/index.md")
        assert "kms_test" in result
        assert "#test-kms_test" in result

    def test_xref_subtest(self, tmp_path):
        p = self._mk_igt(tmp_path)
        md = ":subtest:`kms_test@basic`"
        result = p._apply_xrefs(md, "api/tests/index.md")
        assert "basic" in result
        assert "#subtest-basic" in result


class TestFileXref:
    def _mk(self, tmp_path):
        core = tmp_path / "core"
        core.mkdir()
        (core / "engine.h").write_text("/** Init. */\nvoid engine_init(void);\n")
        drv = tmp_path / "drivers"
        drv.mkdir()
        (drv / "uart.c").write_text("/** Send. */\nvoid uart_send(void);\n")
        plugin = CdocPlugin()
        plugin.config = {
            "source_root": "",
            "sources": [
                {
                    "root": str(core),
                    "nav_title": "Core API",
                    "output_dir": "api/core",
                    "extensions": [".c", ".h"],
                    "exclude": [],
                    "test_mode": "",
                    "test_group_by": [],
                    "test_fields": [],
                },
                {
                    "root": str(drv),
                    "nav_title": "Driver API",
                    "output_dir": "api/drivers",
                    "extensions": [".c"],
                    "exclude": [],
                    "test_mode": "",
                    "test_group_by": [],
                    "test_fields": [],
                },
            ],
            "autodoc": True,
            "autodoc_output_dir": "api",
            "autodoc_nav_title": "API Reference",
            "autodoc_extensions": [".c", ".h"],
            "autodoc_exclude": [],
            "autodoc_index": True,
            "autodoc_pages": [],
            "test_mode": "",
            "test_group_by": [],
            "test_fields": [],
            "project_name": "",
            "version_file": "",
            **_rcfg(),
        }
        plugin._groups = plugin._build_groups(str(tmp_path))
        for g in plugin._groups:
            plugin._discover_and_register(g)
        return plugin

    def test_bare_file_registered(self, tmp_path):
        p = self._mk(tmp_path)
        assert "engine.h" in p._symbols
        assert p._symbols["engine.h"].kind == SymbolKind.FILE

    def test_qualified_file_registered(self, tmp_path):
        p = self._mk(tmp_path)
        assert "core/engine.h" in p._symbols
        assert "drivers/uart.c" in p._symbols

    def test_file_role_resolves(self, tmp_path):
        p = self._mk(tmp_path)
        md = ":file:`engine.h`"
        result = p._apply_xrefs(md, "docs/index.md")
        assert "engine.h" in result
        assert "api/core/engine.h/" in result

    def test_qualified_file_role(self, tmp_path):
        p = self._mk(tmp_path)
        md = ":file:`drivers/uart.c`"
        result = p._apply_xrefs(md, "docs/index.md")
        assert "uart.c" in result
        assert "api/drivers/uart.c/" in result

    def test_auto_xref_file(self, tmp_path):
        p = self._mk(tmp_path)
        md = "see `engine.h` for details"
        result = p._apply_xrefs(md, "docs/index.md")
        assert "[`engine.h`]" in result

    def test_auto_xref_qualified_file(self, tmp_path):
        p = self._mk(tmp_path)
        md = "see `core/engine.h` for details"
        result = p._apply_xrefs(md, "docs/index.md")
        assert "[`core/engine.h`]" in result

    def test_ambiguous_file_needs_qualification(self, tmp_path):
        core = tmp_path / "core"
        core.mkdir()
        (core / "utils.h").write_text("/** A. */\nvoid a(void);\n")
        drv = tmp_path / "drivers"
        drv.mkdir()
        (drv / "utils.h").write_text("/** B. */\nvoid b(void);\n")
        plugin = CdocPlugin()
        plugin.config = {
            "source_root": "",
            "sources": [
                {
                    "root": str(core),
                    "nav_title": "Core",
                    "output_dir": "api/core",
                    "extensions": [".h"],
                    "exclude": [],
                    "test_mode": "",
                    "test_group_by": [],
                    "test_fields": [],
                },
                {
                    "root": str(drv),
                    "nav_title": "Drivers",
                    "output_dir": "api/drivers",
                    "extensions": [".h"],
                    "exclude": [],
                    "test_mode": "",
                    "test_group_by": [],
                    "test_fields": [],
                },
            ],
            "autodoc": True,
            "autodoc_output_dir": "api",
            "autodoc_nav_title": "API",
            "autodoc_extensions": [".h"],
            "autodoc_exclude": [],
            "autodoc_index": True,
            "autodoc_pages": [],
            "test_mode": "",
            "test_group_by": [],
            "test_fields": [],
            "project_name": "",
            "version_file": "",
            **_rcfg(),
        }
        plugin._groups = plugin._build_groups(str(tmp_path))
        for g in plugin._groups:
            plugin._discover_and_register(g)
        # Bare name should be ambiguous / removed
        assert "utils.h" not in plugin._symbols
        # Qualified names should work
        assert "core/utils.h" in plugin._symbols
        assert "drivers/utils.h" in plugin._symbols

    def test_file_no_anchor_fragment(self, tmp_path):
        p = self._mk(tmp_path)
        url = p._resolve_xref("engine.h", "docs/index.md")
        assert url and "#" not in url

    def test_file_not_in_symbol_index(self, tmp_path):
        p = self._mk(tmp_path)
        for g in p._groups:
            idx = p._mk_index(g)
            assert "— File" not in idx


class TestRenderingFixes:
    """Tests for rendering improvements: underscore sort, pointer returns,
    name: stripping, Example layout, Type column, comment cleanup."""

    def test_underscore_sort_in_index(self, tmp_path):
        """_foo and __foo should be sorted by foo, appearing under F."""
        src = tmp_path / "src"
        src.mkdir()
        (src / "api.h").write_text(
            "/** Alpha. */\nvoid alpha(void);\n"
            "/** Internal. */\nvoid __beta_internal(void);\n"
            "/** Gamma. */\nvoid gamma(void);\n"
        )
        plugin = CdocPlugin()
        plugin.config = {
            "source_root": str(src),
            "sources": [],
            "autodoc": True,
            "autodoc_output_dir": "api",
            "autodoc_nav_title": "API",
            "autodoc_extensions": [".h"],
            "autodoc_exclude": [],
            "autodoc_index": True,
            "autodoc_pages": [],
            "test_mode": "",
            "test_group_by": [],
            "test_fields": [],
            "project_name": "",
            "version_file": "",
            **_rcfg(),
        }
        plugin._groups = plugin._build_groups(str(tmp_path))
        for g in plugin._groups:
            plugin._discover_and_register(g)
        g = plugin._groups[0]
        idx = plugin._mk_index(g)
        # __beta_internal should appear under B, not be skipped
        assert "__beta_internal" in idx
        # Should be in the B section
        b_section = idx.split("### B")[1].split("### C")[0] if "### B" in idx else ""
        assert "__beta_internal" in b_section

    def test_pointer_return_from_signature(self):
        from mkdocs_cdoc.parser import rst_to_markdown, DocComment, SymbolKind

        doc = DocComment(
            name="get_name",
            kind=SymbolKind.FUNCTION,
            comment="Get name.",
            return_type="char *",
            params=[],
        )
        result = rst_to_markdown("Get name.", doc=doc)
        assert "Pointer to" in result
        assert "`char`" in result

    def test_name_colon_stripped(self):
        from mkdocs_cdoc.parser import rst_to_markdown, DocComment, SymbolKind

        doc = DocComment(name="my_func", kind=SymbolKind.FUNCTION, comment="")
        result = rst_to_markdown("my_func:\nActual description.", doc=doc)
        assert "my_func:" not in result
        assert "Actual description." in result

    def test_example_section_extracted(self):
        from mkdocs_cdoc.parser import rst_to_markdown, DocComment, SymbolKind

        doc = DocComment(name="foo", kind=SymbolKind.FUNCTION, comment="")
        text = "Does a thing.\n\nExample:\n    foo();\n    bar();\n\n:param x: The x."
        result = rst_to_markdown(text, doc=doc)
        assert "EXAMPLE_START" in result
        assert "foo();" in result
        assert "bar();" in result
        # param should NOT be inside the example
        assert "| `x` |" in result

    def test_param_type_column(self):
        from mkdocs_cdoc.parser import rst_to_markdown, DocComment, SymbolKind

        doc = DocComment(
            name="init",
            kind=SymbolKind.FUNCTION,
            comment="",
            params=[("struct my_config *", "cfg"), ("int", "flags")],
        )
        text = ":param cfg: Configuration.\n:param flags: Flags."
        result = rst_to_markdown(text, doc=doc)
        assert "| Type |" in result  # Type column header
        assert "`struct my_config *`" in result
        assert "`int`" in result

    def test_comment_no_trailing_artifacts(self):
        from mkdocs_cdoc.parser import clean_comment

        raw = "/**\n * Hello world.\n * \n */"
        result = clean_comment(raw)
        assert result == "Hello world."
        assert "*/" not in result

    def test_comment_no_lone_star(self):
        from mkdocs_cdoc.parser import clean_comment

        raw = "/**\n * Description.\n *\n * More text.\n *\n */"
        result = clean_comment(raw)
        assert not result.endswith("*")
        assert "*/" not in result

    def test_void_return_not_shown(self):
        from mkdocs_cdoc.parser import rst_to_markdown, DocComment, SymbolKind

        doc = DocComment(
            name="reset",
            kind=SymbolKind.FUNCTION,
            comment="",
            return_type="void",
            params=[],
        )
        result = rst_to_markdown("Resets.", doc=doc)
        assert "Returns" not in result


class TestMultipleExamples:
    def test_two_examples_extracted(self):
        from mkdocs_cdoc.parser import rst_to_markdown, DocComment, SymbolKind

        doc = DocComment(name="foo", kind=SymbolKind.FUNCTION, comment="")
        text = "Desc.\n\nExample:\n    foo(1);\n\nMiddle text.\n\nExample:\n    foo(2);\n\n:param x: X."
        result = rst_to_markdown(text, doc=doc)
        import re

        n = len(re.findall("EXAMPLE_START", result))
        assert n == 2

    def test_example_labels_numbered(self):
        from mkdocs_cdoc.parser import rst_to_markdown, DocComment, SymbolKind

        doc = DocComment(name="foo", kind=SymbolKind.FUNCTION, comment="")
        text = "Desc.\n\nExample:\n    a();\n\nExample:\n    b();\n"
        result = rst_to_markdown(text, doc=doc)
        assert "EXAMPLE_START:Example -->" in result
        assert "EXAMPLE_START:Example 2 -->" in result

    def test_prose_between_examples_preserved(self):
        from mkdocs_cdoc.parser import rst_to_markdown, DocComment, SymbolKind

        doc = DocComment(name="foo", kind=SymbolKind.FUNCTION, comment="")
        text = "Desc.\n\nExample:\n    a();\n\nMiddle text.\n\nExample:\n    b();\n"
        result = rst_to_markdown(text, doc=doc)
        assert "Middle text." in result
        # Middle text should NOT be inside an example block
        import re

        blocks = re.findall(r"<!-- EXAMPLE_START.*?-->(.*?)<!-- EXAMPLE_END -->", result, re.DOTALL)
        for block in blocks:
            assert "Middle text" not in block

    def test_gtkdoc_multiple_examples(self):
        from mkdocs_cdoc.parser import gtkdoc_to_rst, rst_to_markdown, DocComment, SymbolKind

        raw = (
            'desc.\n\nExample:\n\n|[<!-- language="c" -->\nfoo();\n]|\n\n'
            'More text.\n\nExample:\n\n|[<!-- language="c" -->\nbar();\n]|\n'
        )
        gtkdoc = gtkdoc_to_rst(raw)
        doc = DocComment(name="x", kind=SymbolKind.FUNCTION, comment="")
        result = rst_to_markdown(gtkdoc, doc=doc)
        import re

        assert len(re.findall("EXAMPLE_START", result)) == 2


class TestInlineExamples:
    def test_inline_example_detected(self):
        from mkdocs_cdoc.parser import rst_to_markdown, DocComment, SymbolKind

        doc = DocComment(name="f", kind=SymbolKind.FUNCTION, comment="")
        text = "Does something. Example:\n\n    foo();\n"
        result = rst_to_markdown(text, doc=doc)
        assert "EXAMPLE_START" in result
        assert "foo();" in result

    def test_inline_text_before_example_preserved(self):
        from mkdocs_cdoc.parser import rst_to_markdown, DocComment, SymbolKind

        doc = DocComment(name="f", kind=SymbolKind.FUNCTION, comment="")
        text = "Does something. Example:\n\n    foo();\n"
        result = rst_to_markdown(text, doc=doc)
        assert "Does something." in result
        # "Example:" should NOT appear as text
        lines = [l for l in result.split("\n") if "EXAMPLE" not in l]
        assert not any("Example:" in l for l in lines)

    def test_multi_inline_both_detected(self):
        from mkdocs_cdoc.parser import rst_to_markdown, DocComment, SymbolKind
        import re

        doc = DocComment(name="f", kind=SymbolKind.FUNCTION, comment="")
        text = "Read. Example:\n\n    a();\n\nWrite. Example:\n\n    b();\n"
        result = rst_to_markdown(text, doc=doc)
        assert len(re.findall("EXAMPLE_START", result)) == 2

    def test_bash_detection(self):
        from mkdocs_cdoc.parser import rst_to_markdown, DocComment, SymbolKind

        doc = DocComment(name="f", kind=SymbolKind.FUNCTION, comment="")
        text = "Run it.\n\nExample:\n    $ ./run --test\n"
        result = rst_to_markdown(text, doc=doc)
        assert "```bash" in result

    def test_c_code_no_bash(self):
        from mkdocs_cdoc.parser import rst_to_markdown, DocComment, SymbolKind

        doc = DocComment(name="f", kind=SymbolKind.FUNCTION, comment="")
        text = "Use it.\n\nExample:\n    int x = f();\n"
        result = rst_to_markdown(text, doc=doc)
        assert "```c" in result


class TestSubtestStepExtraction:
    def test_steps_from_comments(self):
        from mkdocs_cdoc.parser import _parse_subtest_steps

        body = """
        /* Open the device */
        fd = open("/dev/dri/card0", O_RDWR);
        /* Verify it worked */
        igt_assert(fd >= 0);
        """
        steps = _parse_subtest_steps(body)
        assert any("Open the device" in s for s in steps)

    def test_steps_from_asserts(self):
        from mkdocs_cdoc.parser import _parse_subtest_steps

        body = """
        igt_assert(handle > 0);
        igt_assert_eq(result, 0);
        """
        steps = _parse_subtest_steps(body)
        assert any("Assert" in s for s in steps)

    def test_steps_from_igt_calls(self):
        from mkdocs_cdoc.parser import _parse_subtest_steps

        body = """
        gem_close(fd, handle);
        """
        steps = _parse_subtest_steps(body)
        assert any("gem_close" in s for s in steps)

    def test_steps_from_require(self):
        from mkdocs_cdoc.parser import _parse_subtest_steps

        body = """
        igt_require(fd >= 0);
        """
        steps = _parse_subtest_steps(body)
        assert any("Require" in s for s in steps)

    def test_comment_absorbs_following_assert(self):
        from mkdocs_cdoc.parser import _parse_subtest_steps

        body = """
        /* Verify the result is valid */
        igt_assert(result > 0);
        """
        steps = _parse_subtest_steps(body)
        # Comment should absorb the assert
        assert len(steps) == 1
        assert "Verify the result is valid" in steps[0]

    def test_steps_integrated_in_subtest_meta(self):
        from mkdocs_cdoc.parser import parse_igt_test_file

        test = parse_igt_test_file("example/src/tests/kms_addfb.c")
        basic = next(s for s in test.subtests if s.name == "basic")
        assert len(basic.steps) >= 3

    def test_bash_dollar_detection(self):
        from mkdocs_cdoc.parser import _detect_code_lang

        assert _detect_code_lang(["$ ./run_test"]) == "bash"
        assert _detect_code_lang(["int x = 5;"]) == "c"

    def test_extract_brace_body(self):
        from mkdocs_cdoc.parser import _extract_brace_body

        source = 'igt_subtest("foo") { bar(); baz(); }'
        body = _extract_brace_body(source, source.index("{"))
        assert "bar()" in body
        assert "baz()" in body
