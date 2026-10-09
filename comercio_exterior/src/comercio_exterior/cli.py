"""Línea de comandos: construir el lakehouse, servir la aplicación y exportar el SQL de Databricks."""

from __future__ import annotations

import argparse
import shutil
import sys
import time
from pathlib import Path

from .simulacion import N_OPERACIONES, SEMILLA


def construir(args) -> int:
    from .lakehouse import Lakehouse
    from .simulacion import generar_operaciones, simular_entregas

    destino = Path(args.destino)
    if args.limpiar and destino.exists():
        shutil.rmtree(destino)
    t0 = time.perf_counter()
    maestro = generar_operaciones(args.n, args.semilla)
    sim = simular_entregas(maestro, args.semilla)
    t_gen = time.perf_counter() - t0
    print(f"Simulación: {len(maestro):,} operaciones en {len(sim.entregas)} entregas "
          f"({sim.inyectados['filas_entregadas']:,} filas con ruido) · {t_gen:.1f} s")
    if args.guardar_verdad:
        ruta = destino.parent / "verdad.parquet"
        ruta.parent.mkdir(parents=True, exist_ok=True)
        sim.verdad.to_parquet(ruta, index=False)
    lk = Lakehouse(destino, args.particion)
    entregas = sim.entregas[args.desde_entrega - 1: args.entregas or None]
    t1 = time.perf_counter()
    for e in entregas:
        t = time.perf_counter()
        r = lk.ingestar(e)
        if r.estado == "OMITIDA":
            print(f"  {e.ingesta_id} {e.fichero_origen}: omitida ({r.motivo_omision})")
        else:
            print(f"  {e.ingesta_id} {e.fichero_origen}: {r.filas_recibidas:>7,} filas · rechazadas {r.filas_rechazadas:>4} · "
                  f"descartes {sum(r.descartes_por_motivo.values()):>4} · {time.perf_counter() - t:5.2f} s")
    print(f"Carga completada en {time.perf_counter() - t1:.1f} s → {destino}")
    lk.cerrar()
    return 0


def servir(args) -> int:
    import uvicorn
    from .api.app import crear_app
    uvicorn.run(crear_app(args.destino), host=args.host, port=args.puerto, log_level="warning")
    return 0


def exportar_sql(args) -> int:
    from .analitica.exportar import exportar
    for ruta in exportar(Path(args.salida)):
        print("escrito", ruta)
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="comercio_exterior", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("construir", help="genera datos ficticios y los carga en bronze/silver/gold")
    c.add_argument("--destino", default="datos/lakehouse")
    c.add_argument("--n", type=int, default=N_OPERACIONES, help="operaciones del maestro (por defecto 1.000.000)")
    c.add_argument("--semilla", type=int, default=SEMILLA)
    c.add_argument("--particion", choices=("trimestre", "anio"), default="trimestre")
    c.add_argument("--entregas", type=int, default=0, help="cargar solo hasta la entrega N (carga incremental)")
    c.add_argument("--desde-entrega", type=int, default=1)
    c.add_argument("--limpiar", action="store_true", help="borra el destino antes de cargar")
    c.add_argument("--guardar-verdad", action="store_true", help="guarda el estado correcto esperado (para contrastes)")
    c.set_defaults(f=construir)

    s = sub.add_parser("servir", help="arranca la API y la interfaz web")
    s.add_argument("--destino", default="datos/lakehouse")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--puerto", type=int, default=8000)
    s.set_defaults(f=servir)

    e = sub.add_parser("exportar-sql", help="genera las consultas para Databricks")
    e.add_argument("--salida", default="sql/databricks")
    e.set_defaults(f=exportar_sql)

    args = p.parse_args(argv)
    return args.f(args)


if __name__ == "__main__":
    sys.exit(main())
