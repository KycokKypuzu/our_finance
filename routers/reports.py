"""Просмотр, редактирование и аналитика сохранённых отчётов."""

import json

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from config import templates
from services.drafts import DRAFTS, create_draft_for_edit
from services.finance import parse_review_payload, analysis_data
from storage import load_finance, save_finance, all_finance_files

router = APIRouter()


@router.get("/finance/edit/{month}/{year}", response_class=HTMLResponse)
def edit_finance(request: Request, month: int, year: int):
    username = request.session.get("username")
    if not username:
        return RedirectResponse("/finance", status_code=303)

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


@router.post("/finance/edit/save")
async def save_edited_finance(request: Request):
    username = request.session.get("username")
    if not username:
        return RedirectResponse("/finance", status_code=303)

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


@router.get("/finance/{month}/{year}/analysis", response_class=HTMLResponse)
def finance_analysis(request: Request, month: int, year: int):
    username = request.session.get("username")
    if not username:
        return RedirectResponse("/finance", status_code=303)

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


@router.get("/finances", response_class=HTMLResponse)
def finances(request: Request):
    username = request.session.get("username")
    if not username:
        return RedirectResponse("/finance", status_code=303)

    return templates.TemplateResponse(
        request=request,
        name="finances.html",
        context={
            "request": request,
            "username": username,
            "files": all_finance_files(username),
        },
    )


@router.get("/finance/{month}/{year}", response_class=HTMLResponse)
def finance_view(request: Request, month: int, year: int):
    username = request.session.get("username")
    if not username:
        return RedirectResponse("/finance", status_code=303)

    data = load_finance(username, month, year)
    if data is None:
        return RedirectResponse("/finances", status_code=303)

    return templates.TemplateResponse(
        request=request,
        name="finance.html",
        context={"request": request, "data": data},
    )
