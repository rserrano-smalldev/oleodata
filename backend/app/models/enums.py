import enum


class AggregationType(str, enum.Enum):
    instant = "instant"
    sum = "sum"
    mean = "mean"
    min = "min"
    max = "max"


class ProviderType(str, enum.Enum):
    station_network = "station_network"
    reanalysis = "reanalysis"
    simulated_sensor = "simulated_sensor"
    forecast = "forecast"


class QualityFlag(str, enum.Enum):
    ok = "ok"
    estimated = "estimated"
    suspect = "suspect"
    missing = "missing"


class SourceRole(str, enum.Enum):
    primary = "primary"
    secondary = "secondary"
    backfill = "backfill"
    fallback = "fallback"


class SusceptibilityLevel(str, enum.Enum):
    altamente_resistente = "altamente_resistente"
    resistente = "resistente"
    moderada = "moderada"
    susceptible = "susceptible"
    altamente_susceptible = "altamente_susceptible"


class EvidenceLevel(str, enum.Enum):
    ensayo_de_campo = "ensayo_de_campo"
    controlado = "controlado"
    literatura = "literatura"
    experto = "experto"
    desconocida = "desconocida"


class TreatmentCategory(str, enum.Enum):
    fungicida = "fungicida"
    insecticida = "insecticida"
    herbicida = "herbicida"
    abono = "abono"
    foliar = "foliar"
    riego = "riego"
    poda = "poda"
    otro = "otro"


class SensorizationStatus(str, enum.Enum):
    simulada_demo = "simulada_demo"
    sensores_propios_activos = "sensores_propios_activos"


class ImportBatchStatus(str, enum.Enum):
    previewed = "previewed"
    committed = "committed"
    expired = "expired"
