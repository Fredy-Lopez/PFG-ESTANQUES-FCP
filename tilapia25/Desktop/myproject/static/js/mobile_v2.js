// ===============================================================
// MONITOREO DE ESTANQUES — SCRIPT PRINCIPAL (mobile_v2.js)
// ===============================================================

// ===== BASE & UTILIDADES ===================================================

// Detección de dispositivo táctil

const IS_TOUCH =
  window.matchMedia("(hover: none) and (pointer: coarse)").matches ||
  "ontouchstart" in window;

// Helper: aplicar efecto interactivo (hover/touch)
function applyInteractiveButton(selector, options = {}) {
  const btn =
    typeof selector === "string" ? document.querySelector(selector) : selector;
  if (!btn) return;

  if (IS_TOUCH) {
    [...btn.classList].forEach((cls) => {
      if (cls.startsWith("hover:")) btn.classList.remove(cls);
    });

    const down = () => {
      btn.style.transform = "scale(0.97)";
      btn.style.filter = "brightness(0.9)";
    };
    const up = () => {
      btn.style.transform = "";
      btn.style.filter = "";
    };

    btn.addEventListener("touchstart", down, { passive: true });
    btn.addEventListener("touchend", up, { passive: true });
    btn.addEventListener("touchcancel", up, { passive: true });
    btn.addEventListener("touchmove", up, { passive: true });
  } else {
    if (options.hoverClass) btn.classList.add(options.hoverClass);
  }
}

// Texto seguro
const txt = (x) => (x == null ? "" : String(x));

// ===== 🧭 MÓDULO: MENÚ / NAVEGACIÓN ===========================================

const sideMenu = document.getElementById("sideMenu");
const menuBtn = document.getElementById("menuBtn");
const closeMenu = document.getElementById("closeMenu");
const notifBtn = document.getElementById("notifBtn");
const notifDropdown = document.getElementById("notifDropdown");
const menuOptions = document.querySelectorAll(".menu-option");
let histPage = 1;
let histTotalPages = 1;
let histLimit = 30; // filas por página


menuBtn.onclick = () => sideMenu.classList.replace("-translate-x-full", "show");
closeMenu.onclick = () =>
  sideMenu.classList.replace("show", "-translate-x-full");

window.addEventListener("click", (e) => {
  if (!sideMenu.contains(e.target) && !menuBtn.contains(e.target)) {
    sideMenu.classList.replace("show", "-translate-x-full");
  }
});

// Notificaciones toggle
notifBtn.onclick = (e) => {
  e.stopPropagation();
  notifDropdown.classList.toggle("hidden");
};
window.addEventListener("click", (e) => {
  if (!notifDropdown.contains(e.target) && !notifBtn.contains(e.target)) {
    notifDropdown.classList.add("hidden");
  }
});

// Secciones
const weatherSection = document.getElementById("weatherSection");
const cardsSection = document.getElementById("monitoreoSection");
const chartsSection = document.getElementById("chartsSection");
const controlSection = document.getElementById("controlSection");
const historySection = document.getElementById("historySection");

let currentSection = "monitoreo";
const mdUp = () => window.matchMedia("(min-width: 768px)").matches;

function setActiveMenu(key) {
  menuOptions.forEach((b) => {
    const active = b.dataset.section === key;
    b.classList.toggle("border-b-2", active);
    b.classList.toggle("border-orange-500", active);
    b.classList.toggle("text-orange-400", active);
  });
}

function showSection(key) {
  currentSection = key;

  const show = (el, v) => el.classList.toggle("hidden", !v);

  if (key === "monitoreo") {
    show(weatherSection, true);
    show(cardsSection, true);
    show(chartsSection, false);
    show(controlSection, false);
    show(historySection, false);
  } else if (key === "graficas") {
    initChartOnce();
    syncButtonsFromState();
    show(weatherSection, true);
    show(chartsSection, true);
    show(cardsSection, mdUp());
    show(controlSection, false);
    show(historySection, false);
  } else if (key === "control") {
    show(weatherSection, false);
    show(cardsSection, false);
    show(chartsSection, false);
    show(controlSection, true);
    show(historySection, false);
  } else if (key === "historial") {
    show(weatherSection, false);
    show(cardsSection, false);
    show(chartsSection, false);
    show(controlSection, false);
    show(historySection, true);
  }

  setActiveMenu(key);
}

menuOptions.forEach((btn) => {
  btn.addEventListener("click", () => {
    showSection(btn.dataset.section);
    sideMenu.classList.remove("show");
    sideMenu.classList.add("-translate-x-full");
  });
});

window.addEventListener("resize", () => {
  if (currentSection === "graficas") showSection("graficas");
});

setActiveMenu("monitoreo");

applyInteractiveButton(menuBtn);
applyInteractiveButton(closeMenu);
applyInteractiveButton(notifBtn);
document
  .querySelectorAll("header button")
  .forEach((b) => applyInteractiveButton(b));

// ===============================================================
// CARGA DE SENSORES DESDE BACKEND
// ===============================================================
function setVal(key, value) {
  const el = document.getElementById(`val-${key}`);
  if (el) el.textContent = value;
}

