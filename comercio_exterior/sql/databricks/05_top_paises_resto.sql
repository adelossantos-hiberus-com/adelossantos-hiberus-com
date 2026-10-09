-- ============================================================================
-- Consulta generada para Databricks SQL / Spark SQL (NO editar a mano).
-- Origen: sql/analitica/top.sql · regenerar con: python -m comercio_exterior.cli exportar-sql
-- Tablas esperadas en main.comercio_exterior: hechos_mensual, dim_pais, dim_producto, dim_mes (ver docs/databricks.md).
-- Escenario por defecto: Top 10 países por comercio total + «Resto»
-- Para filtrar: edite las fechas DATE '…' y active/ajuste las líneas «-- AND … IN (…)» del CTE base.
-- ============================================================================
-- Top N por una medida más una fila "Resto" con el agregado del resto de elementos.
-- Top N + Resto suma exactamente el total del periodo. La cuota no se define para el saldo (puede ser negativo).
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
    WHERE ((h.mes_inicio >= DATE '2018-01-01' AND h.mes_inicio <= DATE '2025-12-01')
          OR (h.mes_inicio >= DATE '2017-01-01' AND h.mes_inicio <= DATE '2024-12-01'))
          -- AND h.pais_codigo IN ('FR', 'DE')  -- filtro país (inactivo)
          -- AND h.producto_codigo IN ('P001', 'P002')  -- filtro producto (inactivo)
          -- AND p.sector_codigo IN ('S01', 'S02')  -- filtro sector (inactivo)
          -- AND p.subsector_codigo IN ('S01-1', 'S01-2')  -- filtro subsector (inactivo)
),
agg AS (
    SELECT
        pais_codigo AS clave,
        pais AS nombre,
        SUM(exportaciones_eur) AS exportaciones_eur,
        SUM(importaciones_eur) AS importaciones_eur,
        SUM(n_op_exportacion + n_op_importacion) AS n_operaciones
    FROM base
    WHERE en_a = 1
    GROUP BY pais_codigo, pais
),
medida AS (
    SELECT a.*, a.exportaciones_eur + a.importaciones_eur AS valor FROM agg a
),
tot AS (
    SELECT SUM(valor) AS total_valor FROM medida
),
ranked AS (
    SELECT m.*, ROW_NUMBER() OVER (ORDER BY m.valor DESC NULLS LAST, m.clave) AS posicion
    FROM medida m
),
resto AS (
    SELECT COUNT(*) AS n_elementos,
           SUM(exportaciones_eur) AS exportaciones_eur,
           SUM(importaciones_eur) AS importaciones_eur,
           SUM(n_operaciones) AS n_operaciones,
           SUM(valor) AS valor
    FROM ranked
    WHERE posicion > 10
),
salida AS (
    SELECT posicion, clave, nombre, exportaciones_eur, importaciones_eur, n_operaciones, valor, 0 AS es_resto
    FROM ranked
    WHERE posicion <= 10
    UNION ALL
    SELECT 10 + 1, 'RESTO', 'Resto', exportaciones_eur, importaciones_eur, n_operaciones, valor, 1
    FROM resto
    WHERE n_elementos > 0
)
SELECT
    s.posicion,
    s.clave,
    s.nombre,
    s.exportaciones_eur,
    s.importaciones_eur,
    s.exportaciones_eur - s.importaciones_eur AS saldo_eur,
    s.exportaciones_eur + s.importaciones_eur AS comercio_total_eur,
    ROUND(100.0 * s.exportaciones_eur / NULLIF(s.importaciones_eur, 0), 2) AS cobertura_pct,
    s.valor,
    ROUND(100.0 * s.valor / NULLIF(t.total_valor, 0), 2) AS cuota_pct,
    s.n_operaciones,
    s.es_resto
FROM salida s
CROSS JOIN tot t
ORDER BY s.es_resto, s.posicion
