"""Módulo 5: importador de tratamientos desde el Excel del agricultor.

El cuaderno de campo llega en el formato que le dé la gana al agricultor,
no en una plantilla fija: este importador se adapta al fichero (detecta la
fila de cabecera, mapea columnas por sinónimos, deduce el tipo de
tratamiento, normaliza fechas/números en varios formatos) en vez de exigir
que el fichero se adapte a él.

Flujo SIEMPRE en dos pasos: preview_treatments_excel() no escribe nada en
la base de datos, solo guarda las filas parseadas bajo un token en
`import_batch`; commit_treatments_import(token) es la única función que
escribe en `treatment`.
"""

import hashlib
import io
import unicodedata
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

import openpyxl
from dateutil import parser as dateutil_parser
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.parcel import Parcel
from app.models.timeseries import Source
from app.models.treatment import ImportBatch, Treatment
from app.models.enums import ImportBatchStatus
from app.services.agronomy.engine import DAILY_MINMAX_SQL, DAILY_SUM_SQL

MAX_HEADER_SCAN_ROWS = 15
IMPORT_BATCH_TTL_MINUTES = 30
EXCEL_EPOCH = date(1899, 12, 30)

SYNONYMS: dict[str, list[str]] = {
    "fecha": ["fecha", "fecha aplicacion", "fecha de aplicacion", "fecha tratamiento", "dia", "fecha trat."],
    "parcela": ["parcela", "codigo parcela", "cod parcela", "cod. parcela", "finca", "id parcela"],
    "categoria": ["categoria", "tipo", "tipo tratamiento", "tipo de tratamiento"],
    "producto": ["producto", "nombre comercial", "producto comercial", "nombre del producto"],
    "materia_activa": ["materia activa", "sustancia activa", "principio activo", "m.a."],
    "dosis_valor": ["dosis", "dosis valor", "cantidad", "cantidad aplicada"],
    "dosis_unidad": ["ud", "ud.", "unidad", "unidades", "u.m.", "unidad dosis"],
    "plaga_objetivo": ["plaga", "plaga objetivo", "objetivo", "diana", "plaga/enfermedad"],
    "coste": ["coste", "precio", "importe", "coste total", "coste (eur)"],
}

CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "fungicida": ["repilo", "cobre", "oxicloruro", "mancozeb", "azufre", "hongo", "antracnosis", "verticil", "fungicida"],
    "insecticida": ["mosca", "prays", "polilla", "insecticida", "ceratitis", "spinosad", "deltametrin", "acaro"],
    "herbicida": ["herbicida", "glifosato", "malas hierbas", "maleza"],
    "abono": ["abono", "fertiliz", "nitrogeno", "npk", "abonado"],
    "foliar": ["foliar", "quelato"],
    "riego": ["riego", "irrigacion"],
    "poda": ["poda"],
}

VALID_CATEGORIES = {"fungicida", "insecticida", "herbicida", "abono", "foliar", "riego", "poda"}


def _normalize_text(value) -> str:
    if value is None:
        return ""
    text = str(value).strip().lower()
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return text


def _build_synonym_lookup() -> dict[str, str]:
    lookup = {}
    for field_name, variants in SYNONYMS.items():
        for variant in variants:
            normalized = _normalize_text(variant)
            if normalized:  # nunca registrar la cadena vacía (p.ej. símbolos que se
                lookup[normalized] = field_name  # pierden al quitar acentos/no-ascii)
    return lookup


_SYNONYM_LOOKUP = _build_synonym_lookup()


def detect_header_row(matrix: list[list]) -> int:
    """Encuentra la fila de cabecera real, aunque haya título/logo/filas en
    blanco por encima: elige la fila (entre las primeras MAX_HEADER_SCAN_ROWS)
    con más celdas que coinciden con algún sinónimo conocido.
    """
    best_row = 0
    best_score = -1
    for row_idx in range(min(MAX_HEADER_SCAN_ROWS, len(matrix))):
        row = matrix[row_idx]
        score = sum(1 for cell in row if _normalize_text(cell) in _SYNONYM_LOOKUP)
        if score > best_score:
            best_score = score
            best_row = row_idx
    return best_row


def map_columns(header_row: list) -> dict[str, int]:
    mapping: dict[str, int] = {}
    for col_idx, cell in enumerate(header_row):
        field_name = _SYNONYM_LOOKUP.get(_normalize_text(cell))
        if field_name and field_name not in mapping:
            mapping[field_name] = col_idx
    return mapping


def normalize_date(value) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, (int, float)):
        try:
            return EXCEL_EPOCH + timedelta(days=int(value))
        except (OverflowError, ValueError):
            return None
    text = str(value).strip()
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d/%m/%y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    try:
        return dateutil_parser.parse(text, dayfirst=True).date()
    except (ValueError, OverflowError):
        return None


