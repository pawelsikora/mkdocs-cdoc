#!/usr/bin/env python3
"""
Batch convert gtk-doc markup to reST in C/C++ doc comments.

Usage:
    python -m mkdocs_cdoc.convert src/
    python -m mkdocs_cdoc.convert src/engine.h --dry-run
    python -m mkdocs_cdoc.convert src/ --ext .c .h --backup
"""

import argparse
import os
import re
import shutil
import sys

from .parser import gtkdoc_to_rst

_BLOCK_COMMENT_RE = re.compile(r"(/\*\*.*?\*/)", re.DOTALL)


def convert_file(path, dry_run=False, backup=False):
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        original = f.read()

    def convert_match(m):
        full = m.group(1)
        if not full.startswith("/**"):
            return full
        prefix = full[:3]
        suffix = full[-2:]
        inner = full[3:-2]
        converted = gtkdoc_to_rst(inner)
        return prefix + converted + suffix

    result = _BLOCK_COMMENT_RE.sub(convert_match, original)

    if result == original:
        return False

    if dry_run:
        return True

    if backup:
        shutil.copy2(path, path + ".bak")

    with open(path, "w", encoding="utf-8") as f:
        f.write(result)
    return True


def main():
    p = argparse.ArgumentParser(description="Convert gtk-doc markup to reST in C/C++ doc comments")
    p.add_argument("path", help="File or directory to convert")
    p.add_argument(
        "--ext",
        nargs="+",
        default=[".c", ".h", ".cpp", ".hpp"],
        help="File extensions to process (default: .c .h .cpp .hpp)",
    )
    p.add_argument(
        "--dry-run", action="store_true", help="Show what would change without modifying files"
    )
    p.add_argument("--backup", action="store_true", help="Create .bak files before modifying")
    args = p.parse_args()

    target = args.path
    exts = set(e if e.startswith(".") else f".{e}" for e in args.ext)

    files = []
    if os.path.isfile(target):
        files.append(target)
    elif os.path.isdir(target):
        for dirpath, _, fnames in os.walk(target):
            for fn in sorted(fnames):
                _, ext = os.path.splitext(fn)
                if ext.lower() in exts:
                    files.append(os.path.join(dirpath, fn))
    else:
        print(f"error: {target} not found", file=sys.stderr)
        sys.exit(1)

    changed = 0
    for fpath in files:
        was_changed = convert_file(fpath, dry_run=args.dry_run, backup=args.backup)
        if was_changed:
            changed += 1
            tag = "[dry-run] " if args.dry_run else ""
            print(f"{tag}converted: {fpath}")

    total = len(files)
    print(f"\n{changed}/{total} files {'would be ' if args.dry_run else ''}modified")


if __name__ == "__main__":
    main()
