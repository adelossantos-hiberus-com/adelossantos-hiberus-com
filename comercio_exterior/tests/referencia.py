"""Implementación de referencia, independiente del SQL, de las métricas sobre pandas.

Parte de la *verdad* generada por el simulador (no del lakehouse), de modo que contrasta a la vez el
pipeline (bronze→silver→gold) y las consultas.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from comercio_exterior.catalogos import CATALOGO


def preparar(verdad: pd.DataFrame) -> pd.DataFrame:
    df = verdad.copy()
    df["fecha"] = pd.to_datetime(df["fecha"])
    df = df.merge(CATALOGO.dim_producto(), on="producto_codigo").merge(CATALOGO.dim_pais(), on="pais_codigo")
    df["mes"] = df["fecha"].dt.to_period("M")
    es_exp = df["flujo"] == "EXPORTACION"
    df["exp"] = np.where(es_exp, df["importe_eur"], 0.0)
    df["imp"] = np.where(es_exp, 0.0, df["importe_eur"])
    df["peso"] = df["peso_kg"]
    df["uds"] = df["unidades"]
    df["n"] = 1
    return df


def filtrar(df, paises=(), productos=(), sectores=(), subsectores=()):
    if paises:
        df = df[df["pais_codigo"].isin(paises)]
    if productos:
        df = df[df["producto_codigo"].isin(productos)]
    if sectores:
        df = df[df["sector_codigo"].isin(sectores)]
    if subsectores:
        df = df[df["subsector_codigo"].isin(subsectores)]
    return df


def pct(a, b):
    if a is None or b is None or pd.isna(a) or pd.isna(b) or b == 0:
        return np.nan
    return 100.0 * (a - b) / abs(b)


def _suma(s):
    return s.sum() if len(s) else np.nan


def _ventanas(df, desde, hasta):
    d, h = pd.Period(desde, "M"), pd.Period(hasta, "M")
    a = df[(df["mes"] >= d) & (df["mes"] <= h)]
    p = df[(df["mes"] >= d - 12) & (df["mes"] <= h - 12)]
    return a, p


def resumen(df, desde, hasta, **dims):
    a, p = _ventanas(filtrar(df, **dims), desde, hasta)
    exp, imp = _suma(a["exp"]), _suma(a["imp"])
    pe, pi = _suma(p["exp"]), _suma(p["imp"])
    return {
        "exportaciones_eur": exp, "importaciones_eur": imp, "saldo_eur": exp - imp, "comercio_total_eur": exp + imp,
        "cobertura_pct": 100 * exp / imp if imp else np.nan, "n_operaciones": len(a),
        "peso_kg": _suma(a["peso"]), "unidades": _suma(a["uds"]),
        "exportaciones_previo_eur": pe, "importaciones_previo_eur": pi, "saldo_previo_eur": pe - pi,
        "var_exportaciones_pct": pct(exp, pe), "var_importaciones_pct": pct(imp, pi),
        "var_comercio_total_pct": pct(exp + imp, pe + pi), "var_saldo_eur": (exp - imp) - (pe - pi),
    }


def _mensual_completo(df, desde, hasta):
    d, h = pd.Period(desde, "M"), pd.Period(hasta, "M")
    meses = pd.period_range(pd.Period(f"{d.year - 1}-01", "M"), h, freq="M")
    g = df.groupby("mes").agg(exp=("exp", "sum"), imp=("imp", "sum"), n=("n", "sum")).reindex(meses)
    g["n"] = g["n"].fillna(0)
    g["anio"] = [m.year for m in meses]
    g["exp_acum"] = g["exp"].fillna(0).groupby(g["anio"]).cumsum()
    g["imp_acum"] = g["imp"].fillna(0).groupby(g["anio"]).cumsum()
    for c in ("exp", "imp", "exp_acum", "imp_acum"):
        g[c + "_prev"] = g[c].shift(12)
    return g, d, h


def serie_mensual(df, desde, hasta, **dims):
    g, d, h = _mensual_completo(filtrar(df, **dims), desde, hasta)
    g = g[(g.index >= d) & (g.index <= h)]
    filas = []
    for m, r in g.iterrows():
        filas.append({
            "mes_inicio": m.start_time.date(), "n_operaciones": int(r["n"]),
            "exportaciones_eur": r["exp"], "importaciones_eur": r["imp"], "saldo_eur": r["exp"] - r["imp"],
            "exportaciones_acum_eur": r["exp_acum"], "importaciones_acum_eur": r["imp_acum"],
            "saldo_acum_eur": r["exp_acum"] - r["imp_acum"],
            "cobertura_acum_pct": 100 * r["exp_acum"] / r["imp_acum"] if r["imp_acum"] else np.nan,
            "var_exportaciones_pct": pct(r["exp"], r["exp_prev"]), "var_importaciones_pct": pct(r["imp"], r["imp_prev"]),
            "var_saldo_eur": (r["exp"] - r["imp"]) - (r["exp_prev"] - r["imp_prev"]),
            "var_exportaciones_acum_pct": pct(r["exp_acum"], r["exp_acum_prev"]),
            "var_importaciones_acum_pct": pct(r["imp_acum"], r["imp_acum_prev"]),
        })
    return filas


def serie_anual(df, desde, hasta, **dims):
    g, d, h = _mensual_completo(filtrar(df, **dims), desde, hasta)
    w = g[(g.index >= d) & (g.index <= h)]
    filas = []
    for anio, x in w.groupby("anio"):
        exp, imp = x["exp"].sum(min_count=1), x["imp"].sum(min_count=1)
        pe, pi = x["exp_prev"].sum(min_count=1), x["imp_prev"].sum(min_count=1)
        filas.append({
            "anio": int(anio), "meses_en_periodo": len(x), "meses_con_datos": int(x["exp"].notna().sum()),
            "n_operaciones": int(x["n"].sum()), "exportaciones_eur": exp, "importaciones_eur": imp,
            "saldo_eur": exp - imp, "cobertura_pct": 100 * exp / imp if imp == imp and imp else np.nan,
            "var_exportaciones_pct": pct(exp, pe), "var_importaciones_pct": pct(imp, pi),
            "var_comercio_total_pct": pct(exp + imp, pe + pi), "var_saldo_eur": (exp - imp) - (pe - pi),
        })
    return filas


CLAVES = {"pais": ("pais_codigo", "pais"), "producto": ("producto_codigo", "producto"), "sector": ("sector_codigo", "sector"),
          "subsector": ("subsector_codigo", "subsector"), "region": ("region", "region")}


def _agrupar(df, dimension, **agg):
    """Agrupa por la dimensión y devuelve columnas `clave` y `nombre` (iguales en `region`)."""
    clave, nombre = CLAVES[dimension]
    d = df.assign(clave=df[clave], nombre=df[nombre])
    return d.groupby(["clave", "nombre"]).agg(**agg)


def _valor(medida, exp, imp):
    return {"exportaciones": exp, "importaciones": imp, "comercio_total": exp + imp, "saldo": exp - imp}[medida]


def tabla(df, dimension, desde, hasta, **dims):
    a, p = _ventanas(filtrar(df, **dims), desde, hasta)
    g = _agrupar(a, dimension, exp=("exp", "sum"), imp=("imp", "sum"), n=("n", "sum"), peso=("peso", "sum"),
                 uds=("uds", "sum")).reset_index()
    gp = _agrupar(p, dimension, exp_prev=("exp", "sum"), imp_prev=("imp", "sum")).reset_index().drop(columns="nombre").set_index("clave")
    g = g.merge(gp, left_on="clave", right_index=True, how="left").fillna({"exp_prev": 0.0, "imp_prev": 0.0})
    te, ti = g["exp"].sum(), g["imp"].sum()
    g["total"] = g["exp"] + g["imp"]
    g["saldo"] = g["exp"] - g["imp"]
    g["cobertura"] = [100 * e / i if i else np.nan for e, i in zip(g["exp"], g["imp"])]
    g["cuota_comercio"] = 100 * g["total"] / (te + ti) if te + ti else np.nan
    g["cuota_exp"] = 100 * g["exp"] / te if te else np.nan
    g["cuota_imp"] = 100 * g["imp"] / ti if ti else np.nan
    g["var_exp"] = [pct(a_, b_) for a_, b_ in zip(g["exp"], g["exp_prev"])]
    g["var_imp"] = [pct(a_, b_) for a_, b_ in zip(g["imp"], g["imp_prev"])]
    g["ranking"] = g["total"].rank(method="min", ascending=False).astype(int)
    return g.sort_values("total", ascending=False, kind="stable").reset_index(drop=True)


def top(df, dimension, medida, n, desde, hasta, sentido="desc", **dims):
    a, _ = _ventanas(filtrar(df, **dims), desde, hasta)
    g = _agrupar(a, dimension, exp=("exp", "sum"), imp=("imp", "sum")).reset_index()
    g["valor"] = _valor(medida, g["exp"], g["imp"])
    g = g.sort_values(["valor", "clave"], ascending=[sentido == "asc", True], kind="stable").reset_index(drop=True)
    cabeza, resto = g.head(n), g.iloc[n:]
    filas = [{"clave": r["clave"], "nombre": r["nombre"], "exp": r["exp"], "imp": r["imp"], "valor": r["valor"], "es_resto": 0}
             for _, r in cabeza.iterrows()]
    if len(resto):
        filas.append({"clave": "RESTO", "nombre": "Resto", "exp": resto["exp"].sum(), "imp": resto["imp"].sum(),
                      "valor": resto["valor"].sum(), "es_resto": 1})
    total = g["valor"].sum()
    for f in filas:
        f["cuota_pct"] = np.nan if medida == "saldo" or not total else 100 * f["valor"] / total
    return filas


def contribucion(df, dimension, medida, n, desde, hasta, **dims):
    a, p = _ventanas(filtrar(df, **dims), desde, hasta)
    ga = _agrupar(a, dimension, exp_a=("exp", "sum"), imp_a=("imp", "sum"))
    gp = _agrupar(p, dimension, exp_p=("exp", "sum"), imp_p=("imp", "sum"))
    g = ga.join(gp, how="outer").fillna(0.0).reset_index()
    g["act"] = _valor(medida, g["exp_a"], g["imp_a"])
    g["prev"] = _valor(medida, g["exp_p"], g["imp_p"])
    g["delta"] = g["act"] - g["prev"]
    t_prev = g["prev"].sum()
    g["contrib"] = 100 * g["delta"] / abs(t_prev) if t_prev else np.nan
    g["abs"] = g["delta"].abs()
    g = g.sort_values(["abs", "clave"], ascending=[False, True], kind="stable").reset_index(drop=True)
    filas = [{"clave": r["clave"], "valor_act": r["act"], "valor_prev": r["prev"], "variacion_eur": r["delta"],
              "contribucion_pp": r["contrib"], "es_resto": 0} for _, r in g.head(n).iterrows()]
    resto = g.iloc[n:]
    if len(resto):
        filas.append({"clave": "RESTO", "valor_act": resto["act"].sum(), "valor_prev": resto["prev"].sum(),
                      "variacion_eur": resto["delta"].sum(),
                      "contribucion_pp": resto["contrib"].sum(min_count=1), "es_resto": 1})
    total_act = g["act"].sum()
    crec = 100 * (total_act - t_prev) / abs(t_prev) if t_prev else np.nan
    return filas, crec


def ranking(df, dimension, medida, n, desde, hasta, sentido="desc", **dims):
    d = filtrar(df, **dims)
    a0, a1 = int(desde[:4]), int(hasta[:4])
    d = d[(d["fecha"].dt.year >= a0 - 1) & (d["fecha"].dt.year <= a1)]
    clave = CLAVES[dimension][0]
    g = d.assign(anio=d["fecha"].dt.year, clave=d[clave]).groupby(["anio", "clave"]).agg(
        exp=("exp", "sum"), imp=("imp", "sum")).reset_index()
    g["valor"] = _valor(medida, g["exp"], g["imp"])
    g = g.sort_values(["anio", "valor", "clave"], ascending=[True, sentido == "asc", True], kind="stable")
    g["posicion"] = g.groupby("anio").cumcount() + 1
    previa = g.set_index(["anio", "clave"])["posicion"]
    filas = []
    for _, r in g[(g["posicion"] <= n) & (g["anio"] >= a0) & (g["anio"] <= a1)].iterrows():
        pp = previa.get((r["anio"] - 1, r["clave"]), np.nan)
        filas.append({"anio": int(r["anio"]), "posicion": int(r["posicion"]), "clave": r["clave"], "valor": r["valor"],
                      "posicion_previa": pp, "cambio_posicion": pp - r["posicion"] if pp == pp else np.nan})
    return filas