async function loadLatestSensores() {
  try {
    const res = await fetch("/api/sensores");
    const data = await res.json();

    // Si hay datos válidos, actualizar valores en pantalla
    if (data.ph != null) {
      setVal("ph", Number(data.ph).toFixed(2));
      setVal("o2", Number(data.o2).toFixed(2));
      setVal("temp", Number(data.temp).toFixed(2));
    }
  } catch (e) {
    console.error("❌ Error cargando sensores:", e);
  }
}

// Ejecutar cada 4 segundos
setInterval(loadLatestSensores, 4000);
loadLatestSensores();

// ==============================================
// CLIMA DESDE BACKEND (/api/clima)
// ==============================================
async function loadWeather() {
  try {
    const res = await fetch("/api/clima");
    const data = await res.json();

    // Datos reales o simulados desde Flask
    const clima = data.data;

    // La API real usa Kelvin → pero ahora estamos simulando
    const temp = clima.main.temp;
    const hum = clima.main.humidity;
    const wind = clima.wind.speed;

    // ======================
    // Ícono del clima
    // ======================
    try {
      if (clima.weather && clima.weather.length > 0) {
        const iconCode = clima.weather[0].icon; // ej: "04d", "01n"
        const iconUrl = `https://openweathermap.org/img/wn/${iconCode}@2x.png`;

        const iconEl = document.getElementById("weather-icon");
        iconEl.src = iconUrl;
        iconEl.classList.remove("hidden");
      }
    } catch (e) {
      console.warn("Icono de clima no disponible:", e);
    }

    // Actualizar UI
    document.getElementById("weather-temp").textContent = `${temp} °C`;
    document.getElementById("weather-hum").textContent = `${hum} %`;
    document.getElementById("weather-wind").textContent = `${wind} km/h`;

    console.log("Clima cargado:", data);
  } catch (err) {
    console.error("❌ Error cargando clima:", err);
  }
}

// Ejecutar cada 120 segundos
setInterval(loadWeather, 120000);
loadWeather();

// ===== MÓDULO: GRÁFICA REAL ====================================================

// Instancia del gráfico
let chartInstance = null;

// Estado inicial de visibilidad de datasets
const datasetVisibility = [false, false, false, true, true];

// ======================================================
// 📡 HISTORIAL REAL DESDE BACKEND PARA GRÁFICAS
// ======================================================
async function loadHistoryForChart() {
  try {
    const res = await fetch("/api/historial");
    const data = await res.json(); // Lista de lecturas DESC

    if (!chartInstance) return;

    // Tomar solo las últimas 20 lecturas
    const last = data.slice(0, 20).reverse();

    // Etiquetas → hora en formato HH:MM
    const labels = last.map((item) => item.hora?.slice(0, 5) || "--:--");

    // Datos reales
    const temp = last.map((item) => item.temp);
    const o2 = last.map((item) => item.o2);
    const ph = last.map((item) => item.ph);

    // CO₂ y amonio (si no existen en BD, se dejan nulos)
    const co2 = last.map((item) => item.co2 || null);
    const turbidez = last.map((item) => item.turbidez || null);

    // Asignar a Chart.js
    chartInstance.data.labels = labels;
    chartInstance.data.datasets[0].data = temp;
    chartInstance.data.datasets[1].data = o2;
    chartInstance.data.datasets[2].data = ph;

    if (chartInstance.data.datasets[3])
      chartInstance.data.datasets[3].data = co2;
    if (chartInstance.data.datasets[4])
      chartInstance.data.datasets[4].data = turbidez;

    chartInstance.update("none");
  } catch (err) {
    console.error("❌ Error cargando historial para gráficas:", err);
  }
}

// ======================================================
// Inicializar la gráfica SOLO una vez
// ======================================================
function initChartOnce() {
  if (chartInstance) return;

  const ctx = document.getElementById("mainChart")?.getContext("2d");
  if (!ctx) return;

  chartInstance = new Chart(ctx, {
    type: "line",
    data: {
      labels: [], // serán reemplazadas por datos reales
      datasets: [
        {
          label: "Temperatura (°C)",
          data: [],
          borderColor: "#FF8C00",
          backgroundColor: "rgba(255,140,0,0.15)",
          tension: 0.3,
          hidden: datasetVisibility[0],
        },
        {
          label: "Oxígeno (mg/L)",
          data: [],
          borderColor: "#00BFFF",
          backgroundColor: "rgba(0,191,255,0.15)",
          tension: 0.3,
          hidden: datasetVisibility[1],
        },
        {
          label: "pH",
          data: [],
          borderColor: "#32CD32",
          backgroundColor: "rgba(50,205,50,0.15)",
          tension: 0.3,
          hidden: datasetVisibility[2],
        },
        {
          label: "CO₂ (mg/L)",
          data: [],
          borderColor: "#AAAAAA",
          backgroundColor: "rgba(180,180,180,0.15)",
          tension: 0.3,
          hidden: datasetVisibility[3],
        },
        {
          label: "Turbidez (NTU)",
          data: [],
          borderColor: "#8A2BE2",
          backgroundColor: "rgba(138,43,226,0.15)",
          tension: 0.3,
          hidden: datasetVisibility[4],
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          enabled: true,
          backgroundColor: "rgba(0, 0, 0, 0.75)",
        },
      },
      scales: {
        x: { ticks: { color: "#CBD5E1" } },
        y: { ticks: { color: "#CBD5E1" } },
      },
    },
  });

  setupVariableButtons();
  syncButtonsFromState();
}

