import pandas as pd

from comercio_exterior import generador, validaciones
from comercio_exterior.generador import ANIOS, COLUMNAS, FLUJOS, SECTORES, generar_registros
import pytest


@pytest.fixture(scope="module")
def df():
    return generar_registros()


def test_genera_50000_registros_con_esquema(df):
    assert len(df) == 50_000
    assert tuple(df.columns) == COLUMNAS


def test_anios_flujos_y_dominios(df):
    assert set(df["anio"]) == set(ANIOS)
    assert set(df["flujo"]) == set(FLUJOS)
    assert df["pais"].nunique() == len(generador.PAISES)
    assert df["sector"].nunique() == len(SECTORES)


def test_producto_pertenece_a_su_sector(df):
    validos = {(s, p) for s, (_, _, prods) in SECTORES.items() for p in prods}
    assert set(zip(df["sector"], df["producto"])) <= validos


def test_sin_nulos_duplicados_ni_negativos(df):
    assert not df.isna().any().any()
    assert df["id_registro"].is_unique
    assert (df["importe_eur"] > 0).all() and (df["peso_kg"] > 0).all()


def test_anio_coincide_con_fecha(df):
    assert (pd.to_datetime(df["fecha"]).dt.year == df["anio"]).all()


def test_es_reproducible_con_la_misma_semilla():
    pd.testing.assert_frame_equal(generar_registros(500, semilla=7), generar_registros(500, semilla=7))


def test_semillas_distintas_dan_datos_distintos():
    assert not generar_registros(500, semilla=1)["importe_eur"].equals(
        generar_registros(500, semilla=2)["importe_eur"])


def test_parametros_invalidos():
    with pytest.raises(ValueError):
        generar_registros(0)
    with pytest.raises(ValueError):
        generar_registros(10, anios=())
    with pytest.raises(ValueError):
        generar_registros(10, anios=(1999,))


def test_los_datos_generados_superan_todas_las_validaciones(df):
    assert not validaciones.hay_errores(validaciones.validar_calidad(df, ANIOS))
