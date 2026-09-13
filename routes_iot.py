from fastapi import APIRouter, HTTPException, Request
from starlette.responses import HTMLResponse, RedirectResponse

from domains.api_interaction import API, YandexAPIError
from templating import templates


app_router = APIRouter(prefix="/devices", tags=["devices"])


@app_router.get("", response_class=HTMLResponse)
@app_router.get("/", response_class=HTMLResponse)
async def list_devices(request: Request) -> HTMLResponse:
    try:
        info = await API.get_user_info()
    except (YandexAPIError, RuntimeError) as exc:
        return templates.TemplateResponse(
            request=request,
            name="iot_index.html",
            context={"devices": [], "error": str(exc)},
            status_code=502,
        )

    return templates.TemplateResponse(
        request=request,
        name="iot_index.html",
        context={
            "devices": info.get("devices", []),
            "rooms": info.get("rooms", []),
            "households": info.get("households", []),
            "error": None,
        },
    )


@app_router.post("/{device_id}/toggle")
async def toggle_device(device_id: str, value: bool) -> RedirectResponse:
    try:
        await API.set_on_off(device_id, value)
    except (YandexAPIError, RuntimeError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return RedirectResponse(url="/devices", status_code=303)
