# API

Documentación interactiva (OpenAPI) en `http://localhost:8000/docs`. Base: `/api/v1`.

## Filtros comunes

| Parámetro | Descripción |
|---|---|
| `desde`, `hasta` | Mes `AAAA-MM` (2018-01 a 2025-12). Por defecto, todo el rango. |
| `pais` | Códigos ISO-2 (`DE`). Repetible (`?pais=DE&pais=FR`) o separados por coma. |
| `producto` | `P001`…`P200` |
| `sector` / `subsector` | `S01`…`S10` / `S01-1`…`S10-4` |

Los filtros se combinan con AND entre tipos y OR dentro de cada tipo.

## Endpoints

| Ruta | Descripción | Parámetros específicos |
|---|---|---|
| `GET /meta` | catálogos, rango de fechas, opciones | |
| `GET /resumen` | indicadores del periodo + comparación con el año anterior | |
| `GET /serie/mensual` | serie mensual, acumulado anual, interanual | |
| `GET /serie/anual` | totales anuales con variación homogénea | |
| `GET /tabla` | métricas, cuotas y ranking por dimensión | `dimension` (`pais`,`producto`,`sector`,`subsector`,`region`), `orden`, `sentido`, `pagina` (≥1), `tamano` (1–500) |
| `GET /top` | Top N + «Resto» | `dimension`, `medida` (`exportaciones`,`importaciones`,`comercio_total`,`saldo`), `n` (1–100), `sentido` |
| `GET /contribucion` | contribución al crecimiento | `dimension`, `medida`, `n` |
| `GET /ranking` | ranking anual y cambio de posición | `dimension`, `medida`, `n`, `sentido` |
| `GET /export/{recurso}.csv` | CSV completo (sin paginar). `recurso`: `tabla`, `serie-mensual`, `serie-anual`, `top`, `contribucion`, `ranking` | los del recurso + `sep` (`,` o `;`), `bom` (`true`/`false`) |
| `GET /calidad` | controles de calidad por capa, conservación, motivos | |
| `GET /calidad/rechazados` | registros rechazados, paginado | `pagina`, `tamano`, `motivo`, `ingesta_id` |
| `GET /ingestas`, `/ingestas/eventos`, `/ingestas/{id}` | seguimiento y detalle de ingestas | |
| `GET /salud` | estado del servicio | |

Las respuestas JSON tienen la forma `{"filtros": {...}, "version_datos": "...", "datos": [...]}`; `/tabla` añade `paginacion` (`pagina`, `tamano`, `total`, `paginas`) y `orden`. Los registros de `datos` son planos y con las mismas columnas (aptos para Power BI). Los importes se devuelven redondeados a 4 decimales.

## Errores

Todos los errores tienen el mismo formato, con mensajes en español:

```json
{"error": {"codigo": "parametro_no_valido",
           "mensaje": "'desde' (2022-05) no puede ser posterior a 'hasta' (2022-01).",
           "detalles": [{"campo": "desde", "mensaje": "…"}]}}
```

`422 parametro_no_valido` (fechas mal formadas o fuera de rango, `desde > hasta`, códigos inexistentes, `tamano` fuera de 1–500, `orden`/`sentido`/`dimension`/`medida` no permitidos…), `404 ingesta_no_encontrada`, `503 sin_datos` (aún no se ha construido el lakehouse) y `500 error_interno` (el detalle solo va al log del servidor).

## Ejemplos (salidas reales sobre el lakehouse de 1 M de operaciones)

```bash
# Indicadores 2024 de Alemania y Francia
curl "http://localhost:8000/api/v1/resumen?desde=2024-01&hasta=2024-12&pais=DE&pais=FR"
# → exportaciones_eur 476284253.96, importaciones_eur 421091345.04, saldo_eur 55192908.92,
#   cobertura_pct 113.11, n_operaciones 25874, var_exportaciones_pct 1.69

# Top 3 sectores por exportaciones + «Resto» (suma = total de exportaciones del periodo)
curl "http://localhost:8000/api/v1/top?dimension=sector&medida=exportaciones&n=3&desde=2024-01&hasta=2024-12"
# → S06 Textil y moda 556 M (23,48 %), S05 Maquinaria 363 M, S01 Agroalimentario 331 M, RESTO 1.118 M (47,23 %)

# Tabla paginada y ordenada en servidor: los 2 países con mayor déficit
curl "http://localhost:8000/api/v1/tabla?dimension=pais&orden=saldo_eur&sentido=asc&pagina=1&tamano=2"
# → paginacion {pagina:1, tamano:2, total:50, paginas:25}; CN −676,3 M €, NL −161,0 M €

# Contribución al crecimiento 2025 (suma de contribuciones = crecimiento total 5,09 %)
curl "http://localhost:8000/api/v1/contribucion?dimension=pais&n=3&desde=2025-01&hasta=2025-12"

# CSV (UTF-8 con BOM para Excel; separador ; con &sep=%3B)
curl -o top.csv "http://localhost:8000/api/v1/export/top.csv?dimension=pais&n=10"
```
