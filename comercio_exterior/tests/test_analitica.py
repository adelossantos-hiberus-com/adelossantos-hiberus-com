"""Motor analítico: contraste con la implementación independiente, casos límite y plantillas SQL."""

import math
import re
from datetime import date

import numpy as np
import pytest

import referencia as ref
from comercio_exterior.analitica import ErrorParametro, Filtros, Motor
from comercio_exterior.analitica import exportar as exp_sql
from comercio_exterior.analitica.sql import RUTA_SQL, renderizar
from comercio_exterior.lakehouse import Lakehouse
from conftest import hacer_entrega

E, I = "EXPORTACION", "IMPORTACION"


def nulo(x):
    return x is None or (isinstance(x, float) and math.isnan(x))


def cerca(a, b, tol=0.011):
    if nulo(a) or nulo(b):
        return nulo(a) and nulo(b)
    return abs(float(a) - float(b)) <= tol + 1e-9 * abs(float(b))


def comparar(real: dict, esperado: dict, claves=None, ctx="", tol=0.011):
    for k in claves or esperado:
        assert cerca(real[k], esperado[k], tol), f"{ctx} {k}: SQL={real[k]!r} referencia={esperado[k]!r}"


# ----------------------------------------------------------------------------- fixtures
@pytest.fixture(scope="module")
def motor(lago):
    m = Motor(lago.raiz)
    yield m
    m.cerrar()


@pytest.fixture(scope="module")
def df(lago):
    return ref.preparar(lago.sim.verdad)


FILTROS = [
    {}, dict(desde="2020-03", hasta="2022-09"), dict(desde="2019-06", hasta="2019-06"),
    dict(paises=["DE", "FR"]), dict(sectores=["S01"], desde="2021-01", hasta="2023-12"),
    dict(subsectores=["S02-1", "S07-3"]), dict(productos=["P001", "P050", "P120"]),
    dict(paises=["CN"], sectores=["S07"], desde="2019-06", hasta="2021-02"),
    dict(paises=["LU"], productos=["P200"]),                       # esparso: meses y años sin datos
    dict(desde="2018-01", hasta="2018-12"),                         # sin año previo
    dict(desde="2025-07", hasta="2025-12"),
]


def split(c):
    dims = {k: tuple(c.get(k, ())) for k in ("paises", "productos", "sectores", "subsectores")}
    return Filtros.crear(c.get("desde"), c.get("hasta"), **dims), c.get("desde", "2018-01"), c.get("hasta", "2025-12"), dims


# ----------------------------------------------------------------------------- contraste con referencia independiente
@pytest.mark.parametrize("caso", FILTROS, ids=lambda c: str(c) or "sin filtros")
def test_resumen_y_series_coinciden_con_la_referencia(motor, df, caso):
    f, d, h, dims = split(caso)
    r = motor.resumen(f)
    esperado = ref.resumen(df, d, h, **dims)
    comparar(r, esperado, ctx="resumen")

    for real, esp in zip(motor.serie_mensual(f), ref.serie_mensual(df, d, h, **dims), strict=True):
        assert real["mes_inicio"] == esp["mes_inicio"]
        comparar(real, esp, [k for k in esp if k != "mes_inicio"], ctx=str(esp["mes_inicio"]))
    anual_sql, anual_ref = motor.serie_anual(f), ref.serie_anual(df, d, h, **dims)
    assert [a["anio"] for a in anual_sql] == [a["anio"] for a in anual_ref]
    for real, esp in zip(anual_sql, anual_ref):
        comparar(real, esp, ctx=f"anual {esp['anio']}")


