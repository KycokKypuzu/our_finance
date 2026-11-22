"""Операции с отчётами и расчёт показателей."""

from storage import load_finance


def empty_finance(username, month, year):
    return {
        "username": username,
        "month": int(month),
        "year": int(year),
        "outcome": {},
        "income": {},
    }


def merge_bank_into_existing(new_data):
    existing = load_finance(
        new_data["username"],
        new_data["month"],
        new_data["year"],
    )

    if existing is None:
        return new_data

    bank_names = set(new_data["outcome"]) | set(new_data["income"])
    for bank in bank_names:
        if bank in new_data["outcome"]:
            existing.setdefault("outcome", {})[bank] = new_data["outcome"][bank]
        if bank in new_data["income"]:
            existing.setdefault("income", {})[bank] = new_data["income"][bank]

    return existing


def parse_review_payload(payload, data):
    """Apply edited rows received as one JSON field.

    A bank statement can contain hundreds of rows. Sending one JSON field
    avoids Starlette's 1000-field limit for regular form submissions.
    """
    if not isinstance(payload, dict):
        raise ValueError("Некорректный формат данных")

    result = {
        "username": data["username"],
        "month": int(data["month"]),
        "year": int(data["year"]),
        "outcome": {},
        "income": {},
    }

    for bank, items in payload.get("outcome", {}).items():
        result["outcome"][bank] = []
        for item in items:
            value_raw = str(item.get("value", 0)).replace(",", ".")
            try:
                value = float(value_raw)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"Некорректная сумма в расходах банка «{bank}»") from exc
            result["outcome"][bank].append({
                "date": str(item.get("date", "")),
                "value": value,
                "description": str(item.get("description", "")),
                "comment": str(item.get("comment", "")),
                "category": str(item.get("category", "")),
                "unnecessary_flag": bool(item.get("unnecessary_flag", False)),
                "onetime_flag": bool(item.get("onetime_flag", False)),
            })

    for bank, items in payload.get("income", {}).items():
        result["income"][bank] = []
        for item in items:
            value_raw = str(item.get("value", 0)).replace(",", ".")
            try:
                value = float(value_raw)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"Некорректная сумма в доходах банка «{bank}»") from exc
            result["income"][bank].append({
                "date": str(item.get("date", "")),
                "value": value,
                "description": str(item.get("description", "")),
                "category": str(item.get("category", "")),
            })

    return result


def analysis_data(data):
    outcome_total = 0.0
    income_total = 0.0
    category_totals = {}
    unnecessary_total = 0.0
    onetime_total = 0.0
    ordinary_total = 0.0

    for items in data.get("outcome", {}).values():
        for item in items:
            value = float(item.get("value", 0) or 0)
            outcome_total += value

            category = str(item.get("category", "") or "").strip() or "Без категории"
            category_totals[category] = category_totals.get(category, 0.0) + value

            if item.get("unnecessary_flag"):
                unnecessary_total += value
            if item.get("onetime_flag"):
                onetime_total += value
            if not item.get("unnecessary_flag") and not item.get("onetime_flag"):
                ordinary_total += value

    for items in data.get("income", {}).values():
        for item in items:
            income_total += float(item.get("value", 0) or 0)

    category_chart = [
        {"label": label, "value": round(value, 2)}
        for label, value in sorted(category_totals.items(), key=lambda x: x[1], reverse=True)
    ]
    flags_chart = [
        {"label": "Лишнее", "value": round(unnecessary_total, 2)},
        {"label": "Единоразовое", "value": round(onetime_total, 2)},
        {"label": "Обычное", "value": round(ordinary_total, 2)},
    ]

    return {
        "outcome_total": round(outcome_total, 2),
        "income_total": round(income_total, 2),
        "difference": round(income_total - outcome_total, 2),
        "category_chart": category_chart,
        "flags_chart": flags_chart,
    }
