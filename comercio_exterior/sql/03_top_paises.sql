-- Ranking de países por año según comercio total (exportaciones + importaciones).
-- Parámetros: {tabla} y {top_n} (10 por defecto en el código Python).
-- Desempate por nombre de país para que el resultado sea determinista.
WITH por_pais AS (
    SELECT
        anio,
        pais,
        SUM(CASE WHEN flujo = 'EXPORTACION' THEN importe_eur ELSE 0 END) AS exportaciones,
        SUM(CASE WHEN flujo = 'IMPORTACION' THEN importe_eur ELSE 0 END) AS importaciones
    FROM {tabla}
    GROUP BY anio, pais
),
con_ranking AS (
    SELECT
        anio,
        pais,
        exportaciones,
        importaciones,
        exportaciones + importaciones AS comercio_total,
        exportaciones - importaciones AS saldo,
        ROUND(100.0 * exportaciones / NULLIF(importaciones, 0), 2) AS cobertura_pct,
        ROUND(100.0 * (exportaciones + importaciones)
              / NULLIF(SUM(exportaciones + importaciones) OVER (PARTITION BY anio), 0), 2)
            AS cuota_pct,
        ROW_NUMBER() OVER (
            PARTITION BY anio
            ORDER BY exportaciones + importaciones DESC, pais
        ) AS ranking
    FROM por_pais
)
SELECT anio, ranking, pais, exportaciones, importaciones, comercio_total, saldo,
       cobertura_pct, cuota_pct
FROM con_ranking
WHERE ranking <= {top_n}
ORDER BY anio, ranking
