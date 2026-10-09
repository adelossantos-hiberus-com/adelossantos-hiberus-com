"""Pipeline bronze → silver → gold con cargas incrementales e idempotentes.

* **Bronze**: la entrega tal cual llega + linaje (ingesta_id, ingesta_seq, ingesta_ts, fichero_origen,
  fila_origen). Inmutable: una carpeta por ingesta, escrita de forma atómica.
* **Silver**: cada operación válida con su versión vigente. Los registros inválidos van a
  `rechazados` (con motivo) y los duplicados/versiones sustituidas a `descartes` (con motivo y
  versión ganadora). Invariante: filas bronze = silver + rechazados + descartes.
* **Gold**: hechos mensuales por país y producto (exportaciones e importaciones en columnas) y
  dimensiones, para consulta analítica.

La carga de una ingesta ya registrada (mismo `ingesta_id` o mismo contenido) se omite.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

import duckdb
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from ..catalogos import ANIO_FIN, ANIO_INICIO, CATALOGO, dim_mes
from ..simulacion import COLUMNAS_ENTREGA, Entrega
from .control import Control, ahora
from .rutas import Rutas

UNIDADES_PARTICION = ("trimestre", "anio")
COMPRESION = "zstd"

COLUMNAS_SILVER = [
    "operacion_id", "version", "tipo_registro", "fecha", "flujo", "pais_codigo", "producto_codigo",
    "importe_eur", "peso_kg", "unidades", "ingesta_id", "ingesta_seq", "fila_origen",
    "ingesta_id_primera", "hash_contenido", "periodo",
]

_VALIDACION = """
CREATE OR REPLACE TEMP TABLE nuevo_v AS
SELECT b.*,
  CASE
    WHEN b.operacion_id IS NULL OR NOT regexp_matches(b.operacion_id, '^OP-[0-9]{8}$') THEN 'ID_INVALIDO'
    WHEN b.fecha IS NULL OR NOT regexp_matches(b.fecha, '^[0-9]{4}-[0-9]{2}-[0-9]{2}$')
         OR TRY_CAST(b.fecha AS DATE) IS NULL THEN 'FECHA_INVALIDA'
    WHEN TRY_CAST(b.fecha AS DATE) < DATE '$INI-01-01' OR TRY_CAST(b.fecha AS DATE) > DATE '$FIN-12-31'
         THEN 'FECHA_FUERA_DE_RANGO'
    WHEN b.flujo IS NULL OR b.flujo NOT IN ('EXPORTACION', 'IMPORTACION') THEN 'FLUJO_INVALIDO'
    WHEN b.pais_codigo IS NULL OR b.pais_codigo NOT IN (SELECT pais_codigo FROM dim_pais_v) THEN 'PAIS_DESCONOCIDO'
    WHEN b.producto_codigo IS NULL OR b.producto_codigo NOT IN (SELECT producto_codigo FROM dim_producto_v)
         THEN 'PRODUCTO_DESCONOCIDO'
    WHEN b.importe_eur IS NULL OR isnan(b.importe_eur) THEN 'IMPORTE_NULO'
    WHEN b.importe_eur < 0 THEN 'IMPORTE_NEGATIVO'
    WHEN b.peso_kg IS NULL OR isnan(b.peso_kg) OR b.peso_kg < 0 THEN 'PESO_INVALIDO'
    WHEN b.unidades IS NULL OR b.unidades < 0 THEN 'UNIDADES_INVALIDAS'
    WHEN b.version IS NULL OR b.version < 1 THEN 'VERSION_INVALIDA'
    ELSE NULL
  END AS motivo