// ======================================================
// Botones de activar / desactivar variables
// ======================================================
function setupVariableButtons() {
  document.querySelectorAll(".varBtn").forEach((btn) => {
    applyInteractiveButton(btn, { hoverClass: "hover:bg-opacity-90" });

    btn.addEventListener("click", () => {
      const i = parseInt(btn.dataset.var, 10);
      datasetVisibility[i] = !datasetVisibility[i];
      chartInstance.data.datasets[i].hidden = datasetVisibility[i];
      chartInstance.update();
      btn.classList.toggle("opacity-50", datasetVisibility[i]);
    });
  });
}

function syncButtonsFromState() {
  document.querySelectorAll(".varBtn").forEach((btn) => {
    const i = parseInt(btn.dataset.var, 10);
    btn.classList.toggle("opacity-50", datasetVisibility[i]);
  });
}

// ======================================================
// Actualización periódica del gráfico
// ======================================================
setInterval(() => {
  if (chartInstance) loadHistoryForChart();
}, 5000);

// ===============================
//   FILTROS — HISTORIAL
// ===============================
const f_tipo = document.getElementById("f_tipo");
const f_periodo = document.getElementById("f_periodo");
const f_estanque = document.getElementById("f_estanque");
const filtrosExtra = document.getElementById("filtrosExtra");
const btnAplicarFiltro = document.getElementById("btnAplicarFiltro");
const btnToggleVista = document.getElementById("btnToggleVista");

let modoVista = "tabla"; // tabla | grafica

function updateHistPaginationUI() {
  const pag = document.getElementById("histPagination");
  const info = document.getElementById("histPageInfo");
  const prev = document.getElementById("histPrev");
  const next = document.getElementById("histNext");

  pag.classList.remove("hidden");

  info.textContent = `Página ${histPage} de ${histTotalPages}`;

  prev.disabled = histPage <= 1;
  next.disabled = histPage >= histTotalPages;
}


// Crear inputs dinámicos
function actualizarFiltrosExtra() {
  const per = f_periodo.value;
  filtrosExtra.innerHTML = "";

  switch (per) {
    case "dia":
      filtrosExtra.innerHTML = `
        <div>
          <label class="text-xs text-slate-300">Fecha</label>
          <input id="f_fecha" type="date"
            class="w-full bg-[#0C2340] text-white border border-slate-500 rounded-md px-3 py-2">
        </div>`;
      break;

    case "mes":
      filtrosExtra.innerHTML = `
        <div>
          <label class="text-xs text-slate-300">Mes</label>
          <input id="f_mes" type="month"
            class="w-full bg-[#0C2340] text-white border border-slate-500 rounded-md px-3 py-2">
        </div>`;
      break;

    case "año":
      filtrosExtra.innerHTML = `
        <div>
          <label class="text-xs text-slate-300">Año</label>
          <input id="f_año" type="number" min="2000" max="2100"
            class="w-full bg-[#0C2340] text-white border border-slate-500 rounded-md px-3 py-2">
        </div>`;
      break;

    case "rango":
      filtrosExtra.innerHTML = `
        <div>
          <label class="text-xs text-slate-300">Desde</label>
          <input id="f_desde" type="date"
            class="w-full bg-[#0C2340] text-white border border-slate-500 rounded-md px-3 py-2">
        </div>

        <div>
          <label class="text-xs text-slate-300">Hasta</label>
          <input id="f_hasta" type="date"
            class="w-full bg-[#0C2340] text-white border border-slate-500 rounded-md px-3 py-2">
        </div>`;
      break;
  }
}

// actualizar cuando cambie período
f_periodo.addEventListener("change", actualizarFiltrosExtra);

// crear por defecto
actualizarFiltrosExtra();

// =======================================
// Cargar historial desde Flask
// =======================================
async function cargarHistorial() {
  const tipo = f_tipo.value;
  const periodo = f_periodo.value;

  let params = new URLSearchParams();
  params.append("tipo", tipo);
  params.append("periodo", periodo);
  params.append("modo", modoVista);  // tabla | grafica
  params.append("page", histPage);
  params.append("limit", histLimit);

  // obtener inputs dinámicos
  const f_fecha = document.getElementById("f_fecha");
  const f_mes = document.getElementById("f_mes");
  const f_año = document.getElementById("f_año");
  const f_desde = document.getElementById("f_desde");
  const f_hasta = document.getElementById("f_hasta");

  if (f_fecha?.value) params.append("fecha", f_fecha.value);
  if (f_mes?.value) params.append("mes", f_mes.value);
  if (f_año?.value) params.append("año", f_año.value);
  if (f_desde?.value) params.append("desde", f_desde.value);
  if (f_hasta?.value) params.append("hasta", f_hasta.value);

  const res = await fetch(`/api/historial_filtros?${params.toString()}`);
  const json = await res.json();

  // -----------------------------------------------------
  // Si estamos en modo TABLA → json es un OBJETO
  // -----------------------------------------------------
  if (modoVista === "tabla") {
    histTotalPages = json.pages || 1;
    updateHistPaginationUI();

    window.historialData = json.data || [];
    mostrarHistTabla(json.data || []);
    return;
  }

  // -----------------------------------------------------
  // Si estamos en modo GRÁFICA → json es un ARRAY
  // -----------------------------------------------------
  let lista = json;

  // Si viene paginado (por error), extraer solo .data
  if (!Array.isArray(json) && json.data) {
    lista = json.data;
  }

  window.historialData = lista;
  mostrarHistGrafica(lista);
}


