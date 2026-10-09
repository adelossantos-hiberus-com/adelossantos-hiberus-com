"""Controles de calidad y trazabilidad sobre las tres capas (se ejecutan con DuckDB sobre Parquet)."""

from __future__ import annotations

import math
from pathlib import Path

import duckdb
import pandas as pd

from ..catalogos import ANIO_FIN, ANIO_INICIO, CATALOGO
from .control import Control
from .rutas import Rutas

TOLERANCIA_REL = 1e-9
TOLERANCIA_ABS = 0.01


def _check(nombre: str, ok: bool, detalle: str, valor=None, capa: str = "") -> dict:
    return {"nombre": nombre, "capa": capa, "ok": bool(ok), "detalle": detalle, "valor": valor}


def _existe(rutas: Rutas) -> dict:
    return {
        "bronze": any(rutas.bronze.glob("*/part-0.parquet")),
        "silver": any(rutas.silver.glob("*/part.parquet")),
        "rechazados": any(rutas.rechazados.glob("*/part.parquet")),
        "descartes": any(rutas.descartes.glob("*/part.parquet")),
        "gold": rutas.existe_gold(),
    }


def informe_calidad(raiz: str | Path) -> dict:
    rutas = Rutas(raiz)
    control = Control(rutas)
    ex = _existe(rutas)
    con = duckdb.connect()
    con.register("dim_pais", CATALOGO.dim_pais())
    con.register("dim_producto", CATALOGO.dim_producto())
    q = lambda sql: con.execute(sql).fetchone()[0]  # noqa: E731
    checks: list[dict] = []

    if not ex["bronze"]:
        return {"checks": [_check("datos_cargados", False, "Todavía no hay ingestas cargadas", capa="bronze")],
                "resumen": {"ok": 0, "error": 1}, "rechazos_por_motivo": [], "descartes_por_motivo": [],
                "conservacion": None, "por_capa": {}}

    bronze = f"read_parquet('{rutas.bronze}/*/part-0.parquet', hive_partitioning=false)"
    n_bronze = q(f"SELECT count(*) FROM {bronze}")
    n_silver = n_rech = n_desc = 0
    if ex["silver"]:
        silver = f"read_parquet('{rutas.silver}/*/part.parquet', hive_partitioning=false)"
        n_silver = q(f"SELECT count(*) FROM {silver}")
    if ex["rechazados"]:
        n_rech = q(f"SELECT count(*) FROM read_parquet('{rutas.rechazados}/*/part.parquet', hive_partitioning=false)")
    if ex["descartes"]:
        n_desc = q(f"SELECT count(*) FROM read_parquet('{rutas.descartes}/*/part.parquet', hive_partitioning=false)")

    conservacion = {"bronze": n_bronze, "silver": n_silver, "rechazados": n_rech, "descartes": n_desc,
                    "diferencia": n_bronze - n_silver - n_rech - n_desc}
    checks.append(_check("conservacion_de_filas", conservacion["diferencia"] == 0,
                         f"bronze {n_bronze:,} = silver {n_silver:,} + rechazados {n_rech:,} + descartes {n_desc:,}"
                         if conservacion["diferencia"] == 0 else
                         f"descuadre de {conservacion['diferencia']:,} filas entre bronze y silver+rechazados+descartes",
                         conservacion["diferencia"], "bronze"))

    # ---- bronze: linaje completo
    n_sin_linaje = q(f"SELECT count(*) FROM {bronze} WHERE ingesta_id IS NULL OR fichero_origen IS NULL OR fila_origen IS NULL")
    dup_linaje = q(f"SELECT count(*) - count(DISTINCT (ingesta_id, fila_origen)) FROM {bronze}")
    checks.append(_check("bronze_linaje_completo", n_sin_linaje == 0 and dup_linaje == 0,
                         "todas las filas tienen ingesta, fichero y fila de origen únicos"
                         if n_sin_linaje == 0 and dup_linaje == 0 else
                         f"{n_sin_linaje} filas sin linaje, {dup_linaje} claves de linaje repetidas", n_sin_linaje + dup_linaje, "bronze"))

    if ex["silver"]:
        def chk(nombre, sql, ok_txt, mal_txt, capa="silver"):
            n = q(sql)
            checks.append(_check(nombre, n == 0, ok_txt if n == 0 else f"{n:,} {mal_txt}", n, capa))
        chk("silver_ids_unicos", f"SELECT count(*) - count(DISTINCT operacion_id) FROM {silver}",
            "una sola versión vigente por operación", "operaciones con más de una versión vigente")
        chk("silver_sin_nulos",
            f"SELECT count(*) FROM {silver} WHERE operacion_id IS NULL OR fecha IS NULL OR flujo IS NULL OR "
            "pais_codigo IS NULL OR producto_codigo IS NULL OR importe_eur IS NULL OR peso_kg IS NULL OR unidades IS NULL",
            "sin nulos en columnas obligatorias", "filas con nulos en columnas obligatorias")
        chk("silver_importes_no_negativos",
            f"SELECT count(*) FROM {silver} WHERE importe_eur < 0 OR peso_kg < 0 OR unidades < 0",
            "importes, pesos y unidades ≥ 0", "filas con importe, peso o unidades negativos")
        chk("silver_flujo_valido", f"SELECT count(*) FROM {silver} WHERE flujo NOT IN ('EXPORTACION','IMPORTACION')",
            "flujo siempre EXPORTACION o IMPORTACION", "filas con flujo no válido")
        chk("silver_sin_huerfanos",
            f"SELECT count(*) FROM {silver} WHERE pais_codigo NOT IN (SELECT pais_codigo FROM dim_pais) "
            "OR producto_codigo NOT IN (SELECT producto_codigo FROM dim_producto)",
            "todos los países y productos existen en las dimensiones", "filas con país o producto fuera del catálogo")
        chk("silver_fechas_en_rango",
            f"SELECT count(*) FROM {silver} WHERE fecha < DATE '{ANIO_INICIO}-01-01' OR fecha > DATE '{ANIO_FIN}-12-31'",
            f"fechas entre {ANIO_INICIO} y {ANIO_FIN}", "filas con fecha fuera de rango")
        chk("silver_trazable_a_bronze",
            f"SELECT count(*) FROM {silver} s ANTI JOIN {bronze} b ON b.ingesta_id = s.ingesta_id AND b.fila_origen = s.fila_origen",
            "cada fila de silver existe en bronze (ingesta y fila de origen)", "filas de silver sin su origen en bronze")

    if ex["silver"] and ex["gold"]:
        gold = f"read_parquet('{rutas.hechos}/*/part.parquet', hive_partitioning=false)"
        dif = con.execute(f"""
            SELECT max(abs(s.imp - g.imp)), max(abs(s.exp - g.exp)), count(*)
            FROM (SELECT year(fecha) a, SUM(CASE WHEN flujo='IMPORTACION' THEN importe_eur ELSE 0 END) imp,
                         SUM(CASE WHEN flujo='EXPORTACION' THEN importe_eur ELSE 0 END) exp FROM {silver} GROUP BY 1) s
            FULL JOIN (SELECT anio a, SUM(importaciones_eur) imp, SUM(exportaciones_eur) exp FROM {gold} GROUP BY 1) g USING (a)
        """).fetchone()
        d = max(dif[0] or 0, dif[1] or 0)
        checks.append(_check("gold_cuadra_con_silver", d <= TOLERANCIA_ABS,
                             f"exportaciones e importaciones anuales coinciden (diferencia máx. {d:.6f} €)"
                             if d <= TOLERANCIA_ABS else f"diferencia máxima de {d:,.2f} € entre silver y gold", d, "gold"))
        n_ops = q(f"SELECT SUM(n_op_exportacion + n_op_importacion) FROM {gold}")
        checks.append(_check("gold_operaciones_cuadran", int(n_ops) == n_silver,
                             f"{int(n_ops):,} operaciones en gold = {n_silver:,} en silver" if int(n_ops) == n_silver
                             else f"gold tiene {int(n_ops):,} operaciones y silver {n_silver:,}", int(n_ops) - n_silver, "gold"))
        dup = q(f"SELECT count(*) - count(DISTINCT (mes_inicio, pais_codigo, producto_codigo)) FROM {gold}")
        checks.append(_check("gold_clave_unica", dup == 0, "una fila por mes, país y producto" if dup == 0
                             else f"{dup:,} claves repetidas", dup, "gold"))
        neg = q(f"SELECT count(*) FROM {gold} WHERE exportaciones_eur < 0 OR importaciones_eur < 0")
        checks.append(_check("gold_sin_negativos", neg == 0, "importes ≥ 0 en todos los hechos" if neg == 0
                             else f"{neg:,} hechos con importes negativos", neg, "gold"))

    ing = control.ingestas()
    if len(ing):
        pend = ing[ing["estado"] != "COMPLETADA"]
        checks.append(_check("ingestas_completadas", pend.empty,
                             f"{len(ing)} ingestas, todas completadas" if pend.empty else
                             f"{len(pend)} ingestas sin completar: " + ", ".join(pend["ingesta_id"].astype(str)[:5]),
                             len(pend), "control"))
        dup_hash = len(ing) - ing["hash_contenido"].nunique()
        checks.append(_check("ingestas_sin_contenido_repetido", dup_hash == 0,
                             "no hay entregas con contenido idéntico" if dup_hash == 0
                             else f"{dup_hash} ingestas con contenido repetido", dup_hash, "control"))

    def tabla(sql):
        return [dict(zip(["motivo", "filas"], r)) for r in con.execute(sql).fetchall()]
    rechazos = tabla(f"SELECT motivo, count(*) c FROM read_parquet('{rutas.rechazados}/*/part.parquet', "
                     "hive_partitioning=false) GROUP BY 1 ORDER BY 2 DESC") if ex["rechazados"] else []
    descartes = tabla(f"SELECT motivo, count(*) c FROM read_parquet('{rutas.descartes}/*/part.parquet', "
                      "hive_partitioning=false) GROUP BY 1 ORDER BY 2 DESC") if ex["descartes"] else []
    con.close()
    ok = sum(1 for c in checks if c["ok"])
    return {"checks": checks, "resumen": {"ok": ok, "error": len(checks) - ok},
            "rechazos_por_motivo": rechazos, "descartes_por_motivo": descartes, "conservacion": conservacion}


