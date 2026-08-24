"""Orquestador del módulo 4: junta GDD/Prays, repilo, helada y balance
hídrico, pasa cada amenaza por el motor de modulación varietal, y devuelve
el resultado que sirve /v1/parcels/{id}/recommendations.

FRONTERA DE NEGOCIO: el resultado es siempre un nivel de atención y una
acción sugerida ("vigilar" / "muestrear en 48h" / "consultar al técnico"),
nunca un producto, materia activa o dosis. Se verifica con
`safety_guard.assert_no_phytosanitary_content` antes de devolver cualquier
texto.

Alcance deliberadamente limitado: verticilosis, antracnosis y mosca del
olivo tienen ficha varietal estática (ver /v1/varieties) pero NINGÚN modelo
climático dinámico en este MVP — no se ha encontrado una fórmula agronómica
simple y fiable para ellas que no implicara inventar umbrales. Se declara
así en la respuesta, no se aparenta cobertura que no existe.
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.catalog import Variable
from app.models.parcel import Parcel
from app.models.timeseries import Observation, Source
from app.models.variety import Threat, VarietySusceptibility
from app.services.agronomy import frost as frost_mod
from app.services.agronomy import gdd as gdd_mod
from app.services.agronomy import repilo as repilo_mod
from app.services.agronomy import water_balance as wb_mod
from app.services.agronomy.safety_guard import assert_no_phytosanitary_content
from app.services.agronomy.varietal_modulation import modulate_risk

NOT_DYNAMICALLY_MODELED_THREATS = ["verticilosis", "antracnosis", "mosca_olivo"]

PRAYS_REFERENCE_GDD_THRESHOLD = 400.0
WATER_BALANCE_LOOKBACK_DAYS = 30

DISCLAIMER = (
    "Los umbrales de estos modelos son valores de partida de literatura agronómica "
    "general (FAO-56 y modelos fenológicos publicados), no calibrados con datos de "
    "campo de esta explotación. El resultado es orientativo: indica cuándo muestrear "
    "o vigilar, nunca sustituye el asesoramiento de un técnico ni prescribe producto, "
    "materia activa o dosis."
)


class MissingDataError(ValueError):
    pass


DAILY_MINMAX_SQL = text(
    """
    SELECT (timestamp AT TIME ZONE 'UTC')::date AS day, min(value) AS t_min, max(value) AS t_max
    FROM observation
    WHERE source_id = :source_id AND variable_id = :variable_id
      AND timestamp >= :start AND timestamp < :end
    GROUP BY day ORDER BY day
    """
)

DAILY_SUM_SQL = text(
    """
    SELECT (timestamp AT TIME ZONE 'UTC')::date AS day, sum(value) AS total
    FROM observation
    WHERE source_id = :source_id AND variable_id = :variable_id
      AND timestamp >= :start AND timestamp < :end
    GROUP BY day ORDER BY day
    """
)


@dataclass
class RecommendationsResult:
    day: date
    variety_code: str | None
    threats: list[dict]
    water_balance: dict | None
    not_dynamically_modeled_threats: list[str]
    disclaimer: str
    warnings: list[str]


async def get_variable_ids(session: AsyncSession) -> dict[str, int]:
    return dict((await session.execute(select(Variable.code, Variable.id))).all())


async def _get_source(session: AsyncSession, code: str) -> Source | None:
    return (await session.execute(select(Source).where(Source.code == code))).scalar_one_or_none()


async def _susceptibility_map(session: AsyncSession, variety_id: int | None) -> dict:
    if variety_id is None:
        return {}
    rows = (
        await session.execute(
            select(
                Threat.code,
                VarietySusceptibility.susceptibility_level,
                VarietySusceptibility.evidence_level,
            )
            .join(VarietySusceptibility, VarietySusceptibility.threat_id == Threat.id)
            .where(VarietySusceptibility.variety_id == variety_id)
        )
    ).all()
    return {code: (level, evidence) for code, level, evidence in rows}


def _utc(d: date) -> datetime:
    return datetime.combine(d, datetime.min.time(), tzinfo=timezone.utc)


async def build_recommendations(session: AsyncSession, parcel: Parcel, day: date) -> RecommendationsResult:
    var_ids = await get_variable_ids(session)
    era5_source = await _get_source(session, f"era5_land:parcel:{parcel.id}")
    sim_source = await _get_source(session, f"sim_sensor_v1:parcel:{parcel.id}")

    if era5_source is None:
        raise MissingDataError(
            "No hay histórico ERA5-Land para esta parcela: ejecuta antes "
            "POST /v1/parcels/{id}/backfill."
        )

    susceptibility_map = await _susceptibility_map(session, parcel.variety_id)
    variety_code = parcel.variety.code if parcel.variety else None

    warnings: list[str] = []
    threats_out: list[dict] = []

    # --- Prays oleae: GDD acumulado desde el 1 de enero del año de `day` ---
    year_start = date(day.year, 1, 1)
    minmax_rows = (
        await session.execute(
            DAILY_MINMAX_SQL,
            {
                "source_id": era5_source.id,
                "variable_id": var_ids["temperature_2m"],
                "start": _utc(year_start),
                "end": _utc(day + timedelta(days=1)),
            },
        )
    ).all()

    if minmax_rows:
        cumulative_gdd = gdd_mod.accumulate_gdd([(row.t_min, row.t_max) for row in minmax_rows])
        prays_raw_pressure = min(1.0, cumulative_gdd / PRAYS_REFERENCE_GDD_THRESHOLD)
        level, evidence = susceptibility_map.get("prays", (None, None))
        result = modulate_risk("prays", prays_raw_pressure, variety_code, level, evidence)
        assert_no_phytosanitary_content(result.explanation, result.suggested_action)
        threats_out.append(
            {
                "threat_code": "prays",
                "attention_level": result.attention_level,
                "suggested_action": result.suggested_action,
                "explanation": result.explanation,
                "evidence_level": result.evidence_level,
                "evidence_downgrade_applied": result.evidence_downgrade_applied,
                "model_detail": {
                    "cumulative_gdd_since_jan1": round(cumulative_gdd, 1),
                    "reference_threshold_gdd": PRAYS_REFERENCE_GDD_THRESHOLD,
                    "note": (
                        "umbral de referencia orientativo de literatura general, pendiente "
                        "de calibrar con capturas de trampeo reales de la finca"
                    ),
                },
            }
        )
    else:
        warnings.append("Sin histórico ERA5-Land suficiente para calcular grados-día de Prays oleae.")

    # --- Helada: temperatura mínima real del día `day` ---
    day_row = next((row for row in minmax_rows if row.day == day), None)
    if day_row is None:
        single_day_rows = (
            await session.execute(
                DAILY_MINMAX_SQL,
                {
                    "source_id": era5_source.id,
                    "variable_id": var_ids["temperature_2m"],
                    "start": _utc(day),
                    "end": _utc(day + timedelta(days=1)),
                },
            )
        ).all()
        day_row = single_day_rows[0] if single_day_rows else None

    if day_row is not None:
        frost_assessment = frost_mod.assess_frost_risk(day_row.t_min, day.month)
        frost_raw_pressure = {"ninguno": 0.1, "dano_posible": 0.55, "dano_severo": 0.9}[
            frost_assessment.risk_level
        ]
        level, evidence = susceptibility_map.get("helada", (None, None))
        result = modulate_risk("helada", frost_raw_pressure, variety_code, level, evidence)
        assert_no_phytosanitary_content(result.explanation, result.suggested_action)
        threats_out.append(
            {
                "threat_code": "helada",
                "attention_level": result.attention_level,
                "suggested_action": result.suggested_action,
                "explanation": result.explanation,
                "evidence_level": result.evidence_level,
                "evidence_downgrade_applied": result.evidence_downgrade_applied,
                "model_detail": {
                    "phenophase": frost_assessment.phase,
                    "daily_min_temp_c": round(day_row.t_min, 1),
                    "damage_threshold_c": frost_assessment.damage_threshold_c,
                    "severe_threshold_c": frost_assessment.severe_threshold_c,
                },
            }
        )
    else:
        warnings.append("Sin histórico ERA5-Land para el día solicitado: no se puede evaluar riesgo de helada.")

    # --- Repilo: requiere humectación foliar SIMULADA (módulo 3) ---
    if sim_source is None:
        warnings.append(
            "Sin lecturas de sensor simulado para esta parcela: no se puede evaluar riesgo "
            "de repilo (depende de humectación foliar, que ninguna fuente real cubre). "
            "Ejecuta antes POST /v1/parcels/{id}/simulate-sensors."
        )
    else:
        window_start = _utc(day - timedelta(days=4))
        window_end = _utc(day + timedelta(days=1))
        rows = (
            await session.execute(
                select(Observation.timestamp, Observation.variable_id, Observation.value)
                .where(Observation.source_id == sim_source.id)
                .where(Observation.variable_id.in_([var_ids["leaf_wetness"], var_ids["temperature_2m"]]))
                .where(Observation.timestamp >= window_start)
                .where(Observation.timestamp < window_end)
                .order_by(Observation.timestamp)
            )
        ).all()

        wetness_by_ts: dict = {}
        temp_by_ts: dict = {}
        for ts, vid, value in rows:
            if vid == var_ids["leaf_wetness"]:
                wetness_by_ts[ts] = value
            else:
                temp_by_ts[ts] = value

        timestamps = sorted(set(wetness_by_ts) & set(temp_by_ts))
        if len(timestamps) < 2:
            warnings.append(
                "No hay suficientes lecturas de sensor simulado en los días previos para "
                "evaluar repilo."
            )
        else:
            samples = []
            for i, ts in enumerate(timestamps):
                step_hours = 0.25 if i == 0 else (ts - timestamps[i - 1]).total_seconds() / 3600.0
                samples.append((step_hours, wetness_by_ts[ts], temp_by_ts[ts]))

            longest_hours, mean_temp = repilo_mod.find_longest_wet_spell(samples)
            assessment = repilo_mod.assess_repilo_risk(longest_hours, mean_temp)
            repilo_raw_pressure = min(1.0, assessment.pressure_ratio * 0.5)
            level, evidence = susceptibility_map.get("repilo", (None, None))
            result = modulate_risk("repilo", repilo_raw_pressure, variety_code, level, evidence)
            assert_no_phytosanitary_content(result.explanation, result.suggested_action)
            threats_out.append(
                {
                    "threat_code": "repilo",
                    "attention_level": result.attention_level,
                    "suggested_action": result.suggested_action,
                    "explanation": result.explanation,
                    "evidence_level": result.evidence_level,
                    "evidence_downgrade_applied": result.evidence_downgrade_applied,
                    "model_detail": {
                        "longest_continuous_wetness_hours": round(longest_hours, 1),
                        "mean_temp_during_wetness_c": round(mean_temp, 1),
                        "required_hours_for_infection": (
                            None if assessment.required_hours == float("inf") else round(assessment.required_hours, 1)
                        ),
                        "infection_triggered": assessment.infection_triggered,
                        "data_basis": "humectación foliar SIMULADA (módulo 3), no medición real",
                    },
                }
            )

    # --- Balance hídrico (no es una amenaza catalogada: indicador general) ---
    water_balance_out = None
    precip_rows = (
        await session.execute(
            DAILY_SUM_SQL,
            {
                "source_id": era5_source.id,
                "variable_id": var_ids["precipitation"],
                "start": _utc(day - timedelta(days=WATER_BALANCE_LOOKBACK_DAYS)),
                "end": _utc(day + timedelta(days=1)),
            },
        )
    ).all()
    et0_rows = (
        await session.execute(
            DAILY_SUM_SQL,
            {
                "source_id": era5_source.id,
                "variable_id": var_ids["et0_fao_evapotranspiration"],
                "start": _utc(day - timedelta(days=WATER_BALANCE_LOOKBACK_DAYS)),
                "end": _utc(day + timedelta(days=1)),
            },
        )
    ).all()
    precip_by_day = {row.day: row.total for row in precip_rows}
    et0_by_day = {row.day: row.total for row in et0_rows}
    common_days = sorted(set(precip_by_day) & set(et0_by_day))

    if common_days:
        series = [(precip_by_day[d], et0_by_day[d], d.month) for d in common_days]
        steps = wb_mod.run_water_balance(series, field_capacity_mm=parcel.field_capacity_mm)
        last = steps[-1]
        ratio = last.reservoir_mm / parcel.field_capacity_mm if parcel.field_capacity_mm else 0.0
        if last.deficit_mm > 0 or ratio <= 0.2:
            status = "estres_severo"
            action = "planificar riego"
        elif ratio <= 0.5:
            status = "estres_moderado"
            action = "vigilar necesidad de riego"
        else:
            status = "sin_estres"
            action = "sin acción de riego necesaria por clima"
        assert_no_phytosanitary_content(action)
        water_balance_out = {
            "status": status,
            "suggested_action": action,
            "reservoir_mm": round(last.reservoir_mm, 1),
            "field_capacity_mm": parcel.field_capacity_mm,
            "deficit_mm": round(last.deficit_mm, 1),
            "lookback_days": len(common_days),
            "note": (
                "depósito único FAO-56, se asume el depósito lleno al inicio de la ventana "
                "de cálculo si no hay dato de partida real"
            ),
        }
    else:
        warnings.append("Sin histórico suficiente de precipitación/ET0 para calcular el balance hídrico.")

    return RecommendationsResult(
        day=day,
        variety_code=variety_code,
        threats=threats_out,
        water_balance=water_balance_out,
        not_dynamically_modeled_threats=NOT_DYNAMICALLY_MODELED_THREATS,
        disclaimer=DISCLAIMER,
        warnings=warnings,
    )
