"""Frontera de negocio explícita (ver módulo 4 del encargo): el motor de
recomendaciones NUNCA prescribe producto, materia activa ni dosis — solo
dice cuándo muestrear, cuándo vigilar y cuándo consultar al técnico.

Esta comprobación se usa (a) como red de seguridad antes de devolver
cualquier texto de /v1/parcels/{id}/recommendations, y (b) en el test que
verifica que la frontera se respeta (tests/test_recommendations_safety.py).
"""

import re

# Fragmentos de nombres de materias activas/familias de producto fitosanitario
# habituales en cuadernos de campo de olivar español. No es exhaustivo: es una
# red de seguridad, no un validador legal.
_ACTIVE_SUBSTANCE_FRAGMENTS = [
    "glifosato", "mancozeb", "oxicloruro de cobre", "clorpirifos", "deltametrin",
    "spinosad", "imidacloprid", "azufre mojable", "cobre", "fosetil", "metil tiofanato",
    "ciproconazol", "tebuconazol", "lambda-cihalotrin", "acetamiprid", "abamectina",
]

# Patrones de dosis con unidades de producto fitosanitario, p.ej. "2 l/ha", "500 g/hl".
_DOSE_PATTERN = re.compile(
    r"\d+([.,]\d+)?\s?(kg|g|l|cc|ml)\s?/\s?(ha|hl)", re.IGNORECASE
)


def contains_phytosanitary_content(text: str) -> bool:
    if not text:
        return False
    lowered = text.lower()
    if any(fragment in lowered for fragment in _ACTIVE_SUBSTANCE_FRAGMENTS):
        return True
    if _DOSE_PATTERN.search(lowered):
        return True
    return False


def assert_no_phytosanitary_content(*texts: str) -> None:
    for text in texts:
        if contains_phytosanitary_content(text):
            raise AssertionError(
                "Violación de la frontera de negocio: el texto de una recomendación "
                f"contiene contenido que parece materia activa o dosis fitosanitaria: {text!r}"
            )
