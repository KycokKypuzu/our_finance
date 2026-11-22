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


@router.get("/weather")
async def weather_page(request: Request):
    client = request.app.state.http_client

    response = await client.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": 55.75,
            "longitude": 37.62,
            "current": (
                "temperature_2m,"
                "relative_humidity_2m,"
                "precipitation,"
                "weather_code,"
                "wind_speed_10m"
            ),
            "timezone": "Europe/Moscow",
        },
    )

    response.raise_for_status()
    data = response.json()

    return data


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
