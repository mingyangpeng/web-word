#!/usr/bin/env python3
"""把《现汉7》配图（data/ModernChineseDict/images/）扫描入媒体资产域。

数据链：data/ModernChineseDict/images/*.jpeg|png（175 个文件）
   → 本脚本：文件名→现汉词条映射 → src/media_db.register_asset
     （sha256 登记 + license 必填）→ src/media_db.bind_asset（词目锚，
     anchor_type='word'，anchor_id=zh_dict_entries.id，purpose='illustration'，
     status='候选'）→ 批次 2 媒体管理页审定（候选→审定→发布）。

图片文件名规律（2024-11 现状盘点，175 个文件 = 169 jpeg + 6 png）：
  * Discourse 论坛附件： <40位hex>_<n>_<WxH>.jpeg（如 01391ffd…_2_690x417.jpeg）；
  * 纯哈希命名：        <40位hex>.jpeg / .png；
  * GitHub 附件：       <epoch>-<uuid>.jpeg（如 156132656-20d702e9-…jpeg）；
  * 时间戳截图：        202202281906621.jpeg、2022-03-02-14.36.28.png 等。
  **文件名全部不携带词目信息**：mdx 文本导出（mdx/dict.mdx.txt）与结构化
  JSON（data/zh_dict_senses.json）中均无 images/ 引用 —— 无法凭文件名
  自动映射词条。因此映射按序尝试三种来源：

  1. --mapping 人工映射 JSON（推荐的正规途径，词典管理员维护）：
       {"<文件名>": "<词目>",                      # 词目字符串（简写形式）
        "<文件名>": {"lemma": "苹果树"},           # 同上，显式形式
        "<文件名>": {"entry_id": 123}}             # 直接指现汉词条 id（精确）
       键可用完整文件名或去扩展名的词干；可选字段 purpose/caption 覆盖默认值；
  2. mdx 文本导出扫描：未来 mdx 若内嵌 images/<文件名> 引用，按词条块
     自动解析映射（当前导出无引用，贡献 0 条）；
  3. 文件名词干 == 现汉词目（zh_dict_entries.lemma 精确命中，如 跑.png）。

  三种来源都映射不上的文件 → 跳过清单（stdout 明细；--report 存 JSON），
  不入库。多音字默认绑 id 最小的读音条目（mdx 首读音=主读音）；需精确
  指定时在映射 JSON 里写 entry_id。

幂等：资产按 sha256 去重（register_asset 同内容只一行）、绑定按
UNIQUE(asset_id, anchor_type, anchor_id, purpose) 去重（bind_asset 幂等
命中返回 True）——重复运行不产生重复行、不重复计数。

用法（--dry-run 默认，--apply 才写库）：
    python3 scripts/load_media_xianhan.py                        # 预演
    python3 scripts/load_media_xianhan.py --mapping m.json       # 预演+映射文件
    python3 scripts/load_media_xianhan.py --apply                # 真入库
    python3 scripts/load_media_xianhan.py --apply --report skips.json
"""

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import media_db  # noqa: E402

IMAGES_DIR = ROOT / "data" / "ModernChineseDict" / "images"
MDX_TXT_PATH = ROOT / "data" / "ModernChineseDict" / "mdx" / "dict.mdx.txt"

# 图片扩展名（kind 一律 'image'；audio/video 资产走别的数据链）
IMAGE_SUFFIXES = {".jpeg", ".jpg", ".png", ".gif"}

# 现汉社区资源的许可口径（源自 data/ModernChineseDict/README.md：仅供学习交流，
# 禁止商用）。可 --license 覆盖；register_asset 强制 license 非空。
DEFAULT_LICENSE = "《现汉7》社区mdx资源（freemdict，仅供学习交流，禁止商用）"
DEFAULT_SOURCE = "ModernChineseDict/images"

