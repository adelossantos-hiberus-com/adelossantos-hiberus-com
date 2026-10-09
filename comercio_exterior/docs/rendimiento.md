# Rendimiento

Medido en un único entorno: contenedor Linux con **4 vCPU**, Python 3.13, DuckDB 1.5.6, sobre el lakehouse de **1.000.000 de operaciones** (1.011.688 filas en bronze, 32 ingestas). Resultados completos en `docs/benchmark_resultados.json`; se reproducen con `PYTHONPATH=src python scripts/benchmark.py`. Son tiempos de reloj, de una sola máquina; las variaciones entre ejecuciones son de ~10 %.

## Datos y carga

| Concepto | Resultado |
|---|---|
| Generar 1 M de operaciones + entregas con ruido | 3,4 s + 9,9 s |
| Carga completa bronze → silver → gold (32 ingestas) | **76,9 s** (bronze 1,7 · silver 50,7 · gold 17,8) |
| Mediana por ingesta | silver 1,65 s (máx. 2,71) · gold 0,57 s (máx. 1,07) |
| Tamaño en disco | bronze 23,9 MB · silver 32,0 MB · gold 7,2 MB · rechazos+descartes 0,4 MB |
| Filas | bronze 1.011.688 · silver 1.000.000 · gold 412.629 |
| Rechazadas / descartadas | 2.161 / 9.527 (6.149 duplicados exactos, 3.378 versiones antiguas) |

## Consultas analíticas (gold, sin caché; p50 / p95 en ms, 15 repeticiones)

| Consulta | Sin filtros | Con filtros* |
|---|---|---|
| resumen | 32,9 / 39,1 | 23,6 / 26,2 |
| serie mensual | 23,4 / 32,0 | 19,8 / 21,0 |
| serie anual | 21,8 / 25,1 | 20,2 / 22,7 |
| tabla por país | 49,6 / 57,1 | 27,6 / 36,7 |
| tabla por producto (200) | 46,2 / 54,5 | 26,0 / 32,9 |
| Top 10 + Resto | 34,3 / 39,5 | 18,6 / 21,9 |
| contribución al crecimiento | 33,1 / 38,7 | 18,4 / 21,2 |
| ranking anual | 30,9 / 36,0 | 18,8 / 24,3 |

\* 2023-01…2024-12, países DE/FR/IT y sectores S02/S07. El filtro de fechas reduce el trabajo porque el escaneo de Parquet descarta ficheros y grupos de filas por sus estadísticas.

## API (HTTP, uvicorn, sobre el mismo lakehouse)

| Caso | Resultado |
|---|---|
| Misma petición repetida (caché) | p50 2,8 ms |
| Peticiones distintas (sin caché) | p50 28,0 ms |
| Rendimiento sin caché, 1 / 4 / 8 clientes | 33 / 60 / 69 peticiones/s (p50 30 / 57 / 85 ms; p95 41 / 87 / 171 ms) |
| `/calidad` (barre 1 M de filas, incluye un anti-join silver↔bronze) | 605 ms la primera vez, 2,3 ms con caché |

## Cuellos de botella y mejoras aplicadas

### 1. Carga de silver (mejora aplicada: −47 % en silver, −37 % en total)

*Línea base* (commit `ecb9f40`, reproducible con `git checkout ecb9f40`): carga completa **121,7 s** (bronze 1,6 · silver **94,8** · gold 18,9). Silver era el 78 % del tiempo y crecía con cada ingesta (0,4 s la primera, 4,9 s la última).

*Diagnóstico* (cronometrando cada sentencia de DuckDB al volver a procesar la última ingesta sobre una copia del lakehouse): ~56 % del tiempo en las ventanas de deduplicación sobre **todas** las filas de los trimestres afectados y ~38 % en reescribir ficheros Parquet. Además, cada ingesta reescribía de media 16 trimestres: los duplicados exactos reenviados y las correcciones obsoletas también «tocaban» periodos antiguos aunque su contenido no cambiara.

*Mejoras*:
1. Las ventanas y la fusión se calculan **solo sobre las operaciones que traen filas nuevas** (las filas no afectadas no se leen en memoria ni se reordenan).
2. **Solo se reescriben los periodos que reciben una fila ganadora**; un periodo en el que todo lo nuevo era duplicado exacto o versión antigua no se reescribe ni se regenera en gold.

*Resultado*: silver 94,8 → 50,7 s (mediana por ingesta 1,65 s). El contenido de silver/gold/descartes es **idéntico** al anterior (comparado con joins por nombre de columna) y las 46 pruebas del pipeline pasan sin cambios.

*Coste que permanece*: las correcciones sobre trimestres antiguos siguen obligando a reescribir esos trimestres (*copy-on-write*), ~16 por ingesta. No se ha evaluado otra granularidad de partición (la opción `--particion anio` existe pero reescribe ficheros más grandes); la solución estructural sería *merge-on-read* o Delta `MERGE`.

### 2. `JOIN` con dimensiones en las consultas (mejora aplicada: −30 % a −40 %)

Se midió que los dos `JOIN` con `dim_pais` y `dim_producto` sobre las 413 mil filas de gold costaban ~1/3 del tiempo del resumen (40 ms → 27 ms sin ellos). Ahora se unen **solo las dimensiones que la consulta usa** (filtros de sector/subsector o agrupación por producto/sector/país/región). Efecto en las consultas sin filtros (p50): resumen 53,1 → 32,9 ms · serie mensual 34,2 → 23,4 · serie anual 32,8 → 21,8 · Top 10 46,3 → 34,3 · contribución 42,6 → 33,1 · ranking 42,6 → 30,9 · tabla por país 58,5 → 49,6 (necesita el `JOIN`). Los resultados siguen coincidiendo con la implementación de referencia (175 pruebas) y con Spark. La versión de Databricks mantiene ambos `JOIN` para poder activar cualquier filtro editando el SQL.

### 3. Capa gold frente a agregar silver al vuelo

Mismas consultas contra las 1 M de filas de silver agregadas en cada petición: resumen 79,7 ms → 20,7 (3,9×), serie mensual 37,9 → 18,1 (2,1×), Top 10 70,0 → 20,6 (3,4×); y gold ocupa 4,4 veces menos (7,2 MB frente a 32,0 MB). La ganancia es moderada porque DuckDB ya es muy rápido sobre 1 M de filas; gold se justifica sobre todo por el modelo estrella y por ser lo que se lleva a Databricks.

### 4. Caché de resultados en el motor

Una petición repetida baja de ~28 ms a ~3 ms. La clave incluye la versión de los datos (cambia al completarse una ingesta), así que no sirve datos obsoletos. Es una LRU de 256 entradas.

### 5. Hilos de DuckDB: no se cambia

Se probó `threads` = 1, 2 y 4 con 1, 4 y 8 clientes simultáneos sin caché: el rendimiento se satura en ~60–68 consultas/s con cualquier valor (los 4 vCPU ya están ocupados) y con 4 hilos un cliente solo obtiene la menor latencia (20 ms frente a 54 ms con 1 hilo). Se mantiene el valor por defecto.

### 6. Pendiente

- El primer cálculo de `/calidad` (~0,6 s) es el endpoint más pesado; está cacheado por versión de datos.
- La generación de entregas con ruido (9,9 s) usa un bucle Python para los registros inválidos; es irrelevante para la carga.

## Tiempo de la batería de pruebas

341 pruebas (unitarias, integración, referencia independiente, API y E2E con Chromium) en ~86 s.
