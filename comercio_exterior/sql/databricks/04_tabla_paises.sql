-- ============================================================================
-- Consulta generada para Databricks SQL / Spark SQL (NO editar a mano).
-- Origen: sql/analitica/tabla.sql · regenerar con: python -m comercio_exterior.cli exportar-sql
-- Tablas esperadas en main.comercio_exterior: hechos_mensual, dim_pais, dim_producto, dim_mes (ver docs/databricks.md).
-- Escenario por defecto: tabla por país ordenada por comercio total (página 1, 25 filas)
-- Para filtrar: edite las fechas DATE '…' y active/ajuste las líneas «-- AND … IN (…)» del CTE base.
-- ============================================================================
-- Métricas por dimensión (país, producto, sector, subsector o región) con cuotas, ranking y variación.
-- Solo aparecen elementos con operaciones en el periodo. Orden y paginación se resuelven en el servidor.
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
        SUM(CASE WHEN en_a = 1 THEN exportaciones_eur ELSE 0 END) AS exportaciones_eur,
        SUM(CASE WHEN en_a = 1 THEN importaciones_eur ELSE 0 END) AS importaciones_eur,
        SUM(CASE WHEN en_a = 1 THEN peso_exportado_kg + peso_importado_kg ELSE 0 END) AS peso_kg,
        SUM(CASE WHEN en_a = 1 THEN unidades_exportadas + unidades_importadas ELSE 0 END) AS unidades,
        SUM(CASE WHEN en_a = 1 THEN n_op_exportacion + n_op_importacion ELSE 0 END) AS n_operaciones,
        SUM(CASE WHEN en_p = 1 THEN exportaciones_eur ELSE 0 END) AS exportaciones_previo_eur,
        SUM(CASE WHEN en_p = 1 THEN importaciones_eur ELSE 0 END) AS importaciones_previo_eur
    FROM base
    GROUP BY pais_codigo, pais
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
ORDER BY comercio_total_eur DESC NULLS LAST, clave
LIMIT 25 OFFSET 0
