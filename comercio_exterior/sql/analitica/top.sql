-- Top N por una medida más una fila "Resto" con el agregado del resto de elementos.
-- Top N + Resto suma exactamente el total del periodo. La cuota no se define para el saldo (puede ser negativo).
WITH {cte_base},
agg AS (
    SELECT
        {clave} AS clave,
        {nombre} AS nombre,
        SUM(exportaciones_eur) AS exportaciones_eur,
        SUM(importaciones_eur) AS importaciones_eur,
        SUM(n_op_exportacion + n_op_importacion) AS n_operaciones
    FROM base
    WHERE en_a = 1
    GROUP BY {clave}, {nombre}
),
medida AS (
    SELECT a.*, {valor_expr} AS valor FROM agg a
),
tot AS (
    SELECT SUM(valor) AS total_valor FROM medida
),
ranked AS (
    SELECT m.*, ROW_NUMBER() OVER (ORDER BY m.valor {sentido} NULLS LAST, m.clave) AS posicion
    FROM medida m
),
resto AS (
    SELECT COUNT(*) AS n_elementos,
           SUM(exportaciones_eur) AS exportaciones_eur,
           SUM(importaciones_eur) AS importaciones_eur,
           SUM(n_operaciones) AS n_operaciones,
           SUM(valor) AS valor
    FROM ranked
    WHERE posicion > {n}
),
salida AS (
    SELECT posicion, clave, nombre, exportaciones_eur, importaciones_eur, n_operaciones, valor, 0 AS es_resto
    FROM ranked
    WHERE posicion <= {n}
    UNION ALL
    SELECT {n} + 1, 'RESTO', 'Resto', exportaciones_eur, importaciones_eur, n_operaciones, valor, 1
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
    {cuota_expr} AS cuota_pct,
    s.n_operaciones,
    s.es_resto
FROM salida s
CROSS JOIN tot t
ORDER BY s.es_resto, s.posicion
