"""API FastAPI y servidor de la interfaz web de comercio exterior (datos ficticios)."""

from __future__ import annotations

import csv
import io
import os
from enum import Enum
from pathlib import Path

from fastapi import Depends, FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from ..analitica import ErrorParametro, Filtros, Motor
from ..analitica.sql import COLUMNAS_ORDENABLES_TABLA, DIMENSIONES, MEDIDAS
from ..catalogos import ANIO_FIN, ANIO_INICIO, CATALOGO
from ..lakehouse import calidad
from ..lakehouse.control import Control
from ..lakehouse.rutas import Rutas

ESTATICOS = Path(__file__).resolve().parents[1] / "web" / "static"
TAMANO_MAX = 500

Dimension = Enum("Dimension", {k: k for k in DIMENSIONES}, type=str)
Medida = Enum("Medida", {k: k for k in MEDIDAS}, type=str)
Orden = Enum("Orden", {k: k for k in sorted(COLUMNAS_ORDENABLES_TABLA)}, type=str)
Sentido = Enum("Sentido", {"asc": "asc", "desc": "desc"}, type=str)
RecursoCsv = Enum("RecursoCsv", {k: k for k in ("tabla", "serie-mensual", "serie-anual", "top", "contribucion", "ranking")},
                  type=str)


class ErrorApi(Exception):
    def __init__(self, estado: int, codigo: str, mensaje: str, detalles: list | None = None):
        self.estado, self.codigo, self.mensaje, self.detalles = estado, codigo, mensaje, detalles or []


def _error(estado: int, codigo: str, mensaje: str, detalles=None) -> JSONResponse:
    return JSONResponse(status_code=estado, content={"error": {"codigo": codigo, "mensaje": mensaje,
                                                               "detalles": detalles or []}})


def _traducir(err: dict) -> dict:
    campo = ".".join(str(x) for x in err["loc"] if x not in ("query", "path"))
    t, ctx = err["type"], err.get("ctx", {})
    if t == "greater_than_equal":
        msg = f"debe ser mayor o igual que {ctx.get('ge')}"
    elif t == "less_than_equal":
        msg = f"debe ser menor o igual que {ctx.get('le')}"
    elif t in ("int_parsing", "int_from_float"):
        msg = "debe ser un número entero"
    elif t in ("enum", "literal_error"):
        msg = f"valor no permitido; opciones: {ctx.get('expected', '')}".replace("'", "")
    elif t == "missing":
        msg = "es obligatorio"
    else:
        msg = err.get("msg", "valor no válido")
    return {"campo": campo, "mensaje": msg}


def _lista(valores: list[str] | None) -> list[str]:
    """Admite ?pais=ES&pais=FR y ?pais=ES,FR."""
    out: list[str] = []
    for v in valores or []:
        out.extend(x for x in v.split(",") if x.strip())
    return out