// Reiniciar página cuando se aplican filtros
btnAplicarFiltro.addEventListener("click", () => {
  histPage = 1;
  cargarHistorial();
});


// ===============================
//    MOSTRAR TABLA HISTORIAL
// ===============================
function mostrarHistTabla(data) {
  document.getElementById("histChartContainer").classList.add("hidden");
  document.getElementById("histTableContainer").classList.remove("hidden");

  const tbody = document.getElementById("histTableBody");
  const msg = document.getElementById("histMsg");

  if (!data || data.length === 0) {
    tbody.innerHTML = "";
    msg.classList.remove("hidden");
    return;
  }

  msg.classList.add("hidden");

  tbody.innerHTML = data
    .map((row) => {
      const fecha = row.fecha || "-";
      const hora = row.hora || "-";
      const categoria = row.categoria || "-";

      let desc = "";

      if (categoria === "lectura") {
        desc = `pH: ${row.ph} | O₂: ${row.o2} | Temp: ${row.temp}`;
      } else if (categoria === "manual") {
        desc = row.descripcion + (row.valor ? ` — (${row.valor})` : "");
      } else if (categoria === "notificacion") {
        desc = `${row.tipo}: ${row.mensaje}`;
      }

      return `
      <tr>
        <td class="px-4 py-2 border border-slate-700">${fecha}</td>
        <td class="px-4 py-2 border border-slate-700">${hora}</td>
        <td class="px-4 py-2 border border-slate-700">${categoria}</td>
        <td class="px-4 py-2 border border-slate-700">${desc}</td>
      </tr>
    `;
    })
    .join("");
}

let histChart = null;