# mdx 文本里的图片文件名引用（如 images/xxx.jpeg 或裸文件名）
_IMG_NAME_RE = re.compile(r"[\w.\-]+\.(?:jpeg|jpg|png|gif)", re.IGNORECASE)


# ============================================
# 映射来源 1：人工映射 JSON
# ============================================
def load_curated_mapping(path: Path) -> tuple:
    """读人工映射 JSON。

    Returns:
        (mapping, errors)：mapping = {小写键: {lemma/entry_id/purpose/caption}}
        （键 = 完整文件名或词干，大小写不敏感；值 = 词目字符串（简写）或
        dict 显式形式）；errors = 规整时的坏值清单。
    """
    mapping: dict = {}
    errors: list = []
    if not path.exists():
        errors.append(f"映射文件不存在: {path}")
        return mapping, errors
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        errors.append(f"映射文件解析失败: {e}")
        return mapping, errors
    if not isinstance(raw, dict):
        errors.append("映射文件顶层须为 JSON object")
        return mapping, errors
    for key, value in raw.items():
        spec: dict = {}
        if isinstance(value, str):
            spec["lemma"] = value.strip()
        elif isinstance(value, dict):
            lemma = value.get("lemma")
            entry_id = value.get("entry_id", value.get("word_id"))
            if isinstance(lemma, str) and lemma.strip():
                spec["lemma"] = lemma.strip()
            if isinstance(entry_id, int) and not isinstance(entry_id, bool) \
                    and entry_id > 0:
                spec["entry_id"] = entry_id
            purpose = value.get("purpose")
            if isinstance(purpose, str) and purpose in media_db.PURPOSES:
                spec["purpose"] = purpose
            caption = value.get("caption")
            if isinstance(caption, str):
                spec["caption"] = caption[: media_db.MAX_CAPTION_LEN]
            if "lemma" not in spec and "entry_id" not in spec:
                errors.append(f"映射值缺 lemma/entry_id: {key!r}")
                continue
        else:
            errors.append(f"不支持的映射值类型: {key!r}")
            continue
        name_lower = str(key).strip().lower()
        mapping[name_lower] = spec
        mapping.setdefault(Path(name_lower).stem, spec)  # 词干键兜底（完整名优先）
    return mapping, errors


# ============================================
# 映射来源 2：mdx 文本导出扫描（未来内嵌图片时自动接上）
# ============================================
def build_mdx_image_index(mdx_txt_path: Path) -> dict:
    """扫 mdx 文本导出：{图片文件名(小写): 词条头词}。

    mdx txt 块结构为「头词行\\n内容行\\n</>」，对每个块在内容里找图片
    文件名引用。当前导出无引用（返回 {}），未来 mdx 内嵌图片后本函数
    自动生效，脚本无需改。
    """
    index: dict = {}
    if not mdx_txt_path.exists():
        return index
    try:
        text = mdx_txt_path.read_text(encoding="utf-8")
    except OSError as e:
        print(f"[警告] mdx 文本读取失败（跳过该映射来源）: {e}")
        return index
    for block in text.split("\n</>\n"):
        lines = block.strip("\n").split("\n")
        if len(lines) < 2:
            continue
        headword = lines[0].strip()
        content = "\n".join(lines[1:])
        for m in _IMG_NAME_RE.finditer(content):
            index.setdefault(m.group(0).lower(), headword)
    return index


# ============================================
# 扫描与映射
# ============================================
def scan_image_files(images_dir: Path) -> list:
    """图片文件清单（按文件名排序，稳定输出；仅图片扩展名）。"""
    if not images_dir.is_dir():
        return []
    return sorted(
        p for p in images_dir.iterdir()
        if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES
    )


def _rel_path(path: Path) -> str:
    """仓库相对路径优先（入库 file_path 可移植）；库外文件用绝对路径。"""
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path.resolve())


