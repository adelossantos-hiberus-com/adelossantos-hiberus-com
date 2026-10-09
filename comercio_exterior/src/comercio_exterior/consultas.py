"""Carga y ejecución de las consultas SQL (portables entre SQLite y Spark SQL/Databricks)."""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

import pandas as pd

from .generador import ANIOS

RUTA_SQL = Path(__file__).resolve().parents[2] / "sql"
TABLA = "comercio"
TOP_N = 10

_IDENTIFICADOR = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*){0,2}$")


def renderizar_sql(nombre: str, tabla: str = TABLA, anios: tuple[int, ...] = ANIOS,
                   top_n: int = TOP_N) -> str:
    """Lee `sql/<nombre>` y sustituye {tabla}, {anios} y {top_n}.

    `tabla` puede ser `catalogo.esquema.tabla` en Databricks.
    """
    if not _IDENTIFICADOR.match(tabla):
        raise ValueError(f"Nombre de tabla no válido: {tabla!r}")
    if not anios or not all(isinstance(a, int) for a in anios):
        raise ValueError("anios debe ser una tupla de enteros no vacía")
    if not isinstance(top_n, int) or top_n < 1:
        raise ValueError("top_n debe ser un entero positivo")
    valores = ", ".join(f"({a})" for a in anios)
    texto = (RUTA_SQL / nombre).read_text(encoding="utf-8")
    return texto.format(tabla=tabla, anios=valores, top_n=top_n)


def crear_conexion(df: pd.DataFrame, tabla: str = TABLA) -> sqlite3.Connection:
    """Base SQLite en memoria con los registros cargados (solo para ejecución local y tests)."""
    conn = sqlite3.connect(":memory:")
    datos = df.copy()
    if pd.api.types.is_datetime64_any_dtype(datos["fecha"]):
        datos["fecha"] = datos["fecha"].dt.strftime("%Y-%m-%d")
    datos.to_sql(tabla, conn, index=False)
    return conn


def ejecutar(conn: sqlite3.Connection, nombre: str, **parametros) -> pd.DataFrame:
    return pd.read_sql_query(renderizar_sql(nombre, **parametros), conn)


def metricas_anuales(conn, **kw) -> pd.DataFrame:
    return ejecutar(conn, "01_metricas_anuales.sql", **kw)


def variacion_interanual(conn, **kw) -> pd.DataFrame:
    return ejecutar(conn, "02_variacion_interanual.sql", **kw)


def top_paises(conn, **kw) -> pd.DataFrame:
    return ejecutar(conn, "03_top_paises.sql", **kw)


def metricas_por_sector(conn, **kw) -> pd.DataFrame:
    return ejecutar(conn, "04_metricas_por_sector.sql", **kw)
