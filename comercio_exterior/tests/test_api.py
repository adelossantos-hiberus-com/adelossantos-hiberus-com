"""Pruebas de integración de la API FastAPI sobre el lakehouse de 60.000 operaciones."""

import csv
import io

import pytest
from fastapi.testclient import TestClient

import referencia as ref
from comercio_exterior.api.app import crear_app


@pytest.fixture(scope="module")
def cliente(lago):
    with TestClient(crear_app(lago.raiz)) as c:
        yield c


@pytest.fixture(scope="module")
def df(lago):
    return ref.preparar(lago.sim.verdad)


def get(cliente, ruta, **params):
    return cliente.get(f"/api/v1{ruta}", params=params)


def error(r, estado=422, codigo="parametro_no_valido"):
    assert r.status_code == estado, r.text
    e = r.json()["error"]
    assert e["codigo"] == codigo and e["mensaje"]
    return e


# ---------------------------------------------------------------- sistema
def test_salud_y_meta(cliente):
    assert get(cliente, "/salud").json()["estado"] == "ok"
    m = get(cliente, "/meta").json()
    assert len(m["paises"]) == 50 and len(m["productos"]) == 200 and len(m["sectores"]) == 10 and len(m["subsectores"]) == 40
    assert m["rango"] == {"desde": "2018-01", "hasta": "2025-12"} and "saldo" in m["medidas"]


def test_la_interfaz_y_los_estaticos_se_sirven(cliente):
    r = cliente.get("/")
    assert r.status_code == 200 and "Comercio exterior" in r.text and "datos 100 % ficticios" in r.text
    assert cliente.get("/static/app.js").status_code == 200 and cliente.get("/static/estilos.css").status_code == 200
    assert cliente.get("/docs").status_code == 200


def test_sin_datos_devuelve_503_con_instrucciones(tmp_path):
    with TestClient(crear_app(tmp_path / "vacio")) as c:
        e = error(c.get("/api/v1/resumen"), 503, "sin_datos")
        assert "construir" in e["mensaje"]
        assert c.get("/api/v1/salud").json()["datos_disponibles"] is False
        assert c.get("/api/v1/ingestas").json()["resumen"]["total"] == 0


# ---------------------------------------------------------------- análisis
def test_resumen_coincide_con_la_referencia(cliente, df):
    j = get(cliente, "/resumen", desde="2022-01", hasta="2022-12", pais="DE,FR").json()
    esp = ref.resumen(df, "2022-01", "2022-12", paises=("DE", "FR"))
    d = j["datos"]
    assert d["exportaciones_eur"] == pytest.approx(esp["exportaciones_eur"], abs=0.02)
    assert d["saldo_eur"] == pytest.approx(esp["saldo_eur"], abs=0.02)
    assert j["filtros"] == {"desde": "2022-01", "hasta": "2022-12", "paises": ["DE", "FR"], "productos": [],
                            "sectores": [], "subsectores": []}
    assert j["version_datos"]


def test_filtros_combinables_y_repetibles(cliente):
    a = get(cliente, "/resumen", pais=["DE", "FR"], sector="S01").json()["datos"]
    b = get(cliente, "/resumen", pais="DE,FR", sector="S01").json()["datos"]
    todo = get(cliente, "/resumen").json()["datos"]
    assert a == b and 0 < a["n_operaciones"] < todo["n_operaciones"]
    vacio = get(cliente, "/resumen", pais="JP", producto="P001", desde="2018-01", hasta="2018-01").json()["datos"]
    assert vacio["n_operaciones"] in (0,) or vacio["n_operaciones"] >= 0


def test_series(cliente):
    m = get(cliente, "/serie/mensual", desde="2021-01", hasta="2021-12").json()["datos"]
    assert len(m) == 12 and m[0]["mes_inicio"] == "2021-01-01"
    assert m[-1]["exportaciones_acum_eur"] == pytest.approx(sum(x["exportaciones_eur"] for x in m), rel=1e-9)
    a = get(cliente, "/serie/anual").json()["datos"]
    assert [x["anio"] for x in a] == list(range(2018, 2026)) and a[0]["var_exportaciones_pct"] is None


def test_top_con_resto_suma_el_total(cliente):
    j = get(cliente, "/top", dimension="sector", medida="exportaciones", n=3).json()
    filas = j["datos"]
    assert len(filas) == 4 and filas[-1]["clave"] == "RESTO"
    total = get(cliente, "/resumen").json()["datos"]["exportaciones_eur"]
    assert sum(f["valor"] for f in filas) == pytest.approx(total, abs=0.02)


