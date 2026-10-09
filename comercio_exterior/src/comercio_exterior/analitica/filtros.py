"""Filtros combinables (fecha, país, producto, sector) y su traducción a predicados SQL."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from ..catalogos import ANIO_FIN, ANIO_INICIO, CATALOGO

PRIMER_MES = date(ANIO_INICIO, 1, 1)
ULTIMO_MES = date(ANIO_FIN, 12, 1)

_RE_MES = re.compile(r"^(\d{4})-(\d{2})$")


class ErrorParametro(ValueError):
    """Parámetro de entrada no válido; el mensaje es apto para mostrarse al usuario."""

    def __init__(self, campo: str, mensaje: str):
        super().__init__(mensaje)
        self.campo = campo
        self.mensaje = mensaje


def parsear_mes(valor: str, campo: str) -> date:
    m = _RE_MES.match(valor or "")
    if not m:
        raise ErrorParametro(campo, f"'{valor}' no es un mes válido; usa el formato AAAA-MM (por ejemplo 2022-03).")
    anio, mes = int(m[1]), int(m[2])
    if not 1 <= mes <= 12:
        raise ErrorParametro(campo, f"'{valor}' no es un mes válido: el mes debe estar entre 01 y 12.")
    d = date(anio, mes, 1)
    if not PRIMER_MES <= d <= ULTIMO_MES:
        raise ErrorParametro(campo, f"'{valor}' está fuera del rango de datos ({PRIMER_MES:%Y-%m} a {ULTIMO_MES:%Y-%m}).")
    return d


def desplazar_meses(d: date, k: int) -> date:
    total = d.year * 12 + (d.month - 1) + k
    return date(total // 12, total % 12 + 1, 1)


def _validar_codigos(valores, validos: set[str], campo: str, que: str) -> tuple[str, ...]:
    out = []
    for v in valores or ():
        c = str(v).strip().upper()
        if not c:
            continue
        if c not in validos:
            ejemplo = ", ".join(sorted(validos)[:8])
            raise ErrorParametro(campo, f"{que} '{c}' no existe. Ejemplos válidos: {ejemplo}…")
        if c not in out:
            out.append(c)
    return tuple(sorted(out))


@dataclass(frozen=True)
class Filtros:
    desde: date = PRIMER_MES
    hasta: date = ULTIMO_MES
    paises: tuple[str, ...] = ()
    productos: tuple[str, ...] = ()
    sectores: tuple[str, ...] = ()
    subsectores: tuple[str, ...] = ()

    @classmethod
    def crear(cls, desde: str | None = None, hasta: str | None = None, paises=(), productos=(),
              sectores=(), subsectores=()) -> "Filtros":
        d = parsear_mes(desde, "desde") if desde else PRIMER_MES
        h = parsear_mes(hasta, "hasta") if hasta else ULTIMO_MES
        if d > h:
            raise ErrorParametro("desde", f"'desde' ({d:%Y-%m}) no puede ser posterior a 'hasta' ({h:%Y-%m}).")
        c = CATALOGO
        return cls(
            d, h,
            _validar_codigos(paises, set(c.paises["pais_codigo"]), "pais", "El país"),
            _validar_codigos(productos, set(c.productos["producto_codigo"]), "producto", "El producto"),
            _validar_codigos(sectores, set(c.productos["sector_codigo"]), "sector", "El sector"),
            _validar_codigos(subsectores, set(c.productos["subsector_codigo"]), "subsector", "El subsector"),
        )

    # --- ventanas temporales ---
    @property
    def desde_previo(self) -> date:
        return desplazar_meses(self.desde, -12)

    @property
    def hasta_previo(self) -> date:
        return desplazar_meses(self.hasta, -12)

    @property
    def inicio_ext_series(self) -> date:
        """Enero del año anterior al de `desde`: permite acumulados anuales y comparación interanual."""
        return date(self.desde.year - 1, 1, 1)

    # --- predicados ---
    def tiempo_ventanas(self) -> str:
        return (f"((h.mes_inicio >= DATE '{self.desde}' AND h.mes_inicio <= DATE '{self.hasta}')\n"
                f"          OR (h.mes_inicio >= DATE '{self.desde_previo}' AND h.mes_inicio <= DATE '{self.hasta_previo}'))")

    def tiempo_series(self) -> str:
        return f"h.mes_inicio >= DATE '{self.inicio_ext_series}' AND h.mes_inicio <= DATE '{self.hasta}'"

    def tiempo_anios(self) -> str:
        return (f"h.mes_inicio >= DATE '{self.desde.year - 1}-01-01' AND h.mes_inicio <= DATE '{self.hasta.year}-12-31'")

    def predicados_dimension(self) -> str:
        """Un predicado por línea; los filtros inactivos quedan comentados como ejemplo de uso."""
        def lista(vals):
            return ", ".join(f"'{v}'" for v in vals)
        reglas = [
            ("h.pais_codigo", self.paises, "'FR', 'DE'", "país"),
            ("h.producto_codigo", self.productos, "'P001', 'P002'", "producto"),
            ("p.sector_codigo", self.sectores, "'S01', 'S02'", "sector"),
            ("p.subsector_codigo", self.subsectores, "'S01-1', 'S01-2'", "subsector"),
        ]
        lineas = []
        for col, vals, ejemplo, nombre in reglas:
            if vals:
                lineas.append(f"AND {col} IN ({lista(vals)})  -- filtro {nombre}")
            else:
                lineas.append(f"-- AND {col} IN ({ejemplo})  -- filtro {nombre} (inactivo)")
        return "\n          ".join(lineas)

    def como_dict(self) -> dict:
        return {"desde": f"{self.desde:%Y-%m}", "hasta": f"{self.hasta:%Y-%m}", "paises": list(self.paises),
                "productos": list(self.productos), "sectores": list(self.sectores),
                "subsectores": list(self.subsectores)}