@pytest.mark.parametrize("dimension", ["pais", "sector", "subsector", "producto", "region"])
@pytest.mark.parametrize("caso", [FILTROS[0], FILTROS[1], FILTROS[4], FILTROS[8]], ids=lambda c: str(c) or "sin filtros")
def test_tabla_por_dimension_coincide(motor, df, dimension, caso):
    f, d, h, dims = split(caso)
    real = motor.tabla(f, dimension, "comercio_total_eur", "desc", 1, 500)
    esp = ref.tabla(df, dimension, d, h, **dims)
    assert real["total"] == len(esp) == len(real["filas"])
    por_clave = {r["clave"]: r for r in real["filas"]}
    for _, e in esp.iterrows():
        r = por_clave[e["clave"]]
        comparar(r, {"exportaciones_eur": e["exp"], "importaciones_eur": e["imp"], "saldo_eur": e["saldo"],
                     "comercio_total_eur": e["total"], "cobertura_pct": e["cobertura"],
                     "cuota_comercio_pct": e["cuota_comercio"], "cuota_exportaciones_pct": e["cuota_exp"],
                     "cuota_importaciones_pct": e["cuota_imp"], "var_exportaciones_pct": e["var_exp"],
                     "var_importaciones_pct": e["var_imp"], "n_operaciones": e["n"], "ranking": e["ranking"],
                     "peso_kg": e["peso"], "unidades": e["uds"]}, ctx=e["clave"])
    if len(esp) > 1:   # cuotas: suman 100 (salvo redondeos)
        assert sum(r["cuota_comercio_pct"] for r in real["filas"]) == pytest.approx(100, abs=0.06 * len(esp) / 2)


@pytest.mark.parametrize("dimension", ["pais", "sector", "producto"])
@pytest.mark.parametrize("medida", ["exportaciones", "importaciones", "comercio_total", "saldo"])
@pytest.mark.parametrize("n", [3, 10, 500])
@pytest.mark.parametrize("sentido", ["desc", "asc"])
def test_top_n_con_resto_coincide_y_suma_el_total(motor, df, dimension, medida, n, sentido):
    caso = FILTROS[1]
    f, d, h, dims = split(caso)
    real = motor.top(f, dimension, medida, n, sentido)
    esp = ref.top(df, dimension, medida, n, d, h, sentido, **dims)
    assert [r["clave"] for r in real] == [e["clave"] for e in esp]
    for r, e in zip(real, esp):
        comparar(r, {"exportaciones_eur": e["exp"], "importaciones_eur": e["imp"], "valor": e["valor"],
                     "cuota_pct": e["cuota_pct"]}, ctx=e["clave"])
    # Top N + Resto == total del periodo, para cualquier medida (también el saldo)
    total = motor.resumen(f)
    esperado_total = {"exportaciones": total["exportaciones_eur"], "importaciones": total["importaciones_eur"],
                      "comercio_total": total["comercio_total_eur"], "saldo": total["saldo_eur"]}[medida]
    assert sum(r["valor"] for r in real) == pytest.approx(esperado_total, abs=0.02)
    assert sum(r["exportaciones_eur"] for r in real) == pytest.approx(total["exportaciones_eur"], abs=0.02)
    assert sum(r["importaciones_eur"] for r in real) == pytest.approx(total["importaciones_eur"], abs=0.02)
    assert sum(r["n_operaciones"] for r in real) == total["n_operaciones"]
    assert sum(r["es_resto"] for r in real) == (1 if real and real[-1]["es_resto"] else 0) <= 1
    if medida != "saldo":
        assert sum(r["cuota_pct"] for r in real) == pytest.approx(100, abs=0.06 * len(real))
    else:
        assert all(r["cuota_pct"] is None for r in real)


@pytest.mark.parametrize("dimension", ["pais", "sector", "subsector"])
@pytest.mark.parametrize("medida", ["exportaciones", "importaciones", "comercio_total", "saldo"])
@pytest.mark.parametrize("caso", [FILTROS[0], FILTROS[1], FILTROS[3], FILTROS[10]], ids=lambda c: str(c) or "sin filtros")
def test_contribucion_al_crecimiento(motor, df, dimension, medida, caso):
    f, d, h, dims = split(caso)
    real = motor.contribucion(f, dimension, medida, 5)
    esp, crec = ref.contribucion(df, dimension, medida, 5, d, h, **dims)
    assert [r["clave"] for r in real] == [e["clave"] for e in esp]
    for r, e in zip(real, esp):
        comparar(r, {k: e[k] for k in ("valor_act", "valor_prev", "variacion_eur", "contribucion_pp")}, tol=0.011)
    if real:
        assert cerca(real[0]["crecimiento_total_pct"], crec, 0.0101)
        # la suma de contribuciones (Top N + Resto) iguala el crecimiento total
        if not nulo(crec):
            assert sum(r["contribucion_pp"] for r in real) == pytest.approx(crec, abs=0.001 * len(real) + 0.01)


