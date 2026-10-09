-- Variación interanual (%) de exportaciones, importaciones y comercio total,
-- y variación absoluta del saldo (el saldo puede ser negativo o cero, así que
-- un porcentaje sobre él sería engañoso).
-- La variación es NULL si falta el año previo (p. ej. el primero del calendario),
-- si el año previo no tiene datos o si su valor es 0.
WITH anios(anio) AS (
    VALUES {anios}
),
agregado AS (
    SELECT
        anio,
        SUM(CASE WHEN flujo = 'EXPORTACION' THEN importe_eur ELSE 0 END) AS exportaciones,
        SUM(CASE WHEN flujo = 'IMPORTACION' THEN importe_eur ELSE 0 END) AS importaciones
    FROM {tabla}
    GROUP BY anio
),
anual AS (
    SELECT
        a.anio,
        g.exportaciones,
        g.importaciones,
        g.exportaciones + g.importaciones AS comercio_total,
        g.exportaciones - g.importaciones AS saldo
    FROM anios a
    LEFT JOIN agregado g ON g.anio = a.anio
)
SELECT
    c.anio,
    c.exportaciones,
    p.exportaciones AS exportaciones_previo,
    ROUND(100.0 * (c.exportaciones - p.exportaciones) / NULLIF(p.exportaciones, 0), 2)
        AS var_exportaciones_pct,
    c.importaciones,
    p.importaciones AS importaciones_previo,
    ROUND(100.0 * (c.importaciones - p.importaciones) / NULLIF(p.importaciones, 0), 2)
        AS var_importaciones_pct,
    c.comercio_total,
    ROUND(100.0 * (c.comercio_total - p.comercio_total) / NULLIF(p.comercio_total, 0), 2)
        AS var_comercio_total_pct,
    c.saldo,
    c.saldo - p.saldo AS var_saldo_abs
FROM anual c
LEFT JOIN anual p ON p.anio = c.anio - 1
ORDER BY c.anio