// ===============================
//    MOSTRAR GRAFICA HISTORIAL (OPTIMIZADA)
// ===============================
function mostrarHistGrafica(data) {
  document.getElementById("histTableContainer").classList.add("hidden");
  document.getElementById("histChartContainer").classList.remove("hidden");

  const cont = document.getElementById("histChartContainer");
  cont.innerHTML = "<canvas id='histChart'></canvas>";
  const newCanvas = document.getElementById("histChart");
  const ctx = newCanvas.getContext("2d");

  if (histChart) histChart.destroy();

  let lecturas = (data || []).filter((d) => d.categoria === "lectura");

  if (lecturas.length === 0) {
    cont.innerHTML =
      "<p class='text-center text-slate-300'>No hay datos para graficar.</p>";
    return;
  }

  // ⭐⭐⭐ ORDEN CORRECTO ⭐⭐⭐
  lecturas.sort((a, b) => {
    const da = new Date(a.label || `${a.fecha} ${a.hora || "00:00"}`);
    const db = new Date(b.label || `${b.fecha} ${b.hora || "00:00"}`);
    return da - db;
  });

  // Ahora sí generamos datasets ordenados
  const labels = lecturas.map(
    (r) => r.label || `${r.fecha} ${r.hora || ""}`.trim()
  );

  const ph  = lecturas.map((r) => r.ph);
  const o2  = lecturas.map((r) => r.o2);
  const tmp = lecturas.map((r) => r.temp);

  histChart = new Chart(ctx, {
    type: "line",
    data: {
      labels,
      datasets: [
        {
          label: "pH",
          data: ph,
          borderColor: "#32CD32",
          backgroundColor: "rgba(50,205,50,0.15)",
          tension: 0.3,
        },
        {
          label: "Oxígeno (mg/L)",
          data: o2,
          borderColor: "#00BFFF",
          backgroundColor: "rgba(0,191,255,0.15)",
          tension: 0.3,
        },
        {
          label: "Temperatura (°C)",
          data: tmp,
          borderColor: "#FF8C00",
          backgroundColor: "rgba(255,140,0,0.15)",
          tension: 0.3,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { labels: { color: "#EEE" } },
        tooltip: {
          backgroundColor: "rgba(0,0,0,0.75)",
          bodyColor: "#FFF",
          titleColor: "#FFF",
          plugins: {
			  legend: { labels: { color: "#EEE" } },

			  tooltip: {
				backgroundColor: "rgba(0,0,0,0.75)",
				bodyColor: "#FFF",
				titleColor: "#FFF",
			  },

			  zoom: {
				zoom: {
				  wheel: {
					enabled: true,   // zoom con scroll (PC)
				  },
				  pinch: {
					enabled: true   // zoom con los dedos (móvil)
				  },
				  mode: "x",         // solo eje horizontal
				},
				pan: {
				  enabled: true,
				  mode: "x",
				}
			  }
			},

        },
      },
      scales: {
        x: {
          ticks: { color: "#BBB" },
          grid: { color: "rgba(255,255,255,0.05)" },
        },
        y: {
          ticks: { color: "#BBB" },
          grid: { color: "rgba(255,255,255,0.05)" },
        },
      },
    },
  });
}

// ===============================
//  BOTONES DE PAGINACIÓN
// ===============================
document.getElementById("histPrev").addEventListener("click", () => {
  if (histPage > 1) {
    histPage--;
    cargarHistorial();
  }
});

document.getElementById("histNext").addEventListener("click", () => {
  if (histPage < histTotalPages) {
    histPage++;
    cargarHistorial();
  }
});



// ===== CONTROL MANUAL ===================================
const phToggleBtn = document.getElementById("togglePhControl");
const o2ToggleBtn = document.getElementById("toggleO2Control");
const phControls = document.getElementById("phManualControls");
const o2Controls = document.getElementById("o2ManualControls");

const doseLimeBtn = document.getElementById("doseLime");
const doseCitricBtn = document.getElementById("doseCitric");
const phDosePreset = document.getElementById("phDosePreset");

const startAeratorsBtn = document.getElementById("startAerators");
const o2DurationInput = document.getElementById("o2Duration");

const emergencyBtn = document.getElementById("btnEmergency");

applyInteractiveButton(phToggleBtn, { hoverClass: "hover:bg-green-700" });
applyInteractiveButton(o2ToggleBtn, { hoverClass: "hover:bg-green-700" });
applyInteractiveButton(doseLimeBtn, { hoverClass: "hover:bg-green-700" });
applyInteractiveButton(doseCitricBtn, { hoverClass: "hover:bg-red-700" });
applyInteractiveButton(startAeratorsBtn, { hoverClass: "hover:bg-blue-700" });
applyInteractiveButton(emergencyBtn, { hoverClass: "hover:bg-red-800" });

// ------- Indicadores -------
let estadoV24 = {};
let ultimoEstadoJson = "";
let cooldownInterval = null;

// ------- Refrescar estado desde Flask -------
async function loadEstadoV24() {
  try {
    const res = await fetch("/api/estado_v24");
    const data = await res.json();

    const nuevoJSON = JSON.stringify(data);

    // Determinar si realmente hay un cambio
    const huboCambio = nuevoJSON !== ultimoEstadoJson;
    ultimoEstadoJson = nuevoJSON;

    estadoV24 = data;
    estadoV24._last_update_ok = huboCambio;

    actualizarUIControlManual();
  } catch (e) {
    console.error("❌ Error cargando estado v24", e);
  }
}

setInterval(loadEstadoV24, 1000);
loadEstadoV24();

// ===========================================================
//         ACTUALIZAR LA UI SEGÚN ESTADO DEL BACKEND
// ===========================================================
function actualizarUIControlManual() {
  const st = estadoV24;
  if (!st) return;

  // Estado global PID
  document.getElementById("pidPhStatus").textContent = st.pid_paused_ph
    ? "Manual"
    : "Automático";

  document.getElementById("pidO2Status").textContent = st.pid_paused_o2
    ? "Manual"
    : "Automático";

  // === BLOQUEO DE SEGURIDAD pH ===
  const timerBox = document.getElementById("phTimerBox");
  const timerLabel = document.getElementById("phTimerLabel");
  const resetBtn = document.getElementById("phResetBtn");
  applyInteractiveButton(resetBtn, { hoverClass: "hover:bg-red-700" });
  if (st.bloqueo_ph) {
    timerBox.classList.remove("hidden");

    const ahora = Date.now() / 1000;
    let restante = st.bloqueo_ph_hasta - ahora;
    if (restante < 0) restante = 0;

    if (st.bloqueo_ph_tipo === "hora") {
      const min = Math.ceil(restante / 60);
      timerLabel.textContent = `Bloqueo pH — Reinicio en ${min} min`;
    } else {
      const horas = (restante / 3600).toFixed(1);
      timerLabel.textContent = `Bloqueo pH 24h — Reinicio en ${horas} h`;
    }

    resetBtn.onclick = () => enviarComandoTCP("10");

  } else {
    timerBox.classList.add("hidden");
  }



  // =======================================================
  //               BOTÓN PH (toggle)
  // =======================================================
  if (st.pid_paused_ph) {
    phToggleBtn.textContent = "Desactivar Control Manual pH";
    phToggleBtn.classList.add("bg-green-600");
    phControls.classList.remove("hidden");
  } else {
    phToggleBtn.textContent = "Activar Control Manual pH";
    phToggleBtn.classList.remove("bg-green-600");
    phControls.classList.add("hidden");
  }

  // =======================================================
  //               BOTÓN O2 (toggle)
  // =======================================================
  if (st.pid_paused_o2) {
    o2ToggleBtn.textContent = "Desactivar Control Manual O₂";
    o2ToggleBtn.classList.add("bg-green-600");
    o2Controls.classList.remove("hidden");
  } else {
    o2ToggleBtn.textContent = "Activar Control Manual O₂";
    o2ToggleBtn.classList.remove("bg-green-600");
    o2Controls.classList.add("hidden");
  }

  // =======================================================
  //               COOLDOWN + BLOQUEOS
  // =======================================================
  const ahora = Date.now() / 1000;

  const ultimoPH = Math.max(st.ultimo_ph_up || 0, st.ultimo_ph_down || 0);
  const tiempoDesdeUltimoPH = ultimoPH ? ahora - ultimoPH : Infinity;

  const enCooldown = tiempoDesdeUltimoPH < st.cooldown;
  const segundosRestantes = Math.max(0, st.cooldown - tiempoDesdeUltimoPH);

  const hayTareaPH = st.tareas.some(
    (t) => t.tipo === "pH↑" || t.tipo === "pH↓"
  );
  const hayTareaO2 = st.tareas.some((t) => t.tipo === "O2");

  // =======================================================
  //           BLOQUEO DE BOTONES (NUEVA LÓGICA)
  // =======================================================

  // 1) PH: Cal Viva + Ácido
  const phBloqueado = hayTareaPH || st.bloqueo_ph || enCooldown;

  doseLimeBtn.disabled = phBloqueado;
  doseCitricBtn.disabled = phBloqueado;

  doseLimeBtn.classList.toggle("opacity-50", phBloqueado);
  doseCitricBtn.classList.toggle("opacity-50", phBloqueado);

	// 2) Toggle PH – bloquear si hay tarea activa O si hay bloqueo de seguridad pH
	if (hayTareaPH || st.bloqueo_ph) {
	  phToggleBtn.disabled = true;
	  phToggleBtn.classList.add("opacity-50", "pointer-events-none");
	} else {
	  phToggleBtn.disabled = false;
	  phToggleBtn.classList.remove("opacity-50", "pointer-events-none");
	}


  // 3) Toggle O2 – solo bloquear si hay tarea O₂ activa
  if (hayTareaO2) {
    o2ToggleBtn.disabled = true;
    o2ToggleBtn.classList.add("opacity-50", "pointer-events-none");
  } else {
    o2ToggleBtn.disabled = false;
    o2ToggleBtn.classList.remove("opacity-50", "pointer-events-none");
  }

  // =======================================================
  //                INDICADORES VISUALES
  // =======================================================
  const cdLbl = document.getElementById("phCooldownLabel");
  const blLbl = document.getElementById("phBlockLabel");

  if (st.bloqueo_ph) blLbl.classList.remove("hidden");
  else blLbl.classList.add("hidden");

  if (enCooldown) {
    cdLbl.textContent = `⏳ Cooldown: ${Math.ceil(segundosRestantes / 60)} min`;
    cdLbl.classList.remove("hidden");
  } else {
    cdLbl.classList.add("hidden");
  }

  // ===== TAREA MANUAL pH =====
  const lblPhTask = document.getElementById("phTaskLabel");
  const tareaPh = st.tareas.find((t) => t.tipo === "pH↑" || t.tipo === "pH↓");

  if (tareaPh) {
    const remaining = Math.max(0, tareaPh.t_fin - Date.now() / 1000);
    lblPhTask.textContent = `${tareaPh.tipo} activa — ${Math.ceil(
      remaining
    )} s restantes`;
    lblPhTask.classList.remove("hidden");
  } else {
    lblPhTask.classList.add("hidden");
  }

  // =======================================================
  //               BOTÓN O2 (toggle)
  // =======================================================

  // ===== TAREA MANUAL O₂ =====
  const lblO2Task = document.getElementById("o2TaskLabel");
  const tareaO2 = st.tareas.find((t) => t.tipo === "O2");

  if (tareaO2) {
    const remaining = Math.max(0, tareaO2.t_fin - Date.now() / 1000);
    lblO2Task.textContent = `Aireadores activos — ${Math.ceil(
      remaining
    )} s restantes`;
    lblO2Task.classList.remove("hidden");
  } else {
    lblO2Task.classList.add("hidden");
  }

  if (st.pid_paused_o2) {
    o2ToggleBtn.textContent = "Desactivar Control Manual O₂";
    o2ToggleBtn.classList.add("bg-green-600");
    o2Controls.classList.remove("hidden");
  } else {
    o2ToggleBtn.textContent = "Activar Control Manual O₂";
    o2ToggleBtn.classList.remove("bg-green-600");
    o2Controls.classList.add("hidden");
  }

  // =======================================================
  //               TAREA MANUAL O2 ACTIVA
  // =======================================================
  // Botón dinámico: Encender / Detener
  if (tareaO2) {
    startAeratorsBtn.textContent = "Detener";
    startAeratorsBtn.classList.remove("bg-blue-600", "hover:bg-blue-700");
    startAeratorsBtn.classList.add("bg-red-600", "hover:bg-red-700");
    startAeratorsBtn.dataset.mode = "stop";
  } else {
    startAeratorsBtn.textContent = "Encender";
    startAeratorsBtn.classList.remove("bg-red-600", "hover:bg-red-700");
    startAeratorsBtn.classList.add("bg-blue-600", "hover:bg-blue-700");
    startAeratorsBtn.dataset.mode = "start";
  }

  // === PARADA DE EMERGENCIA: mostrar solo si algún PID está en manual ===

  if (st.pid_paused_ph || st.pid_paused_o2) {
    emergencyBtn.classList.remove("hidden");
  } else {
    emergencyBtn.classList.add("hidden");
  }
}

// ===========================================================
//               ACCIONES DE BOTONES
// ===========================================================

async function refreshEstadoSeguro() {
  // intentar varias veces hasta ver que el estado cambió
  for (let i = 0; i < 6; i++) {
    // 6 intentos = ~600 ms
    await new Promise((r) => setTimeout(r, 100)); // espera 100ms
    await loadEstadoV24();

    // si el backend ya reflejó cambio → salir
    if (estadoV24 && estadoV24._last_update_ok) break;
  }
}

async function enviarComandoTCP(cmd) {
  try {
    const res = await fetch("/api/tcp_send", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ cmd }),
    });

    const data = await res.json();

    // Recargar ESTADO REAL inmediatamente después del comando
    await refreshEstadoSeguro();

    return data.ok;
  } catch (e) {
    alert("Error comunicando con el sistema");
    return false;
  }
}

