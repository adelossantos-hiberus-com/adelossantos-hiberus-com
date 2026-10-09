# Llevar las consultas a Databricks

## Qué se ha probado y qué no

| | Estado |
|---|---|
| Las 7 consultas en su versión Databricks (`sql/databricks/*.sql`) ejecutadas en **Spark 4.2 local con modo ANSI activado** (el comportamiento de Databricks en versiones recientes), comparadas fila a fila con DuckDB en **48 escenarios** (periodos, filtros combinados, sin datos, un solo mes, todas las dimensiones y medidas, N mayor y menor que los elementos) | **Probado** (`scripts/verificar_databricks_sql_spark.py`) |
| `spark.read.parquet(...)` + `saveAsTable(...)` + `spark.sql(...)` con los Parquet de gold | **Probado** en Spark local |
| Ejecución en un **workspace real** de Databricks (Unity Catalog, SQL Warehouse, Photon, permisos, Volumes) | **No probado** |
| Rendimiento en Databricks | **No medido** |
| Trasladar el pipeline silver/gold a Delta (`MERGE`) | **Propuesta**, no implementada |

## Pasos propuestos

1. **Generar** el lakehouse en local: `python -m comercio_exterior.cli construir`.
2. **Subir** `datos/lakehouse/gold/` a un *Volume* de Unity Catalog (o a DBFS), p. ej. `/Volumes/main/comercio_exterior/lakehouse/gold`.
3. **Crear las tablas** con `notebooks/databricks_gold.py` (carga `hechos_mensual`, `dim_pais`, `dim_producto`, `dim_mes` como tablas Delta en `<catalogo>.<esquema>`). Equivalente en SQL:
   ```sql
   CREATE SCHEMA IF NOT EXISTS main.comercio_exterior;
   CREATE OR REPLACE TABLE main.comercio_exterior.hechos_mensual AS
     SELECT * FROM parquet.`/Volumes/main/comercio_exterior/lakehouse/gold/hechos_mensual/*/part.parquet`;
   -- idem dim_pais, dim_producto, dim_mes (ficheros .parquet de gold/)
   ```
4. **Ejecutar** los `.sql` de `sql/databricks/` en un SQL Warehouse o desde el notebook. Si usas otro catálogo/esquema, sustituye `main.comercio_exterior` (el notebook lo hace).

## De DuckDB a Databricks: qué cambia

Las consultas viven en `sql/analitica/*.sql` como plantillas y se renderizan para cada motor (`renderizar(..., dialecto="databricks")`); los `.sql` de `sql/databricks/` se generan con `python -m comercio_exterior.cli exportar-sql` y una prueba comprueba que están sincronizados.

| Aspecto | DuckDB (local) | Databricks |
|---|---|---|
| Tablas | vistas `hechos_mensual`, `dim_*` sobre `read_parquet(...)` | tablas Delta `catalogo.esquema.tabla` |
| Sintaxis | SQL estándar: CTE, ventanas, `CASE`, `NULLIF`, `DATE '…'`, `LIMIT/OFFSET`, `NULLS LAST` | idéntica; no se usan funciones propias de DuckDB |
| `JOIN` con dimensiones | solo las que la consulta necesita | siempre ambas (así se puede activar cualquier filtro editando el SQL) |
| Divisiones | `NULLIF` | `NULLIF` (**obligatorio**: con ANSI una división por cero lanza error) |
| Filtros | literales ya validados | líneas `-- AND h.pais_codigo IN ('FR','DE')` comentadas en el CTE `base`: se activan editándolas |
| Importes | `DOUBLE` | recomendable `DECIMAL(18,2)` al crear las tablas (el script de verificación ya castea a `DECIMAL(18,2)` y los resultados coinciden) |

Para parametrizar sin editar texto en Databricks SQL se pueden usar marcadores de parámetro (`DATE(:desde)`), pero no listas de códigos de forma sencilla: es una mejora propuesta.

## Pipeline en Databricks (propuesta, no implementada)

El incremental silver de este proyecto (validar → deduplicar → versión vigente) se traduce de forma natural a Delta:

```sql
-- nuevos = filas válidas de la ingesta con operacion_id, version, hash y ranking ya calculados
MERGE INTO silver.operaciones s
USING nuevos n ON s.operacion_id = n.operacion_id
WHEN MATCHED AND n.version > s.version THEN UPDATE SET *
WHEN NOT MATCHED THEN INSERT *;
```

Delta evitaría reescribir trimestres completos (principal coste de la carga local, ver `docs/rendimiento.md`) y daría historial (`DESCRIBE HISTORY`/*time travel*) en lugar del registro de ingestas casero. Un trabajo con *Auto Loader* podría sustituir las entregas simuladas. Nada de esto se ha ejecutado.
