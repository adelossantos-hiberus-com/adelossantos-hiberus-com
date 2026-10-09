"use strict";
/* Interfaz del análisis de comercio exterior (datos ficticios). Sin dependencias externas. */

const API = "/api/v1";
const $ = (s, r = document) => r.querySelector(s);
const esc = (t) => String(t ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const nf1 = new Intl.NumberFormat("es-ES", { maximumFractionDigits: 1, minimumFractionDigits: 1 });
const nf0 = new Intl.NumberFormat("es-ES", { maximumFractionDigits: 0 });
const nf2 = new Intl.NumberFormat("es-ES", { maximumFractionDigits: 2, minimumFractionDigits: 2 });

const fmtEur = (v) => v == null ? "—" : Math.abs(v) >= 1e6 ? nf1.format(v / 1e6) + " M €" : nf1.format(v / 1e3) + " k €";
const fmtNum = (v) => v == null ? "—" : nf0.format(v);
const fmtPct = (v) => v == null ? "—" : nf1.format(v) + " %";
const fmtPp = (v) => v == null ? "—" : (v > 0 ? "+" : "") + nf2.format(v) + " pp";
const cls = (v) => v == null ? "" : v < 0 ? "neg" : "pos";

const DIM = { pais: "País", producto: "Producto", sector: "Sector", subsector: "Subsector", region: "Región" };
const MEDIDA = { exportaciones: "Exportaciones", importaciones: "Importaciones", comercio_total: "Comercio total", saldo: "Saldo" };

const estado = { meta: null, pagina: 1, orden: "comercio_total_eur", sentido: "desc", rechPagina: 1, controles: {}, peticiones: {} };

/* ---------------------------------------------------------------- red */
async function pedir(clave, ruta, params) {
  estado.peticiones[clave]?.abort();
  const ctl = new AbortController();
  estado.peticiones[clave] = ctl;
  const url = `${API}${ruta}${params ? "?" + params : ""}`;
  let resp, cuerpo;
  try {
    resp = await fetch(url, { signal: ctl.signal });
    cuerpo = await resp.json().catch((e) => { if (e.name === "AbortError") throw e; return {}; });
  } catch (e) {
    if (e.name === "AbortError") return null;
    avisar("No se pudo contactar con el servidor.");
    throw e;
  }
  // una respuesta que llega después de lanzar otra petición igual (o cancelada) no debe tocar la pantalla
  if (ctl.signal.aborted || estado.peticiones[clave] !== ctl) return null;
  if (!resp.ok) {
    avisar(cuerpo.error?.mensaje || `Error ${resp.status}`);
    throw new Error(cuerpo.error?.mensaje || resp.status);
  }
  avisar(null);
  return cuerpo;
}
function avisar(msg) { const a = $("#aviso"); a.hidden = !msg; a.textContent = msg || ""; }

/* ---------------------------------------------------------------- filtros */
function selectorMultiple(contenedor, titulo, items, alCambiar) {
  const id = "ms-" + contenedor.id;
  contenedor.innerHTML = `<details class="multi" id="${id}"><summary>${esc(titulo)}</summary><div class="panel">
    <input type="search" placeholder="Buscar…" aria-label="Buscar ${esc(titulo)}">
    ${items.map((i) => `<label><input type="checkbox" value="${esc(i.codigo)}"> ${esc(i.nombre)}</label>`).join("")}</div></details>`;
  const det = $("details", contenedor), resumen = $("summary", det);
  const refrescar = () => {
    const n = det.querySelectorAll("input[type=checkbox]:checked").length;
    resumen.textContent = n ? `${titulo} (${n})` : titulo;
  };
  det.addEventListener("change", (e) => { if (e.target.type === "checkbox") { refrescar(); alCambiar(); } });
  $("input[type=search]", det).addEventListener("input", (e) => {
    const q = e.target.value.toLowerCase();
    det.querySelectorAll("label").forEach((l) => { l.style.display = l.textContent.toLowerCase().includes(q) ? "" : "none"; });
  });
  return {
    valores: () => [...det.querySelectorAll("input[type=checkbox]:checked")].map((c) => c.value),
    limpiar: () => { det.querySelectorAll("input[type=checkbox]").forEach((c) => (c.checked = false)); refrescar(); },
    fijar: (vals) => { det.querySelectorAll("input[type=checkbox]").forEach((c) => (c.checked = vals.includes(c.value))); refrescar(); },
  };
}

function paramsFiltros() {
  const p = new URLSearchParams();
  const d = $("#f-desde").value, h = $("#f-hasta").value;
  if (d) p.set("desde", d);
  if (h) p.set("hasta", h);
  for (const [k, ctl] of Object.entries(estado.controles)) ctl.valores().forEach((v) => p.append(k, v));
  return p;
}
function conExtra(extra) {
  const p = paramsFiltros();
  for (const [k, v] of Object.entries(extra)) p.set(k, v);
  return p.toString();
}
function guardarUrl() { history.replaceState(null, "", "?" + paramsFiltros().toString()); }
function leerUrl() {
  const p = new URLSearchParams(location.search);
  if (p.get("desde")) $("#f-desde").value = p.get("desde");
  if (p.get("hasta")) $("#f-hasta").value = p.get("hasta");
  for (const [k, ctl] of Object.entries(estado.controles)) ctl.fijar(p.getAll(k).flatMap((v) => v.split(",")));
}

/* ---------------------------------------------------------------- gráficos SVG */
const anchoDe = (el) => Math.max(320, Math.round(el.clientWidth || 720));
const etqEje = (v) => v === 0 ? "0" : Math.abs(v) >= 1e6 ? nf0.format(v / 1e6) + " M" : Math.abs(v) >= 1e3 ? nf0.format(v / 1e3) + " k" : nf0.format(v);
function ticks(min, max, n = 5) {
  if (min === max) { max = min + 1; }
  const paso0 = (max - min) / n, mag = Math.pow(10, Math.floor(Math.log10(paso0)));
  const paso = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((p) => p >= paso0);
  const ini = Math.floor(min / paso) * paso, out = [];
  for (let v = ini; v <= max + paso * 0.5; v += paso) out.push(v);
  return out;
}
function vacio(el, texto = "Sin datos para los filtros seleccionados.") { el.innerHTML = `<p class="vacio">${esc(texto)}</p>`; }

function graficoLineas(el, puntos, series) {
  // puntos: [{x:'2019-03', ...}], series: [{clave, color, nombre}]
  const valores = puntos.flatMap((p) => series.map((s) => p[s.clave])).filter((v) => v != null);
  if (!valores.length) return vacio(el);
  const W = anchoDe(el), H = 250, m = { l: 62, r: 12, t: 14, b: 26 };
  const ts = ticks(Math.min(0, ...valores), Math.max(...valores));
  const y0 = ts[0], y1 = ts[ts.length - 1];
  const X = (i) => m.l + (puntos.length === 1 ? (W - m.l - m.r) / 2 : i * (W - m.l - m.r) / (puntos.length - 1));
  const Y = (v) => H - m.b - (v - y0) / (y1 - y0 || 1) * (H - m.t - m.b);
  let s = ts.map((t) => `<line x1="${m.l}" x2="${W - m.r}" y1="${Y(t)}" y2="${Y(t)}" stroke="currentColor" opacity=".12"/><text x="${m.l - 6}" y="${Y(t) + 4}" text-anchor="end">${etqEje(t)}</text>`).join("");
  puntos.forEach((p, i) => { if (p.x.endsWith("-01")) s += `<text x="${X(i)}" y="${H - 8}" text-anchor="middle">${p.x.slice(0, 4)}</text>`; });
  for (const se of series) {
    let d = "", abierto = false;
    puntos.forEach((p, i) => { const v = p[se.clave]; if (v == null) { abierto = false; return; } d += `${abierto ? "L" : "M"}${X(i).toFixed(1)},${Y(v).toFixed(1)}`; abierto = true; });
    s += `<path d="${d}" fill="none" stroke="${se.color}" stroke-width="2"/>`;
    puntos.forEach((p, i) => { const v = p[se.clave]; if (v != null) s += `<circle cx="${X(i).toFixed(1)}" cy="${Y(v).toFixed(1)}" r="${puntos.length > 60 ? 2.5 : 3.5}" fill="${se.color}" opacity="0"><title>${esc(p.x)} · ${esc(se.nombre)}: ${fmtEur(v)}</title></circle>`; });
  }
  s += series.map((se, i) => `<rect x="${m.l + i * 130}" y="${2}" width="10" height="10" fill="${se.color}"/><text x="${m.l + i * 130 + 14}" y="11">${esc(se.nombre)}</text>`).join("");
  el.innerHTML = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Gráfico de líneas">${s}</svg>`;
  el.querySelectorAll("circle").forEach((c) => c.addEventListener("mouseenter", () => (c.style.opacity = 1)) || c.addEventListener("mouseleave", () => (c.style.opacity = 0)));
}

function graficoBarrasVerticales(el, puntos, claveEtq, valorFn, colorFn, titulo, alto = 120) {
  const vals = puntos.map(valorFn);
  if (!vals.some((v) => v != null)) return vacio(el, "Sin datos de saldo.");
  const W = anchoDe(el), m = { l: 62, r: 12, t: 10, b: 8 }, H = alto;
  const ts = ticks(Math.min(0, ...vals.filter((v) => v != null)), Math.max(0, ...vals.filter((v) => v != null)), 3);
  const y0 = ts[0], y1 = ts[ts.length - 1];
  const Y = (v) => H - m.b - (v - y0) / (y1 - y0 || 1) * (H - m.t - m.b);
  const bw = Math.max(1, (W - m.l - m.r) / puntos.length - 1);
  let s = ts.map((t) => `<line x1="${m.l}" x2="${W - m.r}" y1="${Y(t)}" y2="${Y(t)}" stroke="currentColor" opacity="${t === 0 ? .4 : .1}"/><text x="${m.l - 6}" y="${Y(t) + 4}" text-anchor="end">${etqEje(t)}</text>`).join("");
  puntos.forEach((p, i) => { const v = vals[i]; if (v == null) return;
    const x = m.l + i * (W - m.l - m.r) / puntos.length, ya = Y(Math.max(v, 0)), yb = Y(Math.min(v, 0));
    s += `<rect x="${x.toFixed(1)}" y="${ya.toFixed(1)}" width="${bw.toFixed(1)}" height="${Math.max(0.5, yb - ya).toFixed(1)}" fill="${colorFn(v)}"><title>${esc(p[claveEtq])} · ${titulo}: ${fmtEur(v)}</title></rect>`; });
  s += `<text x="${m.l}" y="9">${esc(titulo)}</text>`;
  el.innerHTML = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(titulo)}">${s}</svg>`;
}