@pytest.mark.parametrize("dimension", ["pais", "sector"])
@pytest.mark.parametrize("caso", [FILTROS[0], FILTROS[1], FILTROS[5], FILTROS[10]], ids=lambda c: str(c) or "sin filtros")
def test_ranking_anual_y_cambio_de_posicion(motor, df, dimension, caso):
    f, d, h, dims = split(caso)
    real = motor.ranking(f, dimension, "comercio_total", 4)
    esp = ref.ranking(df, dimension, "comercio_total", 4, d, h, **dims)
    assert [(r["anio"], r["posicion"], r["clave"]) for r in real] == [(e["anio"], e["posicion"], e["clave"]) for e in esp]
    for r, e in zip(real, esp):
        comparar(r, {k: e[k] for k in ("valor", "posicion_previa", "cambio_posicion")}, ctx=str(e["clave"]))


def test_orden_y_paginacion_en_servidor(motor, df):
    f = Filtros.crear()
    todo = motor.tabla(f, "pais", "comercio_total_eur", "desc", 1, 500)["filas"]
    paginas = [motor.tabla(f, "pais", "comercio_total_eur", "desc", p, 20) for p in (1, 2, 3)]
    assert [x["clave"] for p in paginas for x in p["filas"]] == [x["clave"] for x in todo]
    assert paginas[0]["total"] == 50 and [len(p["filas"]) for p in paginas] == [20, 20, 10]
    asc = motor.tabla(f, "pais", "nombre", "asc", 1, 5)["filas"]
    assert [x["nombre"] for x in asc] == sorted(x["nombre"] for x in todo)[:5]
    fuera = motor.tabla(f, "pais", "nombre", "asc", 99, 20)
    assert fuera["filas"] == [] and fuera["total"] == 50          # el total sigue siendo correcto
    por_var = motor.tabla(f, "pais", "var_exportaciones_pct", "desc", 1, 500)["filas"]
    valores = [x["var_exportaciones_pct"] for x in por_var if x["var_exportaciones_pct"] is not None]
    assert valores == sorted(valores, reverse=True)
    with pytest.raises(ValueError):
        motor.tabla(f, "pais", "columna_inventada")


# ----------------------------------------------------------------------------- casos límite con datos mínimos
@pytest.fixture
def mini(tmp_path):
    lks = []

    def _crear(*entregas):
        lk = Lakehouse(tmp_path / "mini")
        for e in entregas:
            lk.ingestar(e)
        lks.append(lk)
        return Motor(tmp_path / "mini"), lk

    yield _crear
    for lk in lks:
        lk.cerrar()


def test_division_por_cero_cobertura_nula_sin_importaciones(mini):
    m, _ = mini(hacer_entrega([(1, "2020-03-01", E, "FR", "P001", 100.0), (2, "2020-04-01", E, "FR", "P001", 50.0)]))
    r = m.resumen(Filtros.crear("2020-01", "2020-12"))
    assert r["exportaciones_eur"] == 150 and r["importaciones_eur"] == 0 and r["saldo_eur"] == 150
    assert r["cobertura_pct"] is None
    fila = m.tabla(Filtros.crear(), "pais")["filas"][0]
    assert fila["cobertura_pct"] is None and fila["cuota_exportaciones_pct"] == 100.0
    assert fila["cuota_importaciones_pct"] is None                  # total de importaciones = 0 -> sin cuota
    assert m.serie_anual(Filtros.crear("2020-01", "2020-12"))[0]["cobertura_pct"] is None


