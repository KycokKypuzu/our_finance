"""Чтение и запись пользовательских JSON без изменения их структуры."""

import json
import re
from pathlib import Path
from config import DATA_DIR, USERS_FILE


def load_users():
    try:
        return json.loads(USERS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, FileNotFoundError):
        return []


def save_users(users):
    USERS_FILE.write_text(
        json.dumps(users, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def remember_user(username: str):
    username = username.strip()
    if not username:
        return
    users = load_users()
    if username not in users:
        users.append(username)
        save_users(users)


def safe_username(username: str) -> str:
    # Имя остаётся отображаемым как введено, но в имени файла
    # запрещаем опасные символы пути.
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", username.strip())


def finance_filename(username: str, month: int, year: int) -> str:
    return f"{safe_username(username)}_{month}_{year}.json"


def finance_path(username: str, month: int, year: int) -> Path:
    return DATA_DIR / finance_filename(username, month, year)


def load_finance(username: str, month: int, year: int):
    path = finance_path(username, month, year)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def save_finance(data):
    path = finance_path(data["username"], int(data["month"]), int(data["year"]))
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def all_finance_files(username):
    prefix = f"{safe_username(username)}_"
    result = []

    for path in DATA_DIR.glob("*.json"):
        if path.name == USERS_FILE.name or not path.name.startswith(prefix):
            continue

        match = re.match(r"^(.+)_(\d+)_(\d+)\.json$", path.name)
        if not match:
            continue

        result.append({
            "filename": path.name,
            "month": int(match.group(2)),
            "year": int(match.group(3)),
            "label": f"{match.group(2)}.{match.group(3)}",
        })

    result.sort(key=lambda x: (x["year"], x["month"]), reverse=True)
    return result