function graficoAnual(el, filas) {
  const datos = filas.filter((f) => f.exportaciones_eur != null || f.importaciones_eur != null);
  if (!datos.length) return vacio(el);
  const W = anchoDe(el), H = 220, m = { l: 62, r: 10, t: 14, b: 26 };
  const max = Math.max(...datos.flatMap((f) => [f.exportaciones_eur ?? 0, f.importaciones_eur ?? 0]));
  const ts = ticks(0, max, 4), top = ts[ts.length - 1];
  const Y = (v) => H - m.b - v / top * (H - m.t - m.b);
  const gw = (W - m.l - m.r) / filas.length;
  let s = ts.map((t) => `<line x1="${m.l}" x2="${W - m.r}" y1="${Y(t)}" y2="${Y(t)}" stroke="currentColor" opacity=".12"/><text x="${m.l - 6}" y="${Y(t) + 4}" text-anchor="end">${etqEje(t)}</text>`).join("");
  filas.forEach((f, i) => {
    const x = m.l + i * gw, bw = gw * 0.34;
    [[f.exportaciones_eur, "var(--exp)", "Exportaciones", 0.12], [f.importaciones_eur, "var(--imp)", "Importaciones", 0.5]].forEach(([v, c, n, off]) => {
      if (v != null) s += `<rect x="${(x + gw * off).toFixed(1)}" y="${Y(v).toFixed(1)}" width="${bw.toFixed(1)}" height="${(H - m.b - Y(v)).toFixed(1)}" fill="${c}"><title>${f.anio} · ${n}: ${fmtEur(v)}</title></rect>`; });
    s += `<text x="${x + gw / 2}" y="${H - 8}" text-anchor="middle">${f.anio}</text>`;
  });
  s += `<rect x="${m.l}" y="2" width="10" height="10" fill="var(--exp)"/><text x="${m.l + 14}" y="11">Exportaciones</text><rect x="${m.l + 110}" y="2" width="10" height="10" fill="var(--imp)"/><text x="${m.l + 124}" y="11">Importaciones</text>`;
  el.innerHTML = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Exportaciones e importaciones por año">${s}</svg>`;
}