FROM nuevo b
"""


@dataclass
class ResultadoIngesta:
    ingesta_id: str
    estado: str                       # COMPLETADA | OMITIDA | FALLIDA
    motivo_omision: str | None = None
    filas_recibidas: int = 0
    filas_validas: int = 0
    filas_rechazadas: int = 0
    rechazos_por_motivo: dict = field(default_factory=dict)
    descartes_por_motivo: dict = field(default_factory=dict)
    nuevas_operaciones: int = 0
    correcciones_aplicadas: int = 0
    periodos_afectados: list = field(default_factory=list)
    duracion_s: dict = field(default_factory=dict)


def hash_entrega(df: pd.DataFrame) -> str:
    """Huella del contenido (sensible al orden de filas) para detectar reentregas idénticas."""
    h = hashlib.sha256()
    h.update(",".join(df.columns).encode())
    h.update(pd.util.hash_pandas_object(df, index=False).to_numpy().tobytes())
    return h.hexdigest()


class Lakehouse:
    def __init__(self, raiz: str | Path, unidad_particion: str = "trimestre"):
        if unidad_particion not in UNIDADES_PARTICION:
            raise ValueError(f"unidad_particion debe ser una de {UNIDADES_PARTICION}")
        self.rutas = Rutas(raiz)
        self.control = Control(self.rutas)
        cfg = self.control.leer_config()
        if cfg.get("unidad_particion", unidad_particion) != unidad_particion:
            raise ValueError(
                f"El lakehouse ya existe con unidad_particion={cfg['unidad_particion']!r}; "
                f"no se puede cambiar a {unidad_particion!r}")
        self.unidad = unidad_particion
        self.con = duckdb.connect()
        self.con.register("dim_pais_v", CATALOGO.dim_pais())
        self.con.register("dim_producto_v", CATALOGO.dim_producto())
        self.con.register("dim_mes_v", dim_mes())

    # ------------------------------------------------------------------ utilidades
    def _expr_periodo(self, col: str = "fecha") -> str:
        if self.unidad == "anio":
            return f"CAST(year({col}) AS VARCHAR)"
        return f"CAST(year({col}) AS VARCHAR) || 'Q' || CAST(quarter({col}) AS VARCHAR)"

    @staticmethod
    def _escribir_parquet_sql(con, consulta: str, destino: Path) -> None:
        destino.parent.mkdir(parents=True, exist_ok=True)
        tmp = destino.with_suffix(".tmp")
        con.execute(f"COPY ({consulta}) TO '{tmp}' (FORMAT PARQUET, COMPRESSION {COMPRESION})")
        os.replace(tmp, destino)

    # ------------------------------------------------------------------ ingesta
    def ingestar(self, entrega: Entrega, *, fuente: str = "SIMULADA", _fallo_en: str | None = None) -> ResultadoIngesta:
        """Carga una entrega. Idempotente: si ya estaba cargada devuelve estado OMITIDA.

        `_fallo_en` ('bronce'|'silver'|'gold') solo se usa en pruebas para simular una caída.
        """
        self.control.escribir_config({"unidad_particion": self.unidad})
        with self.control.bloqueo():
            hash_c = hash_entrega(entrega.datos)
            ing = self.control.ingestas()
            previa = self.control.fila(entrega.ingesta_id)

            if previa is not None and previa["estado"] == "COMPLETADA":
                self.control.evento(entrega.ingesta_id, "OMITIDA", "ingesta_id ya cargada")
                return ResultadoIngesta(entrega.ingesta_id, "OMITIDA", "INGESTA_ID_YA_CARGADA")
            if previa is None and len(ing):
                igual = ing[(ing["hash_contenido"] == hash_c) & (ing["estado"] == "COMPLETADA")]
                if len(igual):
                    self.control.evento(entrega.ingesta_id, "OMITIDA",
                                        f"contenido idéntico a {igual.iloc[0]['ingesta_id']}")
                    return ResultadoIngesta(entrega.ingesta_id, "OMITIDA", "CONTENIDO_YA_CARGADO")

            if previa is None:
                fila = self.control.insertar(
                    ingesta_id=entrega.ingesta_id, fuente=fuente, fichero_origen=entrega.fichero_origen,
                    periodo=entrega.periodo, hash_contenido=hash_c, estado="EN_CURSO", bronze_ok=False,
                    silver_ok=False, gold_ok=False, ts_inicio=ahora(), filas_recibidas=len(entrega.datos))
                self.control.evento(entrega.ingesta_id, "INICIO", entrega.fichero_origen)
            else:
                fila = previa
                if previa["hash_contenido"] != hash_c:
                    raise ValueError(f"{entrega.ingesta_id} está a medias con un contenido distinto; "
                                     "no se puede reanudar con otro fichero")
                self.control.actualizar(entrega.ingesta_id, estado="EN_CURSO", error=None)
                self.control.evento(entrega.ingesta_id, "REANUDADA", "continúa desde el último paso correcto")
            seq = int(fila["ingesta_seq"])

            res = ResultadoIngesta(entrega.ingesta_id, "COMPLETADA", filas_recibidas=len(entrega.datos))
            try:
                if not bool(fila["bronze_ok"]):
                    t = time.perf_counter()
                    self._bronze(entrega, seq)
                    if _fallo_en == "bronce":
                        raise RuntimeError("fallo simulado en bronze")
                    res.duracion_s["bronze"] = time.perf_counter() - t
                    self.control.actualizar(entrega.ingesta_id, bronze_ok=True, dur_bronze_s=res.duracion_s["bronze"])
                fila = self.control.fila(entrega.ingesta_id)
                if not bool(fila["silver_ok"]):
                    t = time.perf_counter()
                    if _fallo_en == "silver":
                        raise RuntimeError("fallo simulado en silver")
                    stats = self._silver(entrega.ingesta_id, seq)
                    res.duracion_s["silver"] = time.perf_counter() - t
                    res.__dict__.update({k: stats[k] for k in (
                        "filas_validas", "filas_rechazadas", "rechazos_por_motivo", "descartes_por_motivo",
                        "nuevas_operaciones", "correcciones_aplicadas", "periodos_afectados")})
                    d = stats["descartes_por_motivo"]
                    self.control.actualizar(
                        entrega.ingesta_id, silver_ok=True, dur_silver_s=res.duracion_s["silver"],
                        filas_validas=stats["filas_validas"], filas_rechazadas=stats["filas_rechazadas"],
                        duplicados_exactos=d.get("DUPLICADO_EXACTO", 0),
                        versiones_antiguas=d.get("VERSION_ANTIGUA", 0),
                        conflictos_version=d.get("CONFLICTO_MISMA_VERSION", 0),
                        nuevas_operaciones=stats["nuevas_operaciones"],
                        correcciones_aplicadas=stats["correcciones_aplicadas"],
                        periodos_afectados=",".join(stats["periodos_afectados"]))
                fila = self.control.fila(entrega.ingesta_id)
                if not bool(fila["gold_ok"]):
                    t = time.perf_counter()
                    if _fallo_en == "gold":
                        raise RuntimeError("fallo simulado en gold")
                    periodos = [p for p in str(fila["periodos_afectados"] or "").split(",") if p]
                    self._gold(periodos)
                    res.duracion_s["gold"] = time.perf_counter() - t
                    self.control.actualizar(entrega.ingesta_id, gold_ok=True, dur_gold_s=res.duracion_s["gold"])
                self.control.actualizar(entrega.ingesta_id, estado="COMPLETADA", ts_fin=ahora())
                self.control.evento(entrega.ingesta_id, "COMPLETADA", "")
            except Exception as exc:
                self.control.actualizar(entrega.ingesta_id, estado="FALLIDA", error=str(exc), ts_fin=ahora())
                self.control.evento(entrega.ingesta_id, "FALLIDA", str(exc))
                res.estado = "FALLIDA"
                raise
            return res

    # ------------------------------------------------------------------ bronze
    def _bronze(self, entrega: Entrega, seq: int) -> None:
        destino = self.rutas.bronze_ingesta(entrega.ingesta_id)
        if destino.exists():
            shutil.rmtree(destino)           # restos de un intento anterior sin confirmar
        df = entrega.datos[COLUMNAS_ENTREGA].copy()
        df["ingesta_id"] = entrega.ingesta_id
        df["ingesta_seq"] = pd.array([seq] * len(df), dtype="int32")
        df["ingesta_ts"] = pd.Timestamp(ahora())
        df["fichero_origen"] = entrega.fichero_origen
        df["fila_origen"] = pd.array(range(1, len(df) + 1), dtype="int64")
        tmp = destino.with_name(destino.name + ".tmp")
        tmp.mkdir(parents=True, exist_ok=True)
        pq.write_table(pa.Table.from_pandas(df, preserve_index=False), tmp / "part-0.parquet",
                       compression=COMPRESION)
        os.replace(tmp, destino)             # visible solo cuando está completa

    # ------------------------------------------------------------------ silver
    def _silver(self, ingesta_id: str, seq: int) -> dict:
        con = self.con
        ini, fin = str(ANIO_INICIO), str(ANIO_FIN)
        con.execute(f"CREATE OR REPLACE TEMP TABLE nuevo AS SELECT * FROM read_parquet("
                    f"'{self.rutas.bronze_ingesta(ingesta_id) / 'part-0.parquet'}')")
        con.execute(_VALIDACION.replace("$INI", ini).replace("$FIN", fin))
        recibidas = con.execute("SELECT count(*) FROM nuevo_v").fetchone()[0]

        # 1) rechazados: se conservan con su motivo y linaje
        rech_dir = self.rutas.rechazados / f"ingesta_id={ingesta_id}"
        if rech_dir.exists():
            shutil.rmtree(rech_dir)
        rechazos = dict(con.execute(
            "SELECT motivo, count(*) FROM nuevo_v WHERE motivo IS NOT NULL GROUP BY motivo").fetchall())
        if rechazos:
            self._escribir_parquet_sql(con, "SELECT * FROM nuevo_v WHERE motivo IS NOT NULL", rech_dir / "part.parquet")

        # 2) válidos tipados
        per = self._expr_periodo("fecha_d")
        con.execute(f"""
            CREATE OR REPLACE TEMP TABLE validos AS
            SELECT operacion_id, CAST(version AS INTEGER) AS version, tipo_registro, fecha_d AS fecha, flujo,
                   pais_codigo, producto_codigo, importe_eur, peso_kg, CAST(unidades AS BIGINT) AS unidades,
                   ingesta_id, ingesta_seq, fila_origen, CAST(NULL AS VARCHAR) AS ingesta_id_primera,
                   md5(concat_ws('|', CAST(fecha_d AS VARCHAR), flujo, pais_codigo, producto_codigo,
                                 CAST(importe_eur AS VARCHAR), CAST(peso_kg AS VARCHAR),
                                 CAST(unidades AS VARCHAR))) AS hash_contenido,
                   {per} AS periodo, 'NUEVO' AS origen
            FROM (SELECT *, TRY_CAST(fecha AS DATE) AS fecha_d FROM nuevo_v WHERE motivo IS NULL)
        """)
        n_validos = con.execute("SELECT count(*) FROM validos").fetchone()[0]
        desc_dir = self.rutas.descartes / f"ingesta_id_proceso={ingesta_id}"
        if desc_dir.exists():
            shutil.rmtree(desc_dir)
        resumen = dict(filas_validas=n_validos, filas_rechazadas=recibidas - n_validos,
                       rechazos_por_motivo=rechazos, descartes_por_motivo={}, nuevas_operaciones=0,
                       correcciones_aplicadas=0, periodos_afectados=[])
        if n_validos == 0:
            return resumen

        periodos = [r[0] for r in con.execute("SELECT DISTINCT periodo FROM validos ORDER BY 1").fetchall()]
        existentes = [self.rutas.silver_periodo(p) / "part.parquet" for p in periodos
                      if (self.rutas.silver_periodo(p) / "part.parquet").exists()]
        cols = ", ".join(COLUMNAS_SILVER)
        if existentes:
            lista = ", ".join(f"'{p}'" for p in existentes)
            existente_sql = (f"SELECT {cols}, 'SILVER' AS origen FROM read_parquet([{lista}])")
            con.execute(f"CREATE OR REPLACE TEMP TABLE existente AS {existente_sql}")
        else:
            con.execute(f"CREATE OR REPLACE TEMP TABLE existente AS SELECT {cols}, 'SILVER' AS origen "
                        f"FROM validos WHERE false")

        # 3) fusión: exactos → versión vigente
        con.execute(f"""
            CREATE OR REPLACE TEMP TABLE candidatos AS
            SELECT *, first_value(COALESCE(ingesta_id_primera, ingesta_id)) OVER (
                          PARTITION BY operacion_id ORDER BY ingesta_seq, fila_origen) AS primera
            FROM (SELECT {cols}, origen FROM existente UNION ALL SELECT {cols}, origen FROM validos)
        """)
        con.execute("""
            CREATE OR REPLACE TEMP TABLE c1 AS
            SELECT *, row_number() OVER (PARTITION BY operacion_id, version, hash_contenido
                                         ORDER BY ingesta_seq, fila_origen) AS rn1
            FROM candidatos
        """)
        con.execute("""
            CREATE OR REPLACE TEMP TABLE c2 AS
            SELECT *, row_number() OVER (PARTITION BY operacion_id
                                         ORDER BY version DESC, ingesta_seq DESC, fila_origen) AS rn2,
                   first_value(ingesta_id) OVER (PARTITION BY operacion_id
                                         ORDER BY version DESC, ingesta_seq DESC, fila_origen) AS ing_ganadora,
                   max(version) OVER (PARTITION BY operacion_id) AS ver_ganadora
            FROM c1 WHERE rn1 = 1
        """)
        winners = f"SELECT {', '.join(c for c in COLUMNAS_SILVER if c != 'ingesta_id_primera')}, primera AS ingesta_id_primera FROM c2 WHERE rn2 = 1"
        # descartes: duplicados exactos y versiones que pierden
        con.execute(f"""
            CREATE OR REPLACE TEMP TABLE descartes AS
            SELECT d.operacion_id, d.version, d.ingesta_id, d.fila_origen, d.motivo, d.ingesta_id_ganadora,
                   d.version_ganadora, '{ingesta_id}' AS ingesta_id_proceso, d.origen AS origen_descartado,
                   d.fecha, d.importe_eur
            FROM (
              SELECT c1.operacion_id, c1.version, c1.ingesta_id, c1.fila_origen, 'DUPLICADO_EXACTO' AS motivo,
                     w.ing_ganadora AS ingesta_id_ganadora, w.ver_ganadora AS version_ganadora,
                     c1.origen, c1.fecha, c1.importe_eur
              FROM c1 JOIN (SELECT DISTINCT operacion_id, ing_ganadora, ver_ganadora FROM c2) w USING (operacion_id)
              WHERE c1.rn1 > 1
              UNION ALL
              SELECT operacion_id, version, ingesta_id, fila_origen,
                     CASE WHEN version < ver_ganadora THEN 'VERSION_ANTIGUA' ELSE 'CONFLICTO_MISMA_VERSION' END,
                     ing_ganadora, ver_ganadora, origen, fecha, importe_eur
              FROM c2 WHERE rn2 > 1
            ) d
        """)
        # el desglose por motivo de los descartes que nacen en esta ingesta
        # (un descarte de origen SILVER es una versión que esta carga sustituye)
        desc = dict(con.execute("SELECT motivo, count(*) FROM descartes GROUP BY motivo").fetchall())
        if desc:
            self._escribir_parquet_sql(con, "SELECT * FROM descartes", desc_dir / "part.parquet")

        stats_sql = con.execute("""
            SELECT
              count(*) FILTER (WHERE origen = 'NUEVO' AND rn2 = 1 AND operacion_id NOT IN (SELECT operacion_id FROM existente)),
              count(*) FILTER (WHERE origen = 'NUEVO' AND rn2 = 1 AND operacion_id IN (SELECT operacion_id FROM existente))
            FROM c2""").fetchone()

        # 4) reescritura de los periodos afectados (atómica por fichero)
        for p in periodos:
            self._escribir_parquet_sql(
                con, f"SELECT * FROM ({winners}) WHERE periodo = '{p}' ORDER BY fecha, operacion_id",
                self.rutas.silver_periodo(p) / "part.parquet")
        resumen.update(descartes_por_motivo=desc, nuevas_operaciones=int(stats_sql[0]),
                       correcciones_aplicadas=int(stats_sql[1]), periodos_afectados=periodos)
        return resumen

    # ------------------------------------------------------------------ gold
    def _gold(self, periodos: list[str]) -> None:
        con = self.con
        gold = self.rutas.gold
        gold.mkdir(parents=True, exist_ok=True)
        for nombre, df in (("dim_pais", CATALOGO.dim_pais()), ("dim_producto", CATALOGO.dim_producto()),
                           ("dim_mes", dim_mes())):
            tmp = gold / f"{nombre}.tmp"
            df.to_parquet(tmp, index=False)
            os.replace(tmp, gold / f"{nombre}.parquet")
        for p in periodos:
            fuente = self.rutas.silver_periodo(p) / "part.parquet"
            self._escribir_parquet_sql(con, f"""
                SELECT CAST(date_trunc('month', fecha) AS DATE) AS mes_inicio,
                       CAST(year(fecha) AS INTEGER) AS anio, CAST(month(fecha) AS INTEGER) AS mes,
                       pais_codigo, producto_codigo,
                       SUM(CASE WHEN flujo = 'EXPORTACION' THEN importe_eur ELSE 0 END) AS exportaciones_eur,
                       SUM(CASE WHEN flujo = 'IMPORTACION' THEN importe_eur ELSE 0 END) AS importaciones_eur,
                       SUM(CASE WHEN flujo = 'EXPORTACION' THEN peso_kg ELSE 0 END) AS peso_exportado_kg,
                       SUM(CASE WHEN flujo = 'IMPORTACION' THEN peso_kg ELSE 0 END) AS peso_importado_kg,
                       CAST(SUM(CASE WHEN flujo = 'EXPORTACION' THEN unidades ELSE 0 END) AS BIGINT) AS unidades_exportadas,
                       CAST(SUM(CASE WHEN flujo = 'IMPORTACION' THEN unidades ELSE 0 END) AS BIGINT) AS unidades_importadas,
                       count(*) FILTER (WHERE flujo = 'EXPORTACION') AS n_op_exportacion,
                       count(*) FILTER (WHERE flujo = 'IMPORTACION') AS n_op_importacion
                FROM read_parquet('{fuente}')
                GROUP BY 1, 2, 3, 4, 5
                ORDER BY 1, 4, 5""", self.rutas.hechos_periodo(p) / "part.parquet")

    # ------------------------------------------------------------------ utilidades públicas
    def reconstruir_silver_y_gold(self) -> None:
        """Borra silver y gold y los regenera desde bronze procesando las ingestas en orden.

        Sirve para demostrar que el estado es reproducible desde la capa bronze.
        """
        for ruta in (self.rutas.raiz / "silver", self.rutas.gold):
            if ruta.exists():
                shutil.rmtree(ruta)
        ing = self.control.ingestas()
        comp = ing[ing["estado"] == "COMPLETADA"].sort_values("ingesta_seq")
        for fila in comp.itertuples():
            stats = self._silver(fila.ingesta_id, int(fila.ingesta_seq))
            self._gold(stats["periodos_afectados"])

    def cerrar(self) -> None:
        self.con.close()
