"""Catálogo varietal y susceptibilidad frente a amenazas.

AVISO IMPORTANTE (léelo antes de usar estos datos en producción):
Estas calificaciones parten de caracterizaciones ampliamente repetidas en
bibliografía divulgativa y boletines fitosanitarios españoles (IFAPA, RAIF/
Junta de Andalucía, literatura universitaria sobre Verticillium dahliae en
olivar). Se han elegido de forma conservadora: solo se incluye una
combinación variedad-amenaza cuando hay una caracterización razonablemente
consistente y ampliamente citada; cuando no se ha localizado una fuente
verificable la fila se omite directamente, o se incluye con
evidence_level='desconocida' y un nivel neutro, nunca se inventa un dato.

Ninguna de estas referencias es una cita bibliográfica primaria verificada
línea a línea por este proyecto: `source_reference` describe el TIPO de
fuente, no un DOI o página concretos. Antes de un uso productivo real, estos
datos deben cotejarse con las publicaciones primarias del Banco Mundial de
Germoplasma de Olivo (IFAPA, Centro Alameda del Obispo, Córdoba), la
Universidad de Córdoba y los boletines de la RAIF (Red de Alerta e
Información Fitosanitaria) de la Junta de Andalucía.

Deliberadamente NO se incluyen calificaciones varietales frente a mosca del
olivo (Bactrocera oleae) ni Prays oleae: la susceptibilidad relativa entre
variedades para estas dos plagas depende mucho de fenología de maduración y
características del fruto, y no se ha localizado una caracterización
suficientemente sólida por variedad para incluirla sin inventar. El motor de
modulación varietal (módulo 4) aplica un ajuste neutro cuando no hay fila de
susceptibilidad, así que el sistema sigue funcionando para esas amenazas.
"""

GENERIC_LITERATURE_NOTE = (
    "Caracterización recogida de forma reiterada en bibliografía divulgativa/"
    "boletines fitosanitarios españoles; pendiente de verificar contra la "
    "publicación primaria antes de uso productivo."
)

VARIETIES = [
    {"code": "picual", "name": "Picual", "origin_region": "Jaén (Andalucía)"},
    {"code": "hojiblanca", "name": "Hojiblanca", "origin_region": "Córdoba/Málaga (Andalucía)"},
    {"code": "arbequina", "name": "Arbequina", "origin_region": "Lleida (Cataluña)"},
    {"code": "cornicabra", "name": "Cornicabra", "origin_region": "Toledo/Ciudad Real (Castilla-La Mancha)"},
    {"code": "manzanilla_sevilla", "name": "Manzanilla de Sevilla", "origin_region": "Sevilla (Andalucía)"},
    {"code": "manzanilla_cacerena", "name": "Manzanilla Cacereña", "origin_region": "Cáceres (Extremadura)"},
    {"code": "lechin_sevilla", "name": "Lechín de Sevilla", "origin_region": "Sevilla (Andalucía)"},
    {"code": "verdial_badajoz", "name": "Verdial de Badajoz", "origin_region": "Badajoz (Extremadura)"},
    {"code": "empeltre", "name": "Empeltre", "origin_region": "Aragón/Baleares"},
    {"code": "farga", "name": "Farga", "origin_region": "Castellón (Comunidad Valenciana)"},
    {"code": "blanqueta", "name": "Blanqueta", "origin_region": "Alicante (Comunidad Valenciana)"},
    {"code": "changlot_real", "name": "Changlot Real", "origin_region": "Comunidad Valenciana"},
    {"code": "picudo", "name": "Picudo", "origin_region": "Córdoba (Andalucía)"},
    {"code": "frantoio", "name": "Frantoio", "origin_region": "Toscana (Italia)"},
    {"code": "leccino", "name": "Leccino", "origin_region": "Toscana (Italia)"},
    {"code": "koroneiki", "name": "Koroneiki", "origin_region": "Creta/Peloponeso (Grecia)"},
    {"code": "kalamata", "name": "Kalamata", "origin_region": "Mesenia (Grecia)"},
    {"code": "coratina", "name": "Coratina", "origin_region": "Apulia (Italia)"},
]

THREATS = [
    {"code": "repilo", "name": "Repilo (Fusicladium oleagineum)", "description": "Enfermedad fúngica foliar; requiere humectación foliar prolongada."},
    {"code": "verticilosis", "name": "Verticilosis (Verticillium dahliae)", "description": "Enfermedad vascular de suelo, muy estudiada en germoplasma de olivo."},
    {"code": "antracnosis", "name": "Antracnosis (Colletotrichum spp.)", "description": "Afecta al fruto, favorecida por humedad en la maduración/recolección."},
    {"code": "mosca_olivo", "name": "Mosca del olivo (Bactrocera oleae)", "description": "Plaga clave del fruto."},
    {"code": "prays", "name": "Prays / polilla del olivo (Prays oleae)", "description": "Plaga con generaciones antófaga, carpófaga y filófaga."},
    {"code": "helada", "name": "Helada", "description": "Daño abiótico por temperaturas bajo cero, dependiente de fase fenológica."},
]

