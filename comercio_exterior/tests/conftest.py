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
