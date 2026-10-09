# Arquitectura

Todo el proyecto usa **datos ficticios generados por código**; no hay servicios externos ni credenciales.

```
                    ┌──────────────┐   entregas trimestrales (con ruido)
 simulacion.py ───▶ │  Entrega     │───────────────────────────────────────────┐
 (1 M operaciones)  └──────────────┘                                           ▼
                                                                    ┌────────────────────┐
                                                                    │ Lakehouse.ingestar │  bloqueo + registro
                                                                    └─────────┬──────────┘  de ingestas
                         ┌────────────────────────────────────────────────────┼───────────────────────────┐
                         ▼                                                    ▼                           ▼
                 BRONZE (Parquet)                                   SILVER (Parquet)               GOLD (Parquet)
         entrega tal cual + linaje                       versión vigente de cada operación      hechos mensuales país×producto
         ingesta_id=ING-0001/part-0.parquet               periodo=2019Q3/part.parquet            periodo=2019Q3/part.parquet
                                                       rechazados/ y descartes/ (con motivo)     dim_pais, dim_producto, dim_mes
                                                                                                            │
                                                          ┌─────────────────────────────────────────────────┤
                                                          ▼                                                 ▼
                                                 Motor (DuckDB + plantillas SQL)                     sql/databricks/*.sql
                                                          │                                          (mismas consultas, Spark SQL)
                                                          ▼
                                                  API FastAPI  ──▶  Interfaz web · CSV · Power BI (propuesto)
```

## Capas

| Capa | Contenido | Escritura |
|---|---|---|
| **bronze** | Cada entrega exactamente como llega (incluidos registros inválidos y duplicados) más el linaje: `ingesta_id`, `ingesta_seq`, `ingesta_ts`, `fichero_origen`, `fila_origen`. | Inmutable. Una carpeta por ingesta, escrita en un directorio temporal y renombrada al terminar (aparece completa o no aparece). |
| **silver** | Una fila por operación con su **versión vigente**, tipada y validada, particionada por trimestre (`periodo=2019Q3`). Además `rechazados/` y `descartes/`. | Incremental: solo se reescriben los periodos que reciben una fila ganadora. |
| **gold** | Hechos mensuales por país y producto (exportaciones e importaciones en columnas) y dimensiones. | Incremental: se regeneran únicamente los periodos cuyo silver cambió. |
| **control** | `ingestas.parquet` (una fila por ingesta), `eventos.parquet` (bitácora), `config.json`. | Escritura atómica (fichero temporal + `os.replace`). |

## Ingesta (`Lakehouse.ingestar`)

1. **Bloqueo** (`control/.lock`): un único proceso de ingesta a la vez.
2. **Identificación**: huella SHA-256 del contenido. Si el `ingesta_id` ya está `COMPLETADA`, o el mismo contenido llegó con otro identificador, la ingesta se **omite** y se anota un evento `OMITIDA`. Por eso volver a ejecutar una carga no duplica nada.
3. **bronze → silver → gold** con indicadores `bronze_ok`, `silver_ok`, `gold_ok` en el registro. Si algo falla, la ingesta queda `FALLIDA` con el error, y un reintento **reanuda desde el último paso correcto** (evento `REANUDADA`). Reanudar con un contenido distinto del original se rechaza.
4. El registro guarda por ingesta: filas recibidas, válidas, rechazadas, duplicados exactos, versiones antiguas, conflictos, operaciones nuevas, correcciones aplicadas, periodos afectados y la duración de cada capa.

## Tratamiento de registros (silver)

**Validación** (primera regla que falla → motivo): `ID_INVALIDO`, `FECHA_INVALIDA` (formato AAAA-MM-DD estricto y fecha real), `FECHA_FUERA_DE_RANGO` (2018–2025), `FLUJO_INVALIDO`, `PAIS_DESCONOCIDO`, `PRODUCTO_DESCONOCIDO`, `IMPORTE_NULO`, `IMPORTE_NEGATIVO`, `PESO_INVALIDO`, `UNIDADES_INVALIDAS`, `VERSION_INVALIDA`. Los inválidos van a `silver/rechazados` con su motivo y su linaje; una corrección inválida no sustituye al original.

**Duplicados y versiones** (sobre las filas válidas, para las operaciones que traen filas nuevas):

1. *Duplicado exacto* (misma operación, versión y contenido): se conserva la primera aparición; el resto → descarte `DUPLICADO_EXACTO`.
2. *Versión vigente*: gana la versión más alta; a igualdad de versión, la última entrega.
3. Las filas que pierden se registran en `silver/descartes` con `VERSION_ANTIGUA` (versión menor que la ganadora, tanto si llega tarde como si era la vigente y la sustituye una corrección) o `CONFLICTO_MISMA_VERSION` (misma versión, contenido distinto), el `ingesta_id` que las trajo, la ingesta y versión ganadoras y la ingesta que provocó el descarte.

**Invariante de conservación**: `filas bronze = silver + rechazados + descartes`, y cada fila de bronze aparece en exactamente uno de los tres sitios (clave `ingesta_id` + `fila_origen`). La pantalla de calidad lo comprueba.

**Trazabilidad**: cada fila de silver conserva `ingesta_id` (ingesta de la versión vigente), `ingesta_id_primera` (primera vez que se vio la operación), `fila_origen` y `hash_contenido`.

## Decisiones de diseño y límites

- **Partición por trimestre** (opción `--particion anio`): equilibra el tamaño de cada reescritura y el número de ficheros. Una corrección en un periodo antiguo obliga a reescribir ese trimestre completo (*copy-on-write*); es el principal coste de la carga (ver `docs/rendimiento.md`).
- **Un solo escritor**: el bloqueo es un fichero; no está pensado para varios procesos de ingesta concurrentes ni para sistemas de ficheros sin `O_EXCL` fiable.
- **Importes en `DOUBLE`** redondeados a 2 decimales. Las comprobaciones usan una tolerancia de 0,01 € por redondeo de coma flotante; en un sistema real se usaría `DECIMAL`.
- **Granularidad mensual en gold**: los filtros de fecha de la API son por mes (`AAAA-MM`), no por día.
- **El estado es reproducible desde bronze**: `Lakehouse.reconstruir_silver_y_gold()` borra silver y gold y los regenera procesando las ingestas en orden; una prueba comprueba que el resultado es idéntico.
