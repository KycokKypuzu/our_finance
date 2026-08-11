from pathlib import Path
from datetime import datetime
import json
import re
import uuid

import pandas as pd
from fastapi import FastAPI, Request, UploadFile, File, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
USERS_FILE = DATA_DIR / "users.json"
DATA_DIR.mkdir(exist_ok=True)

if not USERS_FILE.exists():
    USERS_FILE.write_text("[]", encoding="utf-8")

app = FastAPI(title="Мои финансы")
app.add_middleware(SessionMiddleware, secret_key="local-finance-service-secret")

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

# Черновики не храним в session cookie. SessionMiddleware хранит данные
# сессии прямо в cookie браузера, поэтому большой XLSX быстро превышает
# допустимый размер cookie. Черновик живёт только на сервере до сохранения.
DRAFTS = {}


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


def empty_finance(username, month, year):
    return {
        "username": username,
        "month": int(month),
        "year": int(year),
        "outcome": {},
        "income": {},
    }


def parse_uploaded_file(upload: UploadFile):
    suffix = Path(upload.filename or "").suffix.lower()
    content = upload.file.read()

    if suffix == ".xlsx":
        from io import BytesIO
        df = pd.read_excel(BytesIO(content), header=0)
    elif suffix == ".csv":
        from io import BytesIO
        # Сначала UTF-8, затем распространённая для Windows/RU кодировка.
        try:
            df = pd.read_csv(BytesIO(content), header=0, encoding="utf-8-sig")
        except UnicodeDecodeError:
            df = pd.read_csv(BytesIO(content), header=0, encoding="cp1251")
    else:
        raise ValueError("Поддерживаются только CSV и XLSX.")

    df = df.dropna(how="all")
    df.columns = [str(c).strip() for c in df.columns]
    return df


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
    for fmt in ("%d.%m.%Y", "%d/%m/%Y", "%Y-%m-%d", "%d.%m.%y"):
        try:
            return datetime.strptime(text, fmt).strftime("%d.%m.%Y")
        except ValueError:
            pass

    parsed = pd.to_datetime(text, errors="coerce", dayfirst=False)
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


@app.get("/", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={"request": request, "users": load_users()},
    )


@app.post("/login")
def login(request: Request, username: str = Form(...)):
    username = username.strip()
    if not username:
        return RedirectResponse("/", status_code=303)

    remember_user(username)
    request.session["username"] = username
    return RedirectResponse("/home", status_code=303)


@app.get("/home", response_class=HTMLResponse)
def home(request: Request):
    username = request.session.get("username")
    if not username:
        return RedirectResponse("/", status_code=303)

    return templates.TemplateResponse(
        request=request,
        name="home.html",
        context={"request": request, "username": username},
    )


@app.get("/new", response_class=HTMLResponse)
def new_entry_page(request: Request):
    username = request.session.get("username")
    if not username:
        return RedirectResponse("/", status_code=303)

    return templates.TemplateResponse(
        request=request,
        name="new.html",
        context={
            "request": request,
            "username": username,
            "years": list(range(datetime.now().year - 2, datetime.now().year + 3)),
            "months": list(range(1, 13)),
        },
    )


@app.post("/new/upload", response_class=HTMLResponse)
async def upload_file(
    request: Request,
    year: int = Form(...),
    month: int = Form(...),
    bank: str = Form(...),
    file: UploadFile = File(...),
    draft_id: str = Form(""),
):
    username = request.session.get("username")
    if not username:
        return RedirectResponse("/", status_code=303)

    bank = bank.strip()
    if not bank:
        return templates.TemplateResponse(
            request=request,
            name="new.html",
            context={
                "request": request,
                "username": username,
                "years": list(range(datetime.now().year - 2, datetime.now().year + 3)),
                "months": list(range(1, 13)),
                "error": "Введите название банка.",
                "draft_id": draft_id,
            },
            status_code=400,
        )

    # При добавлении второго/следующего банка месяц и год уже принадлежат
    # существующему черновику. Не даём случайно поменять их.
    existing_draft = DRAFTS.get(draft_id) if draft_id else None
    if existing_draft:
        if existing_draft.get("username") != username:
            return RedirectResponse("/new", status_code=303)
        year = int(existing_draft["year"])
        month = int(existing_draft["month"])

    try:
        df = parse_uploaded_file(file)
    except Exception as exc:
        template_name = "add_bank.html" if draft_id else "new.html"
        return templates.TemplateResponse(
            request=request,
            name=template_name,
            context={
                "request": request,
                "username": username,
                "year": year,
                "month": month,
                "years": list(range(datetime.now().year - 2, datetime.now().year + 3)),
                "months": list(range(1, 13)),
                "draft_id": draft_id,
                "error": f"Не удалось прочитать файл: {exc}",
            },
            status_code=400,
        )

    columns = [str(c) for c in df.columns]
    if not columns:
        return templates.TemplateResponse(
            request=request,
            name="add_bank.html" if draft_id else "new.html",
            context={
                "request": request,
                "username": username,
                "year": year,
                "month": month,
                "years": list(range(datetime.now().year - 2, datetime.now().year + 3)),
                "months": list(range(1, 13)),
                "draft_id": draft_id,
                "error": "В файле нет столбцов.",
            },
            status_code=400,
        )

    # Первый банк создаёт общий черновик. Последующие банки используют
    # тот же draft_id и добавляются в тот же объект data.
    if existing_draft:
        draft_id = draft_id
    else:
        draft_id = str(uuid.uuid4())
        DRAFTS[draft_id] = {
            "username": username,
            "month": month,
            "year": year,
            "data": empty_finance(username, month, year),
        }

    DRAFTS[draft_id]["upload"] = {
        "bank": bank,
        "columns": columns,
        "rows": df.fillna("").astype(str).to_dict(orient="records"),
    }

    return templates.TemplateResponse(
        request=request,
        name="mapping.html",
        context={
            "request": request,
            "draft_id": draft_id,
            "bank": bank,
            "columns": columns,
            "sample_rows": df.fillna("").head(8).astype(str).to_dict(orient="records"),
        },
    )


