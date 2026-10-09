"""Generador de registros ficticios de exportaciones e importaciones.

Todos los datos son inventados: los países son reales solo como etiqueta, pero
los importes, pesos y fechas no corresponden a ninguna estadística oficial.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

ANIOS = (2022, 2023, 2024, 2025)
N_REGISTROS = 50_000
SEMILLA = 42
EXPORTACION = "EXPORTACION"
IMPORTACION = "IMPORTACION"
FLUJOS = (EXPORTACION, IMPORTACION)

COLUMNAS = (
    "id_registro",
    "fecha",
    "anio",
    "pais",
    "producto",
    "sector",
    "flujo",
    "importe_eur",
    "peso_kg",
)

# sector -> (ln del importe típico por registro, peso relativo, {producto: precio ficticio €/kg})
SECTORES = {
    "Agroalimentario": (10.2, 18, {"Aceite de oliva": 6.0, "Vino": 5.0, "Frutas frescas": 1.5,
                                   "Conservas vegetales": 2.5, "Carne porcina": 4.0}),
    "Automoción": (11.6, 16, {"Turismos": 14.0, "Componentes de motor": 25.0, "Neumáticos": 6.0,
                              "Frenos": 18.0, "Baterías de vehículo": 12.0}),
    "Químico": (11.0, 12, {"Plásticos": 1.8, "Fertilizantes": 0.6, "Pinturas": 4.5,
                           "Productos de limpieza": 2.2, "Cosméticos": 30.0}),
    "Energía": (11.9, 10, {"Gas natural": 0.5, "Petróleo refinado": 0.8, "Electricidad": 0.2,
                           "Paneles solares": 9.0, "Biocombustibles": 1.1}),
    "Maquinaria": (11.5, 12, {"Maquinaria agrícola": 22.0, "Bombas industriales": 35.0,
                              "Robots industriales": 60.0, "Turbinas": 80.0, "Herramientas": 15.0}),
    "Textil y moda": (10.0, 10, {"Prendas de vestir": 28.0, "Calzado": 35.0, "Tejidos": 8.0,
                                 "Bolsos": 50.0, "Textil hogar": 12.0}),
    "Tecnología": (11.3, 12, {"Semiconductores": 400.0, "Ordenadores": 120.0, "Teléfonos móviles": 250.0,
                              "Equipos de red": 90.0, "Software embebido": 150.0}),
    "Farmacéutico": (11.4, 10, {"Medicamentos": 300.0, "Vacunas": 500.0, "Material sanitario": 40.0,
                                "Principios activos": 200.0, "Diagnóstico in vitro": 350.0}),
}

# país -> (peso relativo, sesgo exportador: >1 más exportaciones, <1 más importaciones)
PAISES = {
    "Alemania": (14, 0.9), "Francia": (13, 1.3), "Italia": (9, 1.0), "Portugal": (9, 1.4),
    "Reino Unido": (7, 1.2), "Países Bajos": (6, 0.8), "Bélgica": (4, 1.0),
    "Estados Unidos": (8, 1.1), "China": (10, 0.5), "Marruecos": (4, 1.2),
    "Polonia": (3, 1.0), "Turquía": (3, 0.9), "México": (3, 1.2), "Brasil": (2.5, 1.0),
    "India": (2.5, 0.7), "Japón": (2.5, 0.9), "Corea del Sur": (2, 0.8), "Suecia": (1.5, 1.0),
    "Irlanda": (1.5, 0.7), "Suiza": (2, 1.1), "Argelia": (2, 0.6), "Argentina": (1.2, 1.1),
    "Chile": (1.2, 1.0), "Canadá": (1.5, 1.1), "Emiratos Árabes Unidos": (1.5, 1.5),
    "Arabia Saudí": (1.5, 1.3), "Vietnam": (1.8, 0.5), "Rumanía": (1.5, 1.1),
    "Grecia": (1.0, 1.2), "Austria": (1.2, 1.0),
}

# Evolución ficticia del importe medio por año y flujo (2022 = base 1,00).
TENDENCIA = {
    EXPORTACION: {2022: 1.00, 2023: 1.07, 2024: 1.10, 2025: 1.15},
    IMPORTACION: {2022: 1.00, 2023: 1.04, 2024: 0.98, 2025: 1.02},
}


def generar_registros(n: int = N_REGISTROS, semilla: int = SEMILLA,
                      anios: tuple[int, ...] = ANIOS) -> pd.DataFrame:
    """Devuelve un DataFrame con `n` registros ficticios, reproducible por `semilla`."""
    if n < 1:
        raise ValueError("n debe ser al menos 1")
    if not anios:
        raise ValueError("Se necesita al menos un año")
    sin_tendencia = [a for a in anios if a not in TENDENCIA[EXPORTACION]]
    if sin_tendencia:
        raise ValueError(f"Años sin tendencia definida: {sin_tendencia}")

    rng = np.random.default_rng(semilla)

    # Fecha y año
    anios_arr = np.array(anios)
    anio = rng.choice(anios_arr, size=n)
    inicio = np.array([f"{a}-01-01" for a in anio], dtype="datetime64[D]")
    dias_en_anio = np.where((anio % 4 == 0) & ((anio % 100 != 0) | (anio % 400 == 0)), 366, 365)
    fecha = inicio + (rng.random(n) * dias_en_anio).astype(int).astype("timedelta64[D]")

    # País y flujo (el sesgo exportador de cada país fija su probabilidad de exportar)
    nombres_pais = list(PAISES)
    pesos_pais = np.array([PAISES[p][0] for p in nombres_pais], dtype=float)
    sesgo = np.array([PAISES[p][1] for p in nombres_pais])
    idx_pais = rng.choice(len(nombres_pais), size=n, p=pesos_pais / pesos_pais.sum())
    p_exportar = (sesgo / (1 + sesgo))[idx_pais]
    es_export = rng.random(n) < p_exportar
    flujo = np.where(es_export, EXPORTACION, IMPORTACION)

    # Sector y producto
    nombres_sector = list(SECTORES)
    pesos_sector = np.array([SECTORES[s][1] for s in nombres_sector], dtype=float)
    idx_sector = rng.choice(len(nombres_sector), size=n, p=pesos_sector / pesos_sector.sum())
    idx_producto = rng.integers(0, 5, size=n)
    sector = np.array(nombres_sector)[idx_sector]
    producto = np.empty(n, dtype=object)
    precio_kg = np.empty(n)
    for i, nombre in enumerate(nombres_sector):
        productos = list(SECTORES[nombre][2].items())
        for j, (nombre_producto, precio) in enumerate(productos):
            mascara = (idx_sector == i) & (idx_producto == j)
            producto[mascara] = nombre_producto
            precio_kg[mascara] = precio

    # Importe (lognormal por sector, ajustado por tendencia) y peso coherente con el precio
    mu = np.array([SECTORES[s][0] for s in nombres_sector])[idx_sector]
    factor = np.array([TENDENCIA[f][a] for f, a in zip(flujo, anio)])
    importe = np.round(np.exp(rng.normal(mu, 0.9)) * factor, 2)
    peso = np.round(np.maximum(importe / precio_kg * np.exp(rng.normal(0, 0.25, n)), 0.1), 1)

    df = pd.DataFrame({
        "fecha": fecha,
        "anio": anio.astype(int),
        "pais": np.array(nombres_pais)[idx_pais],
        "producto": producto,
        "sector": sector,
        "flujo": flujo,
        "importe_eur": importe,
        "peso_kg": peso,
    }).sort_values("fecha", kind="stable").reset_index(drop=True)
    df.insert(0, "id_registro", np.arange(1, n + 1))
    return df[list(COLUMNAS)]


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Genera datos ficticios de comercio exterior.")
    parser.add_argument("--registros", type=int, default=N_REGISTROS)
    parser.add_argument("--semilla", type=int, default=SEMILLA)
    parser.add_argument("--salida", type=Path, default=Path("datos/comercio_exterior.csv"))
    args = parser.parse_args(argv)

    df = generar_registros(args.registros, args.semilla)
    args.salida.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(args.salida, index=False)
    print(f"{len(df):,} registros escritos en {args.salida}")


if __name__ == "__main__":
    main()
