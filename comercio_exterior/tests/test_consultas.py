import pandas as pd
import pytest

from comercio_exterior import consultas
from comercio_exterior.generador import ANIOS

E, I = "EXPORTACION", "IMPORTACION"


def fila_anio(df, anio):
    return df[df["anio"] == anio].iloc[0]


# ---------- métricas anuales ----------

def test_exportaciones_importaciones_saldo_y_cobertura(conexion):
    conn = conexion([
        (2022, "Francia", E, 100), (2022, "Francia", E, 50), (2022, "Italia", I, 50),
        (2022, "Italia", I, 25),
    ])
    r = fila_anio(consultas.metricas_anuales(conn, anios=(2022,)), 2022)
    assert r["num_registros"] == 4
    assert r["exportaciones"] == pytest.approx(150)
    assert r["importaciones"] == pytest.approx(75)
    assert r["saldo"] == pytest.approx(75)
    assert r["cobertura_pct"] == pytest.approx(200.0)


def test_saldo_negativo_y_cobertura_inferior_a_100(conexion):
    conn = conexion([(2022, "China", E, 30), (2022, "China", I, 120)])
    r = fila_anio(consultas.metricas_anuales(conn, anios=(2022,)), 2022)
    assert r["saldo"] == pytest.approx(-90)
    assert r["cobertura_pct"] == pytest.approx(25.0)


def test_cobertura_con_importaciones_cero_es_nula_sin_error(conexion):
    conn = conexion([(2022, "Francia", E, 100)])
    r = fila_anio(consultas.metricas_anuales(conn, anios=(2022,)), 2022)
    assert r["importaciones"] == 0
    assert r["exportaciones"] == pytest.approx(100)
    assert pd.isna(r["cobertura_pct"])


def test_cobertura_con_exportaciones_cero_es_cero(conexion):
    conn = conexion([(2022, "Francia", I, 100)])
    r = fila_anio(consultas.metricas_anuales(conn, anios=(2022,)), 2022)
    assert r["cobertura_pct"] == pytest.approx(0.0)
    assert r["saldo"] == pytest.approx(-100)


def test_anio_sin_datos_aparece_con_nulos_y_cero_registros(conexion):
    conn = conexion([(2022, "Francia", E, 100), (2022, "Francia", I, 50)])
    df = consultas.metricas_anuales(conn, anios=(2022, 2023))
    assert list(df["anio"]) == [2022, 2023]
    r = fila_anio(df, 2023)
    assert r["num_registros"] == 0
    assert pd.isna(r["exportaciones"]) and pd.isna(r["importaciones"])
    assert pd.isna(r["saldo"]) and pd.isna(r["cobertura_pct"])


def test_tabla_vacia_no_falla(conexion):
    conn = conexion([(2022, "Francia", E, 1)])
    conn.execute("DELETE FROM comercio")
    df = consultas.metricas_anuales(conn, anios=(2022, 2023))
    assert (df["num_registros"] == 0).all()


# ---------- variación interanual ----------

def test_variacion_interanual(conexion):
    conn = conexion([
        (2022, "Francia", E, 100), (2022, "Francia", I, 200),
        (2023, "Francia", E, 150), (2023, "Francia", I, 100),
    ])
    df = consultas.variacion_interanual(conn, anios=(2022, 2023))
    primero, segundo = fila_anio(df, 2022), fila_anio(df, 2023)
    assert pd.isna(primero["var_exportaciones_pct"])  # no hay año previo
    assert pd.isna(primero["var_saldo_abs"])
    assert segundo["var_exportaciones_pct"] == pytest.approx(50.0)
    assert segundo["var_importaciones_pct"] == pytest.approx(-50.0)
    assert segundo["var_comercio_total_pct"] == pytest.approx(-16.67, abs=0.01)
    assert segundo["var_saldo_abs"] == pytest.approx(50 - (-100))


def test_variacion_con_base_cero_es_nula(conexion):
    conn = conexion([(2022, "Francia", I, 100), (2023, "Francia", E, 80), (2023, "Francia", I, 100)])
    r = fila_anio(consultas.variacion_interanual(conn, anios=(2022, 2023)), 2023)
    assert r["exportaciones_previo"] == 0
    assert pd.isna(r["var_exportaciones_pct"])      # 0 en el año previo: no se divide
    assert r["var_importaciones_pct"] == pytest.approx(0.0)


def test_variacion_cuando_el_anio_previo_no_tiene_datos(conexion):
    conn = conexion([(2022, "Francia", E, 100), (2022, "Francia", I, 50),
                     (2024, "Francia", E, 120), (2024, "Francia", I, 60)])
    df = consultas.variacion_interanual(conn, anios=(2022, 2023, 2024))
    assert pd.isna(fila_anio(df, 2023)["var_exportaciones_pct"])   # 2023 sin datos
    # 2024 no se compara con 2022: el año inmediatamente anterior (2023) está vacío
    r24 = fila_anio(df, 2024)
    assert pd.isna(r24["var_exportaciones_pct"]) and pd.isna(r24["var_saldo_abs"])


