#!/usr/bin/env python3
"""义位层 LLM 初筛（编码手册流程第 2 步）——按固定 prompt 生成候选标签草稿。

流程（义项判定标准修改稿 · 标注实施流程）：
  输入：SenseID、词条、义位编号、OALD 释义、例句 1-2 条
  输出：准入标签（Y/拓展/N）+ 意象图式候选（四选一）+ 理由 + 存疑标记
  定位：AI 输出仅为候选参考，全部最终标签由研究者人工复核确认。

用法：
    python3 scripts/llm_sense_screening.py --verbs limp charge   # 试跑指定词
    python3 scripts/llm_sense_screening.py --all                 # 全量 352 条
    python3 scripts/llm_sense_screening.py --resume              # 跳过已出草稿的
输出：data/corpus/llm_screening/<verb>.json（逐词缓存，可断点续跑）
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# 手动加载 .env（dotenv 裸脚本 frame 问题）
for _line in open(ROOT / ".env", encoding="utf-8"):
    if "=" in _line and not _line.startswith("#"):
        _k, _v = _line.strip().split("=", 1)
        os.environ.setdefault(_k, _v)

from openpyxl import load_workbook  # noqa: E402

from src.llm_api import get_zhipuai_client, LLM_MODEL  # noqa: E402

OUT_DIR = ROOT / "data" / "corpus" / "llm_screening"
SRC_XLSX = ROOT / "docs" / "域系初判表v0.2.xlsx"

# 编码手册「给大模型使用的精简 Prompt」（原文，固定不改动）
PROMPT = """任务：英语自移移动动词义位标注。标注单元为【单个义位】，不要混淆同一单词的不同义位。严格执行下面全部规则，输出候选标签，仅作为研究者参考，不代表最终判定。

【规则1 Talmy移动事件准入】
义位能够激活实体源点-路径-终点三维物理空间位移框架 → Y；
义位为抽象隐喻用法，不存在实体物理运动体 → 拓展；
没有实体物理位移（静态方位义 / 纯状态变化义） → N；
N类不再输出后续图式与对齐标注。

【规则2 意象图式标注（仅Y、拓展输出候选）】
只能从下面4种中选择其一：源点脱离图式、终点抵达图式、方式伴随图式、互动位移图式。依据动词义位本身编码语义重心，不要把句子状语信息当作动词自带语义。

【规则3 原型层级】
Y = 原型物理位移义；拓展 = 隐喻引申边缘义。原型义用于范畴与释义模板，隐喻义仅用于隐喻对比。

【规则4 英汉图式对齐判定（仅Y完整输出；拓展简要输出）】
对比英语义位图式和汉语表达同一事件场景常规图式，不是字面单词对照。
完全对齐：图式与移动事件核心要素全部匹配；
部分对齐：图式大体一致，但存在语义要素缺失或汉语句法强制增补成分；
零对齐：汉语不使用空间位移图式表达该概念。

输入：
词条：{verb}
义位编号：S{num}
OALD释义：{definition}
例句1：{ex1}
例句2：{ex2}

输出纪律：不要展示思考过程、不要复述规则、全程使用中文，直接输出且仅输出下面五个字段（参照示例的格式与详略）。

