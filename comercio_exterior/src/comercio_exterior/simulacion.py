"""Simulador de operaciones de comercio exterior y de las entregas que las transportan.

1. `generar_operaciones` crea el maestro limpio (reproducible, vectorizado).
2. `simular_entregas` lo reparte en entregas trimestrales e inyecta duplicados, reentregas,
   correcciones (versiones 2 y 3), correcciones obsoletas y registros inválidos.
3. Devuelve además la *verdad* (estado final correcto) y los contadores inyectados, que sirven
   de oráculo independiente para las pruebas.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .catalogos import ANIO_INICIO, ANIO_FIN, CATALOGO

EXPORTACION = "EXPORTACION"
IMPORTACION = "IMPORTACION"
N_OPERACIONES = 1_000_000
SEMILLA = 2025

COLUMNAS_OPERACION = ["operacion_id", "fecha", "flujo", "pais_codigo", "producto_codigo",
                      "importe_eur", "peso_kg", "unidades"]
COLUMNAS_ENTREGA = ["operacion_id", "version", "tipo_registro", "fecha", "flujo", "pais_codigo",
                    "producto_codigo", "importe_eur", "peso_kg", "unidades"]

# Peso de cada año en el número de operaciones (2020 deprimido) y estacionalidad mensual.
_PESO_ANIO = {2018: 0.118, 2019: 0.122, 2020: 0.105, 2021: 0.125, 2022: 0.133, 2023: 0.133,
              2024: 0.134, 2025: 0.130}
_PESO_MES = np.array([0.080, 0.078, 0.092, 0.082, 0.086, 0.084, 0.082, 0.056, 0.088, 0.092, 0.090, 0.090])
_INFLACION = {2018: 1.00, 2019: 1.01, 2020: 0.97, 2021: 1.04, 2022: 1.14, 2023: 1.19, 2024: 1.21, 2025: 1.24}
# Factor de importe por flujo y año (las exportaciones crecen más que las importaciones).
_TENDENCIA = {
    EXPORTACION: {2018: 1.00, 2019: 1.03, 2020: 0.92, 2021: 1.08, 2022: 1.18, 2023: 1.26, 2024: 1.31, 2025: 1.38},
    IMPORTACION: {2018: 1.00, 2019: 1.04, 2020: 0.90, 2021: 1.10, 2022: 1.24, 2023: 1.25, 2024: 1.22, 2025: 1.27},
}
_DIAS_MES = np.array([31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31])


def generar_operaciones(n: int = N_OPERACIONES, semilla: int = SEMILLA) -> pd.DataFrame:
    """Maestro limpio de `n` operaciones (2018–2025), reproducible por semilla."""
    if n < 1:
        raise ValueError("n debe ser al menos 1")
    rng = np.random.default_rng(semilla)
    anios = np.arange(ANIO_INICIO, ANIO_FIN + 1)
    p_anio = np.array([_PESO_ANIO[a] for a in anios])
    anio = rng.choice(anios, size=n, p=p_anio / p_anio.sum())
    mes = rng.choice(12, size=n, p=_PESO_MES / _PESO_MES.sum())            # 0..11
    bisiesto = (anio % 4 == 0) & ((anio % 100 != 0) | (anio % 400 == 0))
    dias = _DIAS_MES[mes] + ((mes == 1) & bisiesto)
    dia = (rng.random(n) * dias).astype(int)                                # 0..dias-1
    inicio = (anio - 1970).astype("datetime64[Y]").astype("datetime64[M]") + mes.astype("timedelta64[M]")
    fecha = inicio.astype("datetime64[D]") + dia.astype("timedelta64[D]")

    paises = CATALOGO.paises
    p_pais = paises["peso"].to_numpy(float)
    idx_pais = rng.choice(len(paises), size=n, p=p_pais / p_pais.sum())
    sesgo = paises["sesgo_export"].to_numpy(float)[idx_pais]
    exporta = rng.random(n) < sesgo / (1 + sesgo)

    prods = CATALOGO.productos
    p_prod = prods["peso"].to_numpy(float)
    idx_prod = rng.choice(len(prods), size=n, p=p_prod / p_prod.sum())

    tend_exp = np.array([_TENDENCIA[EXPORTACION][a] for a in anios])
    tend_imp = np.array([_TENDENCIA[IMPORTACION][a] for a in anios])
    infl = np.array([_INFLACION[a] for a in anios])
    pos = anio - ANIO_INICIO
    factor_anio = np.where(exporta, tend_exp[pos], tend_imp[pos]) * infl[pos]
    unidades = np.maximum(1, np.round(prods["unidades_tipicas"].to_numpy(float)[idx_prod]
                                       * np.exp(rng.normal(0, 0.8, n)))).astype(np.int64)
    precio = prods["precio_unitario_eur"].to_numpy(float)[idx_prod] * np.exp(rng.normal(0, 0.15, n))
    importe = np.round(unidades * precio * factor_anio, 2)
    peso = np.round(unidades * prods["peso_unitario_kg"].to_numpy(float)[idx_prod]
                    * np.exp(rng.normal(0, 0.10, n)), 2)

    df = pd.DataFrame({
        "fecha": fecha,
        "flujo": np.where(exporta, EXPORTACION, IMPORTACION),
        "pais_codigo": paises["pais_codigo"].to_numpy()[idx_pais],
        "producto_codigo": prods["producto_codigo"].to_numpy()[idx_prod],
        "importe_eur": importe,
        "peso_kg": np.maximum(peso, 0.01),
        "unidades": unidades,
    }).sort_values("fecha", kind="stable").reset_index(drop=True)
    df.insert(0, "operacion_id", ["OP-%08d" % i for i in range(1, n + 1)])
    return df[COLUMNAS_OPERACION]


@dataclass
class Entrega:
    ingesta_id: str
    fichero_origen: str
    periodo: str
    datos: pd.DataFrame          # COLUMNAS_ENTREGA, tal como llegaría de la fuente


@dataclass
class Simulacion:
    entregas: list[Entrega]
    verdad: pd.DataFrame         # estado final correcto de las operaciones (con correcciones válidas)
    inyectados: dict = field(default_factory=dict)


_DEFECTOS = ["fecha_formato", "fecha_imposible", "fecha_fuera_rango", "flujo", "pais", "producto",
             "importe_negativo", "importe_nulo", "peso_negativo", "unidades_nulas", "unidades_negativas"]


def _a_entrega(df: pd.DataFrame, version: int, tipo: str) -> pd.DataFrame:
    out = df[COLUMNAS_OPERACION].copy()
    out.insert(1, "version", np.int32(version))
    out.insert(2, "tipo_registro", tipo)
    out["fecha"] = pd.to_datetime(out["fecha"]).dt.strftime("%Y-%m-%d")
    out["unidades"] = out["unidades"].astype("Int64")
    return out[COLUMNAS_ENTREGA]


def _estropear(df: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    """Aplica un defecto distinto a cada fila (devuelve una copia en formato de entrega)."""
    out = df.copy().reset_index(drop=True)
    out["fecha"] = pd.to_datetime(out["fecha"]).dt.strftime("%Y-%m-%d")
    out["unidades"] = out["unidades"].astype("Int64")
    out.insert(1, "version", np.int32(1))
    out.insert(2, "tipo_registro", "ORIGINAL")
    tipos = rng.choice(_DEFECTOS, size=len(out))
    for i, t in enumerate(tipos):
        if t == "fecha_formato":
            out.at[i, "fecha"] = str(rng.choice(["", "N/D", "15/03/2021", "2021-3-1x"]))
        elif t == "fecha_imposible":
            out.at[i, "fecha"] = str(rng.choice(["2021-02-30", "2022-13-01", "2023-04-31"]))
        elif t == "fecha_fuera_rango":
            out.at[i, "fecha"] = str(rng.choice(["1999-05-05", "2031-01-01", "2017-12-31"]))
        elif t == "flujo":
            out.at[i, "flujo"] = str(rng.choice(["TRANSITO", "export", "", "X"]))
        elif t == "pais":
            out.at[i, "pais_codigo"] = str(rng.choice(["ZZ", "XX", ""]))
        elif t == "producto":
            out.at[i, "producto_codigo"] = str(rng.choice(["P999", "P000", ""]))
        elif t == "importe_negativo":
            out.at[i, "importe_eur"] = -abs(out.at[i, "importe_eur"]) - 1
        elif t == "importe_nulo":
            out.at[i, "importe_eur"] = np.nan
        elif t == "peso_negativo":
            out.at[i, "peso_kg"] = -abs(out.at[i, "peso_kg"]) - 0.5
        elif t == "unidades_nulas":
            out.at[i, "unidades"] = pd.NA
        else:
            out.at[i, "unidades"] = -3
    return out[COLUMNAS_ENTREGA]


def simular_entregas(maestro: pd.DataFrame, semilla: int = SEMILLA, *,
                     p_duplicado: float = 0.004, p_reentrega: float = 0.002,
                     p_correccion: float = 0.003, p_correccion2: float = 0.0005,
                     p_obsoleta: float = 0.0003, p_invalido: float = 0.002,
                     p_correccion_invalida: float = 0.0002) -> Simulacion:
    """Reparte el maestro en entregas trimestrales con ruido controlado (ver módulo)."""
    rng = np.random.default_rng(semilla + 1)
    m = maestro.reset_index(drop=True)
    trimestre = pd.to_datetime(m["fecha"]).dt.to_period("Q")
    periodos = sorted(trimestre.unique())
    trim_arr = trimestre.to_numpy()

    # estado vigente (verdad) por operación
    imp = m["importe_eur"].to_numpy().copy()
    peso = m["peso_kg"].to_numpy().copy()
    uni = m["unidades"].to_numpy().copy()
    version = np.ones(len(m), dtype=np.int32)

    entregadas = np.zeros(len(m), dtype=bool)
    emitidas: list[pd.DataFrame] = []     # correcciones emitidas (se reenvían obsoletas)
    entregas: list[Entrega] = []
    cont = dict(duplicados_internos=0, reentregas=0, correcciones_v2=0, correcciones_v3=0,
                correcciones_invalidas=0, obsoletas=0, invalidos=0)
    id_invalido = 90_000_000

    def correccion(idx: np.ndarray) -> pd.DataFrame:
        base = m.loc[idx, COLUMNAS_OPERACION].copy()
        base["importe_eur"] = np.round(imp[idx] * rng.uniform(0.70, 1.30, len(idx)), 2)
        base["unidades"] = np.maximum(1, np.round(uni[idx] * rng.uniform(0.8, 1.2, len(idx)))).astype(np.int64)
        base["peso_kg"] = np.round(np.maximum(peso[idx] * rng.uniform(0.9, 1.1, len(idx)), 0.01), 2)
        return base

    for k, per in enumerate(periodos):
        idx_base = np.flatnonzero(trim_arr == per)
        n_base = len(idx_base)
        partes = [_a_entrega(m.loc[idx_base], 1, "ORIGINAL")]

        # duplicados exactos dentro de la propia entrega
        n = int(n_base * p_duplicado)
        partes.append(_a_entrega(m.loc[rng.choice(idx_base, size=n, replace=False)], 1, "ORIGINAL"))
        cont["duplicados_internos"] += n

        if k > 0:
            previas = np.flatnonzero(entregadas)
            # reentrega (idéntica) de filas de entregas anteriores
            n = int(n_base * p_reentrega)
            partes.append(_a_entrega(m.loc[rng.choice(previas, size=n, replace=False)], 1, "ORIGINAL"))
            cont["reentregas"] += n

            # correcciones v3: operaciones que ya estaban en v2 antes de esta entrega
            cand3 = previas[version[previas] == 2]
            n3 = min(int(n_base * p_correccion2), len(cand3))
            # correcciones v2: operaciones aún en v1
            cand2 = previas[version[previas] == 1]
            n2 = min(int(n_base * p_correccion), len(cand2))
            for cand, nn, ver in ((cand3, n3, 3), (cand2, n2, 2)):
                if not nn:
                    continue
                sel = rng.choice(cand, size=nn, replace=False)
                df = correccion(sel)
                ent = _a_entrega(df, ver, "CORRECCION")
                partes.append(ent)
                emitidas.append(ent)
                imp[sel], peso[sel], uni[sel] = (df["importe_eur"].to_numpy(), df["peso_kg"].to_numpy(),
                                                 df["unidades"].to_numpy())
                version[sel] = ver
                cont["correcciones_v%d" % ver] += nn

            # correcciones inválidas (se rechazan; la verdad no cambia)
            n = int(n_base * p_correccion_invalida)
            if n:
                ci = rng.choice(previas, size=n, replace=False)
                dfi = correccion(ci)
                dfi["importe_eur"] = -np.abs(dfi["importe_eur"]) - 1
                ent = _a_entrega(dfi, 2, "CORRECCION")
                ent["version"] = (version[ci] + 1).astype(np.int32)
                partes.append(ent)
                cont["correcciones_invalidas"] += n

            # reenvío de correcciones ya emitidas (obsoletas si la verdad ya avanzó)
            if emitidas:
                pool = pd.concat(emitidas)
                n = min(int(n_base * p_obsoleta), len(pool))
                if n:
                    partes.append(pool.sample(n=n, random_state=int(rng.integers(1 << 30))))
                    cont["obsoletas"] += n

        # registros inválidos con identificadores propios
        n = int(n_base * p_invalido)
        origen = m.loc[rng.choice(idx_base, size=n, replace=False), COLUMNAS_OPERACION].copy()
        origen["operacion_id"] = ["OP-%08d" % (id_invalido + i) for i in range(n)]
        id_invalido += n
        partes.append(_estropear(origen, rng))
        cont["invalidos"] += n

        entrega = pd.concat(partes, ignore_index=True)
        entrega = entrega.sample(frac=1.0, random_state=int(rng.integers(1 << 30))).reset_index(drop=True)
        entregadas[idx_base] = True
        entregas.append(Entrega(f"ING-{k + 1:04d}", f"entrega_{per.year}Q{per.quarter}.csv", str(per), entrega))

    verdad = m.copy()
    verdad["importe_eur"], verdad["peso_kg"], verdad["unidades"] = imp, peso, uni
    verdad["version"] = version
    cont["filas_entregadas"] = int(sum(len(e.datos) for e in entregas))
    return Simulacion(entregas, verdad, cont)