# (variety_code, threat_code, susceptibility_level, evidence_level, source_reference)
VARIETY_SUSCEPTIBILITY = [
    # --- Repilo ---
    ("frantoio", "repilo", "resistente", "literatura", GENERIC_LITERATURE_NOTE),
    ("koroneiki", "repilo", "resistente", "literatura", GENERIC_LITERATURE_NOTE),
    ("picual", "repilo", "moderada", "literatura", GENERIC_LITERATURE_NOTE),
    ("arbequina", "repilo", "moderada", "literatura", GENERIC_LITERATURE_NOTE),
    ("cornicabra", "repilo", "moderada", "experto", GENERIC_LITERATURE_NOTE),
    ("leccino", "repilo", "moderada", "experto", GENERIC_LITERATURE_NOTE),
    ("empeltre", "repilo", "moderada", "experto", GENERIC_LITERATURE_NOTE),
    ("hojiblanca", "repilo", "susceptible", "literatura",
     "Clasificación de sensibilidad a repilo recogida habitualmente en boletines "
     "fitosanitarios de Andalucía (RAIF); pendiente de verificar cita primaria."),
    ("lechin_sevilla", "repilo", "susceptible", "literatura", GENERIC_LITERATURE_NOTE),
    ("picudo", "repilo", "susceptible", "experto", GENERIC_LITERATURE_NOTE),
    ("manzanilla_sevilla", "repilo", "altamente_susceptible", "literatura",
     "Ampliamente citada como una de las variedades más sensibles a repilo en la "
     "bibliografía divulgativa de sanidad vegetal del olivar andaluz; pendiente "
     "de verificar cita primaria."),
    ("manzanilla_cacerena", "repilo", "susceptible", "experto", GENERIC_LITERATURE_NOTE),
    ("coratina", "repilo", "moderada", "desconocida",
     "No se ha localizado una fuente específica verificable para esta variedad; "
     "nivel provisional neutro hasta disponer de una calificación fiable."),

    # --- Verticilosis (la mejor documentada: cribados IFAPA/UCO) ---
    ("picual", "verticilosis", "altamente_susceptible", "ensayo_de_campo",
     "Los ensayos de cribado de resistencia a Verticillium dahliae del Banco de "
     "Germoplasma Mundial de Olivo (IFAPA, Centro Alameda del Obispo, Córdoba) y "
     "estudios de la Universidad de Córdoba citan reiteradamente a Picual entre "
     "las variedades comerciales más susceptibles; verificar la publicación "
     "primaria concreta antes de un uso productivo."),
    ("manzanilla_sevilla", "verticilosis", "altamente_susceptible", "ensayo_de_campo",
     "Igual que Picual, ampliamente citada como muy susceptible en los cribados "
     "de germoplasma de IFAPA/UCO; verificar publicación primaria."),
    ("arbequina", "verticilosis", "susceptible", "controlado", GENERIC_LITERATURE_NOTE),
    ("cornicabra", "verticilosis", "susceptible", "literatura", GENERIC_LITERATURE_NOTE),
    ("frantoio", "verticilosis", "moderada", "literatura", GENERIC_LITERATURE_NOTE),
    ("leccino", "verticilosis", "moderada", "experto", GENERIC_LITERATURE_NOTE),
    ("empeltre", "verticilosis", "moderada", "experto", GENERIC_LITERATURE_NOTE),
    ("koroneiki", "verticilosis", "moderada", "desconocida",
     "Referencia no verificada de forma independiente; nivel provisional."),

    # --- Antracnosis ---
    ("picual", "antracnosis", "susceptible", "experto", GENERIC_LITERATURE_NOTE),
    ("hojiblanca", "antracnosis", "moderada", "desconocida",
     "No se ha localizado una fuente específica verificable; nivel provisional neutro."),
    ("frantoio", "antracnosis", "moderada", "desconocida",
     "No se ha localizado una fuente específica verificable; nivel provisional neutro."),

    # --- Helada (tolerancia al frío, percepción de técnicos de campo) ---
    ("arbequina", "helada", "resistente", "experto",
     "Percepción extendida entre técnicos de campo de mayor rusticidad frente al "
     "frío; no se ha verificado un ensayo controlado específico."),
    ("frantoio", "helada", "resistente", "experto", GENERIC_LITERATURE_NOTE),
    ("leccino", "helada", "resistente", "experto", GENERIC_LITERATURE_NOTE),
    ("picual", "helada", "moderada", "experto", GENERIC_LITERATURE_NOTE),
    ("hojiblanca", "helada", "moderada", "experto", GENERIC_LITERATURE_NOTE),
    ("koroneiki", "helada", "susceptible", "experto",
     "Origen en clima mediterráneo cálido (Creta); percepción de menor "
     "tolerancia al frío entre técnicos, sin ensayo controlado verificado."),
]
