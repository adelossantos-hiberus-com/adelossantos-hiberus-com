-- ============================================================================
-- Consulta generada para Databricks SQL / Spark SQL (NO editar a mano).
-- Origen: sql/analitica/serie_mensual.sql · regenerar con: python -m comercio_exterior.cli exportar-sql
-- Tablas esperadas en main.comercio_exterior: hechos_mensual, dim_pais, dim_producto, dim_mes (ver docs/databricks.md).
-- Escenario por defecto: 2018-01 a 2025-12, sin filtros
-- Para filtrar: edite las fechas DATE '…' y active/ajuste las líneas «-- AND … IN (…)» del CTE base.
-- ============================================================================
-- Serie mensual con acumulado del año natural (YTD) y comparación con el mismo mes del año anterior.
-- El calendario sale de dim_mes: un mes sin operaciones aparece con n_operaciones = 0 e importes NULL.
-- En los acumulados un mes sin datos suma 0. Las variaciones son NULL si el valor previo falta o es 0.
WITH base AS (
    SELECT h.mes_inicio, h.anio, h.mes, h.pais_codigo, c.pais, c.region,
           h.producto_codigo, p.producto, p.subsector_codigo, p.subsector, p.sector_codigo, p.sector,
           h.exportaciones_eur, h.importaciones_eur, h.peso_exportado_kg, h.peso_importado_kg,
           h.unidades_exportadas, h.unidades_importadas, h.n_op_exportacion, h.n_op_importacion,
           -- una fila puede pertenecer a la vez al periodo actual y al previo (rangos de más de 12 meses)
           CASE WHEN h.mes_inicio >= DATE '2018-01-01' AND h.mes_inicio <= DATE '2025-12-01' THEN 1 ELSE 0 END AS en_a,
           CASE WHEN h.mes_inicio >= DATE '2017-01-01' AND h.mes_inicio <= DATE '2024-12-01' THEN 1 ELSE 0 END AS en_p
    FROM main.comercio_exterior.hechos_mensual h
    JOIN main.comercio_exterior.dim_pais c ON c.pais_codigo = h.pais_codigo
    JOIN main.comercio_exterior.dim_producto p ON p.producto_codigo = h.producto_codigo
    WHERE h.mes_inicio >= DATE '2017-01-01' AND h.mes_inicio <= DATE '2025-12-01'
          -- AND h.pais_codigo IN ('FR', 'DE')  -- filtro país (inactivo)
          -- AND h.producto_codigo IN ('P001', 'P002')  -- filtro producto (inactivo)
          -- AND p.sector_codigo IN ('S01', 'S02')  -- filtro sector (inactivo)
          -- AND p.subsector_codigo IN ('S01-1', 'S01-2')  -- filtro subsector (inactivo)
),
meses AS (
    SELECT mes_inicio, anio, mes
    FROM main.comercio_exterior.dim_mes
    WHERE mes_inicio >= DATE '2017-01-01' AND mes_inicio <= DATE '2025-12-01'
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
acum AS (
    SELECT s.*,
           SUM(COALESCE(exp_eur, 0)) OVER (PARTITION BY anio ORDER BY mes
                                           ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS exp_acum,
           SUM(COALESCE(imp_eur, 0)) OVER (PARTITION BY anio ORDER BY mes
                                           ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS imp_acum
    FROM serie s
)
SELECT
    a.mes_inicio,
    a.anio,
    a.mes,
    a.n_op AS n_operaciones,
    a.exp_eur AS exportaciones_eur,
    a.imp_eur AS importaciones_eur,
    a.exp_eur - a.imp_eur AS saldo_eur,
    ROUND(100.0 * a.exp_eur / NULLIF(a.imp_eur, 0), 2) AS cobertura_pct,
    a.exp_acum AS exportaciones_acum_eur,
    a.imp_acum AS importaciones_acum_eur,
    a.exp_acum - a.imp_acum AS saldo_acum_eur,
    ROUND(100.0 * a.exp_acum / NULLIF(a.imp_acum, 0), 2) AS cobertura_acum_pct,
    p.exp_eur AS exportaciones_previo_eur,
    p.imp_eur AS importaciones_previo_eur,
    ROUND(100.0 * (a.exp_eur - p.exp_eur) / NULLIF(p.exp_eur, 0), 2) AS var_exportaciones_pct,
    ROUND(100.0 * (a.imp_eur - p.imp_eur) / NULLIF(p.imp_eur, 0), 2) AS var_importaciones_pct,
    (a.exp_eur - a.imp_eur) - (p.exp_eur - p.imp_eur) AS var_saldo_eur,
    ROUND(100.0 * (a.exp_acum - p.exp_acum) / NULLIF(p.exp_acum, 0), 2) AS var_exportaciones_acum_pct,
    ROUND(100.0 * (a.imp_acum - p.imp_acum) / NULLIF(p.imp_acum, 0), 2) AS var_importaciones_acum_pct
FROM acum a
LEFT JOIN acum p ON p.anio = a.anio - 1 AND p.mes = a.mes
WHERE a.mes_inicio >= DATE '2018-01-01' AND a.mes_inicio <= DATE '2025-12-01'
ORDER BY a.mes_inicio
