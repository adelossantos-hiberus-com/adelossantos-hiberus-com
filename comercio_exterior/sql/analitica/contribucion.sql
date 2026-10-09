-- Contribución al crecimiento: cuánto aporta cada elemento (en puntos porcentuales) a la variación
-- interanual del total, comparando el periodo con el mismo periodo del año anterior.
--   contribucion_pp = (valor_actual - valor_previo) / |total_previo| * 100
-- La suma de contribuciones (Top N + Resto) iguala el crecimiento total. Con |total_previo| el cálculo
-- sigue siendo coherente para el saldo cuando es negativo; si el total previo es 0 o no existe -> NULL.
WITH {cte_base},
agg AS (
    SELECT
        {clave} AS clave,
        {nombre} AS nombre,
        SUM(CASE WHEN en_a = 1 THEN exportaciones_eur ELSE 0 END) AS exp_act,
        SUM(CASE WHEN en_a = 1 THEN importaciones_eur ELSE 0 END) AS imp_act,
        SUM(CASE WHEN en_p = 1 THEN exportaciones_eur ELSE 0 END) AS exp_prev,
        SUM(CASE WHEN en_p = 1 THEN importaciones_eur ELSE 0 END) AS imp_prev
    FROM base
    GROUP BY {clave}, {nombre}
),
medida AS (
    SELECT a.clave, a.nombre, {valor_act} AS valor_act, {valor_prev} AS valor_prev FROM agg a
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
    WHERE posicion > {n}
),
salida AS (
    SELECT posicion, clave, nombre, valor_act, valor_prev, variacion_eur, contribucion_pp, 0 AS es_resto
    FROM calc
    WHERE posicion <= {n}
    UNION ALL
    SELECT {n} + 1, 'RESTO', 'Resto', valor_act, valor_prev, variacion_eur, contribucion_pp, 1
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
