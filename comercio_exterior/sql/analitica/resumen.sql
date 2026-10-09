-- Indicadores del periodo filtrado y comparación con el mismo periodo del año anterior.
-- Sin datos en el periodo: importes NULL y n_operaciones = 0 (no es lo mismo que "0 euros").
WITH {cte_base},
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
