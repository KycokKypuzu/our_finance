"""Импорт CSV/XLSX и преобразование строк банковских выписок."""

import csv
import re
from datetime import datetime
from pathlib import Path
from io import BytesIO

import pandas as pd
from fastapi import UploadFile

from services.finance import empty_finance


def parse_uploaded_file(upload: UploadFile):
    suffix = Path(upload.filename or "").suffix.lower()
    content = upload.file.read()

    if suffix == ".xlsx":
        from io import BytesIO
        df = pd.read_excel(BytesIO(content), header=0)
    elif suffix == ".csv":
        from io import BytesIO
        # Банки экспортируют CSV с разными разделителями: например, Т-Банк
        # использует «;», а многие другие — запятую. Определяем его по файлу,
        # чтобы все поля не оказались в одном столбце.
        for encoding in ("utf-8-sig", "cp1251"):
            try:
                text = content.decode(encoding)
            except UnicodeDecodeError:
                continue

            try:
                delimiter = csv.Sniffer().sniff(
                    text[:8192], delimiters=";,\t|"
                ).delimiter
            except csv.Error:
                delimiter = ","

            df = pd.read_csv(
                BytesIO(content),
                header=0,
                encoding=encoding,
                sep=delimiter,
            )
            break
        else:
            raise ValueError("Не удалось определить кодировку CSV-файла.")
    else:
        raise ValueError("Поддерживаются только CSV и XLSX.")

    df = df.dropna(how="all")
    df.columns = [str(c).strip() for c in df.columns]
    return df


def suggest_column_mapping(columns):
    """Choose useful defaults for common bank statement headers."""
    normalized = {str(column).strip().casefold(): str(column) for column in columns}
    aliases = {
        "date_col": ("дата операции", "дата", "date"),
        "value_col": ("сумма операции", "сумма", "amount"),
        "description_col": ("описание", "описание операции", "comment"),
        "category_col": ("категория по-умолчанию", "категория", "category"),
    }

    return {
        field: next(
            (normalized[alias] for alias in names if alias in normalized),
            columns[0] if columns else "",
        )
        for field, names in aliases.items()
    }


def normalize_date(value):
    if pd.isna(value):
        return ""

    if isinstance(value, datetime):
        return value.strftime("%d.%m.%Y")

    # pandas Timestamp
    if hasattr(value, "strftime") and not isinstance(value, str):
        try:
            return value.strftime("%d.%m.%Y")
        except Exception:
            pass

    text = str(value).strip()
    for fmt in (
        "%d.%m.%Y %H:%M:%S",
        "%d.%m.%Y",
        "%d/%m/%Y",
        "%Y-%m-%d",
        "%d.%m.%y",
    ):
        try:
            return datetime.strptime(text, fmt).strftime("%d.%m.%Y")
        except ValueError:
            pass

    parsed = pd.to_datetime(text, errors="coerce", dayfirst=True)
    if not pd.isna(parsed):
        return parsed.strftime("%d.%m.%Y")

    return text


def normalize_value(value):
    if pd.isna(value):
        raise ValueError("Пустая сумма")

    if isinstance(value, str):
        text = value.strip().replace("\xa0", "").replace(" ", "").replace(",", ".")
        text = re.sub(r"[^\d.+-]", "", text)
        if not text:
            raise ValueError("Некорректная сумма")
        return float(text)

    return float(value)


def build_finance_from_dataframe(df, username, month, year, bank, mapping):
    date_col = mapping["date"]
    value_col = mapping["value"]
    description_col = mapping["description"]
    category_col = mapping["category"]

    outcome = []
    income = []

    for _, row in df.iterrows():
        try:
            value = normalize_value(row[value_col])
        except ValueError:
            # Пустые/некорректные строки не превращаем в финансовые записи.
            continue

        item_date = normalize_date(row[date_col])
        description = "" if pd.isna(row[description_col]) else str(row[description_col])
        category = "" if pd.isna(row[category_col]) else str(row[category_col])

        if value < 0:
            outcome.append({
                "date": item_date,
                "value": abs(value),
                "description": description,
                "comment": "",
                "category": category,
                "unnecessary_flag": False,
                "onetime_flag": False,
            })
        elif value > 0:
            income.append({
                "date": item_date,
                "value": value,
                "description": description,
                "category": category,
            })

    data = empty_finance(username, month, year)
    data["outcome"][bank] = outcome
    data["income"][bank] = income
    return data
