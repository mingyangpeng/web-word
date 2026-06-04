"""
.env 文件加载工具

轻量级 dotenv 实现，无外部依赖。

设计要点：
- 仅当环境变量未设置时才从 .env 文件读取（不覆盖已有 env）
- 自动定位项目根目录（向上查找直到含 .env 的目录）
- 忽略空行与 # 开头的注释行
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

_cached_env_path: Optional[Path] = None


def find_env_file(start: Optional[Path] = None, max_depth: int = 5) -> Optional[Path]:
    """
    从指定目录开始向上查找 .env 文件。

    Args:
        start: 起始查找目录，默认为当前文件所在目录
        max_depth: 向上查找的最大层级

    Returns:
        找到的 .env Path，未找到返回 None
    """
    global _cached_env_path
    if _cached_env_path is not None and _cached_env_path.exists():
        return _cached_env_path

    current = (start or Path(__file__).resolve().parent).resolve()
    for _ in range(max_depth):
        candidate = current / ".env"
        if candidate.exists():
            _cached_env_path = candidate
            return candidate
        if current.parent == current:
            break
        current = current.parent
    return None


def load_dotenv(env_path: Optional[Path] = None, override: bool = False) -> bool:
    """
    将 .env 文件中的键值对加载到 os.environ。

    Args:
        env_path: 显式指定 .env 路径；为 None 时自动查找
        override: True 时覆盖已存在的环境变量（默认 False，保留系统 env）

    Returns:
        True 表示成功加载，False 表示未找到或读取失败
    """
    path = env_path or find_env_file()
    if path is None:
        return False

    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False

    for line in content.splitlines():
        line = line.strip()
        # 跳过空行 / 注释 / 不含 = 的行
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()

        # 去除可选引号包裹
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]

        if not key:
            continue

        if override or key not in os.environ:
            os.environ[key] = value

    return True