def rechazados_paginados(raiz: str | Path, pagina: int, tamano: int, motivo: str | None = None,
                         ingesta_id: str | None = None) -> dict:
    rutas = Rutas(raiz)
    if not any(rutas.rechazados.glob("*/part.parquet")):
        return {"filas": [], "total": 0, "pagina": pagina, "tamano": tamano}
    con = duckdb.connect()
    fuente = f"read_parquet('{rutas.rechazados}/*/part.parquet', hive_partitioning=false)"
    cond, params = [], []
    if motivo:
        cond.append("motivo = ?"); params.append(motivo)
    if ingesta_id:
        cond.append("ingesta_id = ?"); params.append(ingesta_id)
    where = ("WHERE " + " AND ".join(cond)) if cond else ""
    total = con.execute(f"SELECT count(*) FROM {fuente} {where}", params).fetchone()[0]
    res = con.execute(
        f"SELECT ingesta_id, fila_origen, fichero_origen, operacion_id, version, tipo_registro, fecha, flujo, "
        f"pais_codigo, producto_codigo, importe_eur, peso_kg, unidades, motivo FROM {fuente} {where} "
        f"ORDER BY ingesta_seq, fila_origen LIMIT ? OFFSET ?", params + [tamano, (pagina - 1) * tamano])
    cols = [d[0] for d in res.description]
    filas = []
    for r in res.fetchall():
        d = {c: (None if isinstance(v, float) and math.isnan(v) else v) for c, v in zip(cols, r)}
        filas.append(d)
    con.close()
    return {"filas": filas, "total": int(total), "pagina": pagina, "tamano": tamano}


