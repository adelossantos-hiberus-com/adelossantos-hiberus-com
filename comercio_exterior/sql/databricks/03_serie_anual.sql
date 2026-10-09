-- ============================================================================
-- Consulta generada para Databricks SQL / Spark SQL (NO editar a mano).
-- Origen: sql/analitica/serie_anual.sql · regenerar con: python -m comercio_exterior.cli exportar-sql
-- Tablas esperadas en main.comercio_exterior: hechos_mensual, dim_pais, dim_producto, dim_mes (ver docs/databricks.md).
-- Escenario por defecto: 2018-01 a 2025-12, sin filtros
-- Para filtrar: edite las fechas DATE '…' y active/ajuste las líneas «-- AND … IN (…)» del CTE base.
-- ============================================================================
-- Totales por año sobre los meses del periodo filtrado, comparados con los MISMOS meses del año anterior
-- (comparación homogénea aunque el último año esté incompleto).
-- Un año sin datos devuelve meses_con_datos = 0 e importes NULL; el primer año de la serie no tiene previo.
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
pares AS (
    SELECT a.anio, a.exp_eur, a.imp_eur, a.n_op, p.exp_eur AS exp_prev, p.imp_eur AS imp_prev
    FROM serie a
    LEFT JOIN serie p ON p.anio = a.anio - 1 AND p.mes = a.mes
    WHERE a.mes_inicio >= DATE '2018-01-01' AND a.mes_inicio <= DATE '2025-12-01'
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
