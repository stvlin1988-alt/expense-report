import json


def build_prompt(categories):
    """categories: [{'id', '科目', '項目'}]。回給 Gemini 的指示字串。"""
    cat_lines = "\n".join(
        f'  - id={c["id"]}: {c["科目"]} / {c["項目"]}' for c in categories
    )
    return (
        "你是台灣門市雜支單據的辨識助理。以下影像是一張收據/發票/估價單/銷貨單。\n"
        "只辨識畫面中『最主要、最完整』的那一張單據（常有多張單疊放，忽略邊角殘單）。\n"
        "\n"
        "抽三個欄位：\n"
        "1) summary：品名摘要，一句話。多品項請濃縮（例：8 項調味料→『調味料雜貨等 8 項』），不要逐條羅列。\n"
        "2) amount：這張單『最終應付的總金額』。\n"
        "   - 認明『合計 / 總計 / 實付金額 / 銷貨金額 / 應付』這類欄位。\n"
        "   - 【重要】務必排除『現金、付現、找零、找回、收現』等收付款欄位——那不是花費金額。\n"
        "     例：單上有『現金 2000 / 找零 710 / 小計 1290 / 實付金額 1290』時，正解是 1290，絕不是 2000。\n"
        "   - 金額回純數字（去千分位逗號、去貨幣符號）。\n"
        "3) category_id：從下列清單挑最符合的 id；若都不合，回 null。\n"
        f"{cat_lines}\n"
        "\n"
        "另外回：confidence（0–1，你對辨識的信心）、is_handwritten（此單金額是否為手寫）。\n"
        "以 JSON 結構化輸出。"
    )


def build_response_schema():
    return {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "category_id": {"type": ["integer", "null"]},
            "amount": {"type": ["number", "string", "null"]},
            "confidence": {"type": "number"},
            "is_handwritten": {"type": "boolean"},
        },
        "required": ["summary", "amount", "confidence", "is_handwritten"],
    }