function graficoBarrasH(el, items, { etiqueta, valor, formato, color }) {
  if (!items.length) return vacio(el);
  const ancho = anchoDe(el), fila = 26, m = { l: 150, r: 95, t: 6, b: 6 }, H = items.length * fila + m.t + m.b;
  const vals = items.map(valor), min = Math.min(0, ...vals), max = Math.max(0, ...vals);
  const X = (v) => m.l + (v - min) / (max - min || 1) * (ancho - m.l - m.r), x0 = X(0);
  let s = `<line x1="${x0}" x2="${x0}" y1="0" y2="${H}" stroke="currentColor" opacity=".3"/>`;
  items.forEach((it, i) => {
    const v = valor(it), y = m.t + i * fila, xa = Math.min(x0, X(v)), w = Math.abs(X(v) - x0);
    const e = String(etiqueta(it)); const eTxt = e.length > 26 ? e.slice(0, 25) + "…" : e;
    s += `<text x="${m.l - 8}" y="${y + 16}" text-anchor="end">${esc(eTxt)}</text>
      <rect x="${xa.toFixed(1)}" y="${y + 4}" width="${Math.max(1, w).toFixed(1)}" height="${fila - 9}" rx="2" fill="${color(it)}"><title>${esc(e)}: ${esc(formato(v))}</title></rect>
      <text x="${(v >= 0 ? xa + w + 5 : xa - 5).toFixed(1)}" y="${y + 16}" text-anchor="${v >= 0 ? "start" : "end"}">${esc(formato(v))}</text>`;
  });
  el.innerHTML = `<svg viewBox="0 0 ${ancho} ${H}" role="img">${s}</svg>`;
}