def lookup_lemma_ids(lemmas) -> dict:
    """现汉词条表查词目 → {lemma: 首个词条 id}（多音字取 id 最小主读音）。

    查库失败返回 {}（调用方结合 zh_dict_entries_reachable 区分「无命中」
    与「查库失败」）。
    """
    if not lemmas:
        return {}
    rows = {}
    try:
        from src.mysql_db import get_db_cursor
        lemma_list = sorted(lemmas)
        placeholders = ",".join(["%s"] * len(lemma_list))
        with get_db_cursor() as cursor:
            cursor.execute(
                f"""SELECT lemma, MIN(id) AS first_id FROM zh_dict_entries
                    WHERE lemma IN ({placeholders})
                    GROUP BY lemma""",
                tuple(lemma_list),
            )
            for r in cursor.fetchall():
                rows[str(r["lemma"])] = int(r["first_id"])
        return rows
    except Exception as e:  # noqa: BLE001
        print(f"[警告] 查现汉词条表失败: {e}")
        return rows  # 空或部分命中


def zh_dict_entries_reachable() -> bool:
    """现汉词条表是否可查（区分「无命中」与「查库失败」）。"""
    try:
        from src.mysql_db import get_db_cursor
        with get_db_cursor() as cursor:
            cursor.execute("SELECT 1 FROM zh_dict_entries LIMIT 1")
            cursor.fetchall()
        return True
    except Exception:  # noqa: BLE001
        return False


def _spec_to_row(path: Path, spec: dict, map_source: str) -> dict:
    """映射 spec → 计划行（默认词目锚 + illustration + 候选）。"""
    return {
        "file": _rel_path(path),
        "abs_path": str(path.resolve()),
        "map_source": map_source,
        "entry_id": spec.get("entry_id"),
        "lemma": spec.get("lemma"),
        "purpose": spec.get("purpose", media_db.PURPOSE_ILLUSTRATION),
        "caption": spec.get("caption", ""),
        "sort_order": 0,
        "status": media_db.STATUS_CANDIDATE,
    }


def resolve_plan(image_files: list, mapping: dict, mdx_index: dict) -> tuple:
    """逐文件解析映射，产出计划行与跳过清单。

    Returns:
        (plan_rows, skipped)
        plan_rows: [{file, abs_path, map_source, entry_id, lemma, purpose,
                     caption, sort_order, status}]（entry_id 已全部解析）
        skipped:   [{file, reason}]
    """
    plan_rows: list = []
    skipped: list = []
    lemmas_for_db: set = set()

    # 第一遍：文件级解析（按映射文件 → mdx 引用 → 词干查库的优先序）
    stem_pending: list = []
    for path in image_files:
        name_lower = path.name.lower()
        stem_lower = path.stem.lower()
        spec = mapping.get(name_lower) or mapping.get(stem_lower)
        if spec is not None:
            row = _spec_to_row(path, spec, "映射文件")
            if row["lemma"]:
                lemmas_for_db.add(row["lemma"])
            plan_rows.append(row)
            continue
        spec = {"lemma": mdx_index[name_lower]} if name_lower in mdx_index else \
            ({"lemma": mdx_index[stem_lower]} if stem_lower in mdx_index else None)
        if spec is not None:
            row = _spec_to_row(path, spec, "mdx文本引用")
            lemmas_for_db.add(row["lemma"])
            plan_rows.append(row)
            continue
        stem_pending.append((path, stem_lower))

    # 来源 3（词干=词目）需要查库；库不可用统一跳过并说明
    if stem_pending:
        if zh_dict_entries_reachable():
            stem_hits = lookup_lemma_ids({s for _, s in stem_pending})
            for path, stem in stem_pending:
                if stem in stem_hits:
                    row = _spec_to_row(
                        path, {"entry_id": stem_hits[stem]}, "文件名词干=词目")
                    row["lemma"] = stem
                    plan_rows.append(row)
                else:
                    skipped.append({
                        "file": _rel_path(path),
                        "reason": "文件名无词条线索（哈希/附件命名），且未出现在"
                                  "映射文件与 mdx 文本中，词干也不等于任何现汉词目",
                    })
        else:
            for path, _ in stem_pending:
                skipped.append({
                    "file": _rel_path(path),
                    "reason": "查现汉词条表失败（数据库不可用），无法按词干映射",
                })

    # 第二遍：lemma → entry_id（映射文件/mdx 来源的词目串查词条 id；
    # 多音字取 id 最小的主读音条目）
    unresolved = lookup_lemma_ids(lemmas_for_db)
    final_rows = []
    for row in plan_rows:
        if row["entry_id"] is None:
            entry_id = unresolved.get(row["lemma"]) if row["lemma"] else None
            if not entry_id:
                skipped.append({
                    "file": row["file"],
                    "reason": f"词目 {row['lemma']!r} 不在现汉词条表"
                              "（zh_dict_entries），无法定词目锚",
                })
                continue
            row["entry_id"] = entry_id
        final_rows.append(row)
    return final_rows, skipped


