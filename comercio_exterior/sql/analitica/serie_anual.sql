-- Totales por año sobre los meses del periodo filtrado, comparados con los MISMOS meses del año anterior
-- (comparación homogénea aunque el último año esté incompleto).
-- Un año sin datos devuelve meses_con_datos = 0 e importes NULL; el primer año de la serie no tiene previo.
WITH {cte_base},
meses AS (
    SELECT mes_inicio, anio, mes
    FROM {dim_mes}
    WHERE mes_inicio >= DATE '{inicio_ext}' AND mes_inicio <= DATE '{hasta}'
),
mensual AS (
    SELECT mes_inicio,
           SUM(exportaciones_eur) AS exp_eur,
           SUM(importaciones_eur) AS imp_eur,
           SUM(n_op_exportacion + n_op_importacion) AS n_op
    FROM base
    GROUP BY mes_inicio
),
serie AS (
    SELECT m.mes_inicio, m.anio, m.mes, v.exp_eur, v.imp_eur, COALESCE(v.n_op, 0) AS n_op
    FROM meses m
    LEFT JOIN mensual v ON v.mes_inicio = m.mes_inicio
),
pares AS (
    SELECT a.anio, a.exp_eur, a.imp_eur, a.n_op, p.exp_eur AS exp_prev, p.imp_eur AS imp_prev
    FROM serie a
    LEFT JOIN serie p ON p.anio = a.anio - 1 AND p.mes = a.mes
    WHERE a.mes_inicio >= DATE '{desde}' AND a.mes_inicio <= DATE '{hasta}'
),
anual AS (
    SELECT anio,
           COUNT(*) AS meses_en_periodo,
           COUNT(exp_eur) AS meses_con_datos,
           SUM(n_op) AS n_operaciones,
           SUM(exp_eur) AS exportaciones_eur,
           SUM(imp_eur) AS importaciones_eur,
           SUM(exp_prev) AS exportaciones_previo_eur,
           SUM(imp_prev) AS importaciones_previo_eur
    FROM pares
    GROUP BY anio
)
SELECT
    anio,
    meses_en_periodo,
    meses_con_datos,
    n_operaciones,
    exportaciones_eur,
    importaciones_eur,
    exportaciones_eur - importaciones_eur AS saldo_eur,
    ROUND(100.0 * exportaciones_eur / NULLIF(importaciones_eur, 0), 2) AS cobertura_pct,
    exportaciones_previo_eur,
    importaciones_previo_eur,
    ROUND(100.0 * (exportaciones_eur - exportaciones_previo_eur) / NULLIF(exportaciones_previo_eur, 0), 2)
        AS var_exportaciones_pct,
    ROUND(100.0 * (importaciones_eur - importaciones_previo_eur) / NULLIF(importaciones_previo_eur, 0), 2)
        AS var_importaciones_pct,
    ROUND(100.0 * ((exportaciones_eur + importaciones_eur) - (exportaciones_previo_eur + importaciones_previo_eur))
          / NULLIF(exportaciones_previo_eur + importaciones_previo_eur, 0), 2) AS var_comercio_total_pct,
    (exportaciones_eur - importaciones_eur) - (exportaciones_previo_eur - importaciones_previo_eur) AS var_saldo_eur
FROM anual
ORDER BY anio