def test_sin_exportaciones_la_cobertura_es_cero(mini):
    m, _ = mini(hacer_entrega([(1, "2020-03-01", I, "FR", "P001", 100.0)]))
    r = m.resumen(Filtros.crear("2020-01", "2020-12"))
    assert r["cobertura_pct"] == 0.0 and r["saldo_eur"] == -100


def test_filtros_sin_resultados(mini):
    m, _ = mini(hacer_entrega([(1, "2020-03-01", E, "FR", "P001", 100.0)]))
    f = Filtros.crear(paises=["JP"])
    r = m.resumen(f)
    assert r["n_operaciones"] == 0 and r["exportaciones_eur"] is None and r["cobertura_pct"] is None
    assert m.tabla(f, "pais")["filas"] == [] and m.top(f, "pais", "saldo", 5) == []
    assert m.contribucion(f, "pais", "saldo", 5) == [] and m.ranking(f) == []
    assert all(a["exportaciones_eur"] is None and a["meses_con_datos"] == 0 for a in m.serie_anual(f))


def test_anios_ausentes_aparecen_vacios_y_no_inventan_variaciones(mini):
    m, _ = mini(hacer_entrega([(1, "2018-05-01", E, "FR", "P001", 100.0), (2, "2018-05-02", I, "FR", "P001", 40.0),
                               (3, "2020-05-01", E, "FR", "P001", 300.0), (4, "2020-05-02", I, "FR", "P001", 60.0)]))
    anual = {a["anio"]: a for a in m.serie_anual(Filtros.crear("2018-01", "2020-12"))}
    assert set(anual) == {2018, 2019, 2020}
    a19, a20, a18 = anual[2019], anual[2020], anual[2018]
    assert a19["meses_con_datos"] == 0 and a19["exportaciones_eur"] is None and a19["saldo_eur"] is None
    assert a18["var_exportaciones_pct"] is None                    # el primer año no tiene año previo
    assert a20["exportaciones_eur"] == 300 and a20["exportaciones_previo_eur"] is None
    assert a20["var_exportaciones_pct"] is None and a20["var_saldo_eur"] is None   # 2019 sin datos
    mensual = m.serie_mensual(Filtros.crear("2019-01", "2019-12"))
    assert len(mensual) == 12 and all(x["n_operaciones"] == 0 and x["exportaciones_eur"] is None for x in mensual)
    assert all(x["exportaciones_acum_eur"] == 0 for x in mensual)  # los acumulados tratan el mes vacío como 0
    # acumulado previo (2018): 0 hasta abril y 100 desde mayo -> sin variación definida / -100 %
    assert [x["var_exportaciones_acum_pct"] for x in mensual] == [None] * 4 + [-100.0] * 8
    mayo20 = m.serie_mensual(Filtros.crear("2020-05", "2020-05"))[0]
    assert mayo20["exportaciones_previo_eur"] is None and mayo20["var_exportaciones_pct"] is None
    r = m.resumen(Filtros.crear("2020-01", "2020-12"))              # ventana previa 2019: vacía
    assert r["exportaciones_previo_eur"] is None and r["var_exportaciones_pct"] is None and r["var_saldo_eur"] is None


def test_variacion_interanual_y_acumulados_con_datos_en_ambos_anios(mini):
    m, _ = mini(hacer_entrega([(1, "2019-01-10", E, "FR", "P001", 100.0), (2, "2019-02-10", E, "FR", "P001", 100.0),
                               (3, "2020-01-10", E, "FR", "P001", 150.0), (4, "2020-02-10", E, "FR", "P001", 50.0),
                               (5, "2019-01-11", I, "FR", "P001", 80.0)]))
    s = {x["mes_inicio"].month: x for x in m.serie_mensual(Filtros.crear("2020-01", "2020-02"))}
    assert s[1]["exportaciones_eur"] == 150 and s[1]["var_exportaciones_pct"] == 50.0
    assert s[2]["var_exportaciones_pct"] == -50.0
    assert s[2]["exportaciones_acum_eur"] == 200 and s[2]["var_exportaciones_acum_pct"] == 0.0   # 200 vs 200
    assert s[1]["importaciones_eur"] == 0 and s[1]["var_importaciones_pct"] == -100.0   # había 80 € en ene-2019
    assert s[1]["saldo_acum_eur"] == 150 and s[1]["cobertura_acum_pct"] is None                  # sin importaciones en 2020


