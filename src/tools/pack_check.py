"""范畴包工具引用自检（FX-18）—— 架构 §4「selfcheck 双校验」之二：
pack 引用 ⊆ 注册表 ＋ 引用启用态校验。

是什么：
    范畴包 configs/<category>/pack.yaml 可声明 ``tools:`` 键（本仓库现
    有 motion/speech/_template 三个包均未声明——motion 走「无引用通过」
    态）。本模块校验声明与工具注册表（src/tools/registry.py）的一致性，
    是 §4「新工具接入五步」第 4 步（selfcheck 绿）的注册表侧数据源；
    范畴包自身六件套的自检在 src/category_pack.run_selfcheck，互不替代。

引用声明格式（pack.yaml）::

    tools:                      # 可省略；省略/空 = 无工具引用
      - typicality              # 纯字符串：工具 id
      - id: alignment           # 映射形态：id 键取工具 id（预留方法参数扩展位）
        params: {...}           #   （本版只校验 id，params 不校验）

三态口径（§4 五步顺序「声明引用 → selfcheck 绿 → 界面点亮」——selfcheck
绿先于点亮，故未启用是警示不是硬失败）：
  1. 无引用（tools 键缺失/为空）→ ok=True，note「无工具引用，通过」；
  2. 有引用且全部已注册 → ok=True；其中未启用的进 warnings（已注册但
     未 enabled——两步激活第二步待词典管理员完成）；
  3. 有引用且存在未注册 id → ok=False，problems 逐条列明。

接口：
    pack_tool_refs(category)   读 tools 键 → (refs, problems)
    pack_selfcheck(category)   完整三态自检 →
                               {category, refs, ok, problems, warnings, note}

降级：
    pack.yaml 缺失 / 不可解析 → problems 带明确文案（ok=False）；范畴包
    六件套其他文件不在本模块职责内（归 category_pack.run_selfcheck）。

安全规则：yaml 只用 ``safe_load``（§6-6 同 category_pack 口径）。
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional, Tuple

import yaml

from src.tools import registry as _registry

logger = logging.getLogger(__name__)

__all__ = ["pack_tool_refs", "pack_selfcheck"]

# 仓库根目录（src/tools/pack_check.py 的上两级）；测试 monkeypatch 此全局
# 即可指向临时 configs 目录（与 category_pack._REPO_ROOT 同一 seam 口径）。
_REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _pack_path(category: str) -> str:
    """范畴包 pack.yaml 路径（category 不含路径分隔符，防目录逃逸）。"""
    safe = str(category).strip().replace("/", "_").replace("\\", "_")
    return os.path.join(_REPO_ROOT, "configs", safe, "pack.yaml")


def pack_tool_refs(category: str) -> Tuple[List[str], List[str]]:
    """读 pack.yaml 的 ``tools`` 键 → (工具 id 列表, 问题文案列表)。

    - tools 缺失 / 空列表 → ([], [])（无引用态）；
    - 列表项为字符串取原值；为 dict 取 ``id`` 键（非空字符串）；
      其余形态 → problems 记「无法解析的引用」不进 refs；
    - pack.yaml 缺失 / 解析失败 / 顶层非 dict → 问题文案（调用方定 ok）。
    """
    path = _pack_path(category)
    if not os.path.isfile(path):
        return [], [f"范畴包缺失 pack.yaml: {path}"]
    try:
        with open(path, "r", encoding="utf-8") as fh:
            doc = yaml.safe_load(fh)
    except Exception as exc:  # noqa: BLE001 yaml 解析失败
        logger.error("pack_tool_refs 解析 %s 失败: %s", path, exc)
        return [], [f"pack.yaml 解析失败: {exc}"]
    if not isinstance(doc, dict):
        return [], ["pack.yaml 顶层必须是映射（dict）"]
    tools = doc.get("tools")
    if tools is None:
        return [], []
    if not isinstance(tools, list):
        return [], [f"pack.yaml tools 必须是列表，得到 {type(tools).__name__}"]
    refs: List[str] = []
    problems: List[str] = []
    for i, item in enumerate(tools):
        if isinstance(item, str) and item.strip():
            refs.append(item.strip())
        elif isinstance(item, dict) and isinstance(item.get("id"), str) \
                and item["id"].strip():
            refs.append(item["id"].strip())
        else:
            problems.append(f"pack.yaml tools[{i}] 无法解析的引用: {item!r}")
    return refs, problems


def pack_selfcheck(category: str) -> Dict[str, Any]:
    """范畴包工具引用自检（三态，见模块 docstring 口径）。

    Returns:
        {category, refs, ok, problems, warnings, note}：
        ok = 无硬问题（未注册引用 / 声明不可解析）；未启用引用只进
        warnings 不降 ok。
    """
    refs, problems = pack_tool_refs(category)
    result: Dict[str, Any] = {
        "category": category,
        "refs": refs,
        "ok": not problems,
        "problems": problems,
        "warnings": [],
        "note": "",
    }
    if problems:
        result["note"] = "工具引用声明存在问题，见 problems"
        return result
    if not refs:
        result["note"] = "无工具引用，通过"
        return result
    # 引用 ⊆ 注册表（§4 双校验之二）＋ 启用态校验（两步激活第二步）
    enabled_ids = {t.id for t in _registry.list_tools(enabled_only=True)}
    warnings: List[str] = []
    for ref in refs:
        if _registry.get_tool(ref) is None:
            problems.append(f"引用的工具未注册（注册表无 id={ref!r}）")
        elif ref not in enabled_ids:
            warnings.append(
                f"工具 {ref} 已注册但未启用（两步激活：available → enabled，"
                "enabled 待词典管理员点亮）")
    result["problems"] = problems
    result["warnings"] = warnings
    result["ok"] = not problems
    result["note"] = (
        f"引用 {len(refs)} 个工具：全部已注册"
        + ("；存在未启用项，见 warnings" if warnings else "且已启用"))
    return result
