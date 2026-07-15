from datetime import date, datetime, timezone
from types import SimpleNamespace

from app.reports.service import build_cross_table, major_category_id


def test_major_category_id_level1_is_self():
    cats = {10: {"level": 1, "parent_id": None}, 20: {"level": 2, "parent_id": 10}}
    assert major_category_id(10, cats) == 10
    assert major_category_id(20, cats) == 10
    assert major_category_id(None, cats) is None


def test_major_category_id_missing_category_is_none():
    cats = {10: {"level": 1, "parent_id": None}}
    assert major_category_id(999, cats) is None


def _exp(store_id, category_id, amount, status):
    """輕量假物件模擬 Expense（build_cross_table 只讀 store_id/category_id/amount/status）。"""
    return SimpleNamespace(store_id=store_id, category_id=category_id,
                            amount=amount, status=status)


def test_build_cross_table_signed_sums_two_stores_two_majors():
    # 大類 100（水電瓦斯），細類 101（水費）在大類 100 之下
    # 大類 200（餐飲），無細類使用（直接掛大類）
    cats = {
        100: {"level": 1, "parent_id": None, "name": "水電瓦斯"},
        101: {"level": 2, "parent_id": 100, "name": "水費"},
        200: {"level": 1, "parent_id": None, "name": "餐飲"},
    }
    stores = [{"id": 1, "name": "A店"}, {"id": 2, "name": "B店"}]
    period = SimpleNamespace(status="open")
    now = datetime(2026, 7, 15, tzinfo=timezone.utc)

    expenses = [
        # A店、水費（細類 101）、reconciled、正數
        _exp(1, 101, 300, "reconciled"),
        # A店、水電瓦斯（大類直接、無細類）、audited（pending）、負數
        _exp(1, 100, -50, "audited"),
        # B店、餐飲（大類 200，無細類）、reconciled、正數
        _exp(2, 200, 120, "reconciled"),
        # B店、餐飲、rejected（pending）、負數
        _exp(2, 200, -20, "rejected"),
        # A店、未分類（category_id=None）、audited（pending）、正數
        _exp(1, None, 10, "audited"),
        # amount=None 應被略過，不計入任何加總
        _exp(1, 100, None, "reconciled"),
    ]

    table = build_cross_table(expenses, cats, stores, now, period)

    assert table["stores"] == stores

    rows_by_major = {r["major_id"]: r for r in table["rows"]}
    assert set(rows_by_major.keys()) == {100, 200, None}

    # 大類 100：直接 -50(pending) + 細類 101 的 300(reconciled) = total reconciled 300, pending -50
    major100 = rows_by_major[100]
    assert major100["major_name"] == "水電瓦斯"
    assert major100["total"] == {"reconciled": 300.0, "pending": -50.0}
    assert major100["per_store"][1] == {"reconciled": 300.0, "pending": -50.0}
    assert major100["per_store"][2] == {"reconciled": 0.0, "pending": 0.0}
    # 細類 101（水費）：只含 A店的 300 reconciled
    assert len(major100["children"]) == 1
    child101 = major100["children"][0]
    assert child101["major_id"] == 101
    assert child101["major_name"] == "水費"
    assert child101["total"] == {"reconciled": 300.0, "pending": 0.0}
    assert child101["per_store"][1] == {"reconciled": 300.0, "pending": 0.0}
    assert child101["children"] == []

    # 大類 200（餐飲）：無細類使用，全部落在大類自己
    major200 = rows_by_major[200]
    assert major200["total"] == {"reconciled": 120.0, "pending": -20.0}
    assert major200["per_store"][2] == {"reconciled": 120.0, "pending": -20.0}
    assert major200["children"] == []

    # 未分類
    unclassified = rows_by_major[None]
    assert unclassified["major_name"] == "未分類"
    assert unclassified["total"] == {"reconciled": 0.0, "pending": 10.0}
    assert unclassified["children"] == []

    # store_totals：A店 = 300(recon,101) -50(pending,100) +10(pending,None) = reconciled 300, pending -40
    assert table["store_totals"][1] == {"reconciled": 300.0, "pending": -40.0}
    # B店 = 120(recon,200) -20(pending,200)
    assert table["store_totals"][2] == {"reconciled": 120.0, "pending": -20.0}

    # grand_total = reconciled 300+120=420, pending -50+-20+10=-60
    assert table["grand_total"] == {"reconciled": 420.0, "pending": -60.0}