@app.get("/new/bank/{draft_id}", response_class=HTMLResponse)
def add_bank_page(request: Request, draft_id: str):
    username = request.session.get("username")
    if not username:
        return RedirectResponse("/", status_code=303)

    draft = DRAFTS.get(draft_id)
    if not draft or draft.get("username") != username or "data" not in draft:
        return RedirectResponse("/new", status_code=303)

    return templates.TemplateResponse(
        request=request,
        name="add_bank.html",
        context={
            "request": request,
            "username": username,
            "year": draft["year"],
            "month": draft["month"],
            "draft_id": draft_id,
            "banks": sorted(set(draft["data"].get("outcome", {})) | set(draft["data"].get("income", {}))),
        },
    )


@app.post("/new/process", response_class=HTMLResponse)
def process_file(
    request: Request,
    draft_id: str = Form(...),
    date_col: str = Form(...),
    value_col: str = Form(...),
    description_col: str = Form(...),
    category_col: str = Form(...),
):
    username = request.session.get("username")
    if not username:
        return RedirectResponse("/", status_code=303)

    draft = DRAFTS.get(draft_id)
    if not draft or draft.get("username") != username or "upload" not in draft:
        return RedirectResponse("/new", status_code=303)

    upload = draft["upload"]
    bank = upload["bank"]

    current_banks = set(draft.get("data", {}).get("outcome", {})) | set(
        draft.get("data", {}).get("income", {})
    )
    if bank in current_banks:
        return templates.TemplateResponse(
            request=request,
            name="mapping.html",
            context={
                "request": request,
                "draft_id": draft_id,
                "bank": bank,
                "columns": upload["columns"],
                "sample_rows": upload["rows"][:8],
                "error": f'Банк «{bank}» уже добавлен в эту запись. Выберите другое название банка.',
            },
            status_code=400,
        )

    mapping = {
        "date": date_col,
        "value": value_col,
        "description": description_col,
        "category": category_col,
    }

    df = pd.DataFrame(upload["rows"], columns=upload["columns"])
    bank_data = build_finance_from_dataframe(
        df,
        draft["username"],
        draft["month"],
        draft["year"],
        bank,
        mapping,
    )

    # Добавляем обработанный банк в общий несохранённый отчёт.
    draft["data"].setdefault("outcome", {}).update(bank_data["outcome"])
    draft["data"].setdefault("income", {}).update(bank_data["income"])
    draft.pop("upload", None)

    return templates.TemplateResponse(
        request=request,
        name="review.html",
        context={
            "request": request,
            "draft_id": draft_id,
            "data": draft["data"],
            "mode": "new",
            "message": f'Банк «{bank}» добавлен. Можно добавить ещё один банк или сохранить общий отчёт.',
        },
    )

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


def create_draft_for_edit(username, data):
    draft_id = str(uuid.uuid4())
    DRAFTS[draft_id] = {
        "username": username,
        "data": data,
        "edit": True,
    }
    return draft_id


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


@app.post("/new/save")
async def save_new(request: Request):
    username = request.session.get("username")
    if not username:
        return RedirectResponse("/", status_code=303)

    form = await request.form()
    draft_id = str(form.get("draft_id", ""))
    payload_raw = str(form.get("payload", ""))

    draft = DRAFTS.get(draft_id)
    data = draft.get("data") if draft else None
    if not data or draft.get("username") != username:
        return RedirectResponse("/new", status_code=303)

    try:
        if payload_raw:
            data = parse_review_payload(json.loads(payload_raw), data)
    except (json.JSONDecodeError, ValueError) as exc:
        return templates.TemplateResponse(
            request=request, name="review.html",
            context={"request": request, "draft_id": draft_id, "data": data,
                     "mode": "new", "message": f"Не удалось сохранить изменения: {exc}"},
            status_code=400,
        )

    save_finance(merge_bank_into_existing(data))
    DRAFTS.pop(draft_id, None)
    return RedirectResponse(f"/finance/{data['month']}/{data['year']}", status_code=303)