emergencyBtn.addEventListener("click", async () => {
  const ok = await enviarComandoTCP("6 2"); // APAGAR TODO
  if (ok) {
    emergencyBtn.textContent = "¡Todo detenido!";
    emergencyBtn.classList.add("opacity-60");
    setTimeout(() => {
      emergencyBtn.textContent = "Parada de Emergencia";
      emergencyBtn.classList.remove("opacity-60");
    }, 2000);
  }
});

// ----- Activar / desactivar PH -----
phToggleBtn.addEventListener("click", async () => {
  const cmd = estadoV24.pid_paused_ph ? "1" : "4";
  await enviarComandoTCP(cmd);
});

// ----- Activar / desactivar O₂ -----
o2ToggleBtn.addEventListener("click", async () => {
  const cmd = estadoV24.pid_paused_o2 ? "2" : "5";
  await enviarComandoTCP(cmd);
});

// ----- pH ↑ -----
doseLimeBtn.addEventListener("click", async () => {
  const preset = phDosePreset.value;
  await enviarComandoTCP(`8 ${preset}`);
});

// ----- pH ↓ -----
doseCitricBtn.addEventListener("click", async () => {
  const preset = phDosePreset.value;
  await enviarComandoTCP(`9 ${preset}`);
});
//------- Activar O2 por cierto tiempo--------
startAeratorsBtn.addEventListener("click", async () => {
  const mode = startAeratorsBtn.dataset.mode;

  if (mode === "start") {
    const dur = parseInt(o2DurationInput.value);
    if (isNaN(dur) || dur <= 0) return alert("Duración inválida.");

    const unit = document.getElementById("o2Unit").value;

    // Conversión correcta
    let seconds = 0;

    if (unit === "min") {
      seconds = dur * 60;
    } else if (unit === "h") {
      seconds = dur * 3600;
    }

    await enviarComandoTCP(`7 ${seconds}`);
  } else if (mode === "stop") {
    await enviarComandoTCP("6 1");
  }
});

