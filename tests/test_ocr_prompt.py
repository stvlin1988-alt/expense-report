from app.ocr.prompt import build_prompt, build_response_schema


def test_prompt_injects_categories_and_amount_rule():
    cats = [{"id": 3, "科目": "廚房支出", "項目": "食材"}]
    p = build_prompt(cats)
    assert "食材" in p and "3" in p
    # 金額規則：抓合計、排除現金/找零
    assert "合計" in p or "實付" in p
    assert "現金" in p and "找零" in p


def test_response_schema_shape():
    s = build_response_schema()
    props = s["properties"]
    assert {"summary", "category_id", "amount", "confidence", "is_handwritten"} <= set(props)


def test_response_schema_types_are_single_strings():
    # Gemini responseSchema 只接受單一 type 字串 + nullable，type 陣列/union 會回 400。
    s = build_response_schema()
    for name, spec in s["properties"].items():
        assert isinstance(spec["type"], str), f"{name} type 必須是單一字串，不能用 list"
