"""Skill 安装/卸载管理。

对应 TypeScript 版本 skills.ts 中的 installSkill / removeManagedSkill。
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Literal


SkillScope = Literal["project", "user"]


def _get_managed_root(scope: SkillScope, cwd: str) -> Path:
    """获取指定 scope 的 skill 管理目录。"""
    if scope == "project":
        return Path(cwd) / ".mini-code" / "skills"
    return Path.home() / ".mini-code" / "skills"


def install_skill(
    cwd: str,
    source_path: str,
    name: str | None = None,
    scope: SkillScope = "user",
) -> tuple[str, str]:
    """安装一个 Skill。

    支持两种源格式:
      - 目录（包含 SKILL.md）→ 复制整个目录
      - 单文件 SKILL.md → 复制到命名目录

    Returns:
        (skill_name, target_path)
    """
    src = Path(source_path).resolve()

    # 确定内容和名称
    if src.is_dir():
        skill_md = src / "SKILL.md"
        if not skill_md.is_file():
            raise FileNotFoundError(f"No SKILL.md found in {src}")
        content = skill_md.read_text(encoding="utf-8")
        inferred_name = src.name
    elif src.name == "SKILL.md" or src.suffix == ".md":
        content = src.read_text(encoding="utf-8")
        inferred_name = src.parent.name
    else:
        skill_md = src / "SKILL.md"
        content = skill_md.read_text(encoding="utf-8")
        inferred_name = src.name

    skill_name = (name or inferred_name).strip()
    if not skill_name:
        raise ValueError("Skill name cannot be empty")

    target_root = _get_managed_root(scope, cwd)
    target_dir = target_root / skill_name
    target_path = target_dir / "SKILL.md"

    target_dir.mkdir(parents=True, exist_ok=True)
    target_path.write_text(content, encoding="utf-8")

    return skill_name, str(target_path)


def remove_skill(
    cwd: str,
    name: str,
    scope: SkillScope = "user",
) -> bool:
    """卸载一个 Skill。

    Returns:
        True 表示成功删除，False 表示 Skill 不存在。
    """
    target_dir = _get_managed_root(scope, cwd) / name

    if not target_dir.exists():
        return False

    shutil.rmtree(target_dir)
    return True
