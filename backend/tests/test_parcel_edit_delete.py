"""Editar y borrar una parcela (botones pedidos para el frontend).

Prueba los endpoints reales de FastAPI en proceso (ASGITransport), no solo
las funciones sueltas: así se valida también el wiring de rutas/esquemas.
`_init_database` (conftest.py, autouse) ya deja el esquema y el seed listos
antes de que corra este fichero, así que no hace falta disparar el lifespan
de la app (que solo repetiría ese mismo init_db).
"""

import httpx

from app.main import app

TEST_PARCEL_CODE = "TEST-EDIT-DELETE-PARCEL"


async def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def _cleanup_leftover(client: httpx.AsyncClient):
    resp = await client.get("/v1/parcels")
    for p in resp.json():
        if p["code"] == TEST_PARCEL_CODE:
            await client.delete(f"/v1/parcels/{p['id']}")


async def test_update_parcel_edits_editable_fields_only():
    async with await _client() as client:
        await _cleanup_leftover(client)

        create_resp = await client.post(
            "/v1/parcels",
            json={
                "code": TEST_PARCEL_CODE,
                "name": "Parcela original",
                "lat": 38.521823062719164,
                "lon": -5.159543633627551,
                "elevation_m": 545.0,
                "area_ha": 3.0,
            },
        )
        assert create_resp.status_code == 200
        parcel = create_resp.json()
        parcel_id = parcel["id"]

        patch_resp = await client.patch(
            f"/v1/parcels/{parcel_id}",
            json={"name": "Parcela renombrada", "area_ha": 5.5, "field_capacity_mm": 100.0},
        )
        assert patch_resp.status_code == 200
        updated = patch_resp.json()
        assert updated["name"] == "Parcela renombrada"
        assert updated["area_ha"] == 5.5
        assert updated["field_capacity_mm"] == 100.0
        # Lat/lon/elevación son inmutables vía este endpoint.
        assert updated["latitude"] == parcel["latitude"]
        assert updated["longitude"] == parcel["longitude"]
        assert updated["elevation_m"] == parcel["elevation_m"]

        await client.delete(f"/v1/parcels/{parcel_id}")


async def test_update_parcel_rejects_unknown_variety_code():
    async with await _client() as client:
        await _cleanup_leftover(client)

        create_resp = await client.post(
            "/v1/parcels",
            json={
                "code": TEST_PARCEL_CODE,
                "name": "Parcela original",
                "lat": 38.521823062719164,
                "lon": -5.159543633627551,
                "elevation_m": 545.0,
            },
        )
        parcel_id = create_resp.json()["id"]

        resp = await client.patch(f"/v1/parcels/{parcel_id}", json={"variety_code": "no-existe-esta-variedad"})
        assert resp.status_code == 404

        await client.delete(f"/v1/parcels/{parcel_id}")


async def test_delete_parcel_cascades_and_is_idempotently_absent_after():
    async with await _client() as client:
        await _cleanup_leftover(client)

        create_resp = await client.post(
            "/v1/parcels",
            json={
                "code": TEST_PARCEL_CODE,
                "name": "Parcela a borrar",
                "lat": 38.521823062719164,
                "lon": -5.159543633627551,
                "elevation_m": 545.0,
            },
        )
        parcel_id = create_resp.json()["id"]

        # La creación intenta backfill/RIA reales (bloqueados en este sandbox,
        # se degradan a nota): puede haber dejado una fuente `source` sin
        # observaciones. Da igual — el delete debe encargarse de cualquier
        # combinación de fuentes/observaciones/tratamientos.
        del_resp = await client.delete(f"/v1/parcels/{parcel_id}")
        assert del_resp.status_code == 200
        body = del_resp.json()
        assert body == {"deleted": True, "code": TEST_PARCEL_CODE}

        get_resp = await client.get(f"/v1/parcels/{parcel_id}")
        assert get_resp.status_code == 404

        # Borrar una parcela que ya no existe da 404, no 500.
        del_again = await client.delete(f"/v1/parcels/{parcel_id}")
        assert del_again.status_code == 404