def normalize_number(value) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace("€", "").replace(" ", "")
    if not text:
        return None
    if "," in text and "." in text:
        text = text.replace(".", "").replace(",", ".")
    elif "," in text:
        text = text.replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


def infer_category(raw_category, product_name, target_pest) -> str:
    normalized_raw = _normalize_text(raw_category)
    if normalized_raw in VALID_CATEGORIES:
        return normalized_raw

    haystack = " ".join(_normalize_text(v) for v in (raw_category, product_name, target_pest))
    for category, keywords in CATEGORY_KEYWORDS.items():
        if any(_normalize_text(kw) in haystack for kw in keywords):
            return category
    return "otro"


def compute_row_hash(parcel_id: int, treatment_date: date, product_name: str | None, dose_value, category: str) -> str:
    key = f"{parcel_id}|{treatment_date.isoformat()}|{_normalize_text(product_name)}|{dose_value}|{category}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


@dataclass
class RowError:
    row_number: int
    reason: str


@dataclass
class PreviewResult:
    token: uuid.UUID
    filename: str
    header_row_number: int
    column_mapping: dict[str, str]
    total_data_rows: int
    rows_ok: int
    rows_error: list[RowError] = field(default_factory=list)
    rows_duplicate: int = 0
    sample: list[dict] = field(default_factory=list)


def _read_matrix(file_bytes: bytes) -> list[list]:
    workbook = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True)
    sheet = workbook.worksheets[0]
    return [list(row) for row in sheet.iter_rows(values_only=True)]


async def preview_treatments_excel(
    session: AsyncSession, file_bytes: bytes, filename: str
) -> PreviewResult:
    matrix = _read_matrix(file_bytes)
    if not matrix:
        raise ValueError("El fichero Excel está vacío.")

    header_row_idx = detect_header_row(matrix)
    column_mapping = map_columns(matrix[header_row_idx])
    if "fecha" not in column_mapping:
        raise ValueError(
            "No se ha podido localizar una columna de fecha en el fichero (se probó con "
            "sinónimos habituales: 'Fecha', 'Fecha aplicación', 'Fecha tratamiento', 'Día'...)."
        )

    parcels = (await session.execute(select(Parcel.id, Parcel.code))).all()
    parcel_by_code = {_normalize_text(code): pid for pid, code in parcels}
    default_parcel_id = parcels[0][0] if len(parcels) == 1 else None

    existing_hashes = set(
        (await session.execute(select(Treatment.row_hash))).scalars().all()
    )
    seen_hashes_in_file: set[str] = set()

    rows_ok: list[dict] = []
    rows_error: list[RowError] = []
    rows_duplicate = 0

    data_rows = matrix[header_row_idx + 1 :]
    for i, row in enumerate(data_rows):
        excel_row_number = header_row_idx + 2 + i  # 1-indexado, como lo ve el usuario en Excel

        if row is None or all(cell in (None, "") for cell in row):
            continue  # fila totalmente vacía, no es un error

        def get(field_name):
            idx = column_mapping.get(field_name)
            return row[idx] if idx is not None and idx < len(row) else None

        raw_date = get("fecha")
        treatment_date = normalize_date(raw_date)
        if treatment_date is None:
            rows_error.append(RowError(excel_row_number, f"fecha inválida: {raw_date!r}"))
            continue

        raw_parcel_code = get("parcela")
        if raw_parcel_code is not None:
            parcel_id = parcel_by_code.get(_normalize_text(raw_parcel_code))
            if parcel_id is None:
                rows_error.append(
                    RowError(excel_row_number, f"parcela no encontrada: {raw_parcel_code!r}")
                )
                continue
        elif default_parcel_id is not None:
            parcel_id = default_parcel_id
        else:
            rows_error.append(
                RowError(
                    excel_row_number,
                    "no se indica parcela y hay varias parcelas dadas de alta: no se puede "
                    "asignar por defecto",
                )
            )
            continue

        product_name = get("producto")
        target_pest = get("plaga_objetivo")
        category = infer_category(get("categoria"), product_name, target_pest)
        dose_value = normalize_number(get("dosis_valor"))
        cost = normalize_number(get("coste"))

        row_hash = compute_row_hash(parcel_id, treatment_date, product_name, dose_value, category)
        if row_hash in existing_hashes or row_hash in seen_hashes_in_file:
            rows_duplicate += 1
            continue
        seen_hashes_in_file.add(row_hash)

        rows_ok.append(
            {
                "row_number": excel_row_number,
                "parcel_id": parcel_id,
                "date": treatment_date.isoformat(),
                "category": category,
                "product_name": str(product_name) if product_name is not None else None,
                "active_substance": get("materia_activa"),
                "dose_value": dose_value,
                "dose_unit": get("dosis_unidad"),
                "target_pest": str(target_pest) if target_pest is not None else None,
                "cost": cost,
                "row_hash": row_hash,
            }
        )

    now = datetime.now(timezone.utc)
    batch = ImportBatch(
        filename=filename,
        status=ImportBatchStatus.previewed,
        preview_payload={
            "rows_ok": rows_ok,
            "rows_error": [{"row_number": e.row_number, "reason": e.reason} for e in rows_error],
            "rows_duplicate": rows_duplicate,
            "column_mapping": column_mapping,
            "header_row_number": header_row_idx + 1,
        },
        created_at=now,
        expires_at=now + timedelta(minutes=IMPORT_BATCH_TTL_MINUTES),
    )
    session.add(batch)
    await session.commit()

    return PreviewResult(
        token=batch.token,
        filename=filename,
        header_row_number=header_row_idx + 1,
        column_mapping=column_mapping,
        total_data_rows=len(data_rows),
        rows_ok=len(rows_ok),
        rows_error=rows_error,
        rows_duplicate=rows_duplicate,
        sample=rows_ok[:10],
    )


