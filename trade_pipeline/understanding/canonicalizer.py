"""
understanding/canonicalizer.py — RFQ Canonical 字段标准化

标准化处理：
  - quantity 单位统一（pcs / kgs / tons / sqm）
  - 标准号规范化（DIN 933 → DIN 933，去多余空格）
  - description 统一英文格式（中文产品名翻译为英文）
  - group_key 提取（按产品类型 + 规格分组）

行业适配：落石防护网（RockFall Fences）
  - 翻译表与分组逻辑已从紧固件改为防护网术语，
    日后补充配件请改 CN_EN 表与 _extract_group_key。
"""
import re

from .llm_parser import _extract_standard


def canonicalize(rfq: dict) -> dict:
    """
    标准化 RFQ canonical dict 中的字段。

    就地修改 items 列表中的每个 item。
    返回修改后的 rfq。
    """
    for item in rfq.get("items", []):
        _normalize_standard(item)
        _normalize_description(item)
        _normalize_unit(item, rfq.get("format", "standard"))
        _extract_group_key(item)

    return rfq


def _normalize_standard(item: dict) -> None:
    """标准号规范化"""
    std = item.get("standard")
    if not std:
        extracted = _extract_standard(item.get("description", ""))
        if extracted:
            item["standard"] = extracted
        return

    # 规范化：去多余空格，大写
    std = re.sub(r"\s+", " ", std.strip()).upper()
    item["standard"] = std


def _normalize_description(item: dict) -> None:
    """描述规范化：去多余空格，中文产品名翻译为英文"""
    desc = item.get("description", "")
    if not desc:
        desc = item.get("description_raw", "")

    # 去多余空格
    desc = re.sub(r"\s+", " ", desc.strip())

    # 中文产品名 → 英文（落石防护网行业；日后补充配件请在此追加）
    cn_en = [
        ("环形网", "STEEL RING NET"),
        ("环型网", "STEEL RING NET"),
        ("菱形网", "RHOMBIC STEEL WIRE MESH"),
        ("菱形钢丝网", "RHOMBIC STEEL WIRE MESH"),
        ("钢丝网", "STEEL WIRE MESH"),
        ("防护网", "PROTECTION NET"),
    ]
    # 逐条替换所有命中的中文品名，不 break——
    # 修复（P1）：原实现命中第一个词就 break，一行含多个中文品名时
    # （如"六角螺栓配平垫圈"）只翻译第一个，其余中文原样留下，
    # 报价单会中英文夹杂发给客户。
    # 按长度降序排序后替换：长词（内六角螺栓）先于其子串（六角螺栓）命中，
    # 用代码强制顺序，不依赖表的书写顺序。
    for cn, en in sorted(cn_en, key=lambda p: len(p[0]), reverse=True):
        if cn in desc:
            desc = desc.replace(cn, en)

    item["description"] = desc


def _normalize_unit(item: dict, fmt: str) -> None:
    """单位规范化"""
    unit = item.get("unit", "")
    if not unit:
        item["unit"] = "tons" if fmt == "washers_mar" else "pcs"
        return

    unit_lower = unit.lower().strip()
    unit_map = {
        "pcs": "pcs",
        "шт": "pcs",
        "pc": "pcs",
        "pieces": "pcs",
        "kg": "kgs",
        "kgs": "kgs",
        "ton": "tons",
        "tons": "tons",
        "t": "tons",
        "m2": "sqm",
        "sqm": "sqm",
        "m²": "sqm",
        "平米": "sqm",
        "平方米": "sqm",
        "平方": "sqm",
    }
    item["unit"] = unit_map.get(unit_lower, unit_lower)


def _extract_group_key(item: dict) -> None:
    """提取分组键（用于报价单分组标题行）— 落石防护网版

    分组键 = 产品类型 + 规格（网孔尺寸 / 钢丝直径）+ 表面处理。
    例如：
      "STEEL RING NET — Ø300MM — GALVANIZED"
      "RHOMBIC STEEL WIRE MESH — 75x93MM — WIRE Ø8MM"
    """
    desc = item.get("description", "")
    std = item.get("standard", "")

    if not desc and not std:
        item["group_key"] = "__OTHER__"
        return

    desc_upper = desc.upper()

    # ── 产品类型识别 ──
    if "RING NET" in desc_upper or "环形网" in desc or "环型网" in desc:
        ptype = "STEEL RING NET"
    elif ("RHOMBIC" in desc_upper or "菱形网" in desc
          or "WIRE MESH" in desc_upper or "钢丝网" in desc):
        ptype = "RHOMBIC STEEL WIRE MESH"
    # ── 预留：日后补充配件类型（如 BRACKET / ANCHOR 等）──
    # elif "BRACKET" in desc_upper:
    #     ptype = "BRACKET"
    else:
        ptype = ""

    # ── 规格提取：钢丝直径 / 网环直径（Ø8mm / ∅300mm / D8）──
    specs = []
    m_dia = re.search(r"(?:WIRE|RING|∅|Ø|DIA|D)\s*(\d{1,4})\s*MM", desc, re.IGNORECASE)
    if m_dia:
        specs.append(f"Ø{m_dia.group(1)}MM")

    # 网孔尺寸（75x93mm / 100X100 MM）
    m_size = re.search(r"(\d{2,4})\s*[x×X]\s*(\d{2,4})\s*MM", desc, re.IGNORECASE)
    if m_size:
        specs.append(f"{m_size.group(1)}x{m_size.group(2)}MM")

    # ── 表面处理 ──
    mat = ""
    if re.search(r"GALVAN|ZP|镀锌", desc, re.IGNORECASE):
        mat = "GALVANIZED"
    elif re.search(r"STAINLESS|不锈钢|A2|A4", desc, re.IGNORECASE):
        mat = "STAINLESS"

    # ── 组装 group_key ──
    parts = []
    if std:
        parts.append(std)
    if ptype:
        parts.append(ptype)
    parts.extend(specs)
    if mat:
        parts.append(mat)

    item["group_key"] = " — ".join(parts) if parts else "__OTHER__"