# ============================================
# 幂等预估（已有资产 / 已有绑定）
# ============================================
def fetch_existing_state() -> tuple:
    """(sha256 → asset_id 映射, 已有词目绑定键集合) —— 幂等预估（只读）。

    media 两表尚未建时返回空口径（预演不触发 ensure/DDL，也没有
    1146 错误日志噪音）。
    """
    sha_map: dict = {}
    binding_keys: set = set()
    from src.mysql_db import get_db_cursor
    with get_db_cursor() as cursor:
        cursor.execute(
            """SELECT TABLE_NAME FROM information_schema.TABLES
               WHERE TABLE_SCHEMA = DATABASE()
                 AND TABLE_NAME IN ('media_assets', 'media_bindings')"""
        )
        present = {r["TABLE_NAME"] for r in cursor.fetchall()}
        if "media_assets" in present:
            cursor.execute("SELECT id, sha256 FROM media_assets")
            for r in cursor.fetchall():
                sha_map[str(r["sha256"])] = int(r["id"])
        if "media_bindings" in present:
            cursor.execute(
                "SELECT asset_id, anchor_type, anchor_id, purpose FROM media_bindings "
                "WHERE anchor_type = 'word'"
            )
            for r in cursor.fetchall():
                binding_keys.add((
                    int(r["asset_id"]), str(r["anchor_type"]),
                    int(r["anchor_id"]), str(r["purpose"]),
                ))
    return sha_map, binding_keys


def sha256_of_file(path: str) -> str:
    """流式计算文件 sha256（与 media_db.register_asset 同口径）。"""
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