【输出示例】（仅示意格式，内容与本题无关）
准入标签：Y
理由：运动体为实体（人），发生三维物理空间位移，激活源点-路径-终点框架。
意象图式候选标签：方式伴随图式
英汉对齐候选等级：部分对齐
备注存疑点：无"""


def load_senses():
    """从域系初判表 v0.2 读 352 义位（含释义与例句）。"""
    wb = load_workbook(SRC_XLSX, read_only=True)
    ws = wb["02 逐义位明细"]
    senses = []
    for r in ws.iter_rows(min_row=5, values_only=True):
        if r[1] is None or r[1] == "合计":
            continue
        exs = [e for e in str(r[4] or "").split("\n") if e.strip()]
        senses.append({
            "word": str(r[2]),
            "sense_num": int(str(r[1]).rsplit("-S", 1)[1]),
            "sense_id": str(r[1]),
            "definition": str(r[3] or ""),
            "examples": exs[:2],
        })
    wb.close()
    return senses


def parse_reply(text: str) -> dict:
    """从模型回复中提取结构化字段（宽容解析，失败字段置 None）。"""
    out = {"准入标签": None, "理由": None, "意象图式候选标签": None,
           "英汉对齐候选等级": None, "备注存疑点": None, "raw": text}
    import re
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    for key in out:
        if key == "raw":
            continue
        for i, line in enumerate(lines):
            if line.startswith(key):
                rest = line[len(key):].lstrip("【】：: 　")
                # 剥掉模型复述的选项串（如 "Y/拓展/N】"）
                rest = re.sub(r"^(Y/拓展/N|Y|拓展|N)[】：:]*\s*", "", rest, count=1) if rest.startswith("Y") else rest
                if rest:
                    out[key] = rest
                    break
                if i + 1 < len(lines) and not lines[i + 1].startswith(("准入", "理由", "意象", "英汉", "备注")):
                    out[key] = lines[i + 1]
                    break
    # 准入标签兜底：中英锚点都试（模型可能写 admission: Y / 准入标签：Y / → Y）
    if out["准入标签"] is None:
        for pat in (r"准入标签[：:][^\n]*?\b(Y|拓展|N)\b",
                    r"admission[：:]\s*(Y|N|拓展)",
                    r"准入[^\n]*?【?\s*(Y|拓展|N)\s*】?\s*[:：]",
                    r"→\s*(Y|拓展|N)\b",
                    r"[Ss]o\s+(?:it\s+is\s+)?(Y|N|拓展)\b",
                    r"\bis\s+(Y|N|拓展)\b"):
            m = re.search(pat, text, re.M)
            if m:
                out["准入标签"] = m.group(1)
                break
    # 图式兜底：全文找四图式名
    if out["意象图式候选标签"] is None:
        for name in ("源点脱离图式", "终点抵达图式", "方式伴随图式", "互动位移图式"):
            if name in text:
                out["意象图式候选标签"] = name
                break
    # 对齐兜底
    if out["英汉对齐候选等级"] is None:
        for name in ("完全对齐", "部分对齐", "零对齐"):
            if name in text:
                out["英汉对齐候选等级"] = name
                break
    # 准入终极兜底：图式与对齐都判出来了（说明模型按 Y/拓展 流程走了），
    # 但准入标签本身没提取到——按"有图式输出"推 Y（N 类不输出图式，规则 2）
    if out["准入标签"] is None and out["意象图式候选标签"] is not None:
        out["准入标签"] = "Y"
    # 理由兜底：抓含"运动体/位移/物理"的中文句
    if out["理由"] is None or out["理由"] in ("...", "…", "一句话"):
        m = re.search(r"[^\n。]*（?运动体[^\n。]*。", text)
        if m:
            out["理由"] = m.group(0)[:120]
    return out


def screen_verb(client, verb, senses, model):
    """逐义位调用，返回 {sense_id: 解析结果}。"""
    results, errors = {}, []
    for s in senses:
        ex1 = s["examples"][0] if s["examples"] else "（无例句）"
        ex2 = s["examples"][1] if len(s["examples"]) > 1 else "（无）"
        prompt = PROMPT.format(
            verb=s["word"], num=s["sense_num"],
            definition=s["definition"] or "（无释义）", ex1=ex1, ex2=ex2,
        )
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": "你是词典学编码助手。严格按用户给定的输出格式作答，直接输出五个字段，不展示思考过程。"},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,
                max_tokens=2000,
            )
            text = resp.choices[0].message.content.strip()
            parsed = parse_reply(text)
            parsed["sense_id"] = s["sense_id"]
            parsed["definition"] = s["definition"]
            results[s["sense_id"]] = parsed
            time.sleep(0.5)  # 温和限速
        except Exception as e:
            errors.append({"sense_id": s["sense_id"], "error": str(e)})
            time.sleep(2)
    return results, errors


def main() -> int:
    parser = argparse.ArgumentParser(description="义位层 LLM 初筛")
    parser.add_argument("--verbs", nargs="*", help="指定词目（试跑）")
    parser.add_argument("--all", action="store_true", help="全部 352 义位")
    parser.add_argument("--resume", action="store_true", help="跳过已有草稿的词")
    args = parser.parse_args()

    if not args.verbs and not args.all:
        args.verbs = ["limp", "charge"]  # 默认试跑

    client = get_zhipuai_client()
    if not client:
        print("LLM 客户端不可用（检查 ZHIPUAI_API_KEY / ZHIPUAI_BASE_URL）")
        return 1
    print(f"模型: {LLM_MODEL} | 客户端就绪")

    all_senses = load_senses()
    by_verb = {}
    for s in all_senses:
        by_verb.setdefault(s["word"], []).append(s)

    verbs = args.verbs if args.verbs else sorted(by_verb)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    done, skipped, failed = 0, 0, []
    for v in verbs:
        out_file = OUT_DIR / f"{v}.json"
        if args.resume and out_file.exists():
            skipped += 1
            continue
        senses = by_verb.get(v)
        if not senses:
            print(f"⚠️ {v} 不在 352 义位清单中，跳过")
            continue
        print(f"→ {v}（{len(senses)} 义位）…")
        results, errors = screen_verb(client, v, senses, LLM_MODEL)
        payload = {
            "verb": v, "model": LLM_MODEL, "screened_at": time.strftime("%Y-%m-%d %H:%M"),
            "n_senses": len(senses), "results": results, "errors": errors,
        }
        out_file.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
        if results:
            done += 1
        if errors:
            failed.append(v)
            print(f"   ⚠️ {len(errors)} 条失败")

    print(f"\n完成 {done} 词（跳过 {skipped}）" + (f"，失败词：{failed}" if failed else ""))
    print(f"草稿目录: {OUT_DIR}")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
