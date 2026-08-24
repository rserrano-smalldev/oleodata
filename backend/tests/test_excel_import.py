import io

from geoalchemy2 import WKTElement
from sqlalchemy import delete, select

from app.models.parcel import Parcel
from app.models.treatment import ImportBatch, Treatment
from app.services.excel_import import commit_treatments_import, preview_treatments_excel
from scripts.make_sample_treatments_xlsx import build_sample_workbook

TEST_PARCEL_CODE = "TEST-EXCEL-IMPORT-PARCEL"


async def _ensure_test_parcel(db_session) -> Parcel:
    existing = (
        await db_session.execute(select(Parcel).where(Parcel.code == TEST_PARCEL_CODE))
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    parcel = Parcel(
        code=TEST_PARCEL_CODE,
        name="Parcela de test del importador",
        location=WKTElement("POINT(-5.16 38.52)", srid=4326),
        latitude=38.52,
        longitude=-5.16,
        elevation_m=540.0,
    )
    db_session.add(parcel)
    await db_session.commit()
    await db_session.refresh(parcel)
    return parcel


async def test_preview_reports_deliberate_error_without_blocking_the_rest(db_session):
    parcel = await _ensure_test_parcel(db_session)

    # Limpiar tratamientos de ejecuciones anteriores del test para que sea repetible.
    await db_session.execute(delete(Treatment).where(Treatment.parcel_id == parcel.id))
    await db_session.commit()

    workbook = build_sample_workbook(parcel_code=parcel.code)
    buffer = io.BytesIO()
    workbook.save(buffer)

    result = await preview_treatments_excel(db_session, buffer.getvalue(), "plantilla_test.xlsx")

    # La plantilla de ejemplo tiene 4 filas de datos, 1 con fecha inválida a propósito.
    assert result.total_data_rows == 4
    assert result.rows_ok == 3
    assert len(result.rows_error) == 1
    assert "fecha inválida" in result.rows_error[0].reason
    assert result.header_row_number == 3  # título + fila en blanco + cabecera

    commit_result = await commit_treatments_import(db_session, result.token)
    assert commit_result["inserted"] == 3

    inserted = (
        await db_session.execute(select(Treatment).where(Treatment.parcel_id == parcel.id))
    ).scalars().all()
    assert len(inserted) == 3
    # El resumen climático congelado debe existir aunque no haya histórico ERA5-Land
    # (se declara explícitamente como no disponible, nunca se omite el campo).
    assert all(t.climate_context_frozen is not None for t in inserted)

    # limpieza para que el test sea repetible
    await db_session.execute(delete(Treatment).where(Treatment.parcel_id == parcel.id))
    await db_session.execute(delete(ImportBatch).where(ImportBatch.token == result.token))
    await db_session.commit()


async def test_commit_rejects_unknown_token(db_session):
    import uuid

    try:
        await commit_treatments_import(db_session, uuid.uuid4())
        assert False, "debía lanzar ValueError para un token desconocido"
    except ValueError:
        pass
