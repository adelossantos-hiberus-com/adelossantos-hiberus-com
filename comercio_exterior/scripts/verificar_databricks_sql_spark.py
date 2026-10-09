"""Ejecuta las consultas en su versión Databricks sobre Spark local (modo ANSI) y las contrasta con DuckDB.

No es una prueba contra un workspace real de Databricks: usa Spark SQL en local como aproximación al motor.
Requiere `pip install pyspark` (y Java). Uso (desde comercio_exterior/):
    PYTHONPATH=src python scripts/verificar_databricks_sql_spark.py [--destino datos/lakehouse]
"""

from __future__ import annotations

import argparse
import math
import shutil
import tempfile
from pathlib import Path

from pyspark.sql import SparkSession

from comercio_exterior.analitica import Filtros, Motor
from comercio_exterior.analitica.sql import parametros_dimension, parametros_medida, renderizar
from comercio_exterior.lakehouse import Rutas

ESQUEMA = "comercio_exterior"


def iguales(a, b, tol=0.011) -> bool:
    if a is None or b is None or (isinstance(a, float) and math.isnan(a)) or (isinstance(b, float) and math.isnan(b)):
        return (a is None or (isinstance(a, float) and math.isnan(a))) and (b is None or (isinstance(b, float) and math.isnan(b)))
    if isinstance(a, (int, float)) or hasattr(a, "__float__") and not isinstance(a, str):
        try:
            return abs(float(a) - float(b)) <= tol + 1e-9 * abs(float(b))
        except (TypeError, ValueError):
            pass
    return str(a) == str(b)


def escenarios():
    pais, prod, sec, sub, reg = (parametros_dimension(d) for d in ("pais", "producto", "sector", "subsector", "region"))
    f0 = Filtros.crear()
    f1 = Filtros.crear("2022-03", "2023-09", paises=["DE", "FR"], sectores=["S02", "S07"])
    fa = Filtros.crear("2021-01", "2023-12")          # periodo amplio: todos los países, varios años
    vacio = Filtros.crear("2018-01", "2018-01", paises=["LU"], productos=["P200"])     # sin datos: divisiones por cero
    corto = Filtros.crear("2025-12", "2025-12")
    sub_f = Filtros.crear("2020-01", "2021-12", subsectores=["S01-1", "S07-3"], productos=["P001", "P090"])
    out = []
    for nombre, f in (("sin filtros", f0), ("con filtros", f1), ("sin datos", vacio), ("un mes", corto), ("subsector y producto", sub_f)):
        out += [(f"resumen/{nombre}", "resumen", f, {}), (f"serie_mensual/{nombre}", "serie_mensual", f, {}),
                (f"serie_anual/{nombre}", "serie_anual", f, {})]
    for d, p in (("pais", pais), ("sector", sec), ("subsector", sub), ("producto", prod), ("region", reg)):
        out.append((f"tabla/{d}", "tabla", fa, dict(**p, orden="comercio_total_eur", sentido="DESC", limite=15, desplazamiento=5)))
    out.append(("tabla/pais orden cobertura asc", "tabla", fa, dict(**pais, orden="cobertura_pct", sentido="ASC", limite=50, desplazamiento=0)))
    for med in ("exportaciones", "importaciones", "comercio_total", "saldo"):
        for sentido in ("desc", "asc"):
            out.append((f"top/pais/{med}/{sentido}", "top", fa, dict(**pais, **parametros_medida(med, 5, sentido))))
            out.append((f"contribucion/pais/{med}", "contribucion", fa, dict(**pais, **parametros_medida(med, 4, "desc"))))
            out.append((f"ranking/pais/{med}/{sentido}", "ranking", fa, dict(**pais, **parametros_medida(med, 4, sentido, forma="ranking"))))
    out.append(("top/producto sin resto (n=500)", "top", f0, dict(**prod, **parametros_medida("comercio_total", 500, "desc"))))
    out.append(("top/sin datos", "top", vacio, dict(**pais, **parametros_medida("saldo", 5, "desc"))))
    out.append(("contribucion/sin datos", "contribucion", vacio, dict(**pais, **parametros_medida("saldo", 5, "desc"))))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--destino", default="datos/lakehouse")
    destino = Path(ap.parse_args().destino)
    r = Rutas(destino)
    tmp = tempfile.mkdtemp(prefix="spark_wh_")
    spark = (SparkSession.builder.master("local[2]").config("spark.ui.enabled", "false")
             .config("spark.sql.shuffle.partitions", "4").config("spark.sql.warehouse.dir", tmp).getOrCreate())
    spark.sparkContext.setLogLevel("ERROR")
    print("spark", spark.version, "· ansi =", spark.conf.get("spark.sql.ansi.enabled"))
    spark.sql(f"CREATE DATABASE IF NOT EXISTS {ESQUEMA}")
    spark.read.parquet(str(r.hechos / "*" / "part.parquet")).write.mode("overwrite").saveAsTable(f"{ESQUEMA}.hechos_mensual")
    for t in ("dim_pais", "dim_producto", "dim_mes"):
        spark.read.parquet(str(r.gold / f"{t}.parquet")).write.mode("overwrite").saveAsTable(f"{ESQUEMA}.{t}")
    motor = Motor(destino)
    fallos = 0
    try:
        for nombre, plantilla, f, params in escenarios():
            esperado = motor.ejecutar_sql(renderizar(plantilla, f, **params), usar_cache=False)
            sql_dbx = renderizar(plantilla, f, dialecto="databricks", esquema=ESQUEMA, **params)
            filas = [r_.asDict() for r_ in spark.sql(sql_dbx).collect()]
            ok = len(filas) == len(esperado)
            if ok:
                for a, b in zip(esperado, filas):
                    for k in a:
                        if not iguales(b.get(k), a[k]):
                            ok = False
                            print(f"   ✗ {nombre}: {k}: Spark={b.get(k)!r} DuckDB={a[k]!r}")
                            break
                    if not ok:
                        break
            else:
                print(f"   ✗ {nombre}: filas Spark={len(filas)} DuckDB={len(esperado)}")
            fallos += not ok
            print(("OK  " if ok else "FALLO ") + f"{nombre} ({len(esperado)} filas)")
    finally:
        spark.stop()
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n{'TODO CORRECTO' if not fallos else str(fallos) + ' ESCENARIOS CON DIFERENCIAS'} ({len(escenarios())} escenarios)")
    raise SystemExit(1 if fallos else 0)


if __name__ == "__main__":
    main()
