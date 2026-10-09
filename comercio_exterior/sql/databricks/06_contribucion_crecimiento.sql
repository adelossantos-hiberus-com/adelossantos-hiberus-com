-- ============================================================================
-- Consulta generada para Databricks SQL / Spark SQL (NO editar a mano).
-- Origen: sql/analitica/contribucion.sql · regenerar con: python -m comercio_exterior.cli exportar-sql
-- Tablas esperadas en main.comercio_exterior: hechos_mensual, dim_pais, dim_producto, dim_mes (ver docs/databricks.md).
-- Escenario por defecto: contribución de los 10 mayores países al crecimiento del comercio total en 2025 (vs 2024)
-- Para filtrar: edite las fechas DATE '…' y active/ajuste las líneas «-- AND … IN (…)» del CTE base.
-- ============================================================================
-- Contribución al crecimiento: cuánto aporta cada elemento (en puntos porcentuales) a la variación
-- interanual del total, comparando el periodo con el mismo periodo del año anterior.
--   contribucion_pp = (valor_actual - valor_previo) / |total_previo| * 100
-- La suma de contribuciones (Top N + Resto) iguala el crecimiento total. Con |total_previo| el cálculo
-- sigue siendo coherente para el saldo cuando es negativo; si el total previo es 0 o no existe -> NULL.
WITH base AS (
    SELECT h.mes_inicio, h.anio, h.mes, h.pais_codigo, c.pais, c.region,
           h.producto_codigo, p.producto, p.subsector_codigo, p.subsector, p.sector_codigo, p.sector,
           h.exportaciones_eur, h.importaciones_eur, h.peso_exportado_kg, h.peso_importado_kg,
           h.unidades_exportadas, h.unidades_importadas, h.n_op_exportacion, h.n_op_importacion,
           -- una fila puede pertenecer a la vez al periodo actual y al previo (rangos de más de 12 meses)
           CASE WHEN h.mes_inicio >= DATE '2025-01-01' AND h.mes_inicio <= DATE '2025-12-01' THEN 1 ELSE 0 END AS en_a,
           CASE WHEN h.mes_inicio >= DATE '2024-01-01' AND h.mes_inicio <= DATE '2024-12-01' THEN 1 ELSE 0 END AS en_p
    FROM main.comercio_exterior.hechos_mensual h
    JOIN main.comercio_exterior.dim_pais c ON c.pais_codigo = h.pais_codigo
    JOIN main.comercio_exterior.dim_producto p ON p.producto_codigo = h.producto_codigo
    WHERE ((h.mes_inicio >= DATE '2025-01-01' AND h.mes_inicio <= DATE '2025-12-01')
          OR (h.mes_inicio >= DATE '2024-01-01' AND h.mes_inicio <= DATE '2024-12-01'))
          -- AND h.pais_codigo IN ('FR', 'DE')  -- filtro país (inactivo)
          -- AND h.producto_codigo IN ('P001', 'P002')  -- filtro producto (inactivo)
          -- AND p.sector_codigo IN ('S01', 'S02')  -- filtro sector (inactivo)
          -- AND p.subsector_codigo IN ('S01-1', 'S01-2')  -- filtro subsector (inactivo)
),
agg AS (
    SELECT
        pais_codigo AS clave,
        pais AS nombre,
        SUM(CASE WHEN en_a = 1 THEN exportaciones_eur ELSE 0 END) AS exp_act,
        SUM(CASE WHEN en_a = 1 THEN importaciones_eur ELSE 0 END) AS imp_act,
        SUM(CASE WHEN en_p = 1 THEN exportaciones_eur ELSE 0 END) AS exp_prev,
        SUM(CASE WHEN en_p = 1 THEN importaciones_eur ELSE 0 END) AS imp_prev
    FROM base
    GROUP BY pais_codigo, pais
),
medida AS (
    SELECT a.clave, a.nombre, a.exp_act + a.imp_act AS valor_act, a.exp_prev + a.imp_prev AS valor_prev FROM agg a
),
tot AS (
    SELECT SUM(valor_act) AS t_act, SUM(valor_prev) AS t_prev FROM medida
),
calc AS (
    SELECT
        m.clave,
        m.nombre,
        m.valor_act,
        m.valor_prev,
        m.valor_act - m.valor_prev AS variacion_eur,
        100.0 * (m.valor_act - m.valor_prev) / NULLIF(ABS(t.t_prev), 0) AS contribucion_pp,
        ROW_NUMBER() OVER (ORDER BY ABS(m.valor_act - m.valor_prev) DESC, m.clave) AS posicion
    FROM medida m
    CROSS JOIN tot t
),
resto AS (
    SELECT COUNT(*) AS n_elementos,
           SUM(valor_act) AS valor_act,
           SUM(valor_prev) AS valor_prev,
           SUM(variacion_eur) AS variacion_eur,
           SUM(contribucion_pp) AS contribucion_pp
    FROM calc
    WHERE posicion > 10
),
salida AS (
    SELECT posicion, clave, nombre, valor_act, valor_prev, variacion_eur, contribucion_pp, 0 AS es_resto
    FROM calc
    WHERE posicion <= 10
    UNION ALL
    SELECT 10 + 1, 'RESTO', 'Resto', valor_act, valor_prev, variacion_eur, contribucion_pp, 1
    FROM resto
    WHERE n_elementos > 0
)
SELECT
    s.posicion,
    s.clave,
    s.nombre,
    s.valor_act,
    s.valor_prev,
    s.variacion_eur,
    -- variación relativa del elemento; el denominador en valor absoluto evita invertir el signo con saldos negativos
    ROUND(100.0 * s.variacion_eur / NULLIF(ABS(s.valor_prev), 0), 2) AS var_pct,
    ROUND(s.contribucion_pp, 4) AS contribucion_pp,
    t.t_act AS total_act,
    t.t_prev AS total_prev,
    ROUND(100.0 * (t.t_act - t.t_prev) / NULLIF(ABS(t.t_prev), 0), 4) AS crecimiento_total_pct,
    s.es_resto
FROM salida s
CROSS JOIN tot t
ORDER BY s.es_resto, s.posicion