def test_saldo_negativo_contribucion_y_variacion_relativa(mini):
    m, _ = mini(hacer_entrega([
        (1, "2019-06-01", E, "FR", "P001", 100.0), (2, "2019-06-02", I, "FR", "P001", 300.0),     # FR 2019: saldo -200
        (3, "2020-06-01", E, "FR", "P001", 100.0), (4, "2020-06-02", I, "FR", "P001", 500.0),     # FR 2020: saldo -400
        (5, "2020-06-03", E, "DE", "P001", 50.0)]))                                               # DE 2020: saldo +50
    f = Filtros.crear("2020-01", "2020-12")
    r = m.resumen(f)
    assert r["saldo_eur"] == -350 and r["saldo_previo_eur"] == -200 and r["var_saldo_eur"] == -150
    assert r["cobertura_pct"] == pytest.approx(30.0)                 # 150 / 500
    c = {x["clave"]: x for x in m.contribucion(f, "pais", "saldo", 5)}
    assert c["FR"]["contribucion_pp"] == pytest.approx(-100.0)        # (-400 - -200) / |-200|
    assert c["DE"]["contribucion_pp"] == pytest.approx(25.0)
    assert c["FR"]["var_pct"] == -100.0                               # empeora: signo correcto con base negativa
    assert c["FR"]["crecimiento_total_pct"] == pytest.approx(-75.0)
    assert sum(x["contribucion_pp"] for x in c.values()) == pytest.approx(-75.0)
    top = m.top(f, "pais", "saldo", 5, "asc")                          # mayores déficits primero
    assert [t["clave"] for t in top] == ["FR", "DE"] and top[0]["saldo_eur"] == -400 and top[0]["cuota_pct"] is None
    fr = next(x for x in m.tabla(f, "pais")["filas"] if x["clave"] == "FR")
    assert fr["saldo_eur"] == -400 and fr["cobertura_pct"] == pytest.approx(20.0)


def test_contribucion_con_total_previo_cero(mini):
    m, _ = mini(hacer_entrega([(1, "2020-06-01", E, "FR", "P001", 100.0)]))
    c = m.contribucion(Filtros.crear("2020-01", "2020-12"), "pais", "exportaciones", 5)
    assert c[0]["contribucion_pp"] is None and c[0]["crecimiento_total_pct"] is None and c[0]["var_pct"] is None
    assert c[0]["variacion_eur"] == 100


def test_elemento_que_solo_existia_en_el_periodo_previo_resta_crecimiento(mini):
    m, _ = mini(hacer_entrega([(1, "2019-06-01", E, "FR", "P001", 100.0), (2, "2019-06-01", E, "DE", "P001", 100.0),
                               (3, "2020-06-01", E, "FR", "P001", 100.0)]))
    c = {x["clave"]: x for x in m.contribucion(Filtros.crear("2020-01", "2020-12"), "pais", "exportaciones", 5)}
    assert c["DE"]["valor_act"] == 0 and c["DE"]["contribucion_pp"] == pytest.approx(-50.0)
    assert c["FR"]["contribucion_pp"] == 0
    tabla = m.tabla(Filtros.crear("2020-01", "2020-12"), "pais")["filas"]
    assert [x["clave"] for x in tabla] == ["FR"]                      # la tabla solo lista lo que opera en el periodo


def test_top_n_mayor_que_elementos_no_crea_resto_y_n_menor_si(mini):
    m, _ = mini(hacer_entrega([(i, "2020-06-01", E, p, "P001", 10.0 * i) for i, p in enumerate(["FR", "DE", "IT"], 1)]))
    f = Filtros.crear()
    assert [r["clave"] for r in m.top(f, "pais", "exportaciones", 3)] == ["IT", "DE", "FR"]
    t = m.top(f, "pais", "exportaciones", 2)
    assert [r["clave"] for r in t] == ["IT", "DE", "RESTO"] and t[-1]["valor"] == 10 and t[-1]["es_resto"] == 1
    assert sum(r["cuota_pct"] for r in t) == pytest.approx(100.0, abs=0.02)