def detalle_ingesta(raiz: str | Path, ingesta_id: str) -> dict | None:
    rutas = Rutas(raiz)
    control = Control(rutas)
    fila = control.fila(ingesta_id)
    if fila is None:
        return None
    con = duckdb.connect()
    def por_motivo(ruta, col, extra=""):
        if not any(ruta.glob("*/part.parquet")):
            return []
        return [dict(zip(["motivo", "filas"], r)) for r in con.execute(
            f"SELECT motivo, count(*) FROM read_parquet('{ruta}/*/part.parquet', hive_partitioning=false) "
            f"WHERE {col} = ? GROUP BY 1 ORDER BY 2 DESC", [ingesta_id]).fetchall()]
    det = {
        "ingesta": _serializar(fila),
        "rechazos_por_motivo": por_motivo(rutas.rechazados, "ingesta_id"),
        "descartes_por_motivo": por_motivo(rutas.descartes, "ingesta_id_proceso"),
        "eventos": [_serializar(e) for e in control.eventos().query("ingesta_id == @ingesta_id").to_dict("records")],
    }
    con.close()
    return det


def _serializar(d: dict) -> dict:
    out = {}
    for k, v in d.items():
        if isinstance(v, pd.Timestamp):
            v = v.isoformat()
        elif v is pd.NaT or (isinstance(v, float) and math.isnan(v)) or v is pd.NA:
            v = None
        elif hasattr(v, "item"):
            v = v.item()
        out[k] = v
    return out
