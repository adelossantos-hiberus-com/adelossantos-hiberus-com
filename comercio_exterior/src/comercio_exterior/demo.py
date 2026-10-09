"""Ejecución local completa: genera datos, valida, calcula métricas y muestra resultados."""

from __future__ import annotations

import sys

import pandas as pd

from . import consultas, validaciones
from .generador import ANIOS, generar_registros


def main() -> int:
    pd.options.display.float_format = "{:,.2f}".format
    pd.options.display.width = 200
    pd.options.display.max_columns = 30

    df = generar_registros()
    print(f"Registros generados: {len(df):,} ({df['anio'].min()}–{df['anio'].max()})\n")

    print("== Validaciones de calidad ==")
    calidad = validaciones.validar_calidad(df, ANIOS)
    print(validaciones.formatear(calidad))

    conn = consultas.crear_conexion(df)
    metricas = consultas.metricas_anuales(conn)
    top = consultas.top_paises(conn)

    print("\n== Validaciones de coherencia de totales ==")
    coherencia = validaciones.validar_coherencia(df, metricas, top)
    print(validaciones.formatear(coherencia))

    print("\n== Métricas anuales (EUR) ==")
    print(metricas.to_string(index=False))
    print("\n== Variación interanual ==")
    print(consultas.variacion_interanual(conn).to_string(index=False))
    print("\n== Top 10 países por comercio total y año ==")
    print(top.to_string(index=False))
    print("\n== Métricas por sector ==")
    print(consultas.metricas_por_sector(conn).to_string(index=False))

    return 1 if validaciones.hay_errores(calidad + coherencia) else 0


if __name__ == "__main__":
    sys.exit(main())