/* ---------------------------------------------------------------- vistas */
function variacion(v) {
  if (v == null) return '<span class="var">sin comparación</span>';
  return `<span class="var"><span class="${v >= 0 ? "sube" : "baja"}">${v >= 0 ? "▲" : "▼"} ${fmtPct(Math.abs(v))}</span> vs. mismo periodo del año anterior</span>`;
}
async function cargarResumen() {
  const cont = $("#vista-resumen");
  cont.classList.add("cargando");
  try {
    const modo = $("#serie-modo").value, dim = $("#top-dim").value, med = $("#top-medida").value, n = $("#top-n").value;
    const [r, sm, sa, tp, ct] = await Promise.all([
      pedir("res", "/resumen", paramsFiltros().toString()),
      pedir("sm", "/serie/mensual", paramsFiltros().toString()),
      pedir("sa", "/serie/anual", paramsFiltros().toString()),
      pedir("top", "/top", conExtra({ dimension: dim, medida: med, n })),
      pedir("ct", "/contribucion", conExtra({ dimension: dim, medida: med, n })),
    ]);
    if (!r) return;
    const d = r.datos;
    $("#kpis").innerHTML = [
      ["exportaciones", "Exportaciones", fmtEur(d.exportaciones_eur), variacion(d.var_exportaciones_pct), ""],
      ["importaciones", "Importaciones", fmtEur(d.importaciones_eur), variacion(d.var_importaciones_pct), ""],
      ["saldo", "Saldo comercial", fmtEur(d.saldo_eur), d.var_saldo_eur == null ? "" : `<span class="var">${d.var_saldo_eur >= 0 ? "▲" : "▼"} ${fmtEur(Math.abs(d.var_saldo_eur))} vs. mismo periodo del año anterior</span>`, cls(d.saldo_eur)],
      ["cobertura", "Tasa de cobertura", d.cobertura_pct == null ? "—" : fmtPct(d.cobertura_pct), '<span class="var">exportaciones / importaciones</span>', ""],
      ["operaciones", "Operaciones", fmtNum(d.n_operaciones), `<span class="var">${fmtNum(d.unidades)} uds · ${fmtNum((d.peso_kg ?? 0) / 1000)} t</span>`, ""],
    ].map(([id, e, v, sub, c]) => `<div class="kpi" data-testid="kpi-${id}"><div class="etq">${e}</div><div class="val ${c}">${v}</div><div class="var">${sub}</div></div>`).join("");

    const acum = modo === "acumulado";
    const pts = sm.datos.map((f) => ({ x: f.mes_inicio.slice(0, 7), exp: acum ? f.exportaciones_acum_eur : f.exportaciones_eur, imp: acum ? f.importaciones_acum_eur : f.importaciones_eur, saldo: acum ? f.saldo_acum_eur : f.saldo_eur }));
    graficoLineas($("#grafico-serie"), pts, [{ clave: "exp", color: "var(--exp)", nombre: "Exportaciones" }, { clave: "imp", color: "var(--imp)", nombre: "Importaciones" }]);
    graficoBarrasVerticales($("#grafico-saldo"), pts, "x", (p) => p.saldo, (v) => (v >= 0 ? "var(--pos)" : "var(--neg)"), acum ? "Saldo acumulado" : "Saldo mensual");

    graficoAnual($("#grafico-anual"), sa.datos);
    $("#tabla-anual").innerHTML = `<table><thead><tr><th>Año</th><th>Saldo</th><th>Cobertura</th><th>Var. export.</th><th>Var. import.</th></tr></thead><tbody>${
      sa.datos.map((f) => `<tr><td>${f.anio}${f.meses_con_datos < f.meses_en_periodo ? ` <span class="nota">(${f.meses_con_datos}/${f.meses_en_periodo} meses)</span>` : ""}</td><td class="${cls(f.saldo_eur)}">${fmtEur(f.saldo_eur)}</td><td>${fmtPct(f.cobertura_pct)}</td><td class="${cls(f.var_exportaciones_pct)}">${fmtPct(f.var_exportaciones_pct)}</td><td class="${cls(f.var_importaciones_pct)}">${fmtPct(f.var_importaciones_pct)}</td></tr>`).join("")}</tbody></table>`;

    graficoBarrasH($("#grafico-top"), tp.datos, { etiqueta: (i) => i.nombre, valor: (i) => i.valor, formato: fmtEur,
      color: (i) => (i.es_resto ? "var(--resto)" : i.valor < 0 ? "var(--neg)" : "var(--exp)") });
    const totalTop = tp.datos.reduce((a, i) => a + i.valor, 0);
    $("#top-total").textContent = tp.datos.length ? `Top ${n} + Resto = ${fmtEur(totalTop)} (${MEDIDA[med].toLowerCase()} del periodo${med === "saldo" ? "; la cuota no se define para el saldo" : ""})` : "";

    graficoBarrasH($("#grafico-contrib"), ct.datos, { etiqueta: (i) => i.nombre, valor: (i) => i.contribucion_pp ?? 0, formato: fmtPp,
      color: (i) => (i.es_resto ? "var(--resto)" : (i.contribucion_pp ?? 0) >= 0 ? "var(--pos)" : "var(--neg)") });
    const g = ct.datos[0]?.crecimiento_total_pct;
    $("#contrib-total").textContent = g == null ? "Sin periodo anterior comparable (variación total no definida)." : `Crecimiento interanual total de ${MEDIDA[med].toLowerCase()}: ${fmtPct(g)} (suma de las contribuciones).`;
  } finally { cont.classList.remove("cargando"); }
}

