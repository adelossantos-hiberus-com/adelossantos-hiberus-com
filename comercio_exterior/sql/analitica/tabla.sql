-- Métricas por dimensión (país, producto, sector, subsector o región) con cuotas, ranking y variación.
-- Solo aparecen elementos con operaciones en el periodo. Orden y paginación se resuelven en el servidor.
WITH {cte_base},
agg AS (
    SELECT
        {clave} AS clave,
        {nombre} AS nombre,
        SUM(CASE WHEN en_a = 1 THEN exportaciones_eur ELSE 0 END) AS exportaciones_eur,
        SUM(CASE WHEN en_a = 1 THEN importaciones_eur ELSE 0 END) AS importaciones_eur,
        SUM(CASE WHEN en_a = 1 THEN peso_exportado_kg + peso_importado_kg ELSE 0 END) AS peso_kg,
        SUM(CASE WHEN en_a = 1 THEN unidades_exportadas + unidades_importadas ELSE 0 END) AS unidades,
        SUM(CASE WHEN en_a = 1 THEN n_op_exportacion + n_op_importacion ELSE 0 END) AS n_operaciones,
        SUM(CASE WHEN en_p = 1 THEN exportaciones_eur ELSE 0 END) AS exportaciones_previo_eur,
        SUM(CASE WHEN en_p = 1 THEN importaciones_eur ELSE 0 END) AS importaciones_previo_eur
    FROM base
    GROUP BY {clave}, {nombre}
),
act AS (
    SELECT * FROM agg WHERE n_operaciones > 0
),
tot AS (
    SELECT SUM(exportaciones_eur) AS t_exp, SUM(importaciones_eur) AS t_imp FROM act
),
calc AS (
    SELECT
        a.clave,
        a.nombre,
        a.exportaciones_eur,
        a.importaciones_eur,
        a.exportaciones_eur - a.importaciones_eur AS saldo_eur,
        a.exportaciones_eur + a.importaciones_eur AS comercio_total_eur,
        ROUND(100.0 * a.exportaciones_eur / NULLIF(a.importaciones_eur, 0), 2) AS cobertura_pct,
        ROUND(100.0 * a.exportaciones_eur / NULLIF(t.t_exp, 0), 2) AS cuota_exportaciones_pct,
        ROUND(100.0 * a.importaciones_eur / NULLIF(t.t_imp, 0), 2) AS cuota_importaciones_pct,
        ROUND(100.0 * (a.exportaciones_eur + a.importaciones_eur) / NULLIF(t.t_exp + t.t_imp, 0), 2)
            AS cuota_comercio_pct,
        ROUND(100.0 * (a.exportaciones_eur - a.exportaciones_previo_eur) / NULLIF(a.exportaciones_previo_eur, 0), 2)
            AS var_exportaciones_pct,
        ROUND(100.0 * (a.importaciones_eur - a.importaciones_previo_eur) / NULLIF(a.importaciones_previo_eur, 0), 2)
            AS var_importaciones_pct,
        a.peso_kg,
        a.unidades,
        a.n_operaciones,
        RANK() OVER (ORDER BY a.exportaciones_eur + a.importaciones_eur DESC) AS ranking
    FROM act a
    CROSS JOIN tot t
)
SELECT calc.*, COUNT(*) OVER () AS total_filas
FROM calc
ORDER BY {orden} {sentido} NULLS LAST, clave
LIMIT {limite} OFFSET {desplazamiento}
