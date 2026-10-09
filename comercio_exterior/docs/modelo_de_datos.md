# Modelo de datos

## Catálogos (ficticios)

- **50 países** (`pais_codigo` ISO-2, `pais`, `region`).
- **Jerarquía de dos niveles**: 10 **sectores** (`S01`…`S10`) → 40 **subsectores** (`S01-1`…`S10-4`) → 200 **productos** (`P001`…`P200`, 5 por subsector).
- Los pesos relativos, precios unitarios y pesos por unidad se derivan de una semilla propia del catálogo (2018), así que son idénticos sea cual sea la semilla de las operaciones.

## Operación (bronze, tal como llega)

| Columna | Tipo | Descripción |
|---|---|---|
| `operacion_id` | texto | `OP-00000001`… (los registros basura usan `OP-9xxxxxxx`) |
| `version` | entero | 1 = original; 2, 3… = correcciones |
| `tipo_registro` | texto | `ORIGINAL` o `CORRECCION` |
| `fecha` | texto | `AAAA-MM-DD` (texto para poder alojar fechas inválidas) |
| `flujo` | texto | `EXPORTACION` / `IMPORTACION` |
| `pais_codigo`, `producto_codigo` | texto | claves de los catálogos |
| `importe_eur`, `peso_kg` | decimal | importe en euros y peso en kg |
| `unidades` | entero (nulable) | unidades |
| `ingesta_id`, `ingesta_seq`, `ingesta_ts`, `fichero_origen`, `fila_origen` | | linaje |

## Silver

`silver/operaciones` (columnas tipadas: `fecha` DATE, `unidades` BIGINT) más `ingesta_id_primera`, `hash_contenido`, `periodo`.
`silver/rechazados`: columnas de bronze + `motivo`. `silver/descartes`: `operacion_id`, `version`, `ingesta_id`, `fila_origen`, `motivo`, `ingesta_id_ganadora`, `version_ganadora`, `ingesta_id_proceso`, `origen_descartado` (`NUEVO`/`SILVER`), `fecha`, `importe_eur`.

## Gold (esquema estrella)

**`hechos_mensual`** — grano: mes × país × producto (≈ 413 000 filas con 1 M de operaciones).

| Columna | Descripción |
|---|---|
| `mes_inicio` (DATE), `anio`, `mes` | primer día del mes |
| `pais_codigo`, `producto_codigo` | claves |
| `exportaciones_eur`, `importaciones_eur` | importes (0 si no hubo ese flujo) |
| `peso_exportado_kg`, `peso_importado_kg` | pesos |
| `unidades_exportadas`, `unidades_importadas` | unidades |
| `n_op_exportacion`, `n_op_importacion` | número de operaciones |

**`dim_pais`** (`pais_codigo`, `pais`, `region`) · **`dim_producto`** (`producto_codigo`, `producto`, `subsector_codigo`, `subsector`, `sector_codigo`, `sector`) · **`dim_mes`** (`mes_inicio`, `anio`, `mes`, `trimestre`; calendario completo 2018-01…2025-12, que permite mostrar meses y años sin datos).

## Control

`ingestas`: `ingesta_seq`, `ingesta_id`, `fuente`, `fichero_origen`, `periodo`, `hash_contenido`, `estado` (`EN_CURSO`/`COMPLETADA`/`FALLIDA`), `bronze_ok`, `silver_ok`, `gold_ok`, `ts_inicio`, `ts_fin`, contadores y duraciones por capa, `error`. `eventos`: `ts`, `ingesta_id`, `evento` (`INICIO`, `COMPLETADA`, `FALLIDA`, `REANUDADA`, `OMITIDA`), `detalle`.