@app.post("/new/continue")
async def continue_new(request: Request):
    username = request.session.get("username")
    if not username:
        return RedirectResponse("/", status_code=303)

    form = await request.form()
    draft_id = str(form.get("draft_id", ""))
    payload_raw = str(form.get("payload", ""))

    draft = DRAFTS.get(draft_id)
    data = draft.get("data") if draft else None
    if not data or draft.get("username") != username:
        return RedirectResponse("/new", status_code=303)

    try:
        data = parse_review_payload(json.loads(payload_raw), data)
    except (json.JSONDecodeError, ValueError) as exc:
        return templates.TemplateResponse(
            request=request, name="review.html",
            context={"request": request, "draft_id": draft_id, "data": data,
                     "mode": "new", "message": f"Не удалось обработать изменения: {exc}"},
            status_code=400,
        )

    DRAFTS[draft_id]["data"] = data
    return templates.TemplateResponse(
        request=request, name="overview.html",
        context={"request": request, "draft_id": draft_id, "data": data},
    )


@app.get("/new/overview", response_class=HTMLResponse)
def new_overview(request: Request, draft_id: str):
    username = request.session.get("username")
    if not username:
        return RedirectResponse("/", status_code=303)

    draft = DRAFTS.get(draft_id)
    if not draft or "data" not in draft:
        return RedirectResponse("/new", status_code=303)

    return templates.TemplateResponse(
        request=request,
        name="overview.html",
        context={"request": request, "draft_id": draft_id, "data": draft["data"]},
    )


@app.get("/finance/edit/{month}/{year}", response_class=HTMLResponse)
def edit_finance(request: Request, month: int, year: int):
    username = request.session.get("username")
    if not username:
        return RedirectResponse("/", status_code=303)

    data = load_finance(username, month, year)
    if data is None:
        return RedirectResponse("/finances", status_code=303)

    draft_id = create_draft_for_edit(username, data)
    return templates.TemplateResponse(
        request=request,
        name="review.html",
        context={
            "request": request,
            "draft_id": draft_id,
            "data": data,
            "mode": "edit",
        },
    )


@app.post("/finance/edit/save")
async def save_edited_finance(request: Request):
    username = request.session.get("username")
    if not username:
        return RedirectResponse("/", status_code=303)

    form = await request.form()
    draft_id = str(form.get("draft_id", ""))
    payload_raw = str(form.get("payload", ""))

    draft = DRAFTS.get(draft_id)
    data = draft.get("data") if draft and draft.get("edit") else None
    if not data or data.get("username") != username:
        return RedirectResponse("/finances", status_code=303)

    try:
        data = parse_review_payload(json.loads(payload_raw), data)
    except (json.JSONDecodeError, ValueError) as exc:
        return templates.TemplateResponse(
            request=request, name="review.html",
            context={"request": request, "draft_id": draft_id, "data": data,
                     "mode": "edit", "message": f"Не удалось сохранить изменения: {exc}"},
            status_code=400,
        )

    save_finance(data)
    DRAFTS.pop(draft_id, None)
    return RedirectResponse(f"/finance/{data['month']}/{data['year']}", status_code=303)


@app.get("/finance/{month}/{year}/analysis", response_class=HTMLResponse)
def finance_analysis(request: Request, month: int, year: int):
    username = request.session.get("username")
    if not username:
        return RedirectResponse("/", status_code=303)

    data = load_finance(username, month, year)
    if data is None:
        return RedirectResponse("/finances", status_code=303)

    return templates.TemplateResponse(
        request=request,
        name="analysis.html",
        context={
            "request": request,
            "data": data,
            "analysis": analysis_data(data),
        },
    )


@app.get("/finances", response_class=HTMLResponse)
def finances(request: Request):
    username = request.session.get("username")
    if not username:
        return RedirectResponse("/", status_code=303)

    return templates.TemplateResponse(
        request=request,
        name="finances.html",
        context={
            "request": request,
            "username": username,
            "files": all_finance_files(username),
        },
    )


@app.get("/finance/{month}/{year}", response_class=HTMLResponse)
def finance_view(request: Request, month: int, year: int):
    username = request.session.get("username")
    if not username:
        return RedirectResponse("/", status_code=303)

    data = load_finance(username, month, year)
    if data is None:
        return RedirectResponse("/finances", status_code=303)

    return templates.TemplateResponse(
        request=request,
        name="finance.html",
        context={"request": request, "data": data},
    )