// Aplicar filtros
btnAplicarFiltro.addEventListener("click", cargarHistorial);

// Cambiar vista Tabla ↔ Gráfica
btnToggleVista.addEventListener("click", () => {
  modoVista = modoVista === "tabla" ? "grafica" : "tabla";

  btnToggleVista.textContent =
    modoVista === "tabla" ? "Ver como Gráfica" : "Ver como Tabla";

  cargarHistorial(); // recargar con modo correcto
});


// Cuando el usuario abre la sección historial
// llamá esta función desde tu showSection("historySection")
window.cargarHistorial = cargarHistorial;

// ===============================================================
// SISTEMA DE NOTIFICACIONES — BACKEND + CAMPANA + DROPDOWN
// ===============================================================

// DOM
const notifContent = document.getElementById("notifDropdownContent");
const notifBadge = document.getElementById("notifBadge");

// Estado interno
let NOTIFS = []; // últimas 20
let unreadCount = 0;

// ==============================================
// Cargar últimas 20 notificaciones desde Flask
// ==============================================
async function loadNotificaciones() {
  try {
    const res = await fetch("/api/notificaciones");
    const data = await res.json();

    NOTIFS = data; // ya viene como array [{id,tipo,mensaje,hora,leida}]
    renderNotifDropdown();
    updateNotifBadge();
  } catch (err) {
    console.error("❌ Error cargando notificaciones:", err);
  }
}

// ==============================================
// Cantidad de NO leídas (para badge 🔔)
// ==============================================
async function loadUnreadCount() {
  try {
    const res = await fetch("/api/notificaciones_no_leidas");
    const { pendientes } = await res.json();
    unreadCount = pendientes;
    updateNotifBadge();
  } catch (err) {
    console.error("❌ Error cargando unread count:", err);
  }
}

