-- Exportaciones, importaciones, saldo y tasa de cobertura por año.
-- Parámetros: {tabla} (tabla de hechos) y {anios} (lista VALUES del calendario).
-- Un año del calendario sin registros devuelve exportaciones/importaciones/saldo/cobertura
-- en NULL y num_registros = 0 (no es lo mismo que "cero euros").
WITH anios(anio) AS (
    VALUES {anios}
),
agregado AS (
    SELECT
        anio,
        COUNT(*) AS num_registros,
        SUM(CASE WHEN flujo = 'EXPORTACION' THEN importe_eur ELSE 0 END) AS exportaciones,
        SUM(CASE WHEN flujo = 'IMPORTACION' THEN importe_eur ELSE 0 END) AS importaciones
    FROM {tabla}
    GROUP BY anio
)
SELECT
    a.anio,
    COALESCE(g.num_registros, 0) AS num_registros,
    g.exportaciones,
    g.importaciones,
    g.exportaciones - g.importaciones AS saldo,
    -- Cobertura = exportaciones / importaciones * 100. NULLIF evita la división por cero.
    ROUND(100.0 * g.exportaciones / NULLIF(g.importaciones, 0), 2) AS cobertura_pct
FROM anios a
LEFT JOIN agregado g ON g.anio = a.anio
ORDER BY a.anio
