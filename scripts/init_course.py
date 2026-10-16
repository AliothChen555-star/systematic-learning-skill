#!/usr/bin/env python3
"""Initialize two course documents and empty chapter directories, without overwrites."""

from __future__ import annotations

import argparse
from datetime import date
import json
from pathlib import Path
import re
import shutil
import sys
import tempfile
from urllib.parse import unquote
from uuid import uuid4


RESERVED = {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"}
RESERVED |= {f"{prefix}{number}" for prefix in ("COM", "LPT") for number in "123456789¹²³"}
ROOT_FILES = ("00-前言.md", "学习记录.md")


def require_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be non-empty text")
    if any(ord(char) < 32 for char in value):
        raise ValueError(f"{label} must be a single line without control characters")
    return value.strip()


def safe_directory(value: object) -> str:
    name = require_text(value, "chapter.directory")
    if name != value or name in {".", ".."} or name.endswith((" ", ".")):
        raise ValueError(f"Unsafe chapter directory: {value!r}")
    if re.search(r'[<>:"/\\|?*]', name) or name.split(".", 1)[0].upper() in RESERVED:
        raise ValueError(f"Unsafe chapter directory: {name!r}")
    if name.casefold() in {item.casefold() for item in ROOT_FILES}:
        raise ValueError(f"Chapter directory conflicts with a course document: {name}")
    if len(name.encode("utf-16-le")) // 2 > 255:
        raise ValueError("Chapter directory exceeds the Windows component length limit")
    return name


def validate_plan(spec: object, preface: str) -> tuple[str, list[dict]]:
    if not isinstance(spec, dict):
        raise ValueError("The plan must be a JSON object")
    title = require_text(spec.get("title"), "title")
    raw_chapters = spec.get("chapters")
    if not isinstance(raw_chapters, list) or not raw_chapters:
        raise ValueError("chapters must be a non-empty list")
    if not preface.strip():
        raise ValueError("The researched preface must not be empty")

    # Match Markdown directory links, including angle-bracket and URL-encoded targets.
    link_targets = set()
    for match in re.finditer(r"\]\(\s*(?:<([^>]+)>|([^\s)]+))\s*\)", preface):
        target = unquote((match.group(1) or match.group(2)).split("#", 1)[0])
        link_targets.add(target.removeprefix("./").rstrip("/"))

    chapter_ids, module_ids, directory_names = set(), set(), set()
    chapters = []
    for raw in raw_chapters:
        if not isinstance(raw, dict):
            raise ValueError("Each chapter must be an object")
        chapter_id = require_text(raw.get("id"), "chapter.id")
        if not re.fullmatch(r"C[0-9]{2,}", chapter_id) or chapter_id in chapter_ids:
            raise ValueError(f"Invalid or duplicate chapter ID: {chapter_id}")
        chapter_ids.add(chapter_id)
        directory = safe_directory(raw.get("directory"))
        if directory.casefold() in directory_names:
            raise ValueError(f"Duplicate chapter directory: {directory}")
        directory_names.add(directory.casefold())
        if directory not in link_targets:
            raise ValueError(f"Preface must link to chapter directory: {directory}/")
        chapter_title = require_text(raw.get("title"), "chapter.title")
        raw_modules = raw.get("modules")
        if not isinstance(raw_modules, list) or not raw_modules:
            raise ValueError(f"Chapter {chapter_id} needs at least one module")
        modules = []
        for module in raw_modules:
            if not isinstance(module, dict):
                raise ValueError("Each module must be an object")
            module_id = require_text(module.get("id"), "module.id")
            if not re.fullmatch(re.escape(chapter_id) + r"-M[0-9]{2,}", module_id):
                raise ValueError(f"Module ID must belong to {chapter_id}: {module_id}")
            if module_id in module_ids:
                raise ValueError(f"Duplicate module ID: {module_id}")
            module_ids.add(module_id)
            if not re.search(r"(?<![A-Z0-9-])" + re.escape(module_id) + r"(?![A-Z0-9-])", preface):
                raise ValueError(f"Module is missing from researched preface: {module_id}")
            modules.append({"id": module_id, "title": require_text(module.get("title"), "module.title")})
        chapters.append({"id": chapter_id, "title": chapter_title, "directory": directory, "modules": modules})
    return title, chapters


def table_cell(text: str) -> str:
    return text.replace("\\", "\\\\").replace("|", "\\|")


def progress_document(title: str, chapters: list[dict], local_date: str, *, course_id: str, course_root: Path) -> str:
    modules = [module for chapter in chapters for module in chapter["modules"]]
    first = modules[0]
    rows = [
        f"| {module['id']} | {table_cell(module['title'])} | 待学习 | 未开始 | 未验证 | 未整理 | 未核对 | 未生成 | — |"
        for module in modules
    ]
    metadata = {
        "schema_version": 2,
        "course_id": course_id,
        "course_title": title,
        "course_root": str(course_root),
        "created": local_date,
    }
    header = "---\n" + "\n".join(f"{key}: {json.dumps(value, ensure_ascii=False)}" for key, value in metadata.items()) + "\n---\n\n"
    return header + f"""# 学习记录

- 课程：{title}
- 创建日期：{local_date}
- 最近更新：{local_date}
- 当前模块：{first['id']} · {first['title']}
- 当前阶段：待自学
- 下次直接开始：按[前言](00-前言.md)中的准确资料位置自学 {first['id']}，随后向 AI 复述。

## 已学内容摘要

尚未开始。后续仅根据真实发生的阅读、复述、纠错和验证更新。

## 模块进度

| 模块 | 标题 | 阅读 | 复述 | 理解验证 | 内容覆盖 | 事实核对 | 教材文档 | 文件 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
{chr(10).join(rows)}

## 本次停在哪里

课程路径与目录已建立，第一次学习尚未开始。

## 易错点、待解决与复习

尚无学习证据；阅读、复述、理解验证、内容覆盖、事实核对和文档生成分别记录。

## 作者表达档案

尚无复述样本，不预设作者风格。以后根据真实复述记录展开顺序、语气、例子偏好和少量带日期/模块的短句样本。

## 核查、纠错与贡献记录

尚无。以后按目标记录来源位置、正文位置、核查结果、原误解及纠正依据、用户重新解释结果，以及用户原创/资料补充的区别。

## 下次学习

- 模块：{first['id']} · {first['title']}。
- 资料：参见前言中对应模块的必学资料与具体位置。
- 行动：先自学，再用自己的话教 AI；复述发生后再生成模块正文。

## 学习轨迹

| 日期 | 模块 | 实际发生的事 | 理解证据或未解决问题 | 下一步 |
| --- | --- | --- | --- | --- |
| {local_date} | — | 已建立学习目录与路线 | 尚未开始学习，不计为掌握 | 自学 {first['id']} |
"""


def initialize(root: Path, spec_path: Path, preface_path: Path, local_date: str) -> dict:
    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", local_date):
        raise ValueError("--date must use YYYY-MM-DD in the user's local timezone")
    date.fromisoformat(local_date)
    if root.exists() or root.is_symlink():
        raise ValueError(f"Refusing to overwrite an existing course: {root.absolute()}")
    spec = json.loads(spec_path.read_text(encoding="utf-8-sig"))
    preface = preface_path.read_text(encoding="utf-8-sig")
    title, chapters = validate_plan(spec, preface)
    root = root.resolve()
    course_id = str(uuid4())
    progress = progress_document(title, chapters, local_date, course_id=course_id, course_root=root)
    root.parent.mkdir(parents=True, exist_ok=True)
    intended_parent = root.parent.resolve()
    staging = Path(tempfile.mkdtemp(prefix=".learning-init-", dir=intended_parent)).resolve()
    try:
        for chapter in chapters:
            (staging / chapter["directory"]).mkdir(exist_ok=False)
        for filename, content in ((ROOT_FILES[0], preface), (ROOT_FILES[1], progress)):
            with (staging / filename).open("x", encoding="utf-8", newline="\n") as handle:
                handle.write(content.rstrip() + "\n")
        if not all(not any((staging / chapter["directory"]).iterdir()) for chapter in chapters):
            raise ValueError("A chapter directory unexpectedly contains files; inspect the course")
        # Check both resolved paths before moving the generated directory.
        if staging.parent != intended_parent or root.parent.resolve() != intended_parent:
            raise ValueError("Staging and destination must stay in the intended parent directory")
        if root.exists() or root.is_symlink():
            raise ValueError(f"Destination appeared during initialization; refusing to overwrite: {root}")
        staging.rename(root)
    finally:
        if staging.exists() or staging.is_symlink():
            # Never recursively delete an unchecked or redirected path.
            if staging.is_symlink() or staging.resolve().parent != intended_parent or not staging.name.startswith(".learning-init-"):
                raise ValueError(f"Unsafe staging cleanup path: {staging}")
            shutil.rmtree(staging)
    return {
        "root": str(root),
        "course_id": course_id,
        "root_documents": list(ROOT_FILES),
        "empty_chapters": len(chapters),
        "planned_modules": sum(len(chapter["modules"]) for chapter in chapters),
        "learning_started": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True, help="New course directory; must not exist")
    parser.add_argument("--spec", type=Path, required=True, help="JSON plan with title, chapters and modules")
    parser.add_argument("--preface", type=Path, required=True, help="Finished researched preface Markdown")
    parser.add_argument("--date", required=True, help="User-local date, YYYY-MM-DD")
    args = parser.parse_args()
    try:
        result = initialize(args.root, args.spec, args.preface, args.date)
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
