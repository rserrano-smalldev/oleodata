let historyChart = null;
let simulatedChart = null;

async function postJson(url, body) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.detail || "Error");
  return data;
}

async function getJson(url) {
  const res = await fetch(url);
  const data = await res.json();
  if (!res.ok) throw new Error(data.detail || "Error");
  return data;
}

function checkedValues(containerId) {
  return Array.from(document.querySelectorAll(`#${containerId} input:checked`)).map((el) => el.value);
}

async function updateVariety(parcelId, varietyCode) {
  await fetch(`/ui/parcel/${parcelId}/variety`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ variety_code: varietyCode || null }),
  });
  loadRecommendations(parcelId);
}

// ---------------------------------------------------------------------
// Histórico REAL (ERA5-Land)
// ---------------------------------------------------------------------

async function runSync(parcelId) {
  const status = document.getElementById("backfill-status");
  status.textContent = "Importando lo que falte desde el último dato guardado hasta hoy…";
  try {
    const result = await postJson(`/ui/parcel/${parcelId}/backfill/sync`, {});
    status.textContent = result.already_up_to_date
      ? "Ya estaba al día, no había nada nuevo que importar."
      : `Listo: ${result.rows_fetched} lecturas nuevas (${result.start_date} → ${result.end_date}).`;
    await drawHistoryChart(parcelId);
  } catch (e) {
    status.textContent = "Error: " + e.message;
  }
}

async function runFullBackfill(parcelId) {
  const status = document.getElementById("backfill-status");
  status.textContent = "Descargando 25 años de histórico real de Open-Meteo/ERA5-Land… puede tardar un minuto.";
  try {
    const result = await postJson(`/ui/parcel/${parcelId}/backfill`, { years_back: 25 });
    status.textContent = `Listo: ${result.rows_fetched} lecturas horarias reales (${result.start_date} → ${result.end_date}).`;
    await drawHistoryChart(parcelId);
  } catch (e) {
    status.textContent = "Error: " + e.message;
  }
}

async function drawHistoryChart(parcelId) {
  const end = new Date();
  const start = new Date();
  start.setFullYear(start.getFullYear() - 25);
  const params = new URLSearchParams({
    start: start.toISOString().slice(0, 10),
    end: end.toISOString().slice(0, 10),
    variables: "temperature_2m,precipitation",
  });
  const url = `/ui/parcel/${parcelId}/daily.json?${params.toString()}`;
  const data = await getJson(url);

  const temp = data.variables.temperature_2m || [];
  const precip = data.variables.precipitation || [];

  if (historyChart) historyChart.destroy();
  const ctx = document.getElementById("historyChart");
  historyChart = new Chart(ctx, {
    type: "line",
    data: {
      labels: temp.map((p) => p.day),
      datasets: [
        {
          label: "Temperatura media diaria (°C) — REAL ERA5-Land",
          data: temp.map((p) => p.value),
          borderColor: "#5c6b2a",
          yAxisID: "y",
          pointRadius: 0,
          borderWidth: 1,
        },
        {
          label: "Precipitación diaria (mm) — REAL ERA5-Land",
          data: precip.map((p) => p.value),
          borderColor: "#2f6b8a",
          yAxisID: "y1",
          pointRadius: 0,
          borderWidth: 1,
        },
      ],
    },
    options: {
      responsive: true,
      scales: {
        y: { position: "left", title: { display: true, text: "°C" } },
        y1: { position: "right", title: { display: true, text: "mm" }, grid: { drawOnChartArea: false } },
      },
    },
  });
}

async function applyHistoryFilter(parcelId) {
  const start = document.getElementById("hist-start").value;
  const end = document.getElementById("hist-end").value;
  const variables = checkedValues("hist-variables");
  const container = document.getElementById("history-table");
  if (!start || !end) { container.innerHTML = '<p class="error-text">Elige fecha de inicio y fin.</p>'; return; }
  if (!variables.length) { container.innerHTML = '<p class="error-text">Marca al menos una variable.</p>'; return; }

  container.innerHTML = "<p class='small'>Consultando…</p>";
  try {
    const params = new URLSearchParams({ start, end, variables: variables.join(",") });
    const data = await getJson(`/ui/parcel/${parcelId}/daily.json?${params.toString()}`);
    const items = [];
    for (const [code, points] of Object.entries(data.variables)) {
      for (const p of points) items.push({ key: p.day, variable: code, value: p.value });
    }
    const { columns, rows } = pivot(items, variables);
    renderTable("history-table", "Día", columns, rows);
  } catch (e) {
    container.innerHTML = `<p class="error-text">${e.message}</p>`;
  }
}

