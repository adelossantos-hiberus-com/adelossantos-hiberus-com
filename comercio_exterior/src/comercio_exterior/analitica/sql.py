"""Plantillas SQL portables (DuckDB y Databricks/Spark SQL) y su renderizado."""

from __future__ import annotations

from pathlib import Path

from .filtros import Filtros

RUTA_SQL = Path(__file__).resolve().parents[3] / "sql" / "analitica"
ESQUEMA_DATABRICKS = "main.comercio_exterior"
TABLAS = ("hechos_mensual", "dim_pais", "dim_producto", "dim_mes")

# dimensión -> (expresión clave, expresión nombre) sobre el CTE `base`
DIMENSIONES = {
    "pais": ("pais_codigo", "pais"),
    "producto": ("producto_codigo", "producto"),
    "sector": ("sector_codigo", "sector"),
    "subsector": ("subsector_codigo", "subsector"),
    "region": ("region", "region"),
}

# medida -> expresión sobre agg (exp/imp del periodo)
MEDIDAS = {
    "exportaciones": ("a.exportaciones_eur", "a.exp_act", "a.exp_prev"),
    "importaciones": ("a.importaciones_eur", "a.imp_act", "a.imp_prev"),
    "comercio_total": ("a.exportaciones_eur + a.importaciones_eur", "a.exp_act + a.imp_act", "a.exp_prev + a.imp_prev"),
    "saldo": ("a.exportaciones_eur - a.importaciones_eur", "a.exp_act - a.imp_act", "a.exp_prev - a.imp_prev"),
}

COLUMNAS_ORDENABLES_TABLA = {
    "clave", "nombre", "exportaciones_eur", "importaciones_eur", "saldo_eur", "comercio_total_eur",
    "cobertura_pct", "cuota_exportaciones_pct", "cuota_importaciones_pct", "cuota_comercio_pct",
    "var_exportaciones_pct", "var_importaciones_pct", "peso_kg", "unidades", "n_operaciones", "ranking",
}

_CTE_BASE = """base AS (
    SELECT h.mes_inicio, h.anio, h.mes, h.pais_codigo, c.pais, c.region,
           h.producto_codigo, p.producto, p.subsector_codigo, p.subsector, p.sector_codigo, p.sector,
           h.exportaciones_eur, h.importaciones_eur, h.peso_exportado_kg, h.peso_importado_kg,
           h.unidades_exportadas, h.unidades_importadas, h.n_op_exportacion, h.n_op_importacion,
           -- una fila puede pertenecer a la vez al periodo actual y al previo (rangos de más de 12 meses)
           CASE WHEN h.mes_inicio >= DATE '{desde}' AND h.mes_inicio <= DATE '{hasta}' THEN 1 ELSE 0 END AS en_a,
           CASE WHEN h.mes_inicio >= DATE '{desde_previo}' AND h.mes_inicio <= DATE '{hasta_previo}' THEN 1 ELSE 0 END AS en_p
    FROM {hechos_mensual} h
    JOIN {dim_pais} c ON c.pais_codigo = h.pais_codigo
    JOIN {dim_producto} p ON p.producto_codigo = h.producto_codigo
    WHERE {tiempo}
          {dims}
)"""


def _plantilla(nombre: str) -> str:
    return (RUTA_SQL / nombre).read_text(encoding="utf-8")


def renderizar(consulta: str, f: Filtros, *, dialecto: str = "duckdb", esquema: str = ESQUEMA_DATABRICKS,
               **params) -> str:
    """Devuelve el SQL de `sql/analitica/<consulta>.sql` listo para ejecutar.

    `dialecto='duckdb'` usa vistas locales; `'databricks'` califica las tablas con `esquema`.
    Los valores van como literales ya validados (fechas ISO y códigos del catálogo).
    """
    if dialecto not in ("duckdb", "databricks"):
        raise ValueError("dialecto debe ser 'duckdb' o 'databricks'")
    tablas = {t: (t if dialecto == "duckdb" else f"{esquema}.{t}") for t in TABLAS}
    tipo_tiempo = {"serie_mensual": "series", "serie_anual": "series", "ranking": "anios"}.get(consulta, "ventanas")
    tiempo = {"series": f.tiempo_series, "anios": f.tiempo_anios, "ventanas": f.tiempo_ventanas}[tipo_tiempo]()
    cte = _CTE_BASE.format(desde=f.desde, hasta=f.hasta, desde_previo=f.desde_previo, hasta_previo=f.hasta_previo,
                           tiempo=tiempo, dims=f.predicados_dimension(), **tablas)
    valores = dict(
        cte_base=cte, desde=f.desde, hasta=f.hasta, inicio_ext=f.inicio_ext_series,
        anio_desde=f.desde.year, anio_hasta=f.hasta.year, **tablas)
    valores.update(params)
    return _plantilla(f"{consulta}.sql").format(**valores).rstrip() + "\n"


def parametros_dimension(dimension: str) -> dict:
    if dimension not in DIMENSIONES:
        raise ValueError(f"dimension debe ser una de {sorted(DIMENSIONES)}")
    clave, nombre = DIMENSIONES[dimension]
    return {"clave": clave, "nombre": nombre}


def parametros_medida(medida: str, n: int, sentido: str, forma: str = "top") -> dict:
    """Parámetros de medida, tamaño del Top N y sentido. `forma` elige la expresión de cuota (top|ranking)."""
    if medida not in MEDIDAS:
        raise ValueError(f"medida debe ser una de {sorted(MEDIDAS)}")
    if sentido not in ("asc", "desc"):
        raise ValueError("sentido debe ser 'asc' o 'desc'")
    if not isinstance(n, int) or not 1 <= n <= 1000:
        raise ValueError("n debe ser un entero entre 1 y 1000")
    valor, v_act, v_prev = MEDIDAS[medida]
    if medida == "saldo":                      # el saldo puede ser negativo: la cuota no está definida
        cuota = "CAST(NULL AS DOUBLE)"
    elif forma == "ranking":
        cuota = "ROUND(r.cuota_raw, 2)"
    else:
        cuota = "ROUND(100.0 * s.valor / NULLIF(t.total_valor, 0), 2)"
    return dict(valor_expr=valor, valor_act=v_act, valor_prev=v_prev, n=n, sentido=sentido.upper(),
                cuota_expr=cuota)
