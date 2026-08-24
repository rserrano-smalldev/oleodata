# OleaData — MVP

Plataforma de decisión agronómica para olivar. Este repositorio es el **MVP
de demostración**, no el sistema completo. Léete la sección
[Qué es real y qué es simulado](#qué-es-real-y-qué-es-simulado-en-este-mvp)
antes de enseñárselo a nadie: es la parte más importante de este documento.

## Qué resuelve

Dadas las coordenadas de una parcela de olivar, el sistema:

1. **Reconstruye el histórico climático** de esa parcela sin instalar nada
   (vía ERA5-Land / Open-Meteo, real).
2. Cruza ese histórico con el **cuaderno de campo** de tratamientos del
   agricultor (importado desde su Excel, en el formato que ya tenga).
3. Da una **recomendación de riesgo fitosanitario** ajustada a la variedad
   de olivo plantada.

**Frontera de negocio, intencionada y no negociable:** el sistema nunca
prescribe producto, materia activa ni dosis. Solo dice cuándo muestrear,
cuándo vigilar y cuándo consultar al técnico. Esto se aplica en el motor
de recomendaciones y se verifica con un test (`tests/test_recommendations_safety.py`)
que falla si aparece una materia activa o una dosis con unidades de
producto fitosanitario en cualquier texto de respuesta.

## Qué es real y qué es simulado en este MVP

| Dato | Estado | Detalle |
|---|---|---|
| Histórico climático diario/horario | **REAL** | Open-Meteo Historical Weather API, modelo ERA5-Land, CC BY 4.0, sin API key, resolución ~9 km, desde 1950. Se importan automáticamente los últimos 5 años al dar de alta la parcela; hasta 25 años bajo demanda. |
| Previsión de los próximos 7 días | **REAL** | Open-Meteo Forecast API, sin API key. Se reemplaza por completo cada vez que se refresca (no se acumula como el histórico). Usada por el motor de recomendaciones para días futuros. |
| Altitud de la parcela | **REAL** | API de elevación de Open-Meteo, resuelta en el alta de la parcela (nunca hardcodeada). |
| Lecturas de sensor de parcela (temperatura, precipitación, humectación foliar) a resolución de 15 min | **100% SIMULADO** | No hay hardware instalado. Ver [módulo 3](#módulo-3--simulador-de-sensores). Etiquetado como tal en BD (`source.is_simulated`, `data_provider.type='simulated_sensor'`), en la API (`is_simulated: true`) y en la interfaz (badge naranja "SIMULADO"). |
| Estación RIA (Red de Información Agroclimática de Andalucía) | **REAL, solo si hay una estación a &lt;15 km** | API pública de la Junta de Andalucía, sin API key. Ver [RIA](#red-de-información-agroclimática-de-andalucía-ria). Si hay una estación real cerca, su histórico diario se usa con prioridad sobre ERA5-Land (estación real > reanálisis). Solo cubre Andalucía. No mide humectación foliar; su radiación/ET0 no se mapean (unidades no verificadas). |
| Redes de estaciones regionales (AEMET, SIAR) | **NO IMPLEMENTADO** | Catalogadas en `data_provider` con `has_adapter=false` para que la arquitectura las soporte sin migrar nada, pero no aportan ningún dato en este MVP. |
| Umbrales de los modelos agronómicos (GDD, repilo, helada, Kc) | **Valores de partida de literatura general** | No calibrados con datos de campo de ninguna explotación real. Ver [módulo 4](#módulo-4--modelos-agronómicos). |
| Susceptibilidad varietal | **Caracterización de bibliografía divulgativa, no citas primarias verificadas línea a línea** | Ver el aviso completo en `backend/app/seed/varieties.py`. |

La ficha de cada parcela muestra siempre un estado explícito:
`Sensorización: simulada (demo)` o `Sensorización: sensores propios activos`,
preparado para cuando haya hardware real sin rediseñar nada.

## Finca de referencia

Todas las pruebas y capturas de este README usan:

- Latitud: `38.521823062719164`
- Longitud: `-5.159543633627551`
- Zona: Los Pedroches, Córdoba. Penillanura, ~540-550 m (la altitud real se
  resuelve vía Open-Meteo en el alta, no está hardcodeada en ningún sitio).

La lógica de descubrimiento de fuentes (módulo 2) no tiene nada específico
de esta finca ni de España: funciona para cualquier punto del planeta,
porque ERA5-Land es global.

## Arquitectura

```
┌─────────────┐      ┌──────────────────┐      ┌─────────────────────────┐
│  Frontend   │─────▶│   API (FastAPI)  │─────▶│ PostgreSQL 16            │
│  HTMX+Jinja2│ HTTP │   SQLAlchemy 2.x │ SQL  │ + TimescaleDB (hypertable│
│  :5180      │      │   async :8420    │      │   de `observation`)      │
└─────────────┘      └──────────────────┘      │ + PostGIS (geografía)    │
                              │                  └─────────────────────────┘
                              │ HTTP real, sin API key
                              ▼
                    Open-Meteo (archive-api + elevation)
```

## Stack

- Backend: Python 3.12, FastAPI, SQLAlchemy 2.x async (asyncpg), GeoAlchemy2.
- Base de datos: PostgreSQL 16 + TimescaleDB + PostGIS, imagen oficial
  `timescale/timescaledb-ha:pg16-all-oss` (la variante "-all" trae PostGIS
  ya instalado junto con TimescaleDB; es la combinación mantenida
  oficialmente por Timescale, el repositorio `timescale/timescaledb-postgis`
  quedó descontinuado).
- Sin Alembic: el esquema se crea de forma **idempotente** en el arranque de
  la API (`app/bootstrap.py`, `CREATE ... IF NOT EXISTS` / `ON CONFLICT DO
  NOTHING` en todas partes). Es una decisión deliberada para un MVP que
  itera rápido: Alembic es el paso natural siguiente cuando el esquema deje
  de cambiar en cada sesión de desarrollo.
- Frontend: **HTMX + Jinja2 server-side + JS vanilla + Chart.js**, en su
  propio contenedor ligero (BFF que llama a la API interna). Se descartó
  React/Vite para el MVP porque exige un pipeline de build de Node y una
  capa extra de estado en el cliente que no aporta nada a una demo de 15
  minutos; HTMX cubre las interacciones tipo formulario (descubrimiento de
  fuentes, importación de Excel) con cero JavaScript, y donde hacía falta
  dibujar gráficas (Chart.js) o mantener un token entre pasos (importación
  en dos fases) se usó JavaScript plano con `fetch()` en vez de forzar todo
  a fragmentos HTMX. Es una superficie de frontend deliberadamente pequeña.
- Todo en Docker Compose: `db`, `api`, `frontend`.
- Sin autenticación compleja: un único usuario admin por variable de
  entorno (`ADMIN_USERNAME`/`ADMIN_PASSWORD` en `.env`), sin uso real
  todavía en el MVP (no hay pantallas protegidas). OAuth/multiusuario queda
  fuera de alcance.

## Arrancar

Requiere Docker Desktop (con backend de Linux; confirmable con `docker info`).

```bash
cp .env.example .env
./dev.sh up
# o: make up
```

- API y documentación OpenAPI: http://localhost:8420/docs
- Frontend: http://localhost:5180
- Postgres: localhost:5480 (usuario/clave en `.env`)

El primer arranque tarda un poco más porque construye las tres imágenes.
La API no arranca hasta que Postgres pasa su healthcheck
(`depends_on: condition: service_healthy`).

Comandos habituales (`./dev.sh <comando>` o `make <comando>`):

| Comando | Qué hace |
|---|---|
| `up` | Construye y levanta todo en segundo plano |
| `down` | Para los contenedores (conserva los datos) |
| `logs [servicio]` | Sigue los logs |
| `reset-db` | **Borra el volumen de Postgres** (`docker compose down -v`) y arranca limpio |
| `seed` | Vuelve a ejecutar el seed de catálogos (idempotente) |
| `test` | Ejecuta la suite de tests dentro del contenedor de la API |
| `shell-db` / `shell-api` | Abren una shell dentro del contenedor correspondiente |

Para borrarlo todo a mano sin el script:

```bash
docker compose down -v   # borra también el volumen oleodata_pgdata
docker compose up --build -d
```

## Recorrido de la demo (criterios de aceptación)

1. Abre http://localhost:5180, pulsa **"Descubrir fuentes de datos"** con
   las coordenadas de la finca de referencia precargadas. Debe aparecer
   `Open-Meteo Historical Weather API (ERA5-Land)` con rol `primary`, y un
   aviso de que no hay ninguna red regional implementada.
2. Crea la parcela (código, nombre, variedad opcional): al crearla se
   importan automáticamente los últimos 5 años de histórico real, y lo
   verás confirmado en un aviso al entrar en su panel.
3. Usa el filtro de histórico (rango de fechas + variables) y comprueba
   que la tabla paginada muestra los datos filtrados; pulsa "Importar
   histórico completo (25 años)" si quieres profundizar más atrás.
4. Pulsa **"Simular sensores del último mes"**: genera lecturas sintéticas
   cada 15 minutos, claramente etiquetadas como `SIMULADO`, con el sesgo de
   ese sensor mostrado en pantalla; fíltralas igual que el histórico.
5. Pulsa **"Traer previsión (7 días)"** y comprueba la tabla de previsión
   real. Elige un día futuro en el selector de recomendaciones: la
   respuesta debe indicar `data_basis: prevision`.
6. Asigna la variedad **Hojiblanca** y mira el nivel de riesgo de repilo del
   día evaluado; cámbiala a **Frantoio** (más resistente en la ficha
   varietal) y comprueba que el nivel de atención baja para el mismo día.
7. Ve a "Importar tratamientos desde Excel", sube un fichero con al menos
   una fila con fecha inválida: la previsualización debe reportar el error
   por número de fila sin bloquear la importación del resto, y solo se
   escribe en base de datos al confirmar.

## Módulos

### Módulo 1 — Esquema de datos

- `observation`: **una única tabla** de series temporales, formato largo
  `(timestamp, source_id, variable_id, value, quality_flag)`, hypertable de
  TimescaleDB. Índice/clave primaria compuesta que hace cada INSERT
  idempotente (`ON CONFLICT DO NOTHING`).
- `variable`: catálogo desnormalizado (código, unidad, tipo de agregación,
  rango válido). Añadir una variable = un INSERT.
- `data_provider` + `station`: catálogo de proveedores (`station_network` /
  `reanalysis` / `simulated_sensor`) con prioridad base, adaptador Python
  (`adapter_name`) y si tiene o no adaptador implementado.
- `source`: liga un `data_provider` con una parcela o estación concreta;
  es la fila que sabe si un dato es real o simulado (`is_simulated`,
  `metadata_json`).
- `parcel`, `olive_variety`, `threat`, `variety_susceptibility` (con
  `susceptibility_level` **y** `evidence_level` siempre informados — nunca
  se omite la evidencia, y si no hay dato fiable se usa `desconocida` con
  nivel neutro en vez de inventar).
- `treatment`: cuaderno de campo, con `climate_context_frozen` (JSON)
  congelado en el momento de la inserción con el resumen del clima de los
  7 días previos.
- `import_batch`: soporta el flujo de importación en dos pasos del módulo 5.

### Módulo 2 — Descubrimiento de fuentes climáticas

Dado un punto, encuentra qué proveedores lo cubren y los puntúa. La pieza
clave es una función SQL reutilizable:

```sql
effective_distance_km(horizontal_km, elevation_diff_m) =
    sqrt(horizontal_km² + (elevation_diff_m × 0.1)²)
```

(el factor 0.1 aproxima el gradiente térmico vertical de ~0.65 °C/100 m).
Se marca `needs_review=true` (no se activa automáticamente) si el desnivel
supera 150 m o la distancia horizontal 25 km, y se declara explícitamente
que el sistema no evalúa barreras orográficas intermedias.

Adaptadores reales implementados en `app/services/openmeteo_client.py`:

- **Open-Meteo / ERA5-Land** (histórico): llamadas HTTP reales, troceadas en
  bloques de 5 años, guardadas siempre en UTC, con conversión de humedad de
  suelo de fracción a porcentaje. Al dar de alta una parcela se importan
  automáticamente los últimos `initial_backfill_years_back` años (5 por
  defecto). Dos formas de traer más histórico después:
  `POST /v1/parcels/{id}/backfill/sync` (solo lo que falta desde el último
  dato guardado hasta hoy — idempotente, rápido) y
  `POST /v1/parcels/{id}/backfill?years_back=N` (vuelve a pedir N años
  completos, para profundizar el histórico).
- **Open-Meteo Forecast API** (previsión, `POST /v1/parcels/{id}/fetch-forecast`):
  trae los próximos `forecast_days_ahead` días (7 por defecto). A diferencia
  del histórico, sus observaciones se **reemplazan por completo** en cada
  refresco (`data_provider.type='forecast'`, prioridad peor que ERA5-Land
  para que un histórico ya confirmado nunca sea sobrescrito por una
  previsión en el raro caso de solape de un día).

AEMET/SIAR están catalogados con `has_adapter=false`: la arquitectura los
soporta sin refactorizar nada el día que se añadan. RIA sí tiene adaptador
real — ver la sección siguiente.

#### Red de Información Agroclimática de Andalucía (RIA)

Adaptador real en `app/services/ria_client.py`, verificado contra el código
fuente abierto del paquete R `meteospain` (no se pudo acceder directamente a
la documentación oficial de juntadeandalucia.es desde el entorno de
desarrollo). API pública, sin API key, solo cubre Andalucía.

- **Caché de estaciones** (`app/services/ria_sync.py`): se trae el listado
  real de estaciones y se cachea en `station` (idempotente,
  `UNIQUE (provider_id, code)`). No se vuelve a pedir a la red mientras
  haya alguna estación cacheada. Esto se hace de forma **eager en el
  arranque de la API** (`app/bootstrap.py::init_db`), no perezosamente en
  la primera parcela que se dé de alta: así la tabla `station` ya está
  poblada "desde el principio", con un timeout corto para no alargar el
  arranque si RIA no responde (se degrada a un aviso en el log y se
  reintenta automáticamente al dar de alta o sincronizar una parcela).
  **Dos bugs reales corregidos, encontrados con ayuda del usuario probando
  contra la API real** (esta demo no tiene acceso directo a
  juntadeandalucia.es desde su entorno de desarrollo):
  1. `latitud`/`longitud` de `estaciones` NO vienen en grados decimales,
     sino en un formato empaquetado `"DDMMSSsssH"` (grados-minutos-segundos
     + hemisferio, verificado contra `meteospain`,
     `R/utils.R::.parse_coords_dmsh`). La primera versión asumía grados
     decimales; el error se atrapaba en silencio como "campo incompleto",
     así que nunca se cacheaba ninguna estación real. Corregido en
     `_parse_dmsh_coord` (con test de regresión).
  2. Ya con el parseo de coordenadas corregido, la API devolvía 123 filas
     pero `station` terminaba con solo 28 — y entre esas 28 no estaba una
     estación real que el usuario sabía que existía (IFAPA Hinojosa del
     Duque, Córdoba, confirmada en la web oficial de RIA en
     `/riaweb/web/estacion/{provincia_id}/{codigoEstacion}`, provincia 14,
     código 102). La causa: `codigoEstacion` **no es único en toda la red
     RIA**, solo dentro de su provincia — la propia URL oficial lo
     confirma. `station.code` se guardaba como el `codigoEstacion` a
     secas, así que dos estaciones de provincias distintas con el mismo
     número colisionaban en el `UNIQUE (provider_id, code)` y la segunda se
     descartaba en silencio. Corregido guardando `code` como el par
     compuesto `"{provincia_id}:{codigoEstacion}"` (que es exactamente como
     la propia RIA direcciona sus estaciones), con `codigo_estacion` y
     `provincia_id` conservados por separado en `metadata_json` para las
     llamadas a `datosdiarios`.
  3. Al probar el punto anterior contra la API real, la primera versión de
     este arreglo asumía `provincia_id` como campo de nivel superior —
     también sin poder verificarlo en vivo desde este entorno — y volvió a
     descartar las 123 estaciones en bloque. La forma real, confirmada con
     una respuesta real de producción, anida la provincia:
     `{"provincia": {"id": 14, "nombre": "Córdoba"}, "codigoEstacion": "2",
     ...}`. Corregido para leer `st["provincia"]["id"]`, con un test que usa
     valores DMSH reales (estación "Adamuz") además de los sintéticos.
  Con los tres arreglos, IFAPA Hinojosa del Duque ya se cachea y se usa
  correctamente para la finca de referencia.
- **Regla "menos de 15 km"**: al dar de alta una parcela (y también vía
  `POST /v1/parcels/{id}/ria/sync`), si hay una estación RIA real a menos de
  `ria_max_distance_km` (15 km, distancia puramente **horizontal** — no la
  `effective_distance_km` ponderada por desnivel del descubrimiento
  genérico anterior), se sincroniza su histórico diario y se usa con
  prioridad sobre ERA5-Land: estación real > reanálisis
  (`base_priority`: RIA 12, ERA5-Land 50, previsión 55, todos leídos de
  `data_provider`, nunca hardcodeados en el motor de recomendaciones).
- **Qué se mapea y qué no**: temperatura, humedad relativa, viento medio y
  precipitación, inequívocos. RIA también ofrece radiación y ET0 (ruta
  `forceEt0`), pero sus unidades no se han podido verificar desde este
  entorno de desarrollo: **no se mapean**, para no inventar una conversión.
  El balance hídrico sigue usando ET0 de ERA5-Land/previsión aunque la
  parcela tenga estación RIA activa. RIA tampoco mide humectación foliar
  (ninguna red pública la mide en este MVP): el repilo sigue dependiendo del
  simulador de sensores o de la previsión.
- **Aproximación de resolución declarada**: RIA publica agregados
  **diarios** (mínimo/medio/máximo), no horarios. Para reutilizar sin
  cambios las consultas SQL basadas en `MIN()`/`MAX()` por día, cada día se
  representa con 3 timestamps sintéticos (06:00, 12:00, 18:00 UTC, sin
  relación con la hora real de esos valores) para temperatura y humedad;
  viento y precipitación usan un único punto al mediodía con el valor
  diario. Esto reproduce el mínimo/máximo diario exactos, pero una media
  calculada sobre esos 3 puntos es una aproximación. Documentado en la
  cabecera de `app/services/ria_sync.py`.
- **400 Bad Request en `datosdiarios` (no siempre es el tamaño del rango)**:
  pedir ~2 años de golpe devuelve 400. Pero al probarlo con una estación
  real concreta (IFAPA Hinojosa del Duque, cerca de la finca de
  referencia), se confirmó que un 400 **también puede significar que esa
  estación no tiene datos en ese periodo**, ni siquiera para un solo día —
  no es solo un límite de tamaño. Por eso `_fetch_daily_range_resilient`
  parte el rango en dos y reintenta cada mitad, pero con un tope BAJO
  (`RIA_MAX_RETRY_SHRINKS = 2`) y sin propagar nunca el 400 hacia arriba:
  la primera versión de este arreglo no tenía tope real y, al toparse con
  una estación que rechazaba todo, acababa troceando día a día durante
  años enteros — cientos de peticiones reales e inútiles a la API de la
  Junta de Andalucía antes de responder. Además, `_fetch_and_store_ria_range`
  tiene un "circuit breaker": si varios bloques anuales seguidos
  (`RIA_MAX_CONSECUTIVE_EMPTY_CHUNKS`) no traen NINGÚN dato, se detiene ahí
  con lo que ya se haya conseguido en vez de agotar el resto del rango
  pedido. Solo un error que no sea 400 (fallo de red, 5xx) se sigue
  propagando de verdad, porque ese sí es inesperado.
- El motor de recomendaciones (`app/services/agronomy/engine.py`) combina
  RIA + ERA5-Land + previsión con el mismo criterio de prioridad genérico
  que ya usa `/daily` (`app/services/daily_series.py`): para cada día gana
  la fuente de mejor prioridad que tenga dato ese día, el resto no se
  descarta.

### Módulo 3 — Simulador de sensores

La pieza más importante de este MVP porque sustituye al hardware que
todavía no existe. Ver la cabecera de `app/services/simulator.py` para el
detalle completo del modelo; resumen:

- Temperatura: interpola el histórico horario **real** de ERA5-Land a pasos
  de 15 min, y le suma un sesgo fijo por sensor (-0.8/+0.8 °C, generado una
  vez y persistido) + ruido de instrumento (±0.3 °C) en cada lectura.
- Humectación foliar: **ninguna red pública la mide**. Se deriva con un
  modelo explícito (sube con humedad relativa >90 % o lluvia, decae con
  radiación y viento) documentado como aproximación, nunca como medición.
- Precipitación: pluviómetro de cazoletas simulado — pulsos discretos de
  0.2 mm repartidos con variación aleatoria entre las horas con
  precipitación horaria de ERA5-Land, no una suavización del dato de ERA5.

Siempre bajo un `source` de tipo `simulated_sensor`, nunca reutilizando el
`source_id` del reanálisis real, con `metadata_json.simulated=true`.

### Módulo 4 — Modelos agronómicos

- **GDD** por el método del seno simple truncado (Baskerville-Emin), umbral
  base 12.5 °C, para Prays oleae.
- **Repilo**: horas de humectación foliar continua (dato simulado) frente a
  horas necesarias según la temperatura media del periodo (curva en U,
  óptimo 15-20 °C).
- **Helada**: umbral de daño dependiente de la fase fenológica aproximada
  por mes (reposo invernal −7/−12 °C, floración −1/−3 °C).
- **Balance hídrico** FAO-56 de depósito único, con Kc mensual orientativo
  de olivar de secano/tradicional.
- **Motor de modulación varietal**: ajusta la presión de riesgo según la
  susceptibilidad de la variedad. Regla de negocio explícita y no opcional:
  si la evidencia de la calificación varietal no es `ensayo_de_campo` o
  `controlado`, el sistema **nunca** emite un nivel `crítico` apoyado en
  eso — lo degrada a `alto` y lo explica en el texto.

Todos los umbrales llevan el aviso de que son valores de partida de
literatura general, no calibrados con datos de campo reales, tanto en el
código como en el campo `disclaimer` de la respuesta de la API.

Verticilosis, antracnosis y mosca del olivo tienen ficha varietal estática
(`/v1/varieties`) pero **ningún modelo climático dinámico** en este MVP: no
se ha encontrado una fórmula agronómica simple y fiable para ellas sin
inventar umbrales, y se declara así en la respuesta de recomendaciones en
vez de aparentar una cobertura que no existe.

**Recomendaciones para días futuros (previsión):** `GET .../recommendations?day=`
detecta si `day` cae dentro del histórico ERA5-Land ya descargado o más
allá (futuro): en el primer caso usa el histórico real como siempre; en el
segundo, usa la previsión de `POST /v1/parcels/{id}/fetch-forecast` para
GDD, helada y balance hídrico, y **deriva la humectación foliar en memoria**
a partir de la previsión (mismo modelo que el simulador, sin guardar nada)
para poder evaluar repilo también en días futuros. La respuesta incluye
siempre `data_basis: "historico_era5" | "prevision"` para que quede
explícito de dónde sale cada recomendación. Limitación conocida y
declarada: el repilo de un día de previsión no tiene en cuenta la
humectación de los días anteriores al inicio de la previsión.

### Módulo 5 — Importador de tratamientos desde Excel

Se adapta al fichero del agricultor, no al revés: detecta la fila de
cabecera aunque haya título/logo/filas en blanco por encima, mapea columnas
por sinónimos en español (no por posición ni nombre exacto), normaliza
fechas (`dd/mm/aaaa`, `aaaa-mm-dd`, serial de Excel) y números con coma
decimal, deduce el tipo de tratamiento cuando falta, salta filas duplicadas,
y procesa fila a fila: una fila con error no aborta el resto del lote.

Flujo en dos pasos, siempre: `POST /v1/imports/treatments/preview` (no
escribe nada, devuelve un token) → `POST /v1/imports/treatments/commit`
(con ese token, es lo único que escribe). Plantilla de ejemplo generable
con `python -m scripts.make_sample_treatments_xlsx` (no es obligatoria).

### Módulo 6 — API

Documentación OpenAPI completa y gratuita en `/docs`. Endpoints principales
(algunos no estaban en la lista mínima original pero fueron necesarios para
que el frontend del módulo 7 funcionara — están marcados en el código):

```
POST /v1/discovery/point
GET  /v1/parcels
POST /v1/parcels                        (importa automáticamente 5 años de histórico + estación RIA si hay una a <15 km)
GET  /v1/parcels/{id}
PATCH /v1/parcels/{id}                  (nombre, variedad, superficie, capacidad de campo — lat/lon/altitud son inmutables)
DELETE /v1/parcels/{id}                 (borra la parcela y todo lo que cuelga de ella: fuentes, observaciones, tratamientos)
PATCH /v1/parcels/{id}/variety
POST /v1/parcels/{id}/resolve-sources?dry_run=
POST /v1/parcels/{id}/backfill          (años explícitos, por defecto 25)
POST /v1/parcels/{id}/backfill/sync     (solo lo que falta hasta hoy)
POST /v1/parcels/{id}/ria/sync          (comprueba/sincroniza estación RIA real a <15 km)
POST /v1/parcels/{id}/fetch-forecast    (previsión real, próximos 7 días)
POST /v1/parcels/{id}/simulate-sensors
GET  /v1/parcels/{id}/daily
GET  /v1/parcels/{id}/observations      (detalle horario/15-min, para gráficas y tablas)
GET  /v1/parcels/{id}/recommendations   (histórico o previsión según el día pedido)
GET  /v1/varieties, GET /v1/varieties/{code}
POST /v1/imports/treatments/preview
POST /v1/imports/treatments/commit
GET  /v1/health
```

### Módulo 7 — Frontend

Ver la sección [Stack](#stack) para la justificación de HTMX + Jinja2 +
JS/Chart.js. Pantallas: alta de parcela + descubrimiento de fuentes
(al crear la parcela se muestra una notificación de una sola vez con el
resultado del import automático de 5 años); listado de parcelas con
botones **Editar** y **Eliminar** por parcela (también presentes en el
panel de cada parcela); un formulario de edición (`/parcel/{id}/edit`)
para nombre, variedad, superficie y capacidad de campo — lat/lon/altitud
quedan fuera a propósito, ver `ParcelUpdate` en `schemas/parcel.py` —, y
un botón de borrado que pide confirmación explícita antes de eliminar la
parcela junto con todo su histórico y su cuaderno de tratamientos; panel
de la parcela con:

- **Histórico**: gráfica + botones "Importar lo que falta hasta hoy" (sync
  incremental) e "Importar histórico completo (25 años)", más un filtro
  (rango de fechas + variables a mostrar) con **tabla paginada** de los
  datos filtrados.
- **Sensores SIMULADO**: gráfica de detalle 15-min + el mismo patrón de
  filtro y tabla paginada sobre las lecturas simuladas.
- **Previsión**: botón para traer los próximos 7 días reales de Open-Meteo
  y tabla con el resultado.
- **Recomendaciones**: selector de variedad, selector de día (puede ser
  futuro, dentro de la previsión) y panel con una etiqueta explícita de si
  la recomendación se basa en histórico real o en previsión.
- Importación de tratamientos con previsualización de errores por fila.

## Tests

```bash
make test
# o: docker compose exec api pytest -v
```

Cubren, como mínimo lo pedido:

- `test_distance.py`: la función SQL `effective_distance_km` (módulo 2),
  contra la base de datos real, no una reimplementación en Python.
- `test_gdd.py`, `test_repilo.py`: casos conocidos del método del seno
  simple truncado y de la curva de horas de humectación necesarias
  (módulo 4).
- `test_excel_import.py`: importa la plantilla de ejemplo (que incluye una
  fila con fecha inválida a propósito) y comprueba que se reporta el error
  sin bloquear el resto del lote.
- `test_recommendations_safety.py`: verifica que ningún texto de acción
  sugerida ni el disclaimer contienen nombres de materias activas o dosis
  con unidades de producto fitosanitario (la frontera de negocio del
  módulo 4).
- `test_provider_catalog.py`: la previsión nunca puede tener mejor
  prioridad que el histórico real en la vista combinada de `/daily`
  (regresión del bug corregido durante el desarrollo).
- `test_seed_upsert.py`: si se corrige un valor de catálogo en el código
  (proveedores, variables, variedades…), el siguiente arranque de la API
  lo repara en la base de datos aunque ya existiera con el valor antiguo.

## Qué falta para el sistema completo

Este README no pretende dar la impresión de que el MVP está más acabado de
lo que está. Para pasar de esta demo a un sistema productivo falta, como
mínimo:

- Adaptadores reales de AEMET y SIAR (catalogados pero inactivos; RIA ya
  tiene adaptador real, ver la sección de módulo 2).
- Verificar las unidades reales de radiación/ET0 de RIA contra la
  documentación oficial de la Junta de Andalucía y, si son correctas,
  mapearlas (hoy deliberadamente no se mapean, ver módulo 2).
- Sensores físicos de parcela de verdad, sustituyendo al simulador del
  módulo 3 (la arquitectura ya está preparada: solo cambia qué adaptador
  escribe en `observation`, con `is_simulated=false`).
- Calibración de todos los umbrales agronómicos (GDD, repilo, helada, Kc,
  el ajuste de modulación varietal) con datos de campo reales de la
  explotación, idealmente contrastados con estaciones de avisos oficiales.
- Verificación de las citas primarias de la susceptibilidad varietal
  (IFAPA, Universidad de Córdoba, boletines RAIF) — el seed actual usa
  caracterizaciones de bibliografía divulgativa, no citas verificadas línea
  a línea.
- Modelos climáticos dinámicos para verticilosis, antracnosis y mosca del
  olivo (hoy solo tienen ficha varietal estática).
- Autenticación multiusuario real (OAuth, roles) — hoy un único admin.
- Migraciones versionadas (Alembic) en vez de creación idempotente de
  esquema en el arranque, una vez el esquema deje de cambiar tan rápido.