// ---------------------------------------------------------------------
// Sensores SIMULADOS (módulo 3)
// ---------------------------------------------------------------------

async function runSimulate(parcelId) {
  const status = document.getElementById("simulate-status");
  status.textContent = "Generando lecturas SIMULADAS del último mes (cada 15 min)…";
  try {
    const result = await postJson(`/ui/parcel/${parcelId}/simulate-sensors`, {});
    status.textContent =
      `SIMULADO: ${result.readings_written} lecturas cada ${result.interval_minutes} min. ` +
      `Sesgo de este sensor: ${result.sensor_offset_c} °C respecto a la malla ERA5-Land.`;
    await drawSimulatedChart(parcelId, result.start, result.end);

    document.getElementById("sim-start").value = toDatetimeLocal(result.start);
    document.getElementById("sim-end").value = toDatetimeLocal(result.end);

    loadRecommendations(parcelId);
  } catch (e) {
    status.textContent = "Error: " + e.message;
  }
}

function toDatetimeLocal(isoString) {
  return isoString.slice(0, 16);
}

async function drawSimulatedChart(parcelId, start, end) {
  const params = new URLSearchParams({
    provider: "sim_sensor_v1",
    start: start,
    end: end,
    variables: "temperature_2m,leaf_wetness,precipitation",
  });
  const url = `/ui/parcel/${parcelId}/observations.json?${params.toString()}`;
  const data = await getJson(url);

  const byVar = { temperature_2m: [], leaf_wetness: [], precipitation: [] };
  for (const p of data.points) {
    if (byVar[p.variable]) byVar[p.variable].push(p);
  }

  if (simulatedChart) simulatedChart.destroy();
  const ctx = document.getElementById("simulatedChart");
  simulatedChart = new Chart(ctx, {
    type: "line",
    data: {
      labels: byVar.temperature_2m.map((p) => p.timestamp),
      datasets: [
        {
          label: "Temperatura 15-min — SIMULADO",
          data: byVar.temperature_2m.map((p) => p.value),
          borderColor: "#b5651d",
          yAxisID: "y",
          pointRadius: 0,
          borderWidth: 1,
        },
        {
          label: "Humectación foliar (0-1) — SIMULADO (derivado, no medido)",
          data: byVar.leaf_wetness.map((p) => p.value),
          borderColor: "#2f6b3a",
          yAxisID: "y2",
          pointRadius: 0,
          borderWidth: 1,
        },
        {
          label: "Precipitación (pulsos 0.2mm) — SIMULADO",
          data: byVar.precipitation.map((p) => p.value),
          borderColor: "#2f6b8a",
          yAxisID: "y1",
          pointRadius: 0,
          borderWidth: 1,
          stepped: true,
        },
      ],
    },
    options: {
      responsive: true,
      scales: {
        y: { position: "left", title: { display: true, text: "°C" } },
        y1: { position: "right", title: { display: true, text: "mm" }, grid: { drawOnChartArea: false } },
        y2: { display: false, min: 0, max: 1 },
      },
    },
  });
}

async function applySimulatedFilter(parcelId) {
  const startLocal = document.getElementById("sim-start").value;
  const endLocal = document.getElementById("sim-end").value;
  const variables = checkedValues("sim-variables");
  const container = document.getElementById("simulated-table");
  if (!startLocal || !endLocal) {
    container.innerHTML = '<p class="error-text">Elige fecha/hora de inicio y fin (simula sensores primero si no hay rango disponible).</p>';
    return;
  }
  if (!variables.length) { container.innerHTML = '<p class="error-text">Marca al menos una variable.</p>'; return; }

  container.innerHTML = "<p class='small'>Consultando…</p>";
  try {
    const params = new URLSearchParams({
      provider: "sim_sensor_v1",
      start: new Date(startLocal).toISOString(),
      end: new Date(endLocal).toISOString(),
      variables: variables.join(","),
    });
    const data = await getJson(`/ui/parcel/${parcelId}/observations.json?${params.toString()}`);
    const items = data.points.map((p) => ({ key: p.timestamp, variable: p.variable, value: p.value }));
    const { columns, rows } = pivot(items, variables);
    renderTable("simulated-table", "Instante (UTC)", columns, rows);
  } catch (e) {
    container.innerHTML = `<p class="error-text">${e.message}</p>`;
  }
}

