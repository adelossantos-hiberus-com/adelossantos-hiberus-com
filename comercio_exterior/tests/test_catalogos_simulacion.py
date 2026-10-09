import numpy as np
import pandas as pd
import pytest

from comercio_exterior.catalogos import ANIO_FIN, ANIO_INICIO, CATALOGO, dim_mes
from comercio_exterior.simulacion import (COLUMNAS_ENTREGA, COLUMNAS_OPERACION, generar_operaciones,
                                          simular_entregas)


def test_catalogo_50_paises_200_productos_y_jerarquia_de_dos_niveles():
    c = CATALOGO
    assert len(c.paises) == 50 and c.paises["pais_codigo"].is_unique and c.paises["pais"].is_unique
    p = c.productos
    assert len(p) == 200 and p["producto_codigo"].is_unique and p["producto"].is_unique
    assert p["sector_codigo"].nunique() == 10 and p["subsector_codigo"].nunique() == 40
    # cada subsector pertenece a un único sector y tiene 5 productos
    assert (p.groupby("subsector_codigo")["sector_codigo"].nunique() == 1).all()
    assert (p.groupby("subsector_codigo").size() == 5).all()
    assert (p[["precio_unitario_eur", "peso_unitario_kg", "unidades_tipicas", "peso"]] > 0).all().all()


def test_catalogo_es_estable():
    from comercio_exterior.catalogos import construir_catalogo
    pd.testing.assert_frame_equal(construir_catalogo().productos, CATALOGO.productos)


def test_calendario_mensual_completo():
    m = dim_mes()
    assert len(m) == 96 and m["mes_inicio"].is_unique
    assert m["anio"].min() == ANIO_INICIO and m["anio"].max() == ANIO_FIN


@pytest.fixture(scope="module")
def maestro():
    return generar_operaciones(20_000, 3)


def test_maestro_esquema_y_dominios(maestro):
    assert list(maestro.columns) == COLUMNAS_OPERACION and len(maestro) == 20_000
    assert maestro["operacion_id"].is_unique
    assert set(maestro["flujo"]) == {"EXPORTACION", "IMPORTACION"}
    assert set(maestro["pais_codigo"]) <= set(CATALOGO.paises["pais_codigo"])
    assert set(maestro["producto_codigo"]) <= set(CATALOGO.productos["producto_codigo"])
    f = pd.to_datetime(maestro["fecha"])
    assert f.dt.year.min() == ANIO_INICIO and f.dt.year.max() == ANIO_FIN
    assert (maestro[["importe_eur", "peso_kg", "unidades"]] > 0).all().all()
    assert not maestro.isna().any().any()


def test_maestro_reproducible_y_sensible_a_la_semilla(maestro):
    pd.testing.assert_frame_equal(maestro, generar_operaciones(20_000, 3))
    assert not maestro["importe_eur"].equals(generar_operaciones(20_000, 4)["importe_eur"])


def test_maestro_cobertura_del_catalogo():
    m = generar_operaciones(100_000, 1)
    assert m["pais_codigo"].nunique() == 50 and m["producto_codigo"].nunique() == 200


def test_parametro_invalido():
    with pytest.raises(ValueError):
        generar_operaciones(0)


def test_simulacion_inyecta_ruido_conocido_y_calcula_la_verdad(maestro):
    sim = simular_entregas(maestro, 3)
    assert len(sim.entregas) == 32
    assert all(list(e.datos.columns) == COLUMNAS_ENTREGA for e in sim.entregas)
    inj = sim.inyectados
    total = sum(len(e.datos) for e in sim.entregas)
    assert total == inj["filas_entregadas"] == len(maestro) + inj["duplicados_internos"] + inj["reentregas"] \
        + inj["correcciones_v2"] + inj["correcciones_v3"] + inj["correcciones_invalidas"] + inj["obsoletas"] + inj["invalidos"]
    assert inj["correcciones_v2"] > 0 and inj["invalidos"] > 0 and inj["duplicados_internos"] > 0
    # la verdad conserva todas las operaciones y refleja las correcciones
    assert len(sim.verdad) == len(maestro) and (sim.verdad["version"] > 1).sum() == inj["correcciones_v2"]
    cambiadas = (sim.verdad["importe_eur"] != maestro["importe_eur"]).sum()
    assert 0 < cambiadas <= inj["correcciones_v2"]


def test_simulacion_reproducible(maestro):
    a, b = simular_entregas(maestro, 3), simular_entregas(maestro, 3)
    assert a.inyectados == b.inyectados
    pd.testing.assert_frame_equal(a.entregas[5].datos, b.entregas[5].datos)
