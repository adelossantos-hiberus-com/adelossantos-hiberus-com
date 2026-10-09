-- ============================================================================
-- Consulta generada para Databricks SQL / Spark SQL (NO editar a mano).
-- Origen: sql/analitica/ranking.sql · regenerar con: python -m comercio_exterior.cli exportar-sql
-- Tablas esperadas en main.comercio_exterior: hechos_mensual, dim_pais, dim_producto, dim_mes (ver docs/databricks.md).
-- Escenario por defecto: ranking anual de los 10 principales países
-- Para filtrar: edite las fechas DATE '…' y active/ajuste las líneas «-- AND … IN (…)» del CTE base.
-- ============================================================================
-- Ranking anual por dimensión (años naturales completos) y cambio de posición respecto al año anterior.
-- cambio_posicion > 0 = sube puestos; NULL si el elemento no estaba en el ranking del año anterior.
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
    WHERE h.mes_inicio >= DATE '2017-01-01' AND h.mes_inicio <= DATE '2025-12-31'
          -- AND h.pais_codigo IN ('FR', 'DE')  -- filtro país (inactivo)
          -- AND h.producto_codigo IN ('P001', 'P002')  -- filtro producto (inactivo)
          -- AND p.sector_codigo IN ('S01', 'S02')  -- filtro sector (inactivo)
          -- AND p.subsector_codigo IN ('S01-1', 'S01-2')  -- filtro subsector (inactivo)
),
anual AS (
    SELECT
        anio,
        pais_codigo AS clave,
        pais AS nombre,
        SUM(exportaciones_eur) AS exportaciones_eur,
        SUM(importaciones_eur) AS importaciones_eur
    FROM base
    GROUP BY anio, pais_codigo, pais
),
con_valor AS (
    SELECT a.*, a.exportaciones_eur + a.importaciones_eur AS valor FROM anual a
),
rankeado AS (
    SELECT
        c.*,
        ROW_NUMBER() OVER (PARTITION BY anio ORDER BY valor DESC NULLS LAST, clave) AS posicion,
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
    ROUND(r.cuota_raw, 2) AS cuota_pct,
    p.posicion AS posicion_previa,
    p.posicion - r.posicion AS cambio_posicion
FROM rankeado r
LEFT JOIN rankeado p ON p.clave = r.clave AND p.anio = r.anio - 1
WHERE r.posicion <= 10 AND r.anio >= 2018 AND r.anio <= 2025
ORDER BY r.anio, r.posicion
