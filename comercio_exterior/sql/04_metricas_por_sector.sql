-- Exportaciones, importaciones, saldo y cobertura por año y sector.
SELECT
    anio,
    sector,
    SUM(CASE WHEN flujo = 'EXPORTACION' THEN importe_eur ELSE 0 END) AS exportaciones,
    SUM(CASE WHEN flujo = 'IMPORTACION' THEN importe_eur ELSE 0 END) AS importaciones,
    SUM(CASE WHEN flujo = 'EXPORTACION' THEN importe_eur ELSE 0 END)
      - SUM(CASE WHEN flujo = 'IMPORTACION' THEN importe_eur ELSE 0 END) AS saldo,
    ROUND(100.0 * SUM(CASE WHEN flujo = 'EXPORTACION' THEN importe_eur ELSE 0 END)
          / NULLIF(SUM(CASE WHEN flujo = 'IMPORTACION' THEN importe_eur ELSE 0 END), 0), 2)
        AS cobertura_pct
FROM {tabla}
GROUP BY anio, sector
ORDER BY anio, sector
