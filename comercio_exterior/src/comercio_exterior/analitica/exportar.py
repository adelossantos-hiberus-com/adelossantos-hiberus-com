"""Exporta las consultas analíticas como ficheros .sql para Databricks (escenario por defecto)."""

from __future__ import annotations

from pathlib import Path

from .filtros import Filtros
from .sql import ESQUEMA_DATABRICKS, parametros_dimension, parametros_medida, renderizar

CABECERA = """-- ============================================================================
-- Consulta generada para Databricks SQL / Spark SQL (NO editar a mano).
-- Origen: sql/analitica/{plantilla}.sql · regenerar con: python -m comercio_exterior.cli exportar-sql
-- Tablas esperadas en {esquema}: hechos_mensual, dim_pais, dim_producto, dim_mes (ver docs/databricks.md).
-- Escenario por defecto: {escenario}
-- Para filtrar: edite las fechas DATE '…' y active/ajuste las líneas «-- AND … IN (…)» del CTE base.
-- ============================================================================
"""

ESCENARIOS = {
    # fichero -> (plantilla, descripción, parámetros)
    "01_resumen": ("resumen", "todo el periodo 2018-01 a 2025-12, sin filtros de dimensión", {}),
    "02_serie_mensual": ("serie_mensual", "2018-01 a 2025-12, sin filtros", {}),
    "03_serie_anual": ("serie_anual", "2018-01 a 2025-12, sin filtros", {}),
    "04_tabla_paises": ("tabla", "tabla por país ordenada por comercio total (página 1, 25 filas)",
                        dict(dim="pais", orden="comercio_total_eur", sentido="DESC", limite=25, desplazamiento=0)),
    "05_top_paises_resto": ("top", "Top 10 países por comercio total + «Resto»", dict(dim="pais", med=("comercio_total", 10, "desc"))),
    "06_contribucion_crecimiento": ("contribucion", "contribución de los 10 mayores países al crecimiento del comercio total en 2025 (vs 2024)",
                                    dict(dim="pais", med=("comercio_total", 10, "desc"), filtros=("2025-01", "2025-12"))),
    "07_ranking_paises": ("ranking", "ranking anual de los 10 principales países", dict(dim="pais", med=("comercio_total", 10, "desc"), forma="ranking")),
}


def generar() -> dict[str, str]:
    salida = {}
    for fichero, (plantilla, escenario, cfg) in ESCENARIOS.items():
        d, h = cfg.get("filtros", (None, None))
        f = Filtros.crear(d, h)
        params = {}
        if "dim" in cfg:
            params.update(parametros_dimension(cfg["dim"]))
        if "med" in cfg:
            params.update(parametros_medida(*cfg["med"], forma=cfg.get("forma", "top")))
        for k in ("orden", "sentido", "limite", "desplazamiento"):
            if k in cfg:
                params[k] = cfg[k]
        sql = renderizar(plantilla, f, dialecto="databricks", **params)
        salida[f"{fichero}.sql"] = CABECERA.format(plantilla=plantilla, esquema=ESQUEMA_DATABRICKS,
                                                    escenario=escenario) + sql
    return salida


def exportar(carpeta: Path) -> list[Path]:
    carpeta.mkdir(parents=True, exist_ok=True)
    rutas = []
    for nombre, texto in generar().items():
        ruta = carpeta / nombre
        ruta.write_text(texto, encoding="utf-8")
        rutas.append(ruta)
    return rutas
