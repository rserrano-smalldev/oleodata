from datetime import date, timedelta

from fastapi import FastAPI, Form, Request, UploadFile
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app import api_client
from app.api_client import ApiError
from app.config import get_settings

settings = get_settings()

app = FastAPI(title="OleaData — Frontend (demo)")
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")


@app.exception_handler(ApiError)
async def api_error_handler(request: Request, exc: ApiError):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/")
async def index(request: Request):
    varieties = await api_client.get("/v1/varieties")
    parcels = await api_client.get("/v1/parcels")
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "varieties": varieties,
            "parcels": parcels,
            "reference_lat": settings.reference_lat,
            "reference_lon": settings.reference_lon,
        },
    )


@app.post("/ui/discover")
async def ui_discover(request: Request, lat: float = Form(...), lon: float = Form(...)):
    try:
        result = await api_client.post("/v1/discovery/point", json={"lat": lat, "lon": lon})
        return templates.TemplateResponse(
            "partials/discovery_result.html", {"request": request, "result": result, "error": None}
        )
    except ApiError as exc:
        return templates.TemplateResponse(
            "partials/discovery_result.html", {"request": request, "result": None, "error": exc.detail}
        )


@app.post("/ui/parcels")
async def ui_create_parcel(
    code: str = Form(...),
    name: str = Form(...),
    lat: float = Form(...),
    lon: float = Form(...),
    elevation_m: str = Form(""),
    variety_code: str = Form(""),
    area_ha: str = Form(""),
):
    payload = {
        "code": code,
        "name": name,
        "lat": lat,
        "lon": lon,
        "elevation_m": float(elevation_m) if elevation_m else None,
        "variety_code": variety_code or None,
        "area_ha": float(area_ha) if area_ha else None,
    }
    parcel = await api_client.post("/v1/parcels", json=payload)
    return RedirectResponse(url=f"/parcel/{parcel['id']}", status_code=303)


@app.get("/parcel/{parcel_id}")
async def parcel_dashboard(request: Request, parcel_id: int):
    parcel = await api_client.get(f"/v1/parcels/{parcel_id}")
    varieties = await api_client.get("/v1/varieties")
    default_day = (date.today() - timedelta(days=10)).isoformat()
    return templates.TemplateResponse(
        "parcel_dashboard.html",
        {"request": request, "parcel": parcel, "varieties": varieties, "default_day": default_day},
    )


@app.post("/ui/parcel/{parcel_id}/variety")
async def ui_update_variety(parcel_id: int, request: Request):
    body = await request.json()
    result = await api_client.patch(f"/v1/parcels/{parcel_id}/variety", json={"variety_code": body.get("variety_code")})
    return result


@app.post("/ui/parcel/{parcel_id}/backfill")
async def ui_backfill(parcel_id: int, request: Request):
    body = await request.json()
    return await api_client.post(f"/v1/parcels/{parcel_id}/backfill", json={"years_back": body.get("years_back", 25)})


@app.post("/ui/parcel/{parcel_id}/simulate-sensors")
async def ui_simulate(parcel_id: int):
    return await api_client.post(f"/v1/parcels/{parcel_id}/simulate-sensors", json={})


@app.get("/ui/parcel/{parcel_id}/daily.json")
async def ui_daily(parcel_id: int, start: str, end: str, variables: str):
    return await api_client.get(
        f"/v1/parcels/{parcel_id}/daily", params={"start": start, "end": end, "variables": variables}
    )


@app.get("/ui/parcel/{parcel_id}/observations.json")
async def ui_observations(parcel_id: int, provider: str, start: str, end: str, variables: str):
    return await api_client.get(
        f"/v1/parcels/{parcel_id}/observations",
        params={"provider": provider, "start": start, "end": end, "variables": variables},
    )


@app.get("/ui/parcel/{parcel_id}/recommendations.json")
async def ui_recommendations(parcel_id: int, day: str):
    return await api_client.get(f"/v1/parcels/{parcel_id}/recommendations", params={"day": day})


@app.get("/parcel/{parcel_id}/import-treatments")
async def import_treatments_page(request: Request, parcel_id: int):
    parcel = await api_client.get(f"/v1/parcels/{parcel_id}")
    return templates.TemplateResponse("import_treatments.html", {"request": request, "parcel": parcel})


@app.post("/ui/parcel/{parcel_id}/import/preview")
async def ui_import_preview(parcel_id: int, file: UploadFile):
    content = await file.read()
    return await api_client.post_file("/v1/imports/treatments/preview", file.filename, content)


@app.post("/ui/parcel/{parcel_id}/import/commit")
async def ui_import_commit(parcel_id: int, request: Request):
    body = await request.json()
    return await api_client.post("/v1/imports/treatments/commit", json={"token": body.get("token")})
