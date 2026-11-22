"""Вход, выбор сервиса и стартовая страница."""

from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse

from config import templates
from storage import load_users, remember_user

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def service_choice(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="service_choice.html",
        context={"request": request},
    )


@router.get("/finance", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={"request": request, "users": load_users()},
    )


@router.post("/login")
def login(request: Request, username: str = Form(...)):
    username = username.strip()
    if not username:
        return RedirectResponse("/finance", status_code=303)

    remember_user(username)
    request.session["username"] = username
    return RedirectResponse("/home", status_code=303)


@router.get("/home", response_class=HTMLResponse)
def home(request: Request):
    username = request.session.get("username")
    if not username:
        return RedirectResponse("/finance", status_code=303)

    return templates.TemplateResponse(
        request=request,
        name="home.html",
        context={"request": request, "username": username},
    )
