"""Skill 发现引擎 — 多源分层扫描 + 同名去重。

查找顺序（优先级从高到低）:
  1. <cwd>/.mini-code/skills/<name>/SKILL.md  (项目级)
  2. ~/.mini-code/skills/<name>/SKILL.md       (用户级)
  3. <cwd>/.claude/skills/<name>/SKILL.md      (兼容项目级)
  4. ~/.claude/skills/<name>/SKILL.md           (兼容用户级)

同名 Skill 以最高优先级为准。

对应 TypeScript 版本 skills.ts。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from pydantic import BaseModel


class SkillSummary(BaseModel):
    name: str
    description: str
    path: str
    source: str  # "project" | "user" | "compat_project" | "compat_user"


class LoadedSkill(SkillSummary):
    content: str


# ---- 扫描根目录 ----

def _get_skill_roots(cwd: str) -> list[tuple[str, str]]:
    """返回 (root_path, source) 列表，按优先级从高到低。"""
    home = str(Path.home())
    return [
        (str(Path(cwd) / ".mini-code" / "skills"), "project"),
        (str(Path(home) / ".mini-code" / "skills"), "user"),
        (str(Path(cwd) / ".claude" / "skills"), "compat_project"),
        (str(Path(home) / ".claude" / "skills"), "compat_user"),
    ]


# ---- 描述提取 ----

def _extract_description(markdown: str) -> str:
    """从 Markdown 正文中提取第一段有意义的文本作为描述。"""
    normalized = markdown.replace("\r\n", "\n")
    paragraphs = normalized.split("\n\n")

    for block in paragraphs:
        text = block.strip()
        if not text or text.startswith("#"):
            continue
        # 取第一个非空、非标题行
        for line in text.split("\n"):
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                return stripped.replace("`", "")
        # 回退：取整段
        return text.replace("`", "")

    return "No description provided."


# ---- 目录扫描 ----

async def _list_skill_dirs(root: str, source: str) -> list[LoadedSkill]:
    """扫描一个根目录下的所有 Skill 子目录。"""
    root_path = Path(root)
    if not root_path.is_dir():
        return []

    results: list[LoadedSkill] = []
    for entry in sorted(root_path.iterdir()):
        if not entry.is_dir():
            continue
        skill_md = entry / "SKILL.md"
        if not skill_md.is_file():
            continue
        try:
            content = skill_md.read_text(encoding="utf-8")
            results.append(LoadedSkill(
                name=entry.name,
                description=_extract_description(content),
                path=str(skill_md),
                source=source,
                content=content,
            ))
        except Exception:
            pass
    return results


# ---- 发现入口 ----

async def discover_skills(cwd: str) -> list[SkillSummary]:
    """发现所有可用的 Skill，按优先级去重。

    Args:
        cwd: 当前工作目录

    Returns:
        SkillSummary 列表（已去重，按发现顺序排列）
    """
    by_name: dict[str, LoadedSkill] = {}

    for root, source in _get_skill_roots(cwd):
        skills = await _list_skill_dirs(root, source)
        for skill in skills:
            if skill.name not in by_name:
                by_name[skill.name] = skill

    return [
        SkillSummary(
            name=s.name,
            description=s.description,
            path=s.path,
            source=s.source,
        )
        for s in by_name.values()
    ]


# ---- 按需加载 ----

async def load_skill(cwd: str, name: str) -> LoadedSkill | None:
    """按名称加载特定 Skill 的完整内容。

    按优先级从高到低搜索，找到第一个匹配即返回。
    """
    normalized = name.strip()
    if not normalized:
        return None

    for root, source in _get_skill_roots(cwd):
        skill_md = Path(root) / normalized / "SKILL.md"
        try:
            content = skill_md.read_text(encoding="utf-8")
            return LoadedSkill(
                name=normalized,
                description=_extract_description(content),
                path=str(skill_md),
                source=source,
                content=content,
            )
        except FileNotFoundError:
            continue
        except Exception:
            continue

    return None
