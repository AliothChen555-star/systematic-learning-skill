#!/usr/bin/env python3
"""Locate learning courses across chats; the catalog stores identity and paths only."""

from __future__ import annotations

import argparse
from datetime import date
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from uuid import UUID


def default_catalog_path() -> Path:
    codex_base = Path(os.environ["CODEX_HOME"]).expanduser() if os.environ.get("CODEX_HOME") else Path.home() / ".codex"
    return codex_base / "skill-state/systematic-learning/courses.json"


def read_identity(root: Path) -> dict:
    text = (root / "学习记录.md").read_text(encoding="utf-8-sig")
    match = re.match(r"\A---\r?\n(.*?)\r?\n---(?:\r?\n|$)", text, re.DOTALL)
    if not match:
        raise ValueError("Learning record needs identity frontmatter; add course_id and course_title without changing its history")
    fields = {}
    for line in match.group(1).splitlines():
        item = re.fullmatch(r"(course_id|course_title|course_root):\s*(.+)", line)
        if item:
            if item.group(1) in fields:
                raise ValueError(f"Duplicate identity field: {item.group(1)}")
            # Identity strings use JSON double quoting, a valid subset of YAML.
            fields[item.group(1)] = json.loads(item.group(2))
    for key in ("course_id", "course_title"):
        if not isinstance(fields.get(key), str) or not fields[key].strip():
            raise ValueError(f"Missing or invalid {key} in learning record")
    UUID(fields["course_id"])
    if not (root / "00-前言.md").is_file():
        raise ValueError("Course preface is missing")
    return fields


def read_catalog(path: Path) -> dict:
    if not path.exists():
        return {"schema_version": 1, "library_root": None, "courses": []}
    catalog = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(catalog, dict) or catalog.get("schema_version") != 1 or not isinstance(catalog.get("courses"), list):
        raise ValueError("Unsupported or invalid course catalog; refusing to replace it")
    if catalog.get("library_root") is not None and not isinstance(catalog["library_root"], str):
        raise ValueError("Invalid library_root in catalog")
    seen = set()
    for entry in catalog["courses"]:
        if not isinstance(entry, dict) or any(not isinstance(entry.get(key), str) or not entry[key] for key in ("course_id", "title", "root")):
            raise ValueError("Invalid course entry; refusing to replace catalog")
        UUID(entry["course_id"])
        if entry["course_id"] in seen:
            raise ValueError("Duplicate course identity in catalog")
        seen.add(entry["course_id"])
    return catalog


def atomic_write_catalog(path: Path, catalog: dict) -> None:
    path = path.expanduser().absolute()
    if path.is_symlink():
        raise ValueError("Catalog path must not be a symbolic link")
    path.parent.mkdir(parents=True, exist_ok=True)
    parent = path.parent.resolve()
    descriptor, name = tempfile.mkstemp(prefix=".course-catalog-", suffix=".json", dir=parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(catalog, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        if temporary.resolve().parent != parent or path.parent.resolve() != parent:
            raise ValueError("Catalog paths left the intended parent directory")
        temporary.replace(path)
    finally:
        if temporary.exists():
            if temporary.resolve().parent != parent:
                raise ValueError("Unsafe catalog temporary path")
            temporary.unlink()


def register_course(catalog_path: Path, root: Path, local_date: str, set_library_root: bool = False) -> dict:
    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", local_date):
        raise ValueError("--date must use the user-local YYYY-MM-DD format")
    date.fromisoformat(local_date)
    root = root.expanduser().resolve()
    identity = read_identity(root)
    catalog = read_catalog(catalog_path)
    for entry in catalog["courses"]:
        if Path(entry["root"]).resolve() == root and entry["course_id"] != identity["course_id"]:
            raise ValueError("This course location is registered under another identity; resolve that conflict first")
    updated = {
        "course_id": identity["course_id"],
        "title": identity["course_title"],
        "root": str(root),
        "registered_on": local_date,
    }
    for index, entry in enumerate(catalog["courses"]):
        if entry["course_id"] == identity["course_id"]:
            catalog["courses"][index] = updated
            break
    else:
        catalog["courses"].append(updated)
    if not catalog.get("library_root") or set_library_root:
        catalog["library_root"] = str(root.parent)
    atomic_write_catalog(catalog_path, catalog)
    result = {"catalog": str(catalog_path.absolute()), "registered": updated, "library_root": catalog["library_root"]}
    if identity.get("course_root") != str(root):
        result["record_path_needs_update"] = True
    return result


def list_courses(catalog_path: Path, query: str = "") -> dict:
    catalog = read_catalog(catalog_path)
    matched = []
    needle = query.strip().casefold()
    for entry in catalog["courses"]:
        if needle and needle not in entry["title"].casefold() and needle != entry["course_id"].casefold():
            continue
        row = dict(entry)
        try:
            row["available"] = read_identity(Path(row["root"]))["course_id"] == row["course_id"]
        except (OSError, ValueError):
            row["available"] = False
        matched.append(row)
    return {"catalog": str(catalog_path.absolute()), "library_root": catalog.get("library_root"), "matches": matched, "ambiguous": len(matched) > 1}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=default_catalog_path())
    commands = parser.add_subparsers(dest="command", required=True)
    show = commands.add_parser("list")
    show.add_argument("--query", default="")
    register = commands.add_parser("register")
    register.add_argument("--root", type=Path, required=True)
    register.add_argument("--date", required=True)
    register.add_argument("--set-library-root", action="store_true")
    args = parser.parse_args()
    try:
        if args.command == "list":
            result = list_courses(args.catalog, args.query)
        else:
            result = register_course(args.catalog, args.root, args.date, args.set_library_root)
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