// ==============================================
// Renderizar notificaciones en el dropdown
// ==============================================
function renderNotifDropdown() {
  notifContent.innerHTML = "";

  if (!NOTIFS.length) {
    notifContent.innerHTML = `<p class="text-slate-400 text-center py-2 text-sm">Sin notificaciones</p>`;
    return;
  }

  NOTIFS.forEach((n) => {
    const div = document.createElement("div");
    div.className =
      "p-2 mb-2 rounded-md bg-[#0C2340] border border-slate-600 text-slate-200";

    div.innerHTML = `
      <p class="text-sm"><strong>${n.tipo}</strong> — ${n.mensaje}</p>
      <p class="text-xs text-slate-400">${n.hora}</p>
    `;
    notifContent.appendChild(div);
  });
}

// ==============================================
// Actualizar badge del icono
// ==============================================
function updateNotifBadge() {
  if (unreadCount === 0) {
    notifBadge.classList.add("hidden");
    notifBadge.textContent = "0";
  } else {
    notifBadge.classList.remove("hidden");
    notifBadge.textContent = unreadCount;
  }
}

// ==============================================
// Marcar notificaciones como leídas
// ==============================================
async function marcarNotificacionesLeidas() {
  try {
    await fetch("/api/notificaciones_marcar_leidas", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}), // marcar TODAS como leídas
    });
    unreadCount = 0;
    updateNotifBadge();
  } catch (err) {
    console.error("❌ Error marcando como leídas:", err);
  }
}

// ==============================================
// Comportamiento al abrir la campana
// ==============================================
notifBtn.onclick = async (e) => {
  e.stopPropagation();

  notifDropdown.classList.toggle("hidden");

  if (!notifDropdown.classList.contains("hidden")) {
    // Al abrir → marcar como leídas
    await marcarNotificacionesLeidas();
    await loadNotificaciones();
  }
};

// ==============================================
// Cerrar dropdown si clic fuera
// ==============================================
window.addEventListener("click", (e) => {
  if (!notifDropdown.contains(e.target) && !notifBtn.contains(e.target)) {
    notifDropdown.classList.add("hidden");
  }
});

// ==============================================
// Ejecutar cada 4–5 segundos
// ==============================================
setInterval(() => {
  loadUnreadCount();
  loadNotificaciones();
}, 5000);

// Primera carga
loadUnreadCount();
loadNotificaciones();

// ===============================================================
// SISTEMA DE ERRORES MULTIUSUARIO — MODAL + REINICIO DE PIDs
// ===============================================================

const modalError = document.getElementById("errorModal");
const modalDesc = document.getElementById("errorDescription");
const btnReiniciar = document.getElementById("btnReiniciarPID");
applyInteractiveButton(btnReiniciar, { hoverClass: "hover:bg-green-700" });
let errorList = document.getElementById("errorList");

let erroresActuales = [];
let needPH = false;
let needO2 = false;
let todosResueltos = false;

setInterval(checkErrores, 4000);
checkErrores();

async function checkErrores() {
  try {
    const res = await fetch("/api/errores_pendientes");
    const data = await res.json();

    if (!data.hay_error) {
      modalError.classList.add("hidden");
      erroresActuales = [];
      return;
    }

    // detectar errores nuevos y actualizados
    erroresActuales = data.errores;
    needPH = data.reiniciar_ph;
    needO2 = data.reiniciar_o2;
    todosResueltos = data.todos_resueltos === true;

    mostrarModalErrores();
  } catch (err) {
    console.error("❌ Error consultando errores_pendientes:", err);
  }
}

function mostrarModalErrores() {
  modalError.classList.remove("hidden");
  modalDesc.textContent = "Se han detectado errores en el sistema:";
  errorList.innerHTML = "";

  erroresActuales.forEach((err) => {
    const div = document.createElement("div");
    div.className =
      "bg-red-900/30 border border-red-600 rounded-md p-2 space-y-1";
    div.innerHTML = `
          <p><strong>[${err.codigo}]</strong> ${err.descripcion}</p>
          <p class="text-xs text-slate-400">Inicio: ${err.hora_inicio}</p>
          <p class="text-xs text-slate-400">${
            err.hora_fin ? "Fin: " + err.hora_fin : "Aún activo"
          }</p>
      `;
    errorList.appendChild(div);
  });

  actualizarBotones();
}

function actualizarBotones() {
  if (!todosResueltos) {
    btnReiniciar.disabled = true;
    btnReiniciar.classList.add("opacity-40", "pointer-events-none");
  } else {
    btnReiniciar.disabled = false;
    btnReiniciar.classList.remove("opacity-40", "pointer-events-none");
  }
}

btnReiniciar.addEventListener("click", async () => {
  if (!todosResueltos) return;

  btnReiniciar.disabled = true;
  btnReiniciar.textContent = "Reiniciando...";

  try {
    const res = await fetch("/api/reiniciar_pids", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        reiniciar_ph: needPH,
        reiniciar_o2: needO2,
      }),
    });

    const data = await res.json();

    if (data.ok) {
      btnReiniciar.textContent = "Reiniciado ✔";
      setTimeout(() => {
        modalError.classList.add("hidden");
        btnReiniciar.textContent = "Reiniciar Control";
        btnReiniciar.disabled = false;
      }, 1500);
    }
  } catch (e) {
    alert("No se pudo comunicar con el servidor.");
    btnReiniciar.textContent = "Reiniciar Control";
    btnReiniciar.disabled = false;
  }
});
