"""危险命令分类器 — 识别需要额外权限审查的命令模式。

对应 TypeScript 版本 permissions.ts 中的 classifyDangerousCommand。
"""

from __future__ import annotations


def classify_dangerous(command: str, args: list[str]) -> str | None:
    """检查命令是否为危险操作。

    Returns:
        危险原因描述字符串，或 None（表示安全）。
    """
    normalized = [a.strip() for a in args if a.strip()]
    signature = " ".join([command] + normalized)

    # git 危险操作
    if command == "git":
        if "reset" in normalized and "--hard" in normalized:
            return f"git reset --hard can discard local changes ({signature})"
        if "clean" in normalized:
            return f"git clean can delete untracked files ({signature})"
        if "checkout" in normalized and "--" in normalized:
            return f"git checkout -- can overwrite working tree files ({signature})"
        if "restore" in normalized and any(a.startswith("--source") for a in normalized):
            return f"git restore --source can overwrite local files ({signature})"
        if "push" in normalized and ("--force" in normalized or "-f" in normalized):
            return f"git push --force rewrites remote history ({signature})"

    # npm publish
    if command == "npm" and "publish" in normalized:
        return f"npm publish affects a registry outside this machine ({signature})"

    # 任意代码执行
    if command in ("node", "python3", "python", "bun", "bash", "sh"):
        return f"{command} can execute arbitrary local code ({signature})"

    # 文件系统危险操作
    if command == "rm" and ("-rf" in normalized or "-r" in normalized):
        return f"rm -rf can permanently delete files ({signature})"

    if command == "chmod" and "777" in normalized:
        return f"chmod 777 makes files world-writable ({signature})"

    if command == "sudo":
        return f"sudo escalates privileges ({signature})"

    if command == "curl" and any("|" in a for a in normalized):
        return f"curl piped to shell can execute remote code ({signature})"

    return None