def test_variacion_con_un_solo_anio(conexion):
    conn = conexion([(2022, "Francia", E, 100)])
    df = consultas.variacion_interanual(conn, anios=(2022,))
    assert len(df) == 1 and pd.isna(df.loc[0, "var_exportaciones_pct"])


# ---------- top países ----------

def datos_paises(n):
    filas = []
    for i in range(n):
        filas.append((2022, f"Pais{i:02d}", E, 100 + i))
        filas.append((2022, f"Pais{i:02d}", I, 10))
    return filas


def test_top_10_ordenado_y_limitado(conexion):
    df = consultas.top_paises(conexion(datos_paises(15)))
    assert len(df) == 10
    assert list(df["ranking"]) == list(range(1, 11))
    assert df["comercio_total"].is_monotonic_decreasing
    assert df.iloc[0]["pais"] == "Pais14"          # mayor comercio total (114 + 10)
    assert "Pais04" not in set(df["pais"])          # el 11.º queda fuera


def test_top_con_menos_de_10_paises_devuelve_los_que_hay(conexion):
    assert len(consultas.top_paises(conexion(datos_paises(3)))) == 3


def test_top_n_configurable(conexion):
    assert len(consultas.top_paises(conexion(datos_paises(15)), top_n=3)) == 3


def test_top_es_por_anio_e_independiente(conexion):
    conn = conexion([(2022, "A", E, 10), (2022, "B", E, 5), (2023, "B", E, 10), (2023, "A", E, 5)])
    df = consultas.top_paises(conn, top_n=1)
    assert dict(zip(df["anio"], df["pais"])) == {2022: "A", 2023: "B"}


def test_empate_se_resuelve_por_nombre(conexion):
    conn = conexion([(2022, "Zeta", E, 10), (2022, "Alfa", E, 10)])
    df = consultas.top_paises(conn, top_n=1)
    assert df.loc[0, "pais"] == "Alfa"


def test_top_cuotas_suman_100_y_cobertura_sin_importaciones_es_nula(conexion):
    df = consultas.top_paises(conexion([(2022, "A", E, 75), (2022, "B", I, 25)]))
    assert df["cuota_pct"].sum() == pytest.approx(100.0)
    a = df[df["pais"] == "A"].iloc[0]
    assert pd.isna(a["cobertura_pct"])


def test_top_con_comercio_total_cero_no_divide_por_cero(conexion):
    df = consultas.top_paises(conexion([(2022, "A", E, 0), (2022, "B", I, 0)]))
    assert len(df) == 2 and df["cuota_pct"].isna().all()


# ---------- sector y plantilla SQL ----------

def test_metricas_por_sector(conexion):
    conn = conexion([(2022, "A", E, 100, "Químico"), (2022, "A", I, 40, "Químico"),
                     (2022, "A", E, 10, "Textil y moda")])
    df = consultas.metricas_por_sector(conn)
    q = df[df["sector"] == "Químico"].iloc[0]
    assert q["saldo"] == pytest.approx(60) and q["cobertura_pct"] == pytest.approx(250.0)
    assert pd.isna(df[df["sector"] == "Textil y moda"].iloc[0]["cobertura_pct"])


def test_renderizar_sql_valida_parametros():
    with pytest.raises(ValueError):
        consultas.renderizar_sql("01_metricas_anuales.sql", tabla="comercio; DROP TABLE x")
    with pytest.raises(ValueError):
        consultas.renderizar_sql("01_metricas_anuales.sql", anios=())
    with pytest.raises(ValueError):
        consultas.renderizar_sql("03_top_paises.sql", top_n=0)
    sql = consultas.renderizar_sql("01_metricas_anuales.sql", tabla="main.demo.comercio", anios=(2022, 2023))
    assert "main.demo.comercio" in sql and "(2022), (2023)" in sql and "{" not in sql


def test_calendario_por_defecto_son_los_cuatro_anios(conexion):
    df = consultas.metricas_anuales(conexion([(2022, "A", E, 1)]))
    assert tuple(df["anio"]) == ANIOS


# SQLite devuelve NULL al dividir por cero, pero Spark/Databricks (modo ANSI) lanza un error.
# Por eso se comprueba de forma estática que cada división del SQL esté protegida con NULLIF.
@pytest.mark.parametrize("fichero", sorted(p.name for p in consultas.RUTA_SQL.glob("*.sql")))
def test_toda_division_del_sql_usa_nullif(fichero):
    import re
    codigo = "\n".join(linea.split("--")[0] for linea in
                       (consultas.RUTA_SQL / fichero).read_text(encoding="utf-8").splitlines())
    divisiones = [m.start() for m in re.finditer(r"/", codigo)]
    sin_proteger = [i for i in divisiones if not re.match(r"/\s*NULLIF\s*\(", codigo[i:])]
    assert not sin_proteger, f"{fichero}: división sin NULLIF en: {codigo[sin_proteger[0]-30:sin_proteger[0]+40]!r}"
