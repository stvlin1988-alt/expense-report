"""金額解析：負數合法（無單據建帳、會計沖銷可能是負的），0 一律不合法。"""
from decimal import Decimal, InvalidOperation


def parse_amount(raw):
    """回 (Decimal|None, error_code|None)。error_code: amount_zero / amount_invalid。
    raw 為 None 代表「沒帶這個欄位／清空」，回 (None, None)，由呼叫端決定要不要擋。"""
    if raw is None:
        return None, None
    try:
        val = Decimal(str(raw))
    except (InvalidOperation, ValueError):
        return None, "amount_invalid"
    if not val.is_finite():          # 擋 NaN / Infinity / -Infinity：jsonify 會吐出裸的
        return None, "amount_invalid"  # Infinity/NaN token，瀏覽器 JSON.parse 嚴格模式直接丟例外
    if abs(val) >= Decimal("10000000000"):   # Numeric(12,2) → 最多 10 位整數
        return None, "amount_invalid"
    if val == 0:
        return None, "amount_zero"
    return val, None