# ============================================
# 主流程
# ============================================
def main() -> int:
    parser = argparse.ArgumentParser(
        description="扫描《现汉7》配图入媒体资产域（--dry-run 默认，--apply 写库）",
    )
    parser.add_argument("--apply", action="store_true",
                        help="写库（缺省只预演，不写任何数据）")
    parser.add_argument("--dry-run", action="store_true",
                        help="显式预演（默认即预演，此参数仅为可读性）")
    parser.add_argument("--mapping", type=Path, default=None,
                        help="人工映射 JSON（文件名→词目/entry_id）")
    parser.add_argument("--report", type=Path, default=None,
                        help="把跳过清单写为 JSON 文件")
    parser.add_argument("--license", default=DEFAULT_LICENSE,
                        help="资产许可（必填非空，缺省为社区资源口径，≤120 字符）")
    parser.add_argument("--source", default=DEFAULT_SOURCE,
                        help="来源说明（≤80 字符）")
    args = parser.parse_args()

    if not args.license.strip():
        print("license 不得为空（许可必填纪律）。")
        return 1
    if len(args.license.strip()) > media_db.MAX_LICENSE_LEN:
        print(f"license 超长（>{media_db.MAX_LICENSE_LEN} 字符）。")
        return 1

    image_files = scan_image_files(IMAGES_DIR)
    if not image_files:
        print(f"图片目录不存在或为空: {IMAGES_DIR}")
        return 1
    print(f"扫描到 {len(image_files)} 个图片文件: {_rel_path(IMAGES_DIR)}/")

    mapping, mapping_errors = ({}, [])
    if args.mapping:
        mapping, mapping_errors = load_curated_mapping(args.mapping)
    else:
        print("未提供 --mapping（建议词典管理员维护映射 JSON，见模块 docstring）。")
    for err in mapping_errors:
        print(f"[映射文件] {err}")

    mdx_index = build_mdx_image_index(MDX_TXT_PATH)
    if mdx_index:
        print(f"mdx 文本引用到 {len(mdx_index)} 个图片文件")

    plan_rows, skipped = resolve_plan(image_files, mapping, mdx_index)
    print(f"\n映射成功 {len(plan_rows)}，跳过 {len(skipped)}")

    # 幂等预估（只读；查库失败视为全量新增）
    try:
        sha_map, binding_keys = fetch_existing_state()
    except Exception as e:  # noqa: BLE001
        print(f"[警告] 查媒体表现状失败（按全量新增预估）: {e}")
        sha_map, binding_keys = {}, set()

    new_assets, new_bindings = 0, 0
    for row in plan_rows:
        try:
            row["sha256"] = sha256_of_file(row["abs_path"])
        except OSError as e:
            skipped.append({"file": row["file"], "reason": f"文件不可读: {e}"})
            row["sha256"] = None
            continue
        existing_asset_id = sha_map.get(row["sha256"])
        row["asset_id"] = existing_asset_id
        if existing_asset_id is None:
            new_assets += 1
            new_bindings += 1  # 新资产的绑定必然是新的
        elif (existing_asset_id, "word", row["entry_id"],
              row["purpose"]) not in binding_keys:
            new_bindings += 1

    print(f"计划登记新资产 {new_assets}，计划新增词目绑定 {new_bindings}"
          f"（幂等：已有资产/绑定不会重复写入）")

    if plan_rows:
        print("\n映射明细（词目锚 anchor_type='word', status='候选'）:")
        for row in plan_rows:
            label = row.get("lemma") or "entry_id 直接指定"
            print(f"  {row['file']}")
            print(f"    → entry_id={row['entry_id']}（{label}，"
                  f"来源 {row['map_source']}） 资产={row.get('asset_id') or '新'}")
    if skipped:
        print(f"\n跳过清单 {len(skipped)} 条:")
        for item in skipped:
            print(f"  {item['file']}：{item['reason']}")
    if args.report:
        args.report.write_text(
            json.dumps({"skipped": skipped, "mapped": len(plan_rows),
                        "total": len(image_files)},
                       ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"\n跳过清单已写入: {args.report}")

    if not args.apply:
        print("\n已按 --dry-run 预演结束，未写库（--apply 才写库）。")
        return 0

    # ---- 写库（--apply）----
    media_db.ensure_media_tables()
    ok, fail = 0, 0
    for row in plan_rows:
        if not row.get("sha256"):
            continue  # 计划阶段就不可读的文件
        asset_id = media_db.register_asset(
            row["abs_path"], media_db.KIND_IMAGE, args.source, args.license,
        )
        if asset_id == 0:
            fail += 1
            print(f"[失败] 登记资产: {row['file']}")
            continue
        if media_db.bind_asset(
            asset_id, media_db.ANCHOR_WORD, row["entry_id"], row["purpose"],
            caption=row["caption"], sort_order=row["sort_order"],
            status=row["status"],
        ):
            ok += 1  # 含幂等命中（重复运行同文件会命中 UNIQUE）
        else:
            fail += 1
            print(f"[失败] 绑定词目锚: {row['file']} → entry_id={row['entry_id']}")
    print(f"\n--apply 完成：绑定成功 {ok}（含幂等命中），失败 {fail}")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
