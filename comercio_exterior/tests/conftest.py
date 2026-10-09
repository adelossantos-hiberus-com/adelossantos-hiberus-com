import pandas as pd
import pytest

from comercio_exterior import consultas


def construir(filas):
    """Crea un DataFrame con el esquema de la tabla a partir de tuplas
    (anio, pais, flujo, importe[, sector])."""
    registros = []
    for i, f in enumerate(filas, start=1):
        anio, pais, flujo, importe = f[:4]
        sector = f[4] if len(f) > 4 else "Energía"
        registros.append({
            "id_registro": i, "fecha": f"{anio}-06-15", "anio": anio, "pais": pais,
            "producto": "Gas natural", "sector": sector, "flujo": flujo,
            "importe_eur": float(importe), "peso_kg": 100.0 + i,
        })
    return pd.DataFrame(registros)


@pytest.fixture
def conexion():
    """Fábrica: conexion(filas) -> conexión SQLite con esas filas."""
    abiertas = []

    def _crear(filas):
        conn = consultas.crear_conexion(construir(filas))
        abiertas.append(conn)
        return conn

    yield _crear
    for c in abiertas:
        c.close()


# ---------------------------------------------------------------------------
# Fixtures del lakehouse (aplicación de BI)
# ---------------------------------------------------------------------------
from dataclasses import dataclass  # noqa: E402

from comercio_exterior.lakehouse import Lakehouse  # noqa: E402
from comercio_exterior.simulacion import (Entrega, COLUMNAS_ENTREGA, Simulacion, generar_operaciones,  # noqa: E402
                                          simular_entregas)

N_PRUEBAS = 60_000


@dataclass
class Lago:
    raiz: object
    sim: Simulacion
    maestro: pd.DataFrame
    lakehouse: Lakehouse


@pytest.fixture(scope="session")
def lago(tmp_path_factory):
    """Lakehouse completo con 60.000 operaciones (2018–2025) y ruido, construido una sola vez."""
    raiz = tmp_path_factory.mktemp("lago") / "lakehouse"
    maestro = generar_operaciones(N_PRUEBAS, 7)
    sim = simular_entregas(maestro, 7)
    lk = Lakehouse(raiz)
    for e in sim.entregas:
        lk.ingestar(e)
    return Lago(raiz, sim, maestro, lk)


def hacer_entrega(filas, ingesta_id="ING-0001", periodo="2020Q1", version=1, tipo="ORIGINAL"):
    """Entrega mínima a partir de tuplas (operacion_n, fecha, flujo, pais, producto, importe[, peso, unidades])."""
    reg = []
    for f in filas:
        n, fecha, flujo, pais, prod, imp = f[:6]
        peso = f[6] if len(f) > 6 else 10.0
        uds = f[7] if len(f) > 7 else 2
        reg.append({"operacion_id": "OP-%08d" % n, "version": version, "tipo_registro": tipo, "fecha": fecha,
                    "flujo": flujo, "pais_codigo": pais, "producto_codigo": prod, "importe_eur": float(imp),
                    "peso_kg": float(peso), "unidades": uds})
    df = pd.DataFrame(reg, columns=COLUMNAS_ENTREGA)
    df["version"] = df["version"].astype("int32")
    df["unidades"] = df["unidades"].astype("Int64")
    return Entrega(ingesta_id, f"{ingesta_id}.csv", periodo, df)


@pytest.fixture
def lago_vacio(tmp_path):
    lk = Lakehouse(tmp_path / "lh")
    yield lk
    lk.cerrar()
