"""Создание финансового отчёта из одной или нескольких выписок."""

import json
import uuid
from datetime import datetime

import pandas as pd
from fastapi import APIRouter, Request, UploadFile, File, Form
from fastapi.responses import HTMLResponse, RedirectResponse

from config import templates
from services.drafts import DRAFTS
from services.finance import empty_finance, parse_review_payload, merge_bank_into_existing
from services.statement_import import (parse_uploaded_file, suggest_column_mapping,
                                       build_finance_from_dataframe)
from storage import save_finance

router = APIRouter()


@router.get("/new", response_class=HTMLResponse)
def new_entry_page(request: Request):
    username = request.session.get("username")
    if not username:
        return RedirectResponse("/finance", status_code=303)

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


@router.post("/new/upload", response_class=HTMLResponse)
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
        return RedirectResponse("/finance", status_code=303)

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
            "suggested_mapping": suggest_column_mapping(columns),
            "sample_rows": df.fillna("").head(8).astype(str).to_dict(orient="records"),
        },
    )


@router.get("/new/bank/{draft_id}", response_class=HTMLResponse)
def add_bank_page(request: Request, draft_id: str):
    username = request.session.get("username")
    if not username:
        return RedirectResponse("/finance", status_code=303)

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


@router.post("/new/process", response_class=HTMLResponse)
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
        return RedirectResponse("/finance", status_code=303)

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


@router.post("/new/save")
async def save_new(request: Request):
    username = request.session.get("username")
    if not username:
        return RedirectResponse("/finance", status_code=303)

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


@router.post("/new/continue")
async def continue_new(request: Request):
    username = request.session.get("username")
    if not username:
        return RedirectResponse("/finance", status_code=303)

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


@router.get("/new/overview", response_class=HTMLResponse)
def new_overview(request: Request, draft_id: str):
    username = request.session.get("username")
    if not username:
        return RedirectResponse("/finance", status_code=303)

    draft = DRAFTS.get(draft_id)
    if not draft or "data" not in draft:
        return RedirectResponse("/new", status_code=303)

    return templates.TemplateResponse(
        request=request,
        name="overview.html",
        context={"request": request, "draft_id": draft_id, "data": draft["data"]},
    )
