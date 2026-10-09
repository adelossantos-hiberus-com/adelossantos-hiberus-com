# Databricks notebook source
# MAGIC %md
# MAGIC # Capa gold de comercio exterior en Databricks (datos ficticios)
# MAGIC Carga los Parquet de `gold/` como tablas Delta y ejecuta las consultas de `sql/databricks/`.
# MAGIC
# MAGIC **Estado:** las llamadas `spark.read.parquet`, `saveAsTable` y `spark.sql` se han probado en Spark local (modo ANSI);
# MAGIC este notebook **no se ha ejecutado en un workspace real de Databricks**. Ajusta rutas y permisos a tu entorno.
# MAGIC
# MAGIC Pasos previos: genera el lakehouse en local (`python -m comercio_exterior.cli construir`) y sube la carpeta
# MAGIC `datos/lakehouse/gold` a un Volume de Unity Catalog (o a DBFS).

# COMMAND ----------

dbutils.widgets.text("ruta_gold", "/Volumes/main/comercio_exterior/lakehouse/gold")
dbutils.widgets.text("catalogo", "main")
dbutils.widgets.text("esquema", "comercio_exterior")
RUTA = dbutils.widgets.get("ruta_gold").rstrip("/")
DESTINO = f"{dbutils.widgets.get('catalogo')}.{dbutils.widgets.get('esquema')}"

# COMMAND ----------

# MAGIC %md ## 1. Tablas Delta (hechos mensuales y dimensiones)

# COMMAND ----------

spark.sql(f"CREATE SCHEMA IF NOT EXISTS {DESTINO}")
for tabla in ("dim_pais", "dim_producto", "dim_mes"):
    spark.read.parquet(f"{RUTA}/{tabla}.parquet").write.mode("overwrite").saveAsTable(f"{DESTINO}.{tabla}")
spark.read.parquet(f"{RUTA}/hechos_mensual/*/part.parquet").write.mode("overwrite").saveAsTable(f"{DESTINO}.hechos_mensual")
display(spark.sql(f"SELECT count(*) AS filas, min(mes_inicio) AS desde, max(mes_inicio) AS hasta FROM {DESTINO}.hechos_mensual"))

# COMMAND ----------

# MAGIC %md ## 2. Consultas
# MAGIC Los ficheros de `sql/databricks/` se generaron con el esquema `main.comercio_exterior`; aquí se sustituye por el elegido.

# COMMAND ----------

import glob
import os

RAIZ_SQL = os.path.abspath(os.path.join(os.getcwd(), "..", "sql", "databricks"))   # notebook en comercio_exterior/notebooks
consultas = {os.path.basename(f): open(f, encoding="utf-8").read().replace("main.comercio_exterior", DESTINO)
             for f in sorted(glob.glob(f"{RAIZ_SQL}/*.sql"))}
list(consultas)

# COMMAND ----------

display(spark.sql(consultas["01_resumen.sql"]))

# COMMAND ----------

display(spark.sql(consultas["02_serie_mensual.sql"]))

# COMMAND ----------

display(spark.sql(consultas["05_top_paises_resto.sql"]))

# COMMAND ----------

display(spark.sql(consultas["06_contribucion_crecimiento.sql"]))
