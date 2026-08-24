"""Balance hídrico simple (depósito único, FAO-56) para olivar.

acumula ET0 * Kc - precipitación, dentro de un depósito acotado por la
capacidad de campo del suelo de la parcela.

AVISO: los coeficientes de cultivo (Kc) mensuales son valores orientativos
de partida para olivar tradicional/secano de la bibliografía FAO-56 y
literatura regional; no están calibrados para ninguna parcela concreta y
deben ajustarse con observaciones reales antes de un uso productivo.
"""

from dataclasses import dataclass

# Kc mensual orientativo para olivar adulto (secano/tradicional).
OLIVE_KC_BY_MONTH: dict[int, float] = {
    1: 0.50, 2: 0.50, 3: 0.55, 4: 0.60, 5: 0.65, 6: 0.65,
    7: 0.60, 8: 0.55, 9: 0.55, 10: 0.50, 11: 0.50, 12: 0.50,
}


@dataclass
class WaterBalanceStep:
    reservoir_mm: float
    etc_mm: float
    deficit_mm: float  # cuánto ha faltado para llenar el depósito, 0 si no hay déficit
    surplus_mm: float  # exceso sobre capacidad de campo (drenaje), 0 si no hay exceso


def water_balance_step(
    previous_reservoir_mm: float,
    precipitation_mm: float,
    et0_mm: float,
    month: int,
    field_capacity_mm: float,
) -> WaterBalanceStep:
    kc = OLIVE_KC_BY_MONTH[month]
    etc_mm = et0_mm * kc

    raw_reservoir = previous_reservoir_mm + precipitation_mm - etc_mm

    surplus = max(0.0, raw_reservoir - field_capacity_mm)
    deficit = max(0.0, -raw_reservoir)
    reservoir = min(field_capacity_mm, max(0.0, raw_reservoir))

    return WaterBalanceStep(
        reservoir_mm=reservoir,
        etc_mm=etc_mm,
        deficit_mm=deficit,
        surplus_mm=surplus,
    )


def run_water_balance(
    daily_precip_et0_month: list[tuple[float, float, int]],
    field_capacity_mm: float,
    initial_reservoir_mm: float | None = None,
) -> list[WaterBalanceStep]:
    """daily_precip_et0_month: lista de (precipitacion_mm, et0_mm, mes) por día, en orden."""
    reservoir = initial_reservoir_mm if initial_reservoir_mm is not None else field_capacity_mm
    steps = []
    for precip, et0, month in daily_precip_et0_month:
        step = water_balance_step(reservoir, precip, et0, month, field_capacity_mm)
        steps.append(step)
        reservoir = step.reservoir_mm
    return steps
