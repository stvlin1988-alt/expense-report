def major_category_id(category_id, cats):
    """回科目大類 id（level 1）。level 2 取 parent，level 1 取自己，None→None。"""
    if category_id is None:
        return None
    c = cats.get(category_id)
    if c is None:
        return None
    if c["level"] == 1:
        return category_id
    return c["parent_id"]


def _bucket(status, effective_period_status):
    """回 'reconciled' 或 'pending'；closed 期不應有 pending，但仍以狀態判定。"""
    return "reconciled" if status == "reconciled" else "pending"


def _empty_cell():
    return {"reconciled": 0.0, "pending": 0.0}


def build_cross_table(expenses, cats, stores, now_utc, period):
    """分店 x 科目大類交叉表。

    結構決策（brief 未完全釘死之處）：
    - rows 依 major_id 由小到大排序，「未分類」（major_id=None）固定排最後——
      cats 傳入的欄位只有 level/parent_id/name，沒有 Category.sort，無法照分類自訂
      排序，退而求其次用 id 這個穩定、確定性的鍵；children（細類）比照同規則。
    - level-1 直接掛帳的單（category 本身就是大類，未落到細類）：只累加進大類自己
      的 total / per_store，「不」生成一個 children 列——因為它不是一個真實存在的
      細類，硬造一個「本類直接」假細類列反而讓使用者以為系統多了一個科目選項。
      大類 total 恆 = 大類直接金額 + 所有 children 加總（因為兩者都寫回同一個
      total 累加器）。
    - children 元素採跟 rows 同一份 shape（major_id/major_name/total/per_store/
      children，children 固定空陣列）——對齊 Interfaces 裡「同結構(細類)」的字面
      約定，即使欄名沿用 major_id/major_name 是給細類自己的 id/name，不是往上指
      回大類。
    - 金額一律有號加總（不 abs()/不 max(0,x)）；amount 為 None 的單直接略過。
    - period 目前只用來取 period.status 傳給 _bucket（該參數未被使用，是 brief
      verbatim 保留的介面），是否 pending 恆 0 是「audited/rejected 單在封月時已被
      _do_close 挪到下一期」這個既有不變量的自然結果，不需要在這裡另外特判。
    """
    store_order = [s["id"] for s in stores]
    store_totals = {sid: _empty_cell() for sid in store_order}
    grand_total = _empty_cell()
    majors = {}

    def _get_major(mid):
        if mid not in majors:
            name = "未分類" if mid is None else cats.get(mid, {}).get("name", "未分類")
            majors[mid] = {
                "major_id": mid,
                "major_name": name,
                "total": _empty_cell(),
                "per_store": {sid: _empty_cell() for sid in store_order},
                "children": {},
            }
        return majors[mid]

    def _get_child(major, minor_id, minor_name):
        children = major["children"]
        if minor_id not in children:
            children[minor_id] = {
                "major_id": minor_id,
                "major_name": minor_name,
                "total": _empty_cell(),
                "per_store": {sid: _empty_cell() for sid in store_order},
                "children": [],
            }
        return children[minor_id]

    for e in expenses:
        if e.amount is None:
            continue
        amt = float(e.amount)
        bucket = _bucket(e.status, period.status if period is not None else None)
        mid = major_category_id(e.category_id, cats)
        major = _get_major(mid)

        major["total"][bucket] += amt
        cell = major["per_store"].setdefault(e.store_id, _empty_cell())
        cell[bucket] += amt

        cat = cats.get(e.category_id) if e.category_id is not None else None
        if cat is not None and cat.get("level") == 2:
            child = _get_child(major, e.category_id, cat.get("name", ""))
            child["total"][bucket] += amt
            ccell = child["per_store"].setdefault(e.store_id, _empty_cell())
            ccell[bucket] += amt

        store_totals.setdefault(e.store_id, _empty_cell())[bucket] += amt
        grand_total[bucket] += amt

    def _sort_key(mid):
        return (mid is None, mid)

    rows = []
    for mid in sorted(majors, key=_sort_key):
        major = majors[mid]
        major["children"] = [
            major["children"][minor_id]
            for minor_id in sorted(major["children"], key=_sort_key)
        ]
        rows.append(major)

    return {
        "stores": stores,
        "rows": rows,
        "store_totals": store_totals,
        "grand_total": grand_total,
    }