const COLUMNAS_TABLA = [
  ["nombre", "Nombre", (f) => esc(f.nombre), "izq"], ["exportaciones_eur", "Exportaciones", (f) => fmtEur(f.exportaciones_eur)],
  ["importaciones_eur", "Importaciones", (f) => fmtEur(f.importaciones_eur)],
  ["saldo_eur", "Saldo", (f) => `<span class="${cls(f.saldo_eur)}">${fmtEur(f.saldo_eur)}</span>`],
  ["cobertura_pct", "Cobertura", (f) => fmtPct(f.cobertura_pct)], ["cuota_comercio_pct", "Cuota comercio", (f) => fmtPct(f.cuota_comercio_pct)],
  ["var_exportaciones_pct", "Var. export.", (f) => `<span class="${cls(f.var_exportaciones_pct)}">${fmtPct(f.var_exportaciones_pct)}</span>`],
  ["var_importaciones_pct", "Var. import.", (f) => `<span class="${cls(f.var_importaciones_pct)}">${fmtPct(f.var_importaciones_pct)}</span>`],
  ["n_operaciones", "Operaciones", (f) => fmtNum(f.n_operaciones)], ["ranking", "Rank.", (f) => f.ranking],
];
async function cargarTabla() {
  const dim = $("#tabla-dim").value, tamano = $("#tabla-tamano").value;
  const extra = { dimension: dim, orden: estado.orden, sentido: estado.sentido, pagina: estado.pagina, tamano };
  const r = await pedir("tabla", "/tabla", conExtra(extra));
  if (!r) return;
  const { total, paginas } = r.paginacion;
  $("#tabla-datos").innerHTML = `<thead><tr>${COLUMNAS_TABLA.map(([k, t, , c]) => `<th class="ord ${c || ""}" data-k="${k}" aria-sort="${estado.orden === k ? (estado.sentido === "asc" ? "ascending" : "descending") : "none"}" tabindex="0">${t}${estado.orden === k ? (estado.sentido === "asc" ? " ▲" : " ▼") : ""}</th>`).join("")}</tr></thead>
    <tbody>${r.datos.length ? r.datos.map((f) => `<tr>${COLUMNAS_TABLA.map(([, , fn, c]) => `<td class="${c || ""}">${fn(f)}</td>`).join("")}</tr>`).join("") : `<tr><td colspan="10" class="vacio">Sin resultados para los filtros seleccionados.</td></tr>`}</tbody>`;
  $("#pag-info").textContent = `Página ${r.paginacion.pagina} de ${paginas} · ${fmtNum(total)} filas`;
  $("#pag-ant").disabled = estado.pagina <= 1;
  $("#pag-sig").disabled = estado.pagina >= paginas;
  $("#btn-exportar").href = `${API}/export/tabla.csv?${conExtra({ dimension: dim, orden: estado.orden, sentido: estado.sentido })}`;
  const rk = await pedir("rank", "/ranking", conExtra({ dimension: $("#rank-dim").value, n: 5 }));
  if (rk) {
    $("#tabla-ranking").innerHTML = `<thead><tr><th>Año</th><th>Pos.</th><th class="izq">Nombre</th><th>Comercio total</th><th>Cuota</th><th>Cambio</th></tr></thead><tbody>${
      rk.datos.map((f) => `<tr><td>${f.anio}</td><td>${f.posicion}</td><td class="izq">${esc(f.nombre)}</td><td>${fmtEur(f.valor)}</td><td>${fmtPct(f.cuota_pct)}</td><td>${f.cambio_posicion == null ? (f.anio <= +estado.meta.rango.desde.slice(0, 4) ? "—" : "nuevo") : f.cambio_posicion > 0 ? `<span class="pos">▲ ${f.cambio_posicion}</span>` : f.cambio_posicion < 0 ? `<span class="neg">▼ ${-f.cambio_posicion}</span>` : "="}</td></tr>`).join("")}</tbody>`;
  }
}

