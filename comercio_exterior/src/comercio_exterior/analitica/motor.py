"""Motor analítico sobre la capa gold con DuckDB (lectura directa de Parquet)."""

from __future__ import annotations

import math
import os
import threading
from collections import OrderedDict
from pathlib import Path

import duckdb

from ..lakehouse.control import Control
from ..lakehouse.rutas import Rutas
from .filtros import Filtros
from .sql import (COLUMNAS_ORDENABLES_TABLA, parametros_dimension, parametros_medida, renderizar)

MAX_FILAS_EXPORT = 1_000_000


def _limpiar(v):
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    return v


class Motor:
    """Ejecuta las consultas analíticas con filtros validados. Seguro para varios hilos."""

    def __init__(self, raiz: str | Path, *, cache: int = 256, hilos: int | None = None):
        self.rutas = Rutas(raiz)
        self.control = Control(self.rutas)
        self.con = duckdb.connect()
        if hilos:
            self.con.execute(f"SET threads TO {int(hilos)}")
        self._cache_max = cache
        self._cache: OrderedDict = OrderedDict()
        self._lock = threading.Lock()
        self.consultas_ejecutadas = 0
        self.aciertos_cache = 0
        self._vistas_listas = False
        self._crear_vistas()

    def _crear_vistas(self) -> None:
        """Crea las vistas sobre gold en cuanto existen datos (el servidor puede arrancar antes de la carga)."""
        if self._vistas_listas or not self.rutas.existe_gold():
            return
        g = self.rutas.gold
        self.con.execute(
            f"CREATE OR REPLACE VIEW hechos_mensual AS SELECT * FROM "
            f"read_parquet('{self.rutas.hechos}/*/part.parquet', hive_partitioning=false)")
        for t in ("dim_pais", "dim_producto", "dim_mes"):
            self.con.execute(f"CREATE OR REPLACE VIEW {t} AS SELECT * FROM read_parquet('{g / (t + '.parquet')}')")
        self._vistas_listas = True

    def version_datos(self) -> str:
        f = self.control.f_ingestas
        if not f.exists():
            return "vacio"
        st = os.stat(f)
        return f"{st.st_mtime_ns}:{st.st_size}"

    def datos_disponibles(self) -> bool:
        self._crear_vistas()
        return self._vistas_listas

    # ------------------------------------------------------------------ ejecución
    def ejecutar_sql(self, sql: str, *, usar_cache: bool = True) -> list[dict]:
        self._crear_vistas()
        clave = (self.version_datos(), sql)
        if usar_cache:
            with self._lock:
                if clave in self._cache:
                    self._cache.move_to_end(clave)
                    self.aciertos_cache += 1
                    return [dict(f) for f in self._cache[clave]]     # copias: el llamador puede modificarlas
        cur = self.con.cursor()
        try:
            res = cur.execute(sql)
            cols = [d[0] for d in res.description]
            filas = [{c: _limpiar(v) for c, v in zip(cols, fila)} for fila in res.fetchall()]
        finally:
            cur.close()
        with self._lock:
            self.consultas_ejecutadas += 1
            if usar_cache:
                self._cache[clave] = [dict(f) for f in filas]
                while len(self._cache) > self._cache_max:
                    self._cache.popitem(last=False)
        return filas

    # ------------------------------------------------------------------ consultas
    def resumen(self, f: Filtros) -> dict:
        return self.ejecutar_sql(renderizar("resumen", f))[0]

    def serie_mensual(self, f: Filtros) -> list[dict]:
        return self.ejecutar_sql(renderizar("serie_mensual", f))

    def serie_anual(self, f: Filtros) -> list[dict]:
        return self.ejecutar_sql(renderizar("serie_anual", f))

    def tabla(self, f: Filtros, dimension: str = "pais", orden: str = "comercio_total_eur", sentido: str = "desc",
              pagina: int = 1, tamano: int = 25, *, todo: bool = False) -> dict:
        if orden not in COLUMNAS_ORDENABLES_TABLA:
            raise ValueError(f"orden debe ser una de {sorted(COLUMNAS_ORDENABLES_TABLA)}")
        if sentido not in ("asc", "desc"):
            raise ValueError("sentido debe ser 'asc' o 'desc'")
        limite = MAX_FILAS_EXPORT if todo else tamano
        desplaz = 0 if todo else (pagina - 1) * tamano
        sql = renderizar("tabla", f, **parametros_dimension(dimension), orden=orden, sentido=sentido.upper(),
                         limite=int(limite), desplazamiento=int(desplaz))
        filas = self.ejecutar_sql(sql)
        total = filas[0]["total_filas"] if filas else 0
        if not filas and pagina > 1:      # página fuera de rango: el total real se pide aparte
            total = self.ejecutar_sql(renderizar("tabla", f, **parametros_dimension(dimension), orden=orden,
                                                 sentido="ASC", limite=1, desplazamiento=0))
            total = total[0]["total_filas"] if total else 0
        for r in filas:
            r.pop("total_filas", None)
        return {"filas": filas, "total": int(total), "pagina": pagina, "tamano": tamano}

    def top(self, f: Filtros, dimension: str = "pais", medida: str = "comercio_total", n: int = 10,
            sentido: str = "desc") -> list[dict]:
        sql = renderizar("top", f, **parametros_dimension(dimension), **parametros_medida(medida, n, sentido))
        return self.ejecutar_sql(sql)

    def contribucion(self, f: Filtros, dimension: str = "pais", medida: str = "comercio_total", n: int = 10) -> list[dict]:
        sql = renderizar("contribucion", f, **parametros_dimension(dimension), **parametros_medida(medida, n, "desc"))
        return self.ejecutar_sql(sql)

    def ranking(self, f: Filtros, dimension: str = "pais", medida: str = "comercio_total", n: int = 10,
                sentido: str = "desc") -> list[dict]:
        sql = renderizar("ranking", f, **parametros_dimension(dimension),
                         **parametros_medida(medida, n, sentido, forma="ranking"))
        return self.ejecutar_sql(sql)

    def cerrar(self) -> None:
        self.con.close()