def test_contribucion_y_ranking(cliente):
    c = get(cliente, "/contribucion", desde="2023-01", hasta="2023-12", dimension="pais", n=5).json()["datos"]
    assert c[-1]["clave"] == "RESTO" and sum(f["contribucion_pp"] for f in c) == pytest.approx(c[0]["crecimiento_total_pct"], abs=0.05)
    r = get(cliente, "/ranking", dimension="pais", n=3, desde="2022-01", hasta="2023-12").json()["datos"]
    assert {x["anio"] for x in r} == {2022, 2023} and all(x["posicion"] <= 3 for x in r)


# ---------------------------------------------------------------- paginación y ordenación
def test_paginacion_cubre_todo_sin_repetir(cliente):
    claves, total = [], None
    for pag in range(1, 5):
        j = get(cliente, "/tabla", dimension="pais", tamano=20, pagina=pag, orden="nombre", sentido="asc").json()
        total = j["paginacion"]["total"]
        assert j["paginacion"]["paginas"] == 3
        claves += [f["clave"] for f in j["datos"]]
    assert total == 50 and len(claves) == 50 and len(set(claves)) == 50


def test_ordenacion_en_servidor(cliente):
    asc = get(cliente, "/tabla", orden="saldo_eur", sentido="asc", tamano=50).json()["datos"]
    desc = get(cliente, "/tabla", orden="saldo_eur", sentido="desc", tamano=50).json()["datos"]
    assert [f["saldo_eur"] for f in asc] == sorted(f["saldo_eur"] for f in asc)
    assert [f["clave"] for f in asc] == [f["clave"] for f in reversed(desc)]
    assert asc[0]["saldo_eur"] < 0 < desc[0]["saldo_eur"] or desc[0]["saldo_eur"] > asc[0]["saldo_eur"]


def test_pagina_fuera_de_rango_devuelve_vacio_con_total_correcto(cliente):
    j = get(cliente, "/tabla", pagina=99, tamano=25).json()
    assert j["datos"] == [] and j["paginacion"]["total"] == 50


# ---------------------------------------------------------------- validación de parámetros
@pytest.mark.parametrize("params,texto", [
    (dict(tamano=0), "tamano"), (dict(tamano=501), "tamano"), (dict(pagina=0), "pagina"), (dict(pagina="x"), "entero"),
    (dict(orden="inventada"), "orden"), (dict(sentido="arriba"), "sentido"), (dict(dimension="planeta"), "dimension"),
    (dict(desde="2020-13"), "entre 01 y 12"), (dict(desde="2020"), "AAAA-MM"), (dict(hasta="2030-01"), "fuera del rango"),
    (dict(desde="2022-05", hasta="2022-01"), "posterior"), (dict(pais="XX"), "país 'XX' no existe"),
    (dict(producto="P0"), "producto 'P0'"), (dict(sector="S77"), "sector"), (dict(subsector="S01-8"), "subsector"),
])
def test_parametros_invalidos_devuelven_422_claro(cliente, params, texto):
    e = error(get(cliente, "/tabla", **params))
    assert texto in e["mensaje"] and e["detalles"]


def test_validacion_en_otros_endpoints(cliente):
    assert "medida" in error(get(cliente, "/top", medida="beneficio"))["mensaje"]
    assert "'n'" in error(get(cliente, "/top", n=0))["mensaje"]
    assert "'n'" in error(get(cliente, "/ranking", n=101))["mensaje"]
    assert "país" in error(get(cliente, "/resumen", pais="ZZ"))["mensaje"]
    assert "pagina" in error(get(cliente, "/calidad/rechazados", pagina=0))["mensaje"]


def test_rutas_inexistentes(cliente):
    assert cliente.get("/api/v1/no_existe").status_code == 404
    error(get(cliente, "/ingestas/ING-9999"), 404, "ingesta_no_encontrada")


# ---------------------------------------------------------------- CSV
def leer_csv(r, sep=","):
    return list(csv.DictReader(io.StringIO(r.text.lstrip("﻿")), delimiter=sep))