const insignia = (ok, t) => `<span class="insignia ${ok ? "ok" : "err"}">${esc(t)}</span>`;
async function cargarCalidad() {
  const r = await pedir("cal", "/calidad");
  if (!r) return;
  $("#calidad-kpis").innerHTML = [["Controles superados", r.resumen.ok], ["Controles fallidos", r.resumen.error],
    ["Filas rechazadas", r.conservacion ? fmtNum(r.conservacion.rechazados) : "—"], ["Filas descartadas", r.conservacion ? fmtNum(r.conservacion.descartes) : "—"]]
    .map(([e, v]) => `<div class="kpi"><div class="etq">${e}</div><div class="val">${v}</div></div>`).join("");
  $("#tabla-checks").innerHTML = `<thead><tr><th class="izq">Control</th><th class="izq">Capa</th><th class="izq">Resultado</th><th class="izq">Detalle</th></tr></thead><tbody>${
    r.checks.map((c) => `<tr><td class="izq">${esc(c.nombre)}</td><td class="izq">${esc(c.capa)}</td><td class="izq">${insignia(c.ok, c.ok ? "OK" : "ERROR")}</td><td class="izq" style="white-space:normal">${esc(c.detalle)}</td></tr>`).join("")}</tbody>`;
  const c = r.conservacion;
  $("#conservacion").innerHTML = c ? `<table><tbody><tr><td>Bronze (filas recibidas)</td><td>${fmtNum(c.bronze)}</td></tr><tr><td>Silver (versión vigente)</td><td>${fmtNum(c.silver)}</td></tr><tr><td>Rechazados</td><td>${fmtNum(c.rechazados)}</td></tr><tr><td>Descartados</td><td>${fmtNum(c.descartes)}</td></tr><tr><th>Diferencia</th><th class="${c.diferencia ? "neg" : "pos"}">${fmtNum(c.diferencia)}</th></tr></tbody></table>` : "";
  const tabla = (titulo, filas) => `<h3 style="font-size:13px;margin:8px 0 4px">${titulo}</h3>` + (filas.length ? `<table><tbody>${filas.map((f) => `<tr><td>${esc(f.motivo)}</td><td>${fmtNum(f.filas)}</td></tr>`).join("")}</tbody></table>` : '<p class="nota">Ninguno.</p>');
  $("#motivos").innerHTML = tabla("Rechazos (registros inválidos)", r.rechazos_por_motivo) + tabla("Descartes (duplicados y versiones sustituidas)", r.descartes_por_motivo);
  const sel = $("#rech-motivo");
  if (sel.options.length === 1) r.rechazos_por_motivo.forEach((m) => sel.add(new Option(m.motivo, m.motivo)));
  await cargarRechazados();
}
async function cargarRechazados() {
  const p = new URLSearchParams({ pagina: estado.rechPagina, tamano: 10 });
  if ($("#rech-motivo").value) p.set("motivo", $("#rech-motivo").value);
  const r = await pedir("rech", "/calidad/rechazados", p.toString());
  if (!r) return;
  $("#tabla-rechazados").innerHTML = `<thead><tr><th class="izq">Ingesta</th><th>Fila</th><th class="izq">Operación</th><th class="izq">Fecha</th><th class="izq">Flujo</th><th class="izq">País</th><th class="izq">Producto</th><th>Importe</th><th class="izq">Motivo</th></tr></thead><tbody>${
    r.filas.map((f) => `<tr><td class="izq">${esc(f.ingesta_id)}</td><td>${f.fila_origen}</td><td class="izq">${esc(f.operacion_id)}</td><td class="izq">${esc(f.fecha)}</td><td class="izq">${esc(f.flujo)}</td><td class="izq">${esc(f.pais_codigo)}</td><td class="izq">${esc(f.producto_codigo)}</td><td>${f.importe_eur == null ? "—" : nf2.format(f.importe_eur)}</td><td class="izq"><span class="insignia neutro">${esc(f.motivo)}</span></td></tr>`).join("")}</tbody>`;
  $("#rech-info").textContent = `Página ${r.pagina} de ${r.paginas} · ${fmtNum(r.total)} rechazados`;
  $("#rech-ant").disabled = r.pagina <= 1; $("#rech-sig").disabled = r.pagina >= r.paginas;
}
async function cargarIngestas() {
  const r = await pedir("ing", "/ingestas");
  if (!r) return;
  const s = r.resumen;
  $("#ingestas-kpis").innerHTML = [["Ingestas", s.total], ["Completadas", s.completadas], ["Fallidas / en curso", `${s.fallidas} / ${s.en_curso}`], ["Reintentos omitidos", s.reintentos_omitidos]]
    .map(([e, v]) => `<div class="kpi"><div class="etq">${e}</div><div class="val">${v}</div></div>`).join("");
  const est = (e) => `<span class="insignia ${e === "COMPLETADA" ? "ok" : e === "FALLIDA" ? "err" : "neutro"}">${esc(e)}</span>`;
  $("#tabla-ingestas").innerHTML = `<thead><tr><th class="izq">Ingesta</th><th class="izq">Fichero</th><th class="izq">Periodo</th><th class="izq">Estado</th><th>Recibidas</th><th>Válidas</th><th>Rechazadas</th><th>Duplicadas</th><th>Versiones antiguas</th><th>Nuevas</th><th>Correcciones</th><th>Duración (s)</th></tr></thead><tbody>${
    r.datos.map((f) => `<tr class="clic" data-id="${esc(f.ingesta_id)}" tabindex="0"><td class="izq">${esc(f.ingesta_id)}</td><td class="izq">${esc(f.fichero_origen)}</td><td class="izq">${esc(f.periodo)}</td><td class="izq">${est(f.estado)}</td><td>${fmtNum(f.filas_recibidas)}</td><td>${fmtNum(f.filas_validas)}</td><td>${fmtNum(f.filas_rechazadas)}</td><td>${fmtNum(f.duplicados_exactos)}</td><td>${fmtNum(f.versiones_antiguas)}</td><td>${fmtNum(f.nuevas_operaciones)}</td><td>${fmtNum(f.correcciones_aplicadas)}</td><td>${nf2.format((f.dur_bronze_s || 0) + (f.dur_silver_s || 0) + (f.dur_gold_s || 0))}</td></tr>`).join("")}</tbody>`;
}
async function abrirIngesta(id) {
  const r = await pedir("ing1", `/ingestas/${encodeURIComponent(id)}`);
  if (!r) return;
  const i = r.ingesta, lista = (a) => a.length ? `<ul>${a.map((x) => `<li>${esc(x.motivo)}: ${fmtNum(x.filas)}</li>`).join("")}</ul>` : '<p class="nota">Ninguno.</p>';
  $("#detalle-ingesta").hidden = false;
  $("#detalle-titulo").textContent = `${i.ingesta_id} · ${i.fichero_origen}`;
  $("#detalle-cuerpo").innerHTML = `<p class="nota">Huella de contenido: <code>${esc((i.hash_contenido || "").slice(0, 16))}…</code> · periodos afectados: ${esc(i.periodos_afectados || "—")}</p>
    <div class="rejilla"><div><h3>Rechazos</h3>${lista(r.rechazos_por_motivo)}</div><div><h3>Descartes originados</h3>${lista(r.descartes_por_motivo)}</div>
    <div><h3>Eventos</h3><ul>${r.eventos.map((e) => `<li>${esc(String(e.ts).slice(0, 19))} · ${esc(e.evento)} ${esc(e.detalle || "")}</li>`).join("")}</ul></div></div>`;
  $("#detalle-ingesta").scrollIntoView({ behavior: "smooth", block: "nearest" });
}