// ---------------------------------------------------------------------
// Previsión (Open-Meteo Forecast API)
// ---------------------------------------------------------------------

async function runFetchForecast(parcelId) {
  const status = document.getElementById("forecast-status");
  status.textContent = "Descargando previsión real de Open-Meteo…";
  try {
    const result = await postJson(`/ui/parcel/${parcelId}/fetch-forecast`, {});
    status.textContent = `Previsión actualizada: ${result.rows_written} lecturas horarias (${result.days_ahead} días).`;

    const params = new URLSearchParams({
      provider: "open_meteo_forecast",
      start: result.start,
      end: result.end,
      variables: "temperature_2m,relative_humidity_2m,precipitation,wind_speed_10m",
    });
    const data = await getJson(`/ui/parcel/${parcelId}/observations.json?${params.toString()}`);
    const items = data.points.map((p) => ({ key: p.timestamp, variable: p.variable, value: p.value }));
    const { columns, rows } = pivot(items, ["temperature_2m", "relative_humidity_2m", "precipitation", "wind_speed_10m"]);
    renderTable("forecast-table", "Instante (UTC)", columns, rows);

    loadRecommendations(parcelId);
  } catch (e) {
    status.textContent = "Error: " + e.message;
  }
}

async function runRiaSync(parcelId) {
  const status = document.getElementById("ria-status");
  status.textContent = "Comprobando estaciones RIA reales cerca de esta parcela…";
  try {
    const result = await postJson(`/ui/parcel/${parcelId}/ria/sync`, {});
    status.textContent = result.station_found
      ? `Estación '${result.station_name}' (${result.horizontal_km} km): ${result.note}`
      : result.note;
    if (result.station_found) {
      await drawHistoryChart(parcelId);
      loadRecommendations(parcelId);
    }
  } catch (e) {
    status.textContent = "Error: " + e.message;
  }
}

// ---------------------------------------------------------------------
// Tabla genérica con filtro (pivota una lista de {key, variable, value} en
// filas por `key` con una columna por variable) y paginación en cliente.
// ---------------------------------------------------------------------

function pivot(items, columns) {
  const rowsMap = new Map();
  for (const it of items) {
    if (!rowsMap.has(it.key)) rowsMap.set(it.key, { _key: it.key });
    rowsMap.get(it.key)[it.variable] = it.value;
  }
  const rows = Array.from(rowsMap.values()).sort((a, b) => (a._key < b._key ? -1 : a._key > b._key ? 1 : 0));
  return { columns, rows };
}

const VARIABLE_LABELS = {
  temperature_2m: "Temperatura (°C)",
  precipitation: "Precipitación (mm)",
  relative_humidity_2m: "Humedad relativa (%)",
  wind_speed_10m: "Viento (km/h)",
  shortwave_radiation: "Radiación (W/m²)",
  soil_moisture_7_28cm: "Humedad suelo (%)",
  et0_fao_evapotranspiration: "ET0 (mm)",
  leaf_wetness: "Humectación foliar (0-1)",
};

const tableState = {};
const PAGE_SIZE = 40;

function renderTable(containerId, keyLabel, columns, rows) {
  tableState[containerId] = { keyLabel, columns, rows, page: 0 };
  renderTablePage(containerId);
}

