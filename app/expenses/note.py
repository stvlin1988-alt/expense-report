"""備註驗證：trim 後 >200 拒絕，空白/空字串正規化成 NULL。
員工 PATCH、無單據建帳、主管/經理稽核端改備註三處規則一致，抽共用函式避免各自維護一份。"""


def validate_note(raw):
    """回 (note|None, error_code|None)。error_code: note_too_long。
    raw 可能是 None（沒帶這個欄位）或字串；trim 後空字串一律存 None。"""
    note = (raw or "").strip()
    if len(note) > 200:
        return None, "note_too_long"
    return note or None, None