async def _frozen_climate_context(session: AsyncSession, parcel_id: int, treatment_date: date) -> dict:
    """Resumen del clima de los 7 días previos, congelado en el momento de
    insertar el tratamiento (ver módulo 1, punto 7 del encargo).
    """
    era5_source = (
        await session.execute(select(Source).where(Source.code == f"era5_land:parcel:{parcel_id}"))
    ).scalar_one_or_none()
    if era5_source is None:
        return {"available": False, "reason": "sin histórico ERA5-Land para esta parcela"}

    from app.services.agronomy.engine import _variable_ids  # import perezoso, evita ciclo en import time

    var_ids = await _variable_ids(session)
    start = datetime.combine(treatment_date - timedelta(days=7), datetime.min.time(), tzinfo=timezone.utc)
    end = datetime.combine(treatment_date, datetime.min.time(), tzinfo=timezone.utc)

    minmax_rows = (
        await session.execute(
            DAILY_MINMAX_SQL,
            {"source_id": era5_source.id, "variable_id": var_ids["temperature_2m"], "start": start, "end": end},
        )
    ).all()
    precip_rows = (
        await session.execute(
            DAILY_SUM_SQL,
            {"source_id": era5_source.id, "variable_id": var_ids["precipitation"], "start": start, "end": end},
        )
    ).all()

    if not minmax_rows:
        return {"available": False, "reason": "sin observaciones ERA5-Land en los 7 días previos"}

    return {
        "available": True,
        "basis": "era5_land",
        "window_days": 7,
        "mean_t_min_c": round(sum(r.t_min for r in minmax_rows) / len(minmax_rows), 1),
        "mean_t_max_c": round(sum(r.t_max for r in minmax_rows) / len(minmax_rows), 1),
        "total_precipitation_mm": round(sum(r.total for r in precip_rows), 1) if precip_rows else 0.0,
    }


async def commit_treatments_import(session: AsyncSession, token: uuid.UUID) -> dict:
    batch = (await session.execute(select(ImportBatch).where(ImportBatch.token == token))).scalar_one_or_none()
    if batch is None:
        raise ValueError("Token de importación desconocido.")
    if batch.status != ImportBatchStatus.previewed:
        raise ValueError(f"Este lote ya no está pendiente de confirmar (estado: {batch.status.value}).")
    if batch.expires_at < datetime.now(timezone.utc):
        batch.status = ImportBatchStatus.expired
        await session.commit()
        raise ValueError("La previsualización ha caducado, vuelve a subir el fichero.")

    rows_ok = batch.preview_payload["rows_ok"]
    inserted = 0
    for row in rows_ok:
        treatment_date = date.fromisoformat(row["date"])
        climate_context = await _frozen_climate_context(session, row["parcel_id"], treatment_date)
        session.add(
            Treatment(
                parcel_id=row["parcel_id"],
                date=treatment_date,
                category=row["category"],
                product_name=row["product_name"],
                active_substance=row["active_substance"],
                dose_value=row["dose_value"],
                dose_unit=row["dose_unit"],
                target_pest=row["target_pest"],
                cost=row["cost"],
                climate_context_frozen=climate_context,
                import_batch_id=batch.token,
                row_hash=row["row_hash"],
            )
        )
        inserted += 1

    batch.status = ImportBatchStatus.committed
    await session.commit()

    return {"inserted": inserted, "batch_token": str(token)}