def test_el_motor_ve_los_datos_nuevos_tras_una_ingesta_y_usa_cache(mini):
    m, lk = mini(hacer_entrega([(1, "2020-03-01", E, "FR", "P001", 100.0)]))
    f = Filtros.crear()
    assert m.resumen(f)["exportaciones_eur"] == 100
    ejecutadas = m.consultas_ejecutadas
    m.resumen(f)
    assert m.consultas_ejecutadas == ejecutadas and m.aciertos_cache >= 1      # segunda llamada: caché
    lk.ingestar(hacer_entrega([(2, "2020-04-01", E, "FR", "P001", 50.0)], "ING-0002"))
    assert m.resumen(f)["exportaciones_eur"] == 150                             # la caché se invalida con la versión


# ----------------------------------------------------------------------------- filtros y SQL
def test_filtros_validan_con_mensajes_claros():
    casos = [
        (dict(desde="2020/01"), "AAAA-MM"), (dict(desde="2020-13"), "entre 01 y 12"),
        (dict(desde="2017-12"), "fuera del rango"), (dict(hasta="2026-01"), "fuera del rango"),
        (dict(desde="2021-05", hasta="2021-04"), "no puede ser posterior"),
        (dict(paises=["ZZ"]), "país 'ZZ' no existe"), (dict(productos=["P999"]), "producto 'P999'"),
        (dict(sectores=["S99"]), "sector 'S99'"), (dict(subsectores=["S01-9"]), "subsector"),
    ]
    for kw, texto in casos:
        with pytest.raises(ErrorParametro, match=texto):
            Filtros.crear(**kw)


def test_filtros_normalizan_y_deduplican():
    f = Filtros.crear(paises=[" fr", "DE", "FR", ""], productos=["p001"])
    assert f.paises == ("DE", "FR") and f.productos == ("P001",)
    assert f.desde == date(2018, 1, 1) and f.hasta == date(2025, 12, 1)
    assert f.desde_previo == date(2017, 1, 1) and Filtros.crear("2020-01", "2020-12").hasta_previo == date(2019, 12, 1)


def test_no_se_pueden_inyectar_literales_en_el_sql():
    with pytest.raises(ErrorParametro):
        Filtros.crear(paises=["FR') OR 1=1 --"])
    sql = renderizar("resumen", Filtros.crear(paises=["FR"]))
    assert "h.pais_codigo IN ('FR')" in sql


def test_toda_division_del_sql_analitico_usa_nullif():
    """DuckDB devuelve NULL/inf al dividir por cero y Spark (ANSI) falla: se exige NULLIF en cada división."""
    ficheros = sorted(RUTA_SQL.glob("*.sql"))
    assert len(ficheros) >= 7
    for fichero in ficheros:
        codigo = "\n".join(linea.split("--")[0] for linea in fichero.read_text(encoding="utf-8").splitlines())
        for m in re.finditer(r"/", codigo):
            assert re.match(r"/\s*NULLIF\s*\(", codigo[m.start():]), \
                f"{fichero.name}: división sin NULLIF cerca de {codigo[max(0, m.start() - 40): m.start() + 40]!r}"


def test_sql_de_databricks_esta_sincronizado_y_es_portable():
    from pathlib import Path
    generado = exp_sql.generar()
    carpeta = RUTA_SQL.parent / "databricks"
    assert sorted(p.name for p in carpeta.glob("*.sql")) == sorted(generado)
    for nombre, texto in generado.items():
        assert (carpeta / nombre).read_text(encoding="utf-8") == texto, f"{nombre} desactualizado: ejecuta exportar-sql"
        codigo = "\n".join(l.split("--")[0] for l in texto.splitlines())
        assert "read_parquet" not in codigo and "::" not in codigo and "main.comercio_exterior.hechos_mensual" in codigo
        assert "{" not in codigo and "}" not in codigo
