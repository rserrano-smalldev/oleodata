"""Prueba la función SQL effective_distance_km del módulo 2 (no una
reimplementación en Python: la función real que usa la consulta espacial de
descubrimiento de fuentes)."""

import math

from sqlalchemy import text

from app.db import engine


async def test_effective_distance_matches_expected_formula():
    async with engine.connect() as conn:
        value = (await conn.execute(text("SELECT effective_distance_km(10, 100)"))).scalar_one()
    expected = math.sqrt(10**2 + (100 * 0.1) ** 2)  # sqrt(100+100) ≈ 14.142
    assert abs(value - expected) < 1e-6


async def test_effective_distance_with_zero_elevation_diff_equals_horizontal():
    async with engine.connect() as conn:
        value = (await conn.execute(text("SELECT effective_distance_km(25, 0)"))).scalar_one()
    assert abs(value - 25.0) < 1e-9


async def test_effective_distance_with_zero_horizontal_scales_with_elevation():
    async with engine.connect() as conn:
        value = (await conn.execute(text("SELECT effective_distance_km(0, 500)"))).scalar_one()
    assert abs(value - 50.0) < 1e-9  # 500 m * 0.1 = 50 km equivalentes


async def test_effective_distance_is_symmetric_in_sign_of_elevation_diff():
    async with engine.connect() as conn:
        positive = (await conn.execute(text("SELECT effective_distance_km(10, 150)"))).scalar_one()
        negative = (await conn.execute(text("SELECT effective_distance_km(10, -150)"))).scalar_one()
    assert abs(positive - negative) < 1e-9
