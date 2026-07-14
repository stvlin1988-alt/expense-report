"""金額解析：負數合法（無單據建帳、會計沖銷可能是負的），0 一律不合法。"""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


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
    try:
        # 必須先 round 到分再檢查範圍：DB 是 Numeric(12,2)，會先四捨五入再存。
        # 9999999999.999 的 abs < 10^10 看似合法，round 完卻是 10000000000.00（13 位）
        # → Postgres numeric field overflow → 500（SQLite 則默默存成 13 位，兩邊行為還不一致）。
        val = val.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except InvalidOperation:         # 位數超出 Decimal context 精度（如 1e300）
        return None, "amount_invalid"
    if abs(val) >= Decimal("10000000000"):   # Numeric(12,2) → 最多 10 位整數
        return None, "amount_invalid"
    if val == 0:                     # 含 0.001 這種 round 完等於 0 的值
        return None, "amount_zero"
    return val, None
