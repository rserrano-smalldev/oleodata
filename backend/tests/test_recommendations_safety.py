"""Verifica la frontera de negocio del módulo 4: el motor de recomendaciones
nunca debe emitir nombres de materias activas ni dosis con unidades de
producto fitosanitario."""

from app.services.agronomy.engine import DISCLAIMER
from app.services.agronomy.safety_guard import contains_phytosanitary_content
from app.services.agronomy.varietal_modulation import ACTION_BY_LEVEL


def test_detects_active_substance_names():
    assert contains_phytosanitary_content("Aplicar glifosato en la parcela") is True


def test_detects_dose_patterns_with_product_units():
    assert contains_phytosanitary_content("Se recomienda 2 l/ha de producto") is True
    assert contains_phytosanitary_content("Dosis: 500 g/hl") is True


def test_clean_recommendation_text_passes():
    assert contains_phytosanitary_content("Consultar al técnico en 48h") is False
    assert contains_phytosanitary_content("Vigilar de cerca en los próximos días") is False


def test_all_suggested_actions_are_free_of_phytosanitary_content():
    for action in ACTION_BY_LEVEL.values():
        assert not contains_phytosanitary_content(action)


def test_disclaimer_is_free_of_phytosanitary_content():
    assert not contains_phytosanitary_content(DISCLAIMER)
