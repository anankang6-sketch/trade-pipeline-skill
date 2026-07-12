"""
models/amounts.py — 统一的金额计算规则（PI / CI 共享单一来源）

背景：PI 与 CI 此前各自内联金额逻辑，PI 漏掉 CNY/MPCS 分支导致
金额被算成 quantity * unit_price（应为 quantity / 1000 * unit_price），
放大 1000 倍。本模块把"按计价方式选公式"的判断收敛到一处，PI / CI
都调用，保证两份单据金额永远一致。

四条金额规则：
  - per-mille (CNY/MPCS): amount = quantity / 1000 * unit_price
  - per-ton   (USD/TON):  amount = weight_kg / 1000 * unit_price
  - per-sqm   (USD/SQM):  amount = quantity(㎡) * unit_price   ← 落石防护网等行业
  - flat      (其他):     amount = quantity * unit_price

两种使用形态（同源、同规则）：
  - compute_amount(): 返回 Python 数值（用于累计、大写金额）
  - amount_formula(): 返回 Excel 公式字符串（写入单元格，用户可见计算过程）
"""
from enum import Enum


class PricingMode(Enum):
    """计价方式枚举。判断只在 from_price_unit() 一处，避免各 writer 重复字符串匹配。"""
    PER_MILLE = "per_mille"   # 千件计价：CNY/MPCS
    PER_TON = "per_ton"       # 吨计价：USD/TON
    PER_SQM = "per_sqm"       # 按平方米计价：USD/SQM（落石防护网等行业）
    FLAT = "flat"             # 普通：单价 × 数量

    @classmethod
    def from_price_unit(cls, price_unit: str | None) -> "PricingMode":
        """从 price_unit 字符串解析计价方式。

        判断顺序：先识别 SQM（平方米），再 TON / MPCS，最后兜底 FLAT。
        「平方米」语义归一：SQM / M2 / M² / SQUARE 都视为 PER_SQM。
        None / 空 / 未知 → FLAT（最安全的默认：数量 × 单价）。
        """
        norm = (price_unit or "").upper().replace("²", "2") \
                                       .replace("平方米", "SQM").replace("平米", "SQM")
        if "SQM" in norm or "M2" in norm or "SQUARE" in norm:
            return cls.PER_SQM
        if "TON" in norm:
            return cls.PER_TON
        if "MPCS" in norm:
            return cls.PER_MILLE
        return cls.FLAT


def compute_amount(
    price_unit: str | None,
    quantity: float | None,
    weight_kg: float | None,
    unit_price: float | None,
) -> float:
    """按计价方式计算单行金额（Python 数值）。

    任一必需输入缺失（unit_price 为 None，或 per-ton 时 weight_kg 为 None）
    时返回 0.0 —— 与既有 CI writer 累计逻辑一致（未报价行不计入合计）。
    """
    if unit_price is None:
        return 0.0

    mode = PricingMode.from_price_unit(price_unit)

    if mode is PricingMode.PER_TON:
        return (weight_kg or 0.0) / 1000.0 * unit_price
    if mode is PricingMode.PER_MILLE:
        return (quantity or 0.0) / 1000.0 * unit_price
    if mode is PricingMode.PER_SQM:
        # 按平方米计价：quantity 字段已是面积（㎡），直接 × 单价
        return (quantity or 0.0) * unit_price
    return (quantity or 0.0) * unit_price


def amount_formula(
    price_unit: str | None,
    *,
    qty_cell: str,
    weight_cell: str,
    price_cell: str,
) -> str:
    """生成 Excel 金额公式字符串（含前导 '='）。

    列引用由调用方传入（PI / CI 列布局不同），但"哪个公式"由本模块统一决定，
    与 compute_amount() 同源同规则。

    参数:
        qty_cell:    数量单元格引用，如 "L12"
        weight_cell: 重量单元格引用，如 "M12"
        price_cell:  单价单元格引用，如 "N12"
    """
    mode = PricingMode.from_price_unit(price_unit)

    if mode is PricingMode.PER_TON:
        return f"={weight_cell}/1000*{price_cell}"
    if mode is PricingMode.PER_MILLE:
        return f"={qty_cell}/1000*{price_cell}"
    if mode is PricingMode.PER_SQM:
        # 按平方米计价：quantity 已是面积（㎡），直接 × 单价
        return f"={qty_cell}*{price_cell}"
    return f"={qty_cell}*{price_cell}"
