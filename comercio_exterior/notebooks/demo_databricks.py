# Databricks notebook source
# MAGIC %md
# MAGIC # Demo de comercio exterior (datos ficticios)
# MAGIC Genera 50.000 registros, los guarda como tabla Delta, valida su calidad y ejecuta las consultas SQL del proyecto.
# MAGIC Importa el repositorio como *Git folder* (Repos) y ejecuta este notebook desde `comercio_exterior/notebooks/`.
# MAGIC No usa servicios externos ni credenciales.

# COMMAND ----------

import os
import sys

# El notebook está en comercio_exterior/notebooks; el código en comercio_exterior/src
RAIZ = os.path.abspath(os.path.join(os.getcwd(), ".."))
sys.path.insert(0, os.path.join(RAIZ, "src"))

from comercio_exterior import consultas, validaciones
from comercio_exterior.generador import ANIOS, generar_registros

dbutils.widgets.text("catalogo", "main")
dbutils.widgets.text("esquema", "comercio_exterior_demo")
TABLA = f"{dbutils.widgets.get('catalogo')}.{dbutils.widgets.get('esquema')}.comercio"

# COMMAND ----------

# MAGIC %md ## 1. Generación y carga como tabla Delta

# COMMAND ----------

from pyspark.sql import functions as F

pdf = generar_registros()
spark.sql(f"CREATE SCHEMA IF NOT EXISTS {dbutils.widgets.get('catalogo')}.{dbutils.widgets.get('esquema')}")
(spark.createDataFrame(pdf)
      .withColumn("fecha", F.to_date("fecha"))
      .withColumn("importe_eur", F.col("importe_eur").cast("decimal(18,2)"))
      .write.mode("overwrite").saveAsTable(TABLA))
print(f"{spark.table(TABLA).count():,} registros en {TABLA}")

# COMMAND ----------

# MAGIC %md ## 2. Validaciones de calidad

# COMMAND ----------

datos = spark.table(TABLA).toPandas()          # 50.000 filas: cabe sin problema en el driver
datos["importe_eur"] = datos["importe_eur"].astype(float)
calidad = validaciones.validar_calidad(datos, ANIOS)
print(validaciones.formatear(calidad))

# COMMAND ----------

# MAGIC %md ## 3. Métricas (las mismas consultas que en local)

# COMMAND ----------

def sql(nombre, **kw):
    return spark.sql(consultas.renderizar_sql(nombre, tabla=TABLA, **kw))

display(sql("01_metricas_anuales.sql"))

# COMMAND ----------

display(sql("02_variacion_interanual.sql"))

# COMMAND ----------

display(sql("03_top_paises.sql"))

# COMMAND ----------

display(sql("04_metricas_por_sector.sql"))

# COMMAND ----------

# MAGIC %md ## 4. Coherencia de totales

# COMMAND ----------

metricas = sql("01_metricas_anuales.sql").toPandas()
top = sql("03_top_paises.sql").toPandas()
for col in ("exportaciones", "importaciones", "saldo", "cobertura_pct"):
    metricas[col] = metricas[col].astype(float)
for col in ("exportaciones", "importaciones", "comercio_total", "saldo", "cobertura_pct", "cuota_pct"):
    top[col] = top[col].astype(float)
coherencia = validaciones.validar_coherencia(datos, metricas, top)
print(validaciones.formatear(coherencia))
assert not validaciones.hay_errores(calidad + coherencia), "Hay validaciones fallidas"
