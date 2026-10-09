-- ============================================================================
-- Consulta generada para Databricks SQL / Spark SQL (NO editar a mano).
-- Origen: sql/analitica/resumen.sql · regenerar con: python -m comercio_exterior.cli exportar-sql
-- Tablas esperadas en main.comercio_exterior: hechos_mensual, dim_pais, dim_producto, dim_mes (ver docs/databricks.md).
-- Escenario por defecto: todo el periodo 2018-01 a 2025-12, sin filtros de dimensión
-- Para filtrar: edite las fechas DATE '…' y active/ajuste las líneas «-- AND … IN (…)» del CTE base.
-- ============================================================================
-- Indicadores del periodo filtrado y comparación con el mismo periodo del año anterior.
-- Sin datos en el periodo: importes NULL y n_operaciones = 0 (no es lo mismo que "0 euros").
WITH base AS (
    SELECT h.mes_inicio, h.anio, h.mes, h.pais_codigo, h.producto_codigo,
           c.pais, c.region,
           p.producto, p.subsector_codigo, p.subsector, p.sector_codigo, p.sector,
           h.exportaciones_eur, h.importaciones_eur, h.peso_exportado_kg, h.peso_importado_kg,
           h.unidades_exportadas, h.unidades_importadas, h.n_op_exportacion, h.n_op_importacion,
           -- una fila puede pertenecer a la vez al periodo actual y al previo (rangos de más de 12 meses)
           CASE WHEN h.mes_inicio >= DATE '2018-01-01' AND h.mes_inicio <= DATE '2025-12-01' THEN 1 ELSE 0 END AS en_a,
           CASE WHEN h.mes_inicio >= DATE '2017-01-01' AND h.mes_inicio <= DATE '2024-12-01' THEN 1 ELSE 0 END AS en_p
    FROM main.comercio_exterior.hechos_mensual h
    JOIN main.comercio_exterior.dim_pais c ON c.pais_codigo = h.pais_codigo
    JOIN main.comercio_exterior.dim_producto p ON p.producto_codigo = h.producto_codigo
    WHERE ((h.mes_inicio >= DATE '2018-01-01' AND h.mes_inicio <= DATE '2025-12-01')
          OR (h.mes_inicio >= DATE '2017-01-01' AND h.mes_inicio <= DATE '2024-12-01'))
          -- AND h.pais_codigo IN ('FR', 'DE')  -- filtro país (inactivo)
          -- AND h.producto_codigo IN ('P001', 'P002')  -- filtro producto (inactivo)
          -- AND p.sector_codigo IN ('S01', 'S02')  -- filtro sector (inactivo)
          -- AND p.subsector_codigo IN ('S01-1', 'S01-2')  -- filtro subsector (inactivo)
),
agg AS (
    SELECT
        SUM(CASE WHEN en_a = 1 THEN exportaciones_eur END) AS exportaciones_eur,
        SUM(CASE WHEN en_a = 1 THEN importaciones_eur END) AS importaciones_eur,
        SUM(CASE WHEN en_a = 1 THEN peso_exportado_kg + peso_importado_kg END) AS peso_kg,
        SUM(CASE WHEN en_a = 1 THEN unidades_exportadas + unidades_importadas END) AS unidades,
        COALESCE(SUM(CASE WHEN en_a = 1 THEN n_op_exportacion + n_op_importacion END), 0) AS n_operaciones,
        SUM(CASE WHEN en_p = 1 THEN exportaciones_eur END) AS exportaciones_previo_eur,
        SUM(CASE WHEN en_p = 1 THEN importaciones_eur END) AS importaciones_previo_eur
    FROM base
)
SELECT
    exportaciones_eur,
    importaciones_eur,
    exportaciones_eur - importaciones_eur AS saldo_eur,
    exportaciones_eur + importaciones_eur AS comercio_total_eur,
    -- cobertura = exportaciones / importaciones * 100; NULLIF evita la división por cero
    ROUND(100.0 * exportaciones_eur / NULLIF(importaciones_eur, 0), 2) AS cobertura_pct,
    peso_kg,
    unidades,
    n_operaciones,
    exportaciones_previo_eur,
    importaciones_previo_eur,
    exportaciones_previo_eur - importaciones_previo_eur AS saldo_previo_eur,
    ROUND(100.0 * (exportaciones_eur - exportaciones_previo_eur) / NULLIF(exportaciones_previo_eur, 0), 2)
        AS var_exportaciones_pct,
    ROUND(100.0 * (importaciones_eur - importaciones_previo_eur) / NULLIF(importaciones_previo_eur, 0), 2)
        AS var_importaciones_pct,
    ROUND(100.0 * ((exportaciones_eur + importaciones_eur) - (exportaciones_previo_eur + importaciones_previo_eur))
          / NULLIF(exportaciones_previo_eur + importaciones_previo_eur, 0), 2) AS var_comercio_total_pct,
    -- el saldo puede ser negativo o cero: su variación se expresa en euros, no en porcentaje
    (exportaciones_eur - importaciones_eur) - (exportaciones_previo_eur - importaciones_previo_eur) AS var_saldo_eur
FROM agg
