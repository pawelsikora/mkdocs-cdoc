# mkdocs-cdoc

[![CI](https://github.com/pawelsikora/mkdocs-cdoc/actions/workflows/ci.yml/badge.svg)](https://github.com/pawelsikora/mkdocs-cdoc/actions/workflows/ci.yml)
[![PyPI version](https://img.shields.io/pypi/v/mkdocs-cdoc)](https://pypi.org/project/mkdocs-cdoc/)
![Python versions](https://img.shields.io/pypi/pyversions/mkdocs-cdoc)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![MkDocs](https://img.shields.io/badge/MkDocs-plugin-blue)](https://www.mkdocs.org/)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

**Generate browsable API documentation from C/C++ source comments directly in MkDocs** — with cross-referencing, symbol indexing, and basic support for test catalogs.

Parses `/** ... */` doc comments using libclang (with a regex fallback), converts reST and gtk-doc markup to Markdown, and builds a fully linked API reference with per-symbol anchors, an A–Z index, and automatic cross-references across all your source files and hand-written pages.

---

## Features

- **Autodoc from C/C++ sources** — scans source trees, extracts doc comments, generates per-file pages with function signatures, parameter tables, and struct/enum member listings.
- **Cross-reference everything** — `:func:`, `:struct:`, `:file:`, backtick auto-linking. Works across generated pages and hand-written Markdown alike.
- **Multiple source groups** — separate nav sections for core libraries, drivers, tests, etc., each with their own A–Z index and overview.
- **IGT test catalog** — parses `TEST:` / `SUBTEST:` structured comments and `igt_subtest()` / `igt_describe()` macros to build test documentation with metadata tables, "By Category" / "By Functionality" index pages, and per-subtest anchors.
- **gtk-doc migration** — converts `#TypeName`, `function()`, `%CONSTANT`, `@param` markup at parse time, plus a CLI for one-time batch conversion of source files.
- **Clang + regex** — uses libclang when available for accurate signatures and types, falls back to regex parsing so it works everywhere.

---

## Install

```bash
pip install mkdocs-cdoc
```

For full clang-based parsing (recommended):

```bash
# Ubuntu / Debian
sudo apt install python3-clang libclang-dev

# Or via pip
pip install mkdocs-cdoc[clang]
```

## Quick start

Minimal setup — point it at a source directory:

```yaml
plugins:
  - cdoc:
      source_root: src/
```

Multiple source trees with their own nav sections:

```yaml
plugins:
  - cdoc:
      project_name: My Project
      version_file: version.json

      sources:
        - root: src/core
          nav_title: Core API
          output_dir: api/core

        - root: src/drivers
          nav_title: Driver API
          output_dir: api/drivers
          extensions: [".c"]
```

The `version_file` is scanned for a line matching `version: 'X.Y'` (or `VERSION = "1.2.3"`, `"version": "2.0"`, etc.) — it works with JSON, YAML, Python, meson.build, or any file with a version key-value pair.

With multiple source groups, a top-level overview page is generated automatically showing the project name, a version badge, and links to each group. Individual source file pages are generated and reachable via cross-references and the index — they just don't crowd the nav:

```
API Reference
  Core API
    Overview
  Driver API
    Overview
```

## Source group options

Each entry under `sources:` accepts:

| Option | Default | Description |
|--------|---------|-------------|
| `root` | *(required)* | Path to the source tree |
| `nav_title` | `API (<dirname>)` | Nav section heading |
| `output_dir` | `api/<dirname>` | Where generated pages go |
| `extensions` | `[".c", ".h"]` | File extensions to scan |
| `exclude` | `[]` | Glob patterns to skip |
| `clang_args` | `[]` | Extra flags, appended to global `clang_args` |
| `index` | `true` | Generate an overview page |
| `pages` | `[]` | Extra hand-written pages to include in the nav |
| `igt` | — | IGT test framework options ([see below](#test-documentation-igt-gpu-tools)) |

## Test documentation (IGT GPU Tools)

The plugin has built-in support for test source trees that use structured doc comments and test macros. While designed around [IGT GPU Tools](https://gitlab.freedesktop.org/drm/igt-gpu-tools) conventions, the approach works for any C test codebase that follows a similar comment structure.

### Enabling test mode

Add an `igt:` block to any source group:

```yaml
sources:
  - root: tests
    nav_title: Tests
    output_dir: api/tests
    extensions: [".c"]
    igt:
      group_by: [category, mega_feature, sub_category, functionality]
```

That's all you need. The presence of `igt:` enables test parsing for that source group.

### IGT GPU Tools options

| Option | Default | Description |
|--------|---------|-------------|
| `group_by` | `[]` | Metadata fields to generate "By …" index pages for |
| `fields` | same as `group_by` | Which metadata fields to show on each test page |
| `extract_steps` | `false` | Parse subtest code bodies for step-by-step tables |

### What it parses

**Structured doc comments** at file scope — either in a main `TEST:` block or standalone `SUBTEST:` blocks above functions:

```c
/**
 * TEST: kms_addfb
 * Category: Display
 * Mega feature: KMS
 * Sub-category: Framebuffer
 * Description: Tests for the DRM framebuffer creation ioctl.
 *
 * SUBTEST: basic
 * Description: Check if addfb2 works with a valid handle.
 * Functionality: addfb
 */
```

Standalone subtest blocks are also supported, placed above individual functions:

```c
/**
 * SUBTEST: attach-debug-metadata
 * Functionality: metadata
 * Description:
 *      Read debug metadata when vm_bind has it attached.
 */
static void test_metadata_attach(int fd, unsigned int flags) { ... }
```

**Test macros** in code — `igt_subtest()`, `igt_describe()`, and `igt_subtest_with_dynamic()`:

```c
igt_describe("Check that invalid legacy set-property calls are "
             "correctly rejected by the kernel.");
igt_subtest("invalid-properties-legacy") {
    ...
}
```

Both sources are merged: subtests from doc comments and code are combined, with `igt_describe()` taking priority for descriptions, then standalone `SUBTEST:` blocks, then the main `TEST:` block.

Multi-line `igt_describe()` strings (concatenated across lines) are handled. Format-string subtests like `igt_subtest("%s")` are automatically excluded.

### Metadata fields

Any `Key: Value` pair in the doc comment becomes a metadata field. Common conventions:

| Field | Level | Typical values |
|-------|-------|----------------|
| `Category` | test | Core, Display, … |
| `Mega feature` | test | KMS, Memory Management, … |
| `Sub-category` | test | GEM, Framebuffer, … |
| `Functionality` | subtest | addfb, gem_create, … |
| `Description` | both | Free-form text (supports multi-line) |

Test-level fields (like Category) group all tests in a file. Subtest-level fields (like Functionality) group individual subtests and produce a different table layout on the "By …" pages.

### Generated pages

The nav sidebar shows:

```
Tests
  Overview              ← file table + A–Z symbol index
  By Category           ← tests grouped by Category field
  By Mega Feature       ← tests grouped by Mega Feature field
  By Sub Category       ← tests grouped by Sub-category field
  By Functionality      ← subtests grouped by Functionality field
```

Each **"By …" page** groups tests under headings matching the field values. Under each value, every test gets its own subheading with a table of its subtests and descriptions.

Each **test page** shows a metadata table, the full subtest listing (with anchor links per subtest), and optionally step-by-step tables when `extract_steps: true`.

### Adapting for your own test framework

The `igt:` parser key specifically enables the IGT-style parser, but the comment format is generic enough for any C test suite. If your tests use `/** ... */` comments with structured `TEST:` / `SUBTEST:` blocks and key-value metadata, they will work as-is. You only need IGT-specific macros (`igt_subtest`, `igt_describe`) if you want code-level subtest discovery.

To use it with a custom test tree:

1. Add `/** TEST: my_test_name */` comments with any metadata fields you like.
2. Optionally add `/** SUBTEST: name */` blocks with per-subtest metadata.
3. Set `group_by` to whichever field names you used.

### Cross-referencing tests

Tests and subtests are registered in the symbol registry:

```markdown
See :test:`kms_addfb` for framebuffer tests.
The :subtest:`kms_addfb@basic` subtest covers the happy path.
```

The `test@subtest` notation mirrors IGT's `--run-subtest` convention. Short-form `:subtest:`basic`` works if the subtest name is unique across all tests.

## Cross-references

The plugin builds a symbol registry at build time and resolves references across all pages — generated API pages and hand-written docs alike.

### reST roles in doc comments

Use reST roles (portable to Sphinx):

```c
/**
 * Initialize the engine.
 *
 * Must be called before :func:`engine_run`. Configure with
 * :struct:`engine_config` first.
 *
 * :param flags: Init flags.
 * :returns: 0 on success.
 */
int engine_init(unsigned int flags);
```

Available roles: `:func:`, `:struct:`, `:union:`, `:enum:`, `:macro:`, `:type:`, `:var:`, `:const:`, `:member:`, `:class:`, `:file:`, `:test:`, `:subtest:`. Domain-qualified forms like `:c:func:` also work.

For struct members use dot notation: `:member:`engine_config.debug``. For files, use the bare filename if unique or qualify with the group: `:file:`core/engine.h``.

### reST roles in Markdown pages

The same roles work in hand-written Markdown:

```markdown
Call :func:`engine_init` with the appropriate flags, then pass
an :struct:`engine_config` to :func:`engine_run`.
```

### Auto-linking

When `auto_xref` is enabled (the default), backticked identifiers that match known symbols become links automatically:

```markdown
Call `engine_init()` first, then create an `engine_config` and
pass it to `engine_run()`.
```

Trailing `()` signals a function reference. Bare backticked names link if they match a struct, enum, type, etc. Filenames with C/C++ extensions also auto-link. Unknown names stay as plain code.

## Rendering

**Parameter tables** — function parameters render as a table. When type information is available (from clang), a Type column is added with cross-reference links for struct/custom types.

**Pointer return types** — functions returning pointers (e.g. `char *get_name(...)`) render as "Pointer to `char`" rather than showing `*` in the name.

**Example sections** — if a doc comment contains `Example:`, the description and code render side-by-side, similar to the Stripe API documentation layout.

**Underscore-prefixed symbols** — functions with `_` or `__` prefix sort by the name without the prefix. `__engine_reset` sorts under **E**.

## gtk-doc migration

If your codebase uses gtk-doc markup:

```yaml
plugins:
  - cdoc:
      convert_gtkdoc: true
```

| gtk-doc | Converts to |
|---------|------------|
| `function_name()` | `:func:`function_name`` |
| `#TypeName` | `:type:`TypeName`` |
| `#Struct.field` | `:member:`Struct.field`` |
| `%CONSTANT` | `:const:`CONSTANT`` |
| `@param: desc` | `:param param: desc` |
| `Returns:` | `:returns:` |
| `\|[ code ]\|` | fenced code block |

Batch conversion CLI to permanently migrate source files:

```bash
python -m mkdocs_cdoc.convert src/
python -m mkdocs_cdoc.convert src/ --dry-run
python -m mkdocs_cdoc.convert src/ --backup
```

## Inline directives

Pull specific symbols into hand-written pages:

```markdown
::: c:autofunction
    :file: engine.h
    :name: engine_init

::: c:autodoc
    :file: uart.c
```

Full directive list: `autodoc`, `autofunction`, `autostruct`, `autounion`, `autoenum`, `automacro`, `autovar`, `autotype`.

## Global config reference

| Option | Default | Description |
|--------|---------|-------------|
| `project_name` | `""` | Project name on the top-level overview page |
| `version_file` | `""` | File to extract version from |
| `sources` | `[]` | List of source group configs (see above) |
| `clang_args` | `[]` | Global clang flags (merged with per-group flags) |
| `convert_rst` | `true` | Convert reST markup to Markdown |
| `convert_gtkdoc` | `false` | Convert gtk-doc markup to reST at parse time |
| `auto_xref` | `true` | Auto-link backticked symbol names |
| `appendix_code_usages` | `false` | Append a "Referenced by" section to each symbol |
| `heading_level` | `2` | Heading depth for symbols |
| `members` | `true` | Show struct/union/enum members |
| `show_source_link` | `false` | Append `[source]` links |
| `source_uri` | `""` | Template: `https://github.com/you/repo/blob/main/{filename}#L{line}` |
| `fallback_parser` | `true` | Use regex parser when clang is unavailable |
| `language` | `"c"` | Source language (`c` or `cpp`) |

For single-source setups without `sources:`, these shortcuts are available: `source_root`, `autodoc_output_dir`, `autodoc_nav_title`, `autodoc_extensions`, `autodoc_exclude`, `autodoc_index`, `autodoc_pages`.

## Example: GTK-doc based project config

```yaml
plugins:
  - cdoc:
      project_name: my-project
      version_file: meson.build
      clang_args: ["-Ilib", "-Itests", "-Iinclude"]

      sources:
        - root: lib
          nav_title: Core API
          output_dir: reference_api/lib

        - root: tests
          nav_title: Tests
          output_dir: reference_api/tests
          extensions: [".c"]

      convert_rst: true
      convert_gtkdoc: true
```

## Credits

This project was inspired by the work of [Jani Nikula](https://github.com/jnikula) and the [Hawkmoth](https://github.com/jnikula/hawkmoth) project, which provides Sphinx-based autodoc for C. The core idea of extracting C doc comments through libclang originates there. mkdocs-cdoc adapts and extends that concept for the MkDocs ecosystem, adding multi-source-group navigation, cross-reference resolution, IGT GPU Tools test catalog generation, and gtk-doc migration tooling.

## License

MIT — see [LICENSE](LICENSE) for details.
