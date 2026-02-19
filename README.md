# mkdocs-cdoc

[![CI](https://github.com/pawelsikora/mkdocs-cdoc/actions/workflows/ci.yml/badge.svg)](https://github.com/pawelsikora/mkdocs-cdoc/actions/workflows/ci.yml)
![PyPI - Version](https://img.shields.io/pypi/v/mkdocs-cdoc)
![Python versions](https://img.shields.io/pypi/pyversions/mkdocs-cdoc)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![MkDocs](https://img.shields.io/badge/MkDocs-plugin-blue)](https://www.mkdocs.org/)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

**Generate browsable API documentation from C/C++ source comments directly in MkDocs** — with cross-referencing, symbol indexing, and first-class support for [IGT GPU Tools](https://gitlab.freedesktop.org/drm/igt-gpu-tools) test catalogs.

Parses `/** ... */` doc comments using libclang (with a regex fallback), converts reST and gtk-doc markup to Markdown, and builds a fully linked API reference with per-symbol anchors, an A–Z index, and automatic cross-references across all your source files and hand-written pages.

---

## Table of contents

- [Features](#features)
- [Installation](#installation)
- [Quick start](#quick-start)
- [Configuration](#configuration)
  - [Single-source setup](#single-source-setup)
  - [Multi-source setup](#multi-source-setup)
  - [Source group options](#source-group-options)
  - [Global options](#global-options)
- [Cross-references](#cross-references)
- [Rendering](#rendering)
- [gtk-doc migration](#gtk-doc-migration)
- [Inline directives](#inline-directives)
- [Test documentation (IGT GPU Tools)](#test-documentation-igt-gpu-tools)
- [Credits](#credits)
- [License](#license)

---

## Features

- **Autodoc from C/C++ sources** — scans source trees, extracts doc comments, generates per-file pages with function signatures, parameter tables, and struct/enum member listings.
- **Cross-reference everything** — `:func:`, `:struct:`, `:file:`, backtick auto-linking. Works across generated pages and hand-written Markdown alike.
- **Multiple source groups** — separate nav sections for core libraries, drivers, tests, etc., each with their own A–Z index and overview.
- **IGT test catalog** — parses `TEST:` / `SUBTEST:` structured comments and `igt_subtest()` / `igt_describe()` macros to build test documentation with metadata tables, "By Category" / "By Functionality" index pages, and per-subtest anchors.
- **gtk-doc migration** — converts `#TypeName`, `function()`, `%CONSTANT`, `@param` markup at parse time, plus a CLI for one-time batch conversion of source files.
- **Clang + regex** — uses libclang when available for accurate signatures and types, falls back to regex parsing so it works everywhere.

---

## Installation

```bash
pip install mkdocs-cdoc
```

For full clang-based parsing (recommended):

```bash
# Ubuntu / Debian
sudo apt install python3-clang libclang-dev

# macOS
brew install llvm

# Or via pip extras
pip install mkdocs-cdoc[clang]
```

---

## Quick start

Minimal setup — point it at a source directory:

```yaml
plugins:
  - cdoc:
      source_root: src/
```

This scans all `.c` and `.h` files under `src/`, generates per-file API pages, and adds them to the nav under "API Reference".

---

## Configuration

### Single-source setup

When you have a single source tree, use the flat `autodoc_*` shortcuts:

```yaml
plugins:
  - cdoc:
      source_root: src/
      autodoc_nav_title: My API
      autodoc_output_dir: reference
      autodoc_extensions: [".c", ".h", ".hpp"]
      autodoc_exclude: ["**/internal/*", "test_*.c"]
      autodoc_index: true
      custom_index_pages:
        - docs/api-intro.md
        - docs/conventions.md
      autodoc_pages:
        - docs/getting-started.md
        - docs/migration-guide.md
```

| Option | Default | Description |
|--------|---------|-------------|
| `source_root` | `""` | Path to the source tree |
| `autodoc_nav_title` | `"API Reference"` | Nav section heading |
| `autodoc_output_dir` | `"API Reference"` | Where generated pages go |
| `autodoc_extensions` | `[".c", ".h"]` | File extensions to scan |
| `autodoc_exclude` | `[]` | Glob patterns to skip |
| `autodoc_index` | `true` | Generate an overview page with file table and A–Z index |
| `custom_index_pages` | `[]` | Markdown files to embed in the overview page (between file table and symbol index) |
| `autodoc_pages` | `[]` | Extra hand-written pages to include in the nav section |
| `autodoc` | `true` | Enable autodoc page generation (set `false` to only use inline directives) |

Setting `autodoc_index: false` disables the overview page — useful if you only want individual file pages without a landing page.

Setting `autodoc: false` disables all automatic page generation entirely. You'd then use [inline directives](#inline-directives) to pull specific symbols into hand-written pages.

**`custom_index_pages` vs `pages`:** `custom_index_pages` embeds the markdown content directly into the overview/index page (between the source file table and the A–Z symbol index). `pages` adds separate pages to the nav sidebar alongside the generated API pages. Use `custom_index_pages` for introductory text, conventions, or quick-start guides you want visitors to see on the overview. Use `pages` for standalone docs that deserve their own page.

### Multi-source setup

For projects with multiple source trees (libraries, drivers, tests), use `sources:`:

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
          exclude: ["*_test.c"]

        - root: src/utils
          nav_title: Utilities
          output_dir: api/utils
          index: false
          pages:
            - docs/utils-guide.md
```

The `version_file` is scanned for a line matching `version: 'X.Y'` (or `VERSION = "1.2.3"`, `"version": "2.0"`, etc.) — it works with JSON, YAML, Python, meson.build, or any file with a version key-value pair.

With multiple source groups a top-level overview page is generated automatically, showing the project name, a version badge, and links to each group:

```
API Reference
  Core API
    Overview
  Driver API
    Overview
  Utilities
```

### Source group options

Each entry under `sources:` accepts:

| Option | Default | Description |
|--------|---------|-------------|
| `root` | *(required)* | Path to the source tree |
| `nav_title` | `API (<dirname>)` | Nav section heading |
| `output_dir` | `api_reference/<dirname>` | Where generated pages go |
| `extensions` | `[".c", ".h"]` | File extensions to scan |
| `exclude` | `[]` | Glob patterns to skip |
| `clang_args` | `[]` | Extra flags, appended to global `clang_args` |
| `index` | `true` | Generate an overview page |
| `custom_index_pages` | `[]` | Markdown files to embed in the overview page |
| `pages` | `[]` | Extra hand-written pages to include in the nav |
| `igt` | — | IGT test framework options ([see below](#enabling-test-mode)) |

### Global options

These apply to all source groups:

| Option | Default | Description |
|--------|---------|-------------|
| `project_name` | `""` | Project name on the top-level overview page |
| `version_file` | `""` | File to extract version from |
| `clang_args` | `[]` | Global clang flags (merged with per-group flags) |
| `convert_rst` | `true` | Convert reST markup to Markdown |
| `convert_gtkdoc` | `false` | Convert gtk-doc markup to reST at parse time |
| `auto_xref` | `true` | Auto-link backticked symbol names |
| `appendix_code_usages` | `false` | Append a "Referenced by" section to each symbol |
| `heading_level` | `2` | Heading depth for symbols (`2` = `##`, `3` = `###`) |
| `members` | `true` | Show struct/union/enum members |
| `signature_style` | `"code"` | How to render function signatures (`"code"` or `"plain"`) |
| `show_source_link` | `false` | Append `[source]` links to each symbol |
| `source_uri` | `""` | URI template: `https://github.com/you/repo/blob/main/{filename}#L{line}` |
| `fallback_parser` | `true` | Use regex parser when clang is unavailable |
| `language` | `"c"` | Source language (`"c"` or `"cpp"`) |

**Full example with all global options:**

```yaml
plugins:
  - cdoc:
      project_name: My Project
      version_file: meson.build
      clang_args: ["-Iinclude", "-DDEBUG=0"]
      convert_rst: true
      convert_gtkdoc: true
      auto_xref: true
      appendix_code_usages: true
      heading_level: 2
      members: true
      signature_style: code
      show_source_link: true
      source_uri: "https://github.com/you/repo/blob/main/{filename}#L{line}"
      fallback_parser: true
      language: c

      sources:
        - root: src
          nav_title: API
          output_dir: api
```

#### Backward-compatible flat config (legacy)

The following flat keys still work for IGT test configuration but are superseded by the nested `igt:` block in source groups:

| Flat key | Equivalent | Description |
|----------|-----------|-------------|
| `test_mode: igt` | presence of `igt:` block | Enable IGT test parsing |
| `test_group_by` | `igt.group_by` | Metadata fields for "By …" pages |
| `test_fields` | `igt.fields` | Metadata fields to display |
| `extract_test_steps` | `igt.extract_steps` | Parse subtest bodies for steps |

---

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

---

## Rendering

**Parameter tables** — function parameters render as a table. When type information is available (from clang), a Type column is added with cross-reference links for struct/custom types.

**Pointer return types** — functions returning pointers (e.g. `char *get_name(...)`) render as "Pointer to `char`" rather than showing `*` in the name.

**Example sections** — if a doc comment contains `Example:`, the description and code render side-by-side, similar to the Stripe API documentation layout.

**Notes/Note sections** — if a doc comment contains `Notes:` or `Note:`, the content renders as a Material Design warning admonition:

```
!!! warning "Note"
    This function is not thread-safe.
    Call only from the main thread.
```

**Underscore-prefixed symbols** — functions with `_` or `__` prefix sort by the name without the prefix. `__engine_reset` sorts under **E**.

---

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

---

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

When using inline directives without automatic page generation, set `autodoc: false`:

```yaml
plugins:
  - cdoc:
      source_root: src/
      autodoc: false
```

Then use directives in your hand-written pages to include only the symbols you want.

---

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

### IGT options

| Option | Default | Description |
|--------|---------|-------------|
| `group_by` | `[]` | Metadata fields to generate "By …" index pages for |
| `fields` | same as `group_by` | Which metadata fields to show on each test page |
| `extract_steps` | `false` | Parse subtest code bodies for step-by-step tables |

When `fields` is not specified it defaults to the same list as `group_by`, so you don't need to repeat yourself.

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

The plugin matches field names flexibly across underscore, hyphen, and space variations — `sub_category` in config matches `Sub-category` or `Sub category` in source comments.

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

---

## Credits

This project was inspired by the work of [Jani Nikula](https://github.com/jnikula) and the [Hawkmoth](https://github.com/jnikula/hawkmoth) project, which provides Sphinx-based autodoc for C. The core idea of extracting C doc comments through libclang originates there. mkdocs-cdoc adapts and extends that concept for the MkDocs ecosystem, adding multi-source-group navigation, cross-reference resolution, IGT test catalog generation, and gtk-doc migration tooling.

## License

MIT — see [LICENSE](LICENSE) for details.
