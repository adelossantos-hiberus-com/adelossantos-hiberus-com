-- Ranking anual por dimensión (años naturales completos) y cambio de posición respecto al año anterior.
-- cambio_posicion > 0 = sube puestos; NULL si el elemento no estaba en el ranking del año anterior.
WITH {cte_base},
anual AS (
    SELECT
        anio,
        {clave} AS clave,
        {nombre} AS nombre,
        SUM(exportaciones_eur) AS exportaciones_eur,
        SUM(importaciones_eur) AS importaciones_eur
    FROM base
    GROUP BY anio, {clave}, {nombre}
),
con_valor AS (
    SELECT a.*, {valor_expr} AS valor FROM anual a
),
rankeado AS (
    SELECT
        c.*,
        ROW_NUMBER() OVER (PARTITION BY anio ORDER BY valor {sentido} NULLS LAST, clave) AS posicion,
        100.0 * valor / NULLIF(SUM(valor) OVER (PARTITION BY anio), 0) AS cuota_raw
    FROM con_valor c
)
SELECT
    r.anio,
    r.posicion,
    r.clave,
    r.nombre,
    r.exportaciones_eur,
    r.importaciones_eur,
    r.exportaciones_eur - r.importaciones_eur AS saldo_eur,
    ROUND(100.0 * r.exportaciones_eur / NULLIF(r.importaciones_eur, 0), 2) AS cobertura_pct,
    r.valor,
    {cuota_expr} AS cuota_pct,
    p.posicion AS posicion_previa,
    p.posicion - r.posicion AS cambio_posicion
FROM rankeado r
LEFT JOIN rankeado p ON p.clave = r.clave AND p.anio = r.anio - 1
WHERE r.posicion <= {n} AND r.anio >= {anio_desde} AND r.anio <= {anio_hasta}
ORDER BY r.anio, r.posicion
