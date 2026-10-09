"""Benchmarks sobre el lakehouse de 1 M de operaciones.

Uso (desde comercio_exterior/):  PYTHONPATH=src python scripts/benchmark.py [--destino datos/lakehouse]
Escribe docs/benchmark_resultados.json y muestra un resumen en texto.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import socket
import statistics
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

import duckdb

from comercio_exterior.analitica import Filtros, Motor
from comercio_exterior.analitica.sql import parametros_dimension, parametros_medida, renderizar
from comercio_exterior.lakehouse import Lakehouse, Rutas


def pct(xs, q):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(q * (len(xs) - 1))))]


def medir(fn, n=15):
    t0 = time.perf_counter()
    fn()
    frio = time.perf_counter() - t0
    ts = []
    for _ in range(n):
        t = time.perf_counter()
        fn()
        ts.append((time.perf_counter() - t) * 1000)
    return {"frio_ms": round(frio * 1000, 1), "p50_ms": round(statistics.median(ts), 1),
            "p95_ms": round(pct(ts, 0.95), 1), "min_ms": round(min(ts), 1)}


def tam(ruta: Path) -> float:
    return round(sum(f.stat().st_size for f in ruta.rglob("*") if f.is_file()) / 1e6, 1)


def pipeline(destino: Path) -> dict:
    lk = Lakehouse(destino)
    ing = lk.control.ingestas()
    r = Rutas(destino)
    con = duckdb.connect()
    filas = lambda g: con.execute(f"SELECT count(*) FROM read_parquet('{g}', hive_partitioning=false)").fetchone()[0]  # noqa: E731
    out = {
        "ingestas": len(ing),
        "suma_s": {k: round(float(ing[c].sum()), 1) for k, c in (("bronze", "dur_bronze_s"), ("silver", "dur_silver_s"), ("gold", "dur_gold_s"))},
        "por_ingesta_s": {
            "silver_mediana": round(float(ing["dur_silver_s"].median()), 2), "silver_max": round(float(ing["dur_silver_s"].max()), 2),
            "gold_mediana": round(float(ing["dur_gold_s"].median()), 2), "gold_max": round(float(ing["dur_gold_s"].max()), 2)},
        "periodos_reescritos_por_ingesta_mediana": float(ing["periodos_afectados"].str.count(",").add(1).median()),
        "tamano_mb": {"bronze": tam(r.bronze), "silver": tam(r.silver), "rechazados_y_descartes": round(tam(r.rechazados) + tam(r.descartes), 1),
                      "gold": tam(r.gold)},
        "filas": {"bronze": filas(f"{r.bronze}/*/part-0.parquet"), "silver": filas(f"{r.silver}/*/part.parquet"),
                  "gold": filas(f"{r.hechos}/*/part.parquet")},
    }
    lk.cerrar()
    return out


def consultas(motor: Motor) -> dict:
    f_all = Filtros.crear()
    f_filtro = Filtros.crear("2023-01", "2024-12", paises=["DE", "FR", "IT"], sectores=["S02", "S07"])
    pais, prod = parametros_dimension("pais"), parametros_dimension("producto")
    casos = {
        "resumen": lambda f: renderizar("resumen", f),
        "serie_mensual": lambda f: renderizar("serie_mensual", f),
        "serie_anual": lambda f: renderizar("serie_anual", f),
        "tabla_paises": lambda f: renderizar("tabla", f, **pais, orden="comercio_total_eur", sentido="DESC", limite=25, desplazamiento=0),
        "tabla_productos_200": lambda f: renderizar("tabla", f, **prod, orden="comercio_total_eur", sentido="DESC", limite=25, desplazamiento=0),
        "top10_resto": lambda f: renderizar("top", f, **pais, **parametros_medida("comercio_total", 10, "desc")),
        "contribucion": lambda f: renderizar("contribucion", f, **pais, **parametros_medida("comercio_total", 10, "desc")),
        "ranking": lambda f: renderizar("ranking", f, **pais, **parametros_medida("comercio_total", 10, "desc", forma="ranking")),
    }
    res = {}
    for nombre, fn in casos.items():
        for etiqueta, f in (("sin_filtros", f_all), ("con_filtros", f_filtro)):
            sql = fn(f)
            res[f"{nombre}/{etiqueta}"] = medir(lambda: motor.ejecutar_sql(sql, usar_cache=False))
    return res


def gold_vs_silver(destino: Path, motor: Motor) -> dict:
    """Mismas consultas, pero agregando silver (1 M de filas) al vuelo en lugar de leer gold."""
    r = Rutas(destino)
    con = duckdb.connect()
    con.execute(f"""CREATE VIEW hechos_mensual AS SELECT CAST(date_trunc('month', fecha) AS DATE) AS mes_inicio,
        CAST(year(fecha) AS INTEGER) AS anio, CAST(month(fecha) AS INTEGER) AS mes, pais_codigo, producto_codigo,
        SUM(CASE WHEN flujo='EXPORTACION' THEN importe_eur ELSE 0 END) AS exportaciones_eur,
        SUM(CASE WHEN flujo='IMPORTACION' THEN importe_eur ELSE 0 END) AS importaciones_eur,
        SUM(CASE WHEN flujo='EXPORTACION' THEN peso_kg ELSE 0 END) AS peso_exportado_kg,
        SUM(CASE WHEN flujo='IMPORTACION' THEN peso_kg ELSE 0 END) AS peso_importado_kg,
        CAST(SUM(CASE WHEN flujo='EXPORTACION' THEN unidades ELSE 0 END) AS BIGINT) AS unidades_exportadas,
        CAST(SUM(CASE WHEN flujo='IMPORTACION' THEN unidades ELSE 0 END) AS BIGINT) AS unidades_importadas,
        count(*) FILTER (WHERE flujo='EXPORTACION') AS n_op_exportacion, count(*) FILTER (WHERE flujo='IMPORTACION') AS n_op_importacion
        FROM read_parquet('{r.silver}/*/part.parquet', hive_partitioning=false) GROUP BY 1,2,3,4,5""")
    for t in ("dim_pais", "dim_producto", "dim_mes"):
        con.execute(f"CREATE VIEW {t} AS SELECT * FROM read_parquet('{r.gold / (t + '.parquet')}')")
    f = Filtros.crear("2023-01", "2024-12", paises=["DE", "FR", "IT"], sectores=["S02", "S07"])
    pais = parametros_dimension("pais")
    sqls = {"resumen": renderizar("resumen", f), "serie_mensual": renderizar("serie_mensual", f),
            "top10_resto": renderizar("top", f, **pais, **parametros_medida("comercio_total", 10, "desc"))}
    out = {}
    for nombre, sql in sqls.items():
        base = medir(lambda: con.execute(sql).fetchall(), n=5)
        gold = medir(lambda: motor.ejecutar_sql(sql, usar_cache=False), n=15)
        out[nombre] = {"silver_al_vuelo_p50_ms": base["p50_ms"], "gold_p50_ms": gold["p50_ms"],
                       "mejora_x": round(base["p50_ms"] / max(gold["p50_ms"], 0.1), 1)}
    return out


def concurrencia_motor(destino: Path) -> dict:
    """Consultas distintas (sin caché) lanzadas desde varios hilos contra un único Motor/DuckDB."""
    from concurrent.futures import ThreadPoolExecutor
    paises = ["DE", "FR", "IT", "PT", "GB", "US", "CN", "NL", "BE", "MA"]
    qs = [renderizar("resumen", Filtros.crear(f"{2018 + i % 5}-{1 + i % 12:02d}", f"{2023 + i % 3}-{1 + (i * 5) % 12:02d}",
                                              paises=[paises[i % 10], paises[(i * 3 + 1) % 10]])) for i in range(160)]
    motor = Motor(destino)
    motor.ejecutar_sql(qs[0], usar_cache=False)
    out = {}
    for clientes in (1, 4, 8):
        lat = []

        def run(q):
            t = time.perf_counter()
            motor.ejecutar_sql(q, usar_cache=False)
            lat.append((time.perf_counter() - t) * 1000)
        t0 = time.perf_counter()
        with ThreadPoolExecutor(clientes) as ex:
            list(ex.map(run, qs))
        out[f"{clientes}_clientes"] = {"consultas_por_s": round(len(qs) / (time.perf_counter() - t0), 1),
                                       "p50_ms": round(statistics.median(lat), 1), "p95_ms": round(pct(lat, 0.95), 1)}
    motor.cerrar()
    return out


def api(destino: Path) -> dict:
    s = socket.socket(); s.bind(("127.0.0.1", 0)); puerto = s.getsockname()[1]; s.close()
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")}
    proc = subprocess.Popen([sys.executable, "-m", "comercio_exterior.cli", "servir", "--destino", str(destino), "--puerto", str(puerto)],
                            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{puerto}/api/v1"
    for _ in range(100):
        try:
            urllib.request.urlopen(base + "/salud", timeout=1); break
        except Exception:
            time.sleep(0.1)

    def get(ruta):
        t = time.perf_counter()
        with urllib.request.urlopen(base + ruta) as r:
            r.read()
        return (time.perf_counter() - t) * 1000

    paises = ["DE", "FR", "IT", "PT", "GB", "US", "CN", "NL", "BE", "MA"]

    def variados(i):   # peticiones distintas (>600 combinaciones) para que la caché no ayude
        return (f"/resumen?desde={2018 + i % 5}-{1 + i % 12:02d}&hasta={2023 + i % 3}-{1 + (i * 5) % 12:02d}"
                f"&pais={paises[i % 10]}&pais={paises[(i * 3 + 1) % 10]}&producto=P{1 + i % 200:03d}&producto=P{1 + (i * 7) % 200:03d}")

    res = {}
    try:
        res["resumen_misma_peticion_(cache)_p50_ms"] = round(statistics.median([get("/resumen?desde=2023-01&hasta=2023-12") for _ in range(50)]), 1)
        res["resumen_peticiones_distintas_(sin_cache)_p50_ms"] = round(statistics.median([get(variados(1000 + i)) for i in range(60)]), 1)
        res["top10_p50_ms"] = round(statistics.median([get("/top?dimension=pais&n=10&desde=2023-01&hasta=2023-12") for _ in range(30)]), 1)
        res["calidad_primera_ms"] = round(get("/calidad"), 0)
        res["calidad_con_cache_ms"] = round(get("/calidad"), 1)
        for hilos in (1, 4, 8):
            lat, n = [], 30
            def tarea(k):
                for j in range(n):
                    lat.append(get(variados(5000 + hilos * 1000 + k * n + j)))
            t0 = time.perf_counter()
            ts = [threading.Thread(target=tarea, args=(k,)) for k in range(hilos)]
            [t.start() for t in ts]; [t.join() for t in ts]
            dur = time.perf_counter() - t0
            res[f"concurrencia_{hilos}_hilos"] = {"peticiones_por_s": round(hilos * n / dur, 1), "p50_ms": round(statistics.median(lat), 1),
                                                   "p95_ms": round(pct(lat, 0.95), 1)}
    finally:
        proc.terminate(); proc.wait(timeout=10)
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--destino", default="datos/lakehouse")
    ap.add_argument("--salida", default="docs/benchmark_resultados.json")
    a = ap.parse_args()
    destino = Path(a.destino)
    motor = Motor(destino)
    resultado = {
        "entorno": {"python": platform.python_version(), "duckdb": duckdb.__version__, "cpus": os.cpu_count(),
                    "plataforma": platform.platform()},
        "pipeline": pipeline(destino),
    }
    print("pipeline:", json.dumps(resultado["pipeline"], indent=1, ensure_ascii=False))
    resultado["consultas_gold"] = consultas(motor)
    for k, v in resultado["consultas_gold"].items():
        print(f"  {k:<40} p50 {v['p50_ms']:>7} ms  p95 {v['p95_ms']:>7} ms  frío {v['frio_ms']:>7} ms")
    resultado["gold_vs_silver"] = gold_vs_silver(destino, motor)
    print("gold vs silver:", json.dumps(resultado["gold_vs_silver"], ensure_ascii=False))
    resultado["concurrencia_motor_sin_cache"] = concurrencia_motor(destino)
    print("concurrencia motor:", json.dumps(resultado["concurrencia_motor_sin_cache"], ensure_ascii=False))
    resultado["api"] = api(destino)
    print("api:", json.dumps(resultado["api"], indent=1, ensure_ascii=False))
    Path(a.salida).parent.mkdir(parents=True, exist_ok=True)
    Path(a.salida).write_text(json.dumps(resultado, indent=2, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
