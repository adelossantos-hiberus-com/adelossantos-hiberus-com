"""Pruebas de extremo a extremo: servidor real (uvicorn) + navegador Chromium (Playwright).

Se omiten si Playwright o Chromium no están disponibles.
"""

import os
import re
import socket
import subprocess
import sys
import time
import urllib.request
import json
from pathlib import Path

import pytest

sync_api = pytest.importorskip("playwright.sync_api")

SRC = str(Path(__file__).resolve().parents[1] / "src")
pytestmark = pytest.mark.e2e


def _puerto_libre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def servidor(lago):
    puerto = _puerto_libre()
    env = {**os.environ, "PYTHONPATH": SRC}
    proc = subprocess.Popen([sys.executable, "-m", "comercio_exterior.cli", "servir", "--destino", str(lago.raiz),
                             "--puerto", str(puerto)], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    url = f"http://127.0.0.1:{puerto}"
    for _ in range(100):
        try:
            urllib.request.urlopen(url + "/api/v1/salud", timeout=1)
            break
        except Exception:
            time.sleep(0.1)
    else:
        proc.kill()
        pytest.fail("el servidor no arrancó: " + proc.stdout.read().decode())
    yield url
    proc.terminate()
    proc.wait(timeout=10)


@pytest.fixture(scope="module")
def navegador():
    with sync_api.sync_playwright() as p:
        candidatos = [dict(executable_path="/opt/pw-browsers/chromium", args=["--no-sandbox"]), dict(args=["--no-sandbox"])]
        for kw in candidatos:
            try:
                b = p.chromium.launch(**kw)
                break
            except Exception:
                continue
        else:
            pytest.skip("Chromium no disponible")
        yield b
        b.close()


@pytest.fixture
def pagina(navegador, servidor):
    ctx = navegador.new_context(viewport={"width": 1400, "height": 1000}, accept_downloads=True, locale="es-ES")
    pg = ctx.new_page()
    problemas = []
    pg.on("pageerror", lambda e: problemas.append(f"pageerror: {e}"))
    pg.on("console", lambda m: problemas.append(f"console: {m.text}") if m.type == "error" else None)
    # las peticiones obsoletas se cancelan a propósito (AbortController): no son un fallo
    pg.on("requestfailed", lambda r: problemas.append(f"requestfailed: {r.url} {r.failure}")
          if "ERR_ABORTED" not in (r.failure or "") else None)
    pg.problemas, pg.base = problemas, servidor
    yield pg
    ctx.close()


def api(servidor, ruta, **params):
    from urllib.parse import urlencode
    with urllib.request.urlopen(f"{servidor}/api/v1{ruta}?{urlencode(params, doseq=True)}") as r:
        return json.load(r)


def millones(texto: str) -> float:
    """'14.581,7 M €' -> 14581.7"""
    return float(re.sub(r"[^\d,\-]", "", texto).replace(",", "."))


def abrir(pg, qs="", graficos=True):
    pg.goto(pg.base + "/" + qs)
    pg.wait_for_selector("[data-testid=kpi-exportaciones] .val")
    pg.wait_for_selector("[data-testid=grafico-top] svg" if graficos else "[data-testid=grafico-top] .vacio")


def kpi(pg, k):
    return pg.inner_text(f"[data-testid=kpi-{k}] .val")


def test_la_pagina_carga_con_indicadores_graficos_y_sin_errores(pagina, servidor):
    abrir(pagina)
    d = api(servidor, "/resumen")["datos"]
    assert millones(kpi(pagina, "exportaciones")) == pytest.approx(d["exportaciones_eur"] / 1e6, abs=0.06)
    assert millones(kpi(pagina, "importaciones")) == pytest.approx(d["importaciones_eur"] / 1e6, abs=0.06)
    assert millones(kpi(pagina, "saldo")) == pytest.approx(d["saldo_eur"] / 1e6, abs=0.06)
    assert millones(kpi(pagina, "operaciones").replace("€", "")) * 1 == pytest.approx(d["n_operaciones"] / 1000 * 1000, abs=1) \
        or kpi(pagina, "operaciones").replace(".", "") == str(d["n_operaciones"])
    for t in ("grafico-serie", "grafico-saldo", "grafico-anual", "grafico-top", "grafico-contrib"):
        assert pagina.locator(f"[data-testid={t}] svg").count() == 1
    assert pagina.locator("[data-testid=grafico-top] svg rect").count() >= 8
    assert pagina.title().startswith("Comercio exterior")
    pagina.wait_for_timeout(300)
    assert pagina.problemas == []


def test_filtro_por_pais_actualiza_indicadores_y_url(pagina, servidor):
    abrir(pagina)
    antes = kpi(pagina, "operaciones")
    pagina.click("#f-pais summary")
    pagina.fill("#f-pais input[type=search]", "alem")
    pagina.check("#f-pais input[value=DE]")
    pagina.wait_for_function("(a) => document.querySelector('[data-testid=kpi-operaciones] .val').textContent !== a", arg=antes)
    esperado = api(servidor, "/resumen", pais="DE")["datos"]
    assert kpi(pagina, "operaciones").replace(".", "") == str(esperado["n_operaciones"])
    assert millones(kpi(pagina, "exportaciones")) == pytest.approx(esperado["exportaciones_eur"] / 1e6, abs=0.06)
    assert "pais=DE" in pagina.url
    assert pagina.inner_text("#f-pais summary") == "Países (1)"
    # el Top N se recalcula con el filtro: solo un país, sin «Resto»
    pagina.wait_for_function("document.querySelectorAll('[data-testid=grafico-top] svg rect').length === 1")


def test_filtros_de_fecha_y_estado_restaurable_desde_la_url(pagina, servidor):
    abrir(pagina, "?desde=2022-01&hasta=2022-12&sector=S01")
    assert pagina.input_value("#f-desde") == "2022-01" and pagina.input_value("#f-hasta") == "2022-12"
    assert pagina.inner_text("#f-sector summary") == "Sectores (1)"
    esperado = api(servidor, "/resumen", desde="2022-01", hasta="2022-12", sector="S01")["datos"]
    assert kpi(pagina, "operaciones").replace(".", "") == str(esperado["n_operaciones"])
    # el selector de vista acumulada cambia el gráfico sin errores
    pagina.select_option("#serie-modo", "acumulado")
    pagina.wait_for_function("document.querySelector('[data-testid=grafico-saldo] svg').getAttribute('aria-label') === 'Saldo acumulado'")
    # cambiar el rango desde la interfaz
    pagina.fill("#f-hasta", "2022-06")
    pagina.dispatch_event("#f-hasta", "change")
    esp2 = api(servidor, "/resumen", desde="2022-01", hasta="2022-06", sector="S01")["datos"]
    pagina.wait_for_function("(n) => document.querySelector('[data-testid=kpi-operaciones] .val').textContent.replace(/\\./g,'') === n",
                             arg=str(esp2["n_operaciones"]))
    assert pagina.problemas == []


def test_rango_invalido_muestra_un_mensaje_claro(pagina):
    abrir(pagina)
    pagina.fill("#f-desde", "2023-05")
    pagina.dispatch_event("#f-desde", "change")
    pagina.fill("#f-hasta", "2023-01")
    pagina.dispatch_event("#f-hasta", "change")
    pagina.wait_for_selector("#aviso:not([hidden])")
    assert "no puede ser posterior" in pagina.inner_text("#aviso")
    pagina.fill("#f-hasta", "2023-12")
    pagina.dispatch_event("#f-hasta", "change")
    pagina.wait_for_selector("#aviso", state="hidden")


def test_sin_resultados_muestra_estado_vacio(pagina, servidor):
    codigos = [p["pais_codigo"] for p in api(servidor, "/meta")["paises"]]
    vacio = next(c for c in codigos if api(servidor, "/resumen", pais=c, desde="2018-01", hasta="2018-01")["datos"]["n_operaciones"] == 0)
    abrir(pagina, f"?pais={vacio}&desde=2018-01&hasta=2018-01", graficos=False)
    assert kpi(pagina, "operaciones") == "0"
    assert kpi(pagina, "exportaciones") == "—"
    assert "Sin datos" in pagina.inner_text("[data-testid=grafico-top]")
    pagina.click("#tab-detalle")
    pagina.wait_for_selector("[data-testid=tabla-datos] .vacio")
    assert "Sin resultados" in pagina.inner_text("[data-testid=tabla-datos]")


def test_tabla_ordenacion_paginacion_y_exportacion_csv(pagina, servidor):
    abrir(pagina)
    pagina.click("#tab-detalle")
    pagina.wait_for_selector("[data-testid=tabla-datos] tbody tr")
    assert pagina.locator("[data-testid=tabla-datos] tbody tr").count() == 25
    assert "Página 1 de 2 · 50 filas" in pagina.inner_text("#pag-info")
    # ordenar por nombre ascendente (clic en la cabecera) -> petición al servidor
    pagina.click("th[data-k=nombre]")
    pagina.wait_for_function("document.querySelector('th[data-k=nombre]').getAttribute('aria-sort') === 'descending'")
    pagina.click("th[data-k=nombre]")
    pagina.wait_for_function("document.querySelector('th[data-k=nombre]').getAttribute('aria-sort') === 'ascending'")
    primeros = pagina.locator("[data-testid=tabla-datos] tbody tr td:first-child").all_inner_texts()
    assert primeros == sorted(primeros, key=str.lower) or primeros[0] == "Alemania"
    esperado = api(servidor, "/tabla", orden="nombre", sentido="asc", tamano=25)["datos"]
    assert primeros == [f["nombre"] for f in esperado]
    # página siguiente
    pagina.click("#pag-sig")
    pagina.wait_for_function("document.querySelector('#pag-info').textContent.startsWith('Página 2')")
    assert pagina.locator("[data-testid=tabla-datos] tbody tr").count() == 25
    assert pagina.is_disabled("#pag-sig") and not pagina.is_disabled("#pag-ant")
    # exportación CSV con los mismos criterios
    with pagina.expect_download() as dl:
        pagina.click("[data-testid=btn-exportar]")
    ruta = dl.value.path()
    texto = Path(ruta).read_text(encoding="utf-8-sig")
    filas = texto.strip().splitlines()
    assert len(filas) == 51 and filas[0].startswith("clave,nombre,exportaciones_eur")
    assert filas[1].split(",")[1] == "Alemania"
    # cambio de dimensión: sectores
    pagina.select_option("#tabla-dim", "sector")
    pagina.wait_for_function("document.querySelector('#pag-info').textContent.includes('10 filas')")
    assert pagina.problemas == []


def test_pantalla_de_calidad(pagina, servidor):
    abrir(pagina)
    pagina.click("#tab-calidad")
    pagina.wait_for_selector("[data-testid=tabla-checks] tbody tr")
    assert pagina.locator("[data-testid=tabla-checks] tbody tr").count() >= 14
    assert pagina.locator("[data-testid=tabla-checks] .insignia.err").count() == 0
    assert pagina.locator("[data-testid=tabla-checks] .insignia.ok").count() == pagina.locator("[data-testid=tabla-checks] tbody tr").count()
    assert "conservacion_de_filas" in pagina.inner_text("[data-testid=tabla-checks]")
    assert pagina.is_hidden("#filtros")
    cal = api(servidor, "/calidad")
    pagina.wait_for_selector("[data-testid=tabla-rechazados] tbody tr")
    assert f"{cal['conservacion']['rechazados']} rechazados".replace(",", "") in pagina.inner_text("#rech-info").replace(".", "")
    pagina.select_option("#rech-motivo", "FLUJO_INVALIDO")
    pagina.wait_for_function("[...document.querySelectorAll('[data-testid=tabla-rechazados] tbody .insignia')].every(e => e.textContent === 'FLUJO_INVALIDO')")


def test_pantalla_de_seguimiento_de_ingestas(pagina, servidor):
    abrir(pagina)
    pagina.click("#tab-ingestas")
    pagina.wait_for_selector("[data-testid=tabla-ingestas] tbody tr")
    assert pagina.locator("[data-testid=tabla-ingestas] tbody tr").count() == 32
    assert pagina.locator("[data-testid=tabla-ingestas] .insignia.ok").count() == 32
    assert "ING-0032" in pagina.inner_text("[data-testid=tabla-ingestas] tbody tr:first-child")
    pagina.click("[data-testid=tabla-ingestas] tbody tr[data-id=ING-0002]")
    pagina.wait_for_selector("#detalle-ingesta:not([hidden])")
    assert "ING-0002" in pagina.inner_text("#detalle-titulo")
    assert "COMPLETADA" in pagina.inner_text("#detalle-cuerpo")
    assert pagina.problemas == []
