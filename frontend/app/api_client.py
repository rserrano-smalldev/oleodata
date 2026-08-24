"""Cliente HTTP delgado hacia la API de OleaData. El frontend es solo una
capa de presentación: toda la lógica vive en el backend (módulo 6)."""

import httpx

from app.config import get_settings

settings = get_settings()


class ApiError(Exception):
    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"{status_code}: {detail}")


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url=settings.api_internal_url, timeout=180.0)


async def _handle(response: httpx.Response) -> dict:
    if response.status_code >= 400:
        try:
            detail = response.json().get("detail", response.text)
        except Exception:
            detail = response.text
        raise ApiError(response.status_code, str(detail))
    return response.json()


async def get(path: str, params: dict | None = None) -> dict:
    async with _client() as client:
        return await _handle(await client.get(path, params=params))


async def post(path: str, json: dict | None = None, params: dict | None = None) -> dict:
    async with _client() as client:
        return await _handle(await client.post(path, json=json or {}, params=params))


async def patch(path: str, json: dict | None = None) -> dict:
    async with _client() as client:
        return await _handle(await client.patch(path, json=json or {}))


async def post_file(path: str, filename: str, content: bytes) -> dict:
    async with _client() as client:
        files = {"file": (filename, content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
        return await _handle(await client.post(path, files=files))
