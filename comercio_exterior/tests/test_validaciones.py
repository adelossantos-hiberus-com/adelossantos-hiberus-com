import numpy as np
import pandas as pd
import pytest

from comercio_exterior import consultas, validaciones
from comercio_exterior.generador import generar_registros

from conftest import construir

E, I = "EXPORTACION", "IMPORTACION"
BASE = [(2022, "Francia", E, 100), (2022, "Italia", I, 50), (2023, "Francia", E, 120)]


def fallos(resultados):
    return {r.nombre for r in resultados if not r.ok}


def test_datos_limpios_no_dan_errores():
    assert fallos(validaciones.validar_calidad(construir(BASE), (2022, 2023))) == set()


def test_detecta_id_duplicado():
    df = construir(BASE)
    df.loc[1, "id_registro"] = 1
    assert "sin_ids_duplicados" in fallos(validaciones.validar_calidad(df))


def test_detecta_fila_duplicada_con_distinto_id():
    df = construir(BASE)
    copia = df.iloc[[0]].copy()
    copia["id_registro"] = 99
    df = pd.concat([df, copia], ignore_index=True)
    f = fallos(validaciones.validar_calidad(df))
    assert f == {"sin_filas_duplicadas"}


@pytest.mark.parametrize("columna", ["pais", "importe_eur", "fecha", "flujo", "anio"])
def test_detecta_nulos(columna):
    df = construir(BASE)
    df[columna] = df[columna].astype(object)
    df.loc[0, columna] = None
    assert f"sin_nulos:{columna}" in fallos(validaciones.validar_calidad(df))


def test_detecta_texto_vacio():
    df = construir(BASE)
    df.loc[0, "pais"] = "  "
    assert "sin_nulos:pais" in fallos(validaciones.validar_calidad(df))


def test_detecta_importes_y_pesos_negativos():
    df = construir(BASE)
    df.loc[0, "importe_eur"] = -5.0
    df.loc[1, "peso_kg"] = -1.0
    assert {"sin_negativos:importe_eur", "sin_negativos:peso_kg"} <= fallos(validaciones.validar_calidad(df))


def test_importe_cero_no_es_negativo():
    df = construir(BASE)
    df.loc[0, "importe_eur"] = 0.0
    assert fallos(validaciones.validar_calidad(df)) == set()


def test_detecta_flujo_invalido_y_anio_incoherente():
    df = construir(BASE)
    df.loc[0, "flujo"] = "REEXPORTACION"
    df.loc[1, "anio"] = 2030
    assert {"flujo_valido", "anio_coherente_con_fecha"} <= fallos(validaciones.validar_calidad(df))


def test_detecta_anio_sin_datos():
    r = validaciones.validar_calidad(construir(BASE), (2022, 2023, 2024))
    assert "anios_con_datos" in fallos(r)
    assert "2024" in next(x for x in r if x.nombre == "anios_con_datos").detalle


def test_detecta_columnas_ausentes():
    r = validaciones.validar_calidad(construir(BASE).drop(columns=["sector"]))
    assert fallos(r) == {"esquema"}


def test_dataframe_vacio_no_falla():
    vacio = construir(BASE).iloc[0:0]
    r = validaciones.validar_calidad(vacio, (2022,))
    assert "anios_con_datos" in fallos(r)


# ---------- coherencia ----------

def coherencia(df, tamper=None):
    conn = consultas.crear_conexion(df)
    metricas = consultas.metricas_anuales(conn, anios=(2022, 2023))
    if tamper:
        tamper(metricas)
    top = consultas.top_paises(conn)
    return validaciones.validar_coherencia(df, metricas, top)


def test_coherencia_correcta():
    assert fallos(coherencia(construir(BASE))) == set()


def test_coherencia_con_anio_sin_datos_y_cero_importaciones():
    df = construir([(2022, "Francia", E, 100)])
    conn = consultas.crear_conexion(df)
    metricas = consultas.metricas_anuales(conn, anios=(2022, 2023))
    assert fallos(validaciones.validar_coherencia(df, metricas)) == set()


def test_detecta_total_alterado():
    def alterar(m):
        m.loc[0, "exportaciones"] += 1000
    assert "totales_anuales_sql_igual_pandas" in fallos(coherencia(construir(BASE), alterar))


def test_detecta_saldo_incoherente():
    def alterar(m):
        m.loc[0, "saldo"] += 5
    assert "saldo_y_cobertura_coherentes" in fallos(coherencia(construir(BASE), alterar))


def test_detecta_cobertura_incoherente():
    def alterar(m):
        m.loc[0, "cobertura_pct"] = 1.0
    assert "saldo_y_cobertura_coherentes" in fallos(coherencia(construir(BASE), alterar))


def test_detecta_importes_sin_pais():
    df = construir(BASE)
    df["pais"] = df["pais"].astype(object)
    df.loc[0, "pais"] = None
    assert "suma_por_pais_igual_total" in fallos(coherencia(df))


def test_coherencia_sobre_los_50000_registros():
    df = generar_registros()
    conn = consultas.crear_conexion(df)
    metricas = consultas.metricas_anuales(conn)
    top = consultas.top_paises(conn)
    assert fallos(validaciones.validar_coherencia(df, metricas, top)) == set()
    # Recálculo independiente con pandas de uno de los valores
    esperado = df[(df.anio == 2024) & (df.flujo == E)]["importe_eur"].sum()
    assert metricas.loc[metricas.anio == 2024, "exportaciones"].iloc[0] == pytest.approx(esperado)
    assert np.isclose(top.groupby("anio").size().max(), 10)


def test_formatear_y_hay_errores():
    r = [validaciones.Resultado("a", True), validaciones.Resultado("b", False, "x")]
    assert validaciones.hay_errores(r) and not validaciones.hay_errores(r[:1])
    assert "[ERROR] b — x" in validaciones.formatear(r)