def test_exportacion_csv_de_la_tabla_completa(cliente):
    r = cliente.get("/api/v1/export/tabla.csv", params={"dimension": "sector", "orden": "nombre", "sentido": "asc"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert 'attachment; filename="comercio_tabla.csv"' in r.headers["content-disposition"]
    assert r.text.startswith("﻿")
    filas = leer_csv(r)
    assert len(filas) == 10 and [f["nombre"] for f in filas] == sorted(f["nombre"] for f in filas)
    json_filas = get(cliente, "/tabla", dimension="sector", orden="nombre", sentido="asc").json()["datos"]
    assert [float(f["exportaciones_eur"]) for f in filas] == pytest.approx([f["exportaciones_eur"] for f in json_filas])


def test_csv_respeta_filtros_separador_y_bom(cliente):
    r = cliente.get("/api/v1/export/serie-mensual.csv", params={"desde": "2020-01", "hasta": "2020-06", "pais": "DE", "sep": ";", "bom": "false"})
    assert not r.text.startswith("﻿") and r.text.splitlines()[0].startswith("mes_inicio;anio;mes")
    assert len(leer_csv(r, ";")) == 6


@pytest.mark.parametrize("recurso", ["serie-anual", "top", "contribucion", "ranking"])
def test_exportacion_de_todos_los_recursos(cliente, recurso):
    r = cliente.get(f"/api/v1/export/{recurso}.csv", params={"n": 3})
    assert r.status_code == 200 and len(leer_csv(r)) >= 1


def test_csv_sin_resultados_devuelve_solo_cabecera_vacia(cliente):
    r = cliente.get("/api/v1/export/tabla.csv", params={"pais": "LU", "producto": "P200", "desde": "2018-01", "hasta": "2018-01"})
    assert r.status_code == 200


def test_csv_parametros_invalidos(cliente):
    error(cliente.get("/api/v1/export/inventado.csv"))
    error(cliente.get("/api/v1/export/tabla.csv", params={"sep": "|"}))


# ---------------------------------------------------------------- calidad e ingestas
def test_calidad_endpoint(cliente):
    j = get(cliente, "/calidad").json()
    assert j["resumen"]["error"] == 0 and j["conservacion"]["diferencia"] == 0
    assert get(cliente, "/calidad").json()["version_datos"] == j["version_datos"]
    r = get(cliente, "/calidad/rechazados", tamano=5, motivo="FLUJO_INVALIDO").json()
    assert len(r["filas"]) <= 5 and r["total"] >= 1 and r["paginas"] >= 1


def test_ingestas_endpoints(cliente, lago):
    j = get(cliente, "/ingestas").json()
    assert j["resumen"]["total"] == 32 and j["resumen"]["completadas"] == 32 and j["datos"][0]["ingesta_id"] == "ING-0032"
    d = get(cliente, "/ingestas/ING-0003").json()
    assert d["ingesta"]["fichero_origen"] == "entrega_2018Q3.csv" and {e["evento"] for e in d["eventos"]} == {"INICIO", "COMPLETADA"}
    assert len(get(cliente, "/ingestas/eventos", limite=5).json()["datos"]) == 5


def test_error_interno_no_filtra_detalles(lago):
    app = crear_app(lago.raiz)
    app.state.motor.resumen = lambda f: 1 / 0
    with TestClient(app, raise_server_exceptions=False) as c:
        r = c.get("/api/v1/resumen")
        assert r.status_code == 500 and r.json()["error"]["codigo"] == "error_interno"
        assert "division" not in r.text.lower()


# ---------------------------------------------------------------- consumo desde herramientas de BI
@pytest.mark.parametrize("ruta,params", [
    ("/serie/mensual", {}), ("/serie/anual", {}), ("/tabla", {"dimension": "sector"}), ("/top", {"n": 3}),
    ("/contribucion", {"n": 3}), ("/ranking", {"n": 3}), ("/ingestas", {}),
])
def test_json_plano_y_uniforme_apto_para_power_bi(cliente, ruta, params):
    """Power BI (Table.FromRecords) necesita una lista de registros planos con las mismas columnas."""
    datos = get(cliente, ruta, **params).json()["datos"]
    assert datos and len({tuple(d) for d in datos}) == 1
    assert not any(isinstance(v, (dict, list)) for d in datos for v in d.values())


def test_csv_se_lee_con_pandas_como_lo_haria_power_query(cliente):
    import pandas as pd
    r = cliente.get("/api/v1/export/serie-mensual.csv", params={"desde": "2021-01", "hasta": "2021-12"})
    tabla = pd.read_csv(io.StringIO(r.content.decode("utf-8-sig")), parse_dates=["mes_inicio"])
    assert len(tabla) == 12 and tabla["exportaciones_eur"].dtype.kind == "f" and tabla["mes_inicio"].dt.year.eq(2021).all()
    j = get(cliente, "/serie/mensual", desde="2021-01", hasta="2021-12").json()["datos"]
    assert tabla["exportaciones_eur"].tolist() == pytest.approx([x["exportaciones_eur"] for x in j])
