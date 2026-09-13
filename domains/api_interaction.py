import os
from typing import Any

import aiohttp
from dotenv import load_dotenv

from domains.api_constants import DEVICE_ACTION_URL, DEVICE_INFO_URL, USER_INFO_URL


load_dotenv()

YANDEX_TOKEN = os.getenv("YANDEX_TOKEN")


class YandexAPIError(RuntimeError):
    """Raised when Yandex Smart Home API returns an error response."""

    def __init__(self, status: int, message: str, payload: Any = None):
        self.status = status
        self.message = message
        self.payload = payload
        super().__init__(f"Yandex API error {status}: {message}")


def _get_headers() -> dict[str, str]:
    if not YANDEX_TOKEN:
        raise RuntimeError(
            "YANDEX_TOKEN is not set. Put it in .env or in the process environment."
        )
    return {
        "Authorization": f"Bearer {YANDEX_TOKEN}",
        "Accept": "application/json",
    }


async def _read_response(response: aiohttp.ClientResponse) -> Any:
    """Read JSON when possible, otherwise return the raw response text."""
    text = await response.text()
    if not text:
        return None

    try:
        return await response.json(content_type=None)
    except (aiohttp.ContentTypeError, ValueError):
        return text


async def _request(method: str, url: str, **kwargs: Any) -> Any:
    timeout = aiohttp.ClientTimeout(total=15)
    headers = kwargs.pop("headers", None) or _get_headers()

    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.request(method, url, headers=headers, **kwargs) as response:
            data = await _read_response(response)

            if response.status >= 400:
                if isinstance(data, dict):
                    message = data.get("message") or data.get("status") or str(data)
                else:
                    message = str(data)
                raise YandexAPIError(response.status, message, data)

            return data


class API:
    """Small async client for Yandex Smart Home programmatic control API."""

    @staticmethod
    async def get_user_info() -> dict[str, Any]:
        data = await _request("GET", USER_INFO_URL)
        if not isinstance(data, dict):
            raise YandexAPIError(502, "Yandex returned an unexpected response", data)
        return data

    @staticmethod
    async def get_devices() -> list[dict[str, Any]]:
        data = await API.get_user_info()
        devices = data.get("devices", [])
        if not isinstance(devices, list):
            raise YandexAPIError(502, "Invalid devices field in Yandex response", data)
        return devices

    @staticmethod
    async def get_device(device_id: str) -> dict[str, Any]:
        data = await _request("GET", DEVICE_INFO_URL.format(device_id=device_id))
        if not isinstance(data, dict):
            raise YandexAPIError(502, "Yandex returned an unexpected device response", data)
        return data

    @staticmethod
    async def perform_device_action(
        device_id: str,
        action_type: str,
        instance: str,
        value: bool | str | int | float | dict,
    ) -> dict[str, Any]:
        payload = {
            "devices": [
                {
                    "id": device_id,
                    "actions": [
                        {
                            "type": action_type,
                            "state": {
                                "instance": instance,
                                "value": value,
                            },
                        }
                    ],
                }
            ]
        }

        data = await _request("POST", DEVICE_ACTION_URL, json=payload)
        if not isinstance(data, dict):
            raise YandexAPIError(502, "Yandex returned an unexpected action response", data)
        return data

    @staticmethod
    async def set_on_off(device_id: str, value: bool) -> dict[str, Any]:
        return await API.perform_device_action(
            device_id=device_id,
            action_type="devices.capabilities.on_off",
            instance="on",
            value=value,
        )
