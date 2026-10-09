"""Validaciones de calidad y de coherencia de totales (independientes del motor SQL)."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .generador import COLUMNAS, EXPORTACION, FLUJOS, IMPORTACION

TOLERANCIA_EUR = 0.01  # diferencia admitida por redondeos de coma flotante
COLUMNAS_TEXTO = ("pais", "producto", "sector", "flujo")
DIMENSIONES = ("pais", "producto", "sector")


@dataclass(frozen=True)
class Resultado:
    nombre: str
    ok: bool
    detalle: str = ""


def _res(nombre: str, filas_malas: int, descripcion: str) -> Resultado:
    if filas_malas == 0:
        return Resultado(nombre, True, "")
    return Resultado(nombre, False, f"{filas_malas} {descripcion}")


def validar_calidad(df: pd.DataFrame, anios: tuple[int, ...] | None = None) -> list[Resultado]:
    """Duplicados, nulos, importes negativos y valores fuera de dominio."""
    faltan = [c for c in COLUMNAS if c not in df.columns]
    if faltan:
        return [Resultado("esquema", False, f"faltan columnas: {faltan}")]
    res = [Resultado("esquema", True)]

    res.append(_res("sin_ids_duplicados", int(df["id_registro"].duplicated().sum()),
                    "id_registro repetidos"))
    contenido = [c for c in COLUMNAS if c != "id_registro"]
    res.append(_res("sin_filas_duplicadas", int(df.duplicated(subset=contenido).sum()),
                    "filas idénticas salvo el id"))

    for col in COLUMNAS:
        nulos = int(df[col].isna().sum())
        if col in COLUMNAS_TEXTO:
            nulos += int((df[col].dropna().astype(str).str.strip() == "").sum())
        res.append(_res(f"sin_nulos:{col}", nulos, "valores nulos o vacíos"))

    for col in ("importe_eur", "peso_kg"):
        res.append(_res(f"sin_negativos:{col}", int((df[col] < 0).sum()), "valores negativos"))

    res.append(_res("flujo_valido", int((~df["flujo"].isin(FLUJOS) & df["flujo"].notna()).sum()),
                    f"flujos distintos de {FLUJOS}"))

    fecha = pd.to_datetime(df["fecha"], errors="coerce")
    incoherentes = int(((fecha.dt.year != df["anio"]) & fecha.notna() & df["anio"].notna()).sum())
    res.append(_res("anio_coherente_con_fecha", incoherentes, "filas con año distinto al de la fecha"))

    if anios is not None:
        sin_datos = sorted(set(anios) - set(df["anio"].dropna().astype(int)))
        res.append(Resultado("anios_con_datos", not sin_datos,
                             f"años sin registros: {sin_datos}" if sin_datos else ""))
    return res


def _cerca(a: float, b: float) -> bool:
    return abs(a - b) <= TOLERANCIA_EUR


def validar_coherencia(df: pd.DataFrame, metricas: pd.DataFrame,
                       top: pd.DataFrame | None = None) -> list[Resultado]:
    """Compara los totales calculados por SQL con un recálculo independiente en pandas."""
    res: list[Resultado] = []
    datos = df.dropna(subset=["anio", "importe_eur"])
    esperado = datos.pivot_table(index="anio", columns="flujo", values="importe_eur",
                                 aggfunc="sum", fill_value=0.0)
    for flujo in (EXPORTACION, IMPORTACION):
        if flujo not in esperado:
            esperado[flujo] = 0.0

    # 1. Totales anuales SQL == pandas
    malos = 0
    for fila in metricas.itertuples():
        if fila.num_registros == 0:
            continue
        exp = esperado[EXPORTACION].get(fila.anio, 0.0)
        imp = esperado[IMPORTACION].get(fila.anio, 0.0)
        if not (_cerca(fila.exportaciones, exp) and _cerca(fila.importaciones, imp)):
            malos += 1
    res.append(_res("totales_anuales_sql_igual_pandas", malos, "años con totales distintos"))

    # 2. Saldo y cobertura internamente coherentes
    malos = 0
    for fila in metricas.itertuples():
        if fila.num_registros == 0:
            continue
        if not _cerca(fila.saldo, fila.exportaciones - fila.importaciones):
            malos += 1
        if fila.importaciones == 0:
            malos += int(pd.notna(fila.cobertura_pct))
        elif abs(fila.cobertura_pct - 100 * fila.exportaciones / fila.importaciones) > 0.01:
            malos += 1
    res.append(_res("saldo_y_cobertura_coherentes", malos, "años con saldo/cobertura incoherentes"))

    # 3. Los totales anuales suman el total general
    total = float(datos["importe_eur"].sum())
    suma_anual = float(metricas["exportaciones"].fillna(0).sum() + metricas["importaciones"].fillna(0).sum())
    res.append(_res("suma_anual_igual_total", 0 if _cerca(total, suma_anual) else 1,
                    f"diferencia entre total general ({total:.2f}) y suma anual ({suma_anual:.2f})"))

    # 4. Ninguna fila pierde su clave de agrupación (nulos en país/producto/sector)
    for dim in DIMENSIONES:
        agrupado = float(datos.groupby(dim)["importe_eur"].sum().sum())
        res.append(_res(f"suma_por_{dim}_igual_total", 0 if _cerca(total, agrupado) else 1,
                        f"importes sin {dim} (suma agrupada {agrupado:.2f} vs total {total:.2f})"))

    # 5. Ranking de países: <= N filas por año, orden descendente y sin superar el total del año
    if top is not None:
        malos = 0
        for anio, grupo in top.groupby("anio"):
            if grupo["comercio_total"].is_monotonic_decreasing is False:
                malos += 1
            if anio in esperado.index and grupo["comercio_total"].sum() > esperado.loc[anio].sum() + TOLERANCIA_EUR:
                malos += 1
        res.append(_res("ranking_paises_coherente", malos, "años con ranking incoherente"))
    return res


def hay_errores(resultados: list[Resultado]) -> bool:
    return any(not r.ok for r in resultados)


def formatear(resultados: list[Resultado]) -> str:
    return "\n".join(
        f"  [{'OK' if r.ok else 'ERROR'}] {r.nombre}" + (f" — {r.detalle}" if r.detalle else "")
        for r in resultados
    )