function renderTablePage(containerId) {
  const state = tableState[containerId];
  const totalPages = Math.max(1, Math.ceil(state.rows.length / PAGE_SIZE));
  state.page = Math.min(state.page, totalPages - 1);
  const start = state.page * PAGE_SIZE;
  const pageRows = state.rows.slice(start, start + PAGE_SIZE);

  let html = "<table><thead><tr>";
  html += `<th>${state.keyLabel}</th>`;
  for (const c of state.columns) html += `<th>${VARIABLE_LABELS[c] || c}</th>`;
  html += "</tr></thead><tbody>";
  if (!pageRows.length) {
    html += `<tr><td colspan="${state.columns.length + 1}" class="small">Sin datos en el rango filtrado.</td></tr>`;
  }
  for (const r of pageRows) {
    html += `<tr><td>${r._key}</td>`;
    for (const c of state.columns) {
      const v = r[c];
      html += `<td>${v === undefined ? "—" : (typeof v === "number" ? v.toFixed(2) : v)}</td>`;
    }
    html += "</tr>";
  }
  html += "</tbody></table>";
  html += `<div class="table-pager small">
      Página ${state.page + 1} de ${totalPages} (${state.rows.length} filas)
      <button class="secondary" onclick="tablePage('${containerId}', -1)">« Anterior</button>
      <button class="secondary" onclick="tablePage('${containerId}', 1)">Siguiente »</button>
    </div>`;

  document.getElementById(containerId).innerHTML = html;
}

function tablePage(containerId, delta) {
  const state = tableState[containerId];
  state.page += delta;
  renderTablePage(containerId);
}

// ---------------------------------------------------------------------
// Recomendaciones
// ---------------------------------------------------------------------

async function loadRecommendations(parcelId) {
  const panel = document.getElementById("recommendations-panel");
  const dayInput = document.getElementById("rec-day");
  const day = dayInput ? dayInput.value : new Date().toISOString().slice(0, 10);
  panel.innerHTML = "cargando…";
  try {
    const data = await getJson(`/ui/parcel/${parcelId}/recommendations.json?day=${day}`);
    panel.innerHTML = renderRecommendations(data);
  } catch (e) {
    panel.innerHTML = `<p class="error-text">${e.message}</p>`;
  }
}

function renderRecommendations(data) {
  let html = "";
  const basisTags = {
    historico_ria: '<span class="tag role-primary">Basado en histórico real — estación RIA</span>',
    historico_era5: '<span class="tag role-primary">Basado en histórico real — ERA5-Land</span>',
    prevision: '<span class="tag real">Basado en PREVISIÓN</span>',
    sin_dato: '<span class="tag simulated">Sin dato climático para este día</span>',
  };
  const basisTag = basisTags[data.data_basis] || "";
  html += `<p>${basisTag}</p>`;

  if (data.warnings && data.warnings.length) {
    html += `<ul>${data.warnings.map((w) => `<li class="small">${w}</li>`).join("")}</ul>`;
  }
  for (const t of data.threats || []) {
    html += `
      <div class="threat-card attention-${t.attention_level}">
        <h4>${t.threat_code} — atención: ${t.attention_level.toUpperCase()}</h4>
        <p><strong>Acción sugerida:</strong> ${t.suggested_action}</p>
        <p class="small">${t.explanation}</p>
      </div>`;
  }
  if (data.water_balance) {
    const wb = data.water_balance;
    html += `
      <div class="threat-card">
        <h4>Balance hídrico — ${wb.status}</h4>
        <p><strong>Acción sugerida:</strong> ${wb.suggested_action}</p>
        <p class="small">Depósito: ${wb.reservoir_mm} / ${wb.field_capacity_mm} mm (${wb.lookback_days} días de histórico)</p>
      </div>`;
  }
  if (data.not_dynamically_modeled_threats && data.not_dynamically_modeled_threats.length) {
    html += `<p class="small">Sin modelo climático dinámico en este MVP (solo ficha varietal estática): ${data.not_dynamically_modeled_threats.join(", ")}</p>`;
  }
  html += `<p class="small"><em>${data.disclaimer}</em></p>`;
  return html;
}

// ---------------------------------------------------------------------
// Valores por defecto de los filtros al cargar la página
// ---------------------------------------------------------------------

function setDefaultFilterDates() {
  const histStart = document.getElementById("hist-start");
  const histEnd = document.getElementById("hist-end");
  if (histStart && histEnd) {
    const end = new Date();
    const start = new Date();
    start.setDate(start.getDate() - 90);
    histStart.value = start.toISOString().slice(0, 10);
    histEnd.value = end.toISOString().slice(0, 10);
  }
}
