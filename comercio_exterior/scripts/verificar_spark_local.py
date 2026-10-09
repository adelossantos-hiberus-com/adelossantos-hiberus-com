"""Comprueba que el SQL da los mismos resultados en Spark (modo ANSI, como Databricks) y en SQLite.

Requiere `pip install pyspark` y Java; NO forma parte de los tests ni de las dependencias.
Uso (desde comercio_exterior/):  python scripts/verificar_spark_local.py
"""

import sys
from pathlib import Path

import pandas as pd
from pyspark.sql import SparkSession

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from comercio_exterior import consultas  # noqa: E402
from comercio_exterior.generador import generar_registros  # noqa: E402

CONSULTAS = ["01_metricas_anuales.sql", "02_variacion_interanual.sql",
             "03_top_paises.sql", "04_metricas_por_sector.sql"]
TEXTO = ("pais", "sector")


def normalizar(d: pd.DataFrame) -> pd.DataFrame:
    return d.apply(lambda c: c if c.name in TEXTO else pd.to_numeric(c, errors="coerce").astype(float))


def comparar(spark, df: pd.DataFrame, nombre: str) -> None:
    sdf = spark.createDataFrame(df.assign(fecha=df["fecha"].dt.strftime("%Y-%m-%d"))).selectExpr(
        "id_registro", "to_date(fecha) AS fecha", "anio", "pais", "producto", "sector", "flujo",
        "CAST(importe_eur AS DECIMAL(18,2)) AS importe_eur", "peso_kg")
    sdf.createOrReplaceTempView("comercio")
    esperado = consultas.ejecutar(consultas.crear_conexion(df), nombre)
    obtenido = spark.sql(consultas.renderizar_sql(nombre)).toPandas()
    pd.testing.assert_frame_equal(normalizar(esperado), normalizar(obtenido),
                                  check_dtype=False, rtol=1e-6, atol=0.011)
    print(f"OK  {nombre} ({len(esperado)} filas)")


def main() -> None:
    spark = (SparkSession.builder.master("local[2]").config("spark.ui.enabled", "false")
             .config("spark.sql.shuffle.partitions", "2").getOrCreate())
    print("spark.sql.ansi.enabled =", spark.conf.get("spark.sql.ansi.enabled"))
    df = generar_registros()
    casos = {
        "datos completos": df,
        "solo exportaciones 2022 (importaciones = 0, años sin datos)":
            df[(df.anio == 2022) & (df.flujo == "EXPORTACION")],
        "sin 2023 (año intermedio sin datos)": df[df.anio != 2023],
    }
    for etiqueta, datos in casos.items():
        print(f"\n# {etiqueta}")
        for nombre in CONSULTAS:
            comparar(spark, datos, nombre)
    spark.stop()


if __name__ == "__main__":
    main()
