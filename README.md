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
| Histórico climático diario/horario (25 años) | **REAL** | Open-Meteo Historical Weather API, modelo ERA5-Land, CC BY 4.0, sin API key, resolución ~9 km, desde 1950. |
| Altitud de la parcela | **REAL** | API de elevación de Open-Meteo, resuelta en el alta de la parcela (nunca hardcodeada). |
| Lecturas de sensor de parcela (temperatura, precipitación, humectación foliar) a resolución de 15 min | **100% SIMULADO** | No hay hardware instalado. Ver [módulo 3](#módulo-3--simulador-de-sensores). Etiquetado como tal en BD (`source.is_simulated`, `data_provider.type='simulated_sensor'`), en la API (`is_simulated: true`) y en la interfaz (badge naranja "SIMULADO"). |
| Redes de estaciones regionales (AEMET, SIAR, RIA/RAIF) | **NO IMPLEMENTADO** | Catalogadas en `data_provider` con `has_adapter=false` para que la arquitectura las soporte sin migrar nada, pero no aportan ningún dato en este MVP. |
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
2. Crea la parcela (código, nombre, variedad opcional) y entra en su panel.
3. Pulsa **"Importar histórico de 25 años"**: descarga real de Open-Meteo y
   dibuja la gráfica de temperatura/precipitación diaria.
4. Pulsa **"Simular sensores del último mes"**: genera lecturas sintéticas
   cada 15 minutos, claramente etiquetadas como `SIMULADO`, con el sesgo de
   ese sensor mostrado en pantalla.
5. Asigna la variedad **Hojiblanca** y mira el nivel de riesgo de repilo del
   día evaluado; cámbiala a **Frantoio** (más resistente en la ficha
   varietal) y comprueba que el nivel de atención baja para el mismo día.
6. Ve a "Importar tratamientos desde Excel", sube un fichero con al menos
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

Único adaptador real implementado: **Open-Meteo / ERA5-Land**
(`app/services/openmeteo_client.py`), con llamadas HTTP reales, troceadas en
bloques de 5 años, guardadas siempre en UTC, con conversión de humedad de
suelo de fracción a porcentaje. AEMET/SIAR/RIA están catalogados con
`has_adapter=false`: la arquitectura los soporta sin refactorizar nada el
día que se añadan.

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
POST /v1/parcels
GET  /v1/parcels/{id}
PATCH /v1/parcels/{id}/variety
POST /v1/parcels/{id}/resolve-sources?dry_run=
POST /v1/parcels/{id}/backfill
POST /v1/parcels/{id}/simulate-sensors
GET  /v1/parcels/{id}/daily
GET  /v1/parcels/{id}/observations      (detalle horario/15-min, para las gráficas)
GET  /v1/parcels/{id}/recommendations
GET  /v1/varieties, GET /v1/varieties/{code}
POST /v1/imports/treatments/preview
POST /v1/imports/treatments/commit
GET  /v1/health
```

### Módulo 7 — Frontend

Ver la sección [Stack](#stack) para la justificación de HTMX + Jinja2 +
JS/Chart.js. Pantallas: alta de parcela + descubrimiento de fuentes,
importación de histórico con gráfica, simulación de sensores con gráfica de
detalle y etiqueta SIMULADO, selector de variedad + panel de
recomendaciones, e importación de tratamientos con previsualización de
errores.

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

## Qué falta para el sistema completo

Este README no pretende dar la impresión de que el MVP está más acabado de
lo que está. Para pasar de esta demo a un sistema productivo falta, como
mínimo:

- Adaptadores reales de AEMET, SIAR y RIA/RAIF (catalogados pero inactivos).
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