def crear_app(raiz_lake: str | Path | None = None) -> FastAPI:
    raiz = Path(raiz_lake or os.environ.get("COMERCIO_LAKEHOUSE", "datos/lakehouse"))
    app = FastAPI(title="API de comercio exterior (datos ficticios)", version="1.0.0",
                  description="Indicadores, series, rankings y calidad de datos sobre un lakehouse Parquet "
                              "(bronze/silver/gold) generado con datos 100 % ficticios.")
    app.state.raiz = raiz
    app.state.motor = Motor(raiz)
    app.state.cache_calidad = (None, None)

    # ---------------------------------------------------------------- errores
    @app.exception_handler(ErrorParametro)
    async def _h_param(_: Request, exc: ErrorParametro):
        return _error(422, "parametro_no_valido", exc.mensaje, [{"campo": exc.campo, "mensaje": exc.mensaje}])

    @app.exception_handler(ErrorApi)
    async def _h_api(_: Request, exc: ErrorApi):
        return _error(exc.estado, exc.codigo, exc.mensaje, exc.detalles)

    @app.exception_handler(RequestValidationError)
    async def _h_val(_: Request, exc: RequestValidationError):
        det = [_traducir(e) for e in exc.errors()]
        return _error(422, "parametro_no_valido",
                      "; ".join(f"'{d['campo']}' {d['mensaje']}" for d in det), det)

    @app.exception_handler(Exception)
    async def _h_inesperado(_: Request, exc: Exception):
        return _error(500, "error_interno", "Se ha producido un error inesperado al procesar la solicitud.",
                      [{"tipo": type(exc).__name__}])

    # ---------------------------------------------------------------- dependencias
    def motor() -> Motor:
        m: Motor = app.state.motor
        if not m.datos_disponibles():
            raise ErrorApi(503, "sin_datos",
                           "Todavía no hay datos cargados. Ejecuta `python -m comercio_exterior.cli construir` "
                           "para generar el lakehouse.")
        return m

    def filtros(desde: str | None = Query(None, description="Mes inicial AAAA-MM", examples=["2022-01"]),
                hasta: str | None = Query(None, description="Mes final AAAA-MM", examples=["2024-12"]),
                pais: list[str] = Query([], description="Códigos ISO de país (repetible o separados por coma)"),
                producto: list[str] = Query([], description="Códigos de producto P001…P200"),
                sector: list[str] = Query([], description="Códigos de sector S01…S10"),
                subsector: list[str] = Query([], description="Códigos de subsector, p. ej. S01-2")) -> Filtros:
        return Filtros.crear(desde, hasta, _lista(pais), _lista(producto), _lista(sector), _lista(subsector))

    def envoltorio(m: Motor, f: Filtros, datos, **extra) -> dict:
        return {"filtros": f.como_dict(), "version_datos": m.version_datos(), **extra, "datos": datos}

    # ---------------------------------------------------------------- API
    api = "/api/v1"

    @app.get(f"{api}/salud", tags=["sistema"], summary="Estado del servicio")
    def salud():
        m: Motor = app.state.motor
        return {"estado": "ok", "datos_disponibles": m.datos_disponibles(), "version_datos": m.version_datos()}

    @app.get(f"{api}/meta", tags=["sistema"], summary="Catálogos, rango de fechas y opciones disponibles")
    def meta(m: Motor = Depends(motor)):
        c = CATALOGO
        return {
            "rango": {"desde": f"{ANIO_INICIO}-01", "hasta": f"{ANIO_FIN}-12"},
            "paises": c.dim_pais().to_dict("records"),
            "sectores": [{"codigo": k, "nombre": v} for k, v in
                         c.productos[["sector_codigo", "sector"]].drop_duplicates().itertuples(index=False)],
            "subsectores": c.productos[["subsector_codigo", "subsector", "sector_codigo"]].drop_duplicates()
                            .to_dict("records"),
            "productos": c.productos[["producto_codigo", "producto", "subsector_codigo", "sector_codigo"]].to_dict("records"),
            "dimensiones": sorted(DIMENSIONES), "medidas": sorted(MEDIDAS),
            "columnas_ordenables": sorted(COLUMNAS_ORDENABLES_TABLA),
            "version_datos": m.version_datos(),
        }

    @app.get(f"{api}/resumen", tags=["análisis"], summary="Indicadores principales del periodo")
    def resumen(f: Filtros = Depends(filtros), m: Motor = Depends(motor)):
        return envoltorio(m, f, m.resumen(f))

    @app.get(f"{api}/serie/mensual", tags=["análisis"], summary="Serie mensual con acumulado anual e interanual")
    def serie_mensual(f: Filtros = Depends(filtros), m: Motor = Depends(motor)):
        return envoltorio(m, f, m.serie_mensual(f))

    @app.get(f"{api}/serie/anual", tags=["análisis"], summary="Serie anual con variación interanual homogénea")
    def serie_anual(f: Filtros = Depends(filtros), m: Motor = Depends(motor)):
        return envoltorio(m, f, m.serie_anual(f))

    @app.get(f"{api}/tabla", tags=["análisis"], summary="Tabla por dimensión con paginación y ordenación en servidor")
    def tabla(f: Filtros = Depends(filtros), m: Motor = Depends(motor),
              dimension: Dimension = Query(Dimension.pais), orden: Orden = Query(Orden.comercio_total_eur),
              sentido: Sentido = Query(Sentido.desc), pagina: int = Query(1, ge=1),
              tamano: int = Query(25, ge=1, le=TAMANO_MAX)):
        r = m.tabla(f, dimension.value, orden.value, sentido.value, pagina, tamano)
        paginas = max(1, -(-r["total"] // tamano))
        return envoltorio(m, f, r["filas"], paginacion={"pagina": pagina, "tamano": tamano, "total": r["total"],
                                                         "paginas": paginas},
                          orden={"campo": orden.value, "sentido": sentido.value}, dimension=dimension.value)

    @app.get(f"{api}/top", tags=["análisis"], summary="Top N con categoría «Resto»")
    def top(f: Filtros = Depends(filtros), m: Motor = Depends(motor), dimension: Dimension = Query(Dimension.pais),
            medida: Medida = Query(Medida.comercio_total), n: int = Query(10, ge=1, le=100),
            sentido: Sentido = Query(Sentido.desc)):
        return envoltorio(m, f, m.top(f, dimension.value, medida.value, n, sentido.value),
                          dimension=dimension.value, medida=medida.value, n=n)

    @app.get(f"{api}/contribucion", tags=["análisis"], summary="Contribución al crecimiento interanual")
    def contribucion(f: Filtros = Depends(filtros), m: Motor = Depends(motor),
                     dimension: Dimension = Query(Dimension.pais), medida: Medida = Query(Medida.comercio_total),
                     n: int = Query(10, ge=1, le=100)):
        return envoltorio(m, f, m.contribucion(f, dimension.value, medida.value, n),
                          dimension=dimension.value, medida=medida.value, n=n)

    @app.get(f"{api}/ranking", tags=["análisis"], summary="Ranking anual y cambio de posición")
    def ranking(f: Filtros = Depends(filtros), m: Motor = Depends(motor), dimension: Dimension = Query(Dimension.pais),
                medida: Medida = Query(Medida.comercio_total), n: int = Query(10, ge=1, le=100),
                sentido: Sentido = Query(Sentido.desc)):
        return envoltorio(m, f, m.ranking(f, dimension.value, medida.value, n, sentido.value),
                          dimension=dimension.value, medida=medida.value, n=n)

    # ---------------------------------------------------------------- exportación CSV
    @app.get(f"{api}/export/{{recurso}}.csv", tags=["exportación"], summary="Exporta el resultado completo en CSV")
    def exportar(recurso: RecursoCsv, f: Filtros = Depends(filtros), m: Motor = Depends(motor),
                 dimension: Dimension = Query(Dimension.pais), medida: Medida = Query(Medida.comercio_total),
                 n: int = Query(10, ge=1, le=100), orden: Orden = Query(Orden.comercio_total_eur),
                 sentido: Sentido = Query(Sentido.desc), sep: str = Query(",", pattern="^[,;]$"),
                 bom: bool = Query(True, description="Añade BOM UTF-8 (recomendado para Excel)")):
        r = recurso.value
        if r == "tabla":
            filas = m.tabla(f, dimension.value, orden.value, sentido.value, todo=True)["filas"]
        elif r == "serie-mensual":
            filas = m.serie_mensual(f)
        elif r == "serie-anual":
            filas = m.serie_anual(f)
        elif r == "top":
            filas = m.top(f, dimension.value, medida.value, n, sentido.value)
        elif r == "contribucion":
            filas = m.contribucion(f, dimension.value, medida.value, n)
        else:
            filas = m.ranking(f, dimension.value, medida.value, n, sentido.value)
        buf = io.StringIO()
        if bom:
            buf.write("﻿")
        if filas:
            w = csv.DictWriter(buf, fieldnames=list(filas[0].keys()), delimiter=sep, lineterminator="\n")
            w.writeheader()
            w.writerows(filas)
        return Response(buf.getvalue(), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="comercio_{r}.csv"'})

    # ---------------------------------------------------------------- calidad e ingestas
    @app.get(f"{api}/calidad", tags=["calidad"], summary="Controles de calidad y trazabilidad por capa")
    def calidad_datos():
        m: Motor = app.state.motor
        version, informe = app.state.cache_calidad
        if version != m.version_datos() or informe is None:
            informe = calidad.informe_calidad(raiz)
            app.state.cache_calidad = (m.version_datos(), informe)
        return {"version_datos": m.version_datos(), **informe}

    @app.get(f"{api}/calidad/rechazados", tags=["calidad"], summary="Registros rechazados (paginado)")
    def rechazados(pagina: int = Query(1, ge=1), tamano: int = Query(25, ge=1, le=TAMANO_MAX),
                   motivo: str | None = Query(None, max_length=40), ingesta_id: str | None = Query(None, max_length=20)):
        r = calidad.rechazados_paginados(raiz, pagina, tamano, motivo, ingesta_id)
        r["paginas"] = max(1, -(-r["total"] // tamano))
        return r

    @app.get(f"{api}/ingestas", tags=["ingestas"], summary="Seguimiento de ingestas")
    def ingestas():
        ctl = Control(Rutas(raiz))
        df = ctl.ingestas()
        filas = [calidad._serializar(r) for r in df.sort_values("ingesta_seq", ascending=False).to_dict("records")]
        ev = ctl.eventos()
        omitidas = int((ev["evento"] == "OMITIDA").sum()) if len(ev) else 0
        return {"datos": filas, "resumen": {
            "total": len(df), "completadas": int((df["estado"] == "COMPLETADA").sum()) if len(df) else 0,
            "fallidas": int((df["estado"] == "FALLIDA").sum()) if len(df) else 0,
            "en_curso": int((df["estado"] == "EN_CURSO").sum()) if len(df) else 0, "reintentos_omitidos": omitidas}}

    @app.get(f"{api}/ingestas/eventos", tags=["ingestas"], summary="Bitácora de eventos de ingesta")
    def eventos(limite: int = Query(100, ge=1, le=1000)):
        ev = Control(Rutas(raiz)).eventos()
        filas = [calidad._serializar(r) for r in ev.sort_values("ts", ascending=False).head(limite).to_dict("records")] if len(ev) else []
        return {"datos": filas}

    @app.get(f"{api}/ingestas/{{ingesta_id}}", tags=["ingestas"], summary="Detalle y trazabilidad de una ingesta")
    def ingesta(ingesta_id: str):
        det = calidad.detalle_ingesta(raiz, ingesta_id)
        if det is None:
            raise ErrorApi(404, "ingesta_no_encontrada", f"No existe la ingesta '{ingesta_id}'.")
        return det

    # ---------------------------------------------------------------- web
    @app.get("/", include_in_schema=False)
    def inicio():
        return FileResponse(ESTATICOS / "index.html")

    app.mount("/static", StaticFiles(directory=ESTATICOS), name="static")
    return app


def app_por_defecto() -> FastAPI:  # para `uvicorn comercio_exterior.api.app:app_por_defecto --factory`
    return crear_app()