/* ---------------------------------------------------------------- navegación */
const CARGADORES = { resumen: cargarResumen, detalle: cargarTabla, calidad: cargarCalidad, ingestas: cargarIngestas };
let pestanaActual = "resumen";
function cambiarPestana(t) {
  pestanaActual = t;
  document.querySelectorAll("[role=tab]").forEach((b) => b.setAttribute("aria-selected", b.dataset.tab === t));
  document.querySelectorAll(".vista").forEach((v) => (v.hidden = v.id !== `vista-${t}`));
  $("#filtros").hidden = t === "calidad" || t === "ingestas";
  refrescar();
}
function refrescar() { guardarUrl(); CARGADORES[pestanaActual]().catch(() => {}); }

async function iniciar() {
  const meta = await (await fetch(`${API}/meta`)).json().catch(() => null);
  if (!meta || meta.error) { avisar(meta?.error?.mensaje || "No hay datos cargados."); return; }
  estado.meta = meta;
  const cambio = () => { estado.pagina = 1; refrescar(); };
  estado.controles = {
    pais: selectorMultiple($("#f-pais"), "Países", meta.paises.map((p) => ({ codigo: p.pais_codigo, nombre: `${p.pais} (${p.pais_codigo})` })), cambio),
    sector: selectorMultiple($("#f-sector"), "Sectores", meta.sectores.map((s) => ({ codigo: s.codigo, nombre: s.nombre })), cambio),
    subsector: selectorMultiple($("#f-subsector"), "Subsectores", meta.subsectores.map((s) => ({ codigo: s.subsector_codigo, nombre: s.subsector })), cambio),
    producto: selectorMultiple($("#f-producto"), "Productos", meta.productos.map((p) => ({ codigo: p.producto_codigo, nombre: p.producto })), cambio),
  };
  const opcDim = (id, def) => { const s = $(id); s.innerHTML = meta.dimensiones.map((d) => `<option value="${d}">${DIM[d] || d}</option>`).join(""); s.value = def; };
  opcDim("#top-dim", "pais"); opcDim("#tabla-dim", "pais"); opcDim("#rank-dim", "pais");
  $("#top-medida").innerHTML = meta.medidas.map((m) => `<option value="${m}">${MEDIDA[m]}</option>`).join("");
  $("#top-medida").value = "comercio_total";
  leerUrl();
  ["#f-desde", "#f-hasta"].forEach((id) => $(id).addEventListener("change", cambio));
  ["#serie-modo", "#top-dim", "#top-medida", "#top-n"].forEach((id) => $(id).addEventListener("change", () => refrescar()));
  ["#tabla-dim", "#tabla-tamano", "#rank-dim"].forEach((id) => $(id).addEventListener("change", cambio));
  $("#f-limpiar").addEventListener("click", () => { $("#f-desde").value = "2018-01"; $("#f-hasta").value = "2025-12"; Object.values(estado.controles).forEach((c) => c.limpiar()); cambio(); });
  document.querySelectorAll("[role=tab]").forEach((b) => b.addEventListener("click", () => cambiarPestana(b.dataset.tab)));
  $("#pag-ant").addEventListener("click", () => { estado.pagina--; refrescar(); });
  $("#pag-sig").addEventListener("click", () => { estado.pagina++; refrescar(); });
  $("#tabla-datos").addEventListener("click", (e) => {
    const th = e.target.closest("th[data-k]"); if (!th) return;
    estado.sentido = estado.orden === th.dataset.k && estado.sentido === "desc" ? "asc" : "desc"; estado.orden = th.dataset.k; estado.pagina = 1; refrescar();
  });
  $("#rech-motivo").addEventListener("change", () => { estado.rechPagina = 1; cargarRechazados(); });
  $("#rech-ant").addEventListener("click", () => { estado.rechPagina--; cargarRechazados(); });
  $("#rech-sig").addEventListener("click", () => { estado.rechPagina++; cargarRechazados(); });
  $("#tabla-ingestas").addEventListener("click", (e) => { const tr = e.target.closest("tr[data-id]"); if (tr) abrirIngesta(tr.dataset.id); });
  refrescar();
}
let anchoPrevio = window.innerWidth, temporizador;
window.addEventListener("resize", () => {
  clearTimeout(temporizador);
  temporizador = setTimeout(() => { if (Math.abs(window.innerWidth - anchoPrevio) > 120) { anchoPrevio = window.innerWidth; if (estado.meta) refrescar(); } }, 300);
});
iniciar();
