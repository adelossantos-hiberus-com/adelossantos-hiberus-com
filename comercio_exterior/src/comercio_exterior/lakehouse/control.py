"""Registro de ingestas y bitácora de eventos (tablas Parquet pequeñas, escritura atómica)."""

from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from .rutas import Rutas

COLUMNAS_INGESTAS = [
    "ingesta_seq", "ingesta_id", "fuente", "fichero_origen", "periodo", "hash_contenido", "estado",
    "bronze_ok", "silver_ok", "gold_ok", "ts_inicio", "ts_fin",
    "filas_recibidas", "filas_validas", "filas_rechazadas", "duplicados_exactos", "versiones_antiguas",
    "conflictos_version", "nuevas_operaciones", "correcciones_aplicadas", "periodos_afectados",
    "dur_bronze_s", "dur_silver_s", "dur_gold_s", "error",
]
_ENTERAS = {"ingesta_seq", "filas_recibidas", "filas_validas", "filas_rechazadas", "duplicados_exactos",
            "versiones_antiguas", "conflictos_version", "nuevas_operaciones", "correcciones_aplicadas"}
_REALES = {"dur_bronze_s", "dur_silver_s", "dur_gold_s"}
_BOOLEANAS = {"bronze_ok", "silver_ok", "gold_ok"}
_FECHAS = {"ts_inicio", "ts_fin"}
COLUMNAS_EVENTOS = ["ts", "ingesta_id", "evento", "detalle"]


def ahora() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _escribir_atomico(df: pd.DataFrame, ruta: Path) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    tmp = ruta.with_suffix(".tmp")
    df.to_parquet(tmp, index=False)
    os.replace(tmp, ruta)


class Control:
    def __init__(self, rutas: Rutas):
        self.rutas = rutas
        self.f_ingestas = rutas.control / "ingestas.parquet"
        self.f_eventos = rutas.control / "eventos.parquet"
        self.f_config = rutas.control / "config.json"

    # -- configuración persistente (unidad de partición) --
    def leer_config(self) -> dict:
        return json.loads(self.f_config.read_text()) if self.f_config.exists() else {}

    def escribir_config(self, cfg: dict) -> None:
        self.rutas.control.mkdir(parents=True, exist_ok=True)
        self.f_config.write_text(json.dumps(cfg, indent=2))

    # -- ingestas --
    def ingestas(self) -> pd.DataFrame:
        if not self.f_ingestas.exists():
            return pd.DataFrame({c: pd.Series(dtype="object") for c in COLUMNAS_INGESTAS})
        return pd.read_parquet(self.f_ingestas)

    def eventos(self) -> pd.DataFrame:
        if not self.f_eventos.exists():
            return pd.DataFrame({c: pd.Series(dtype="object") for c in COLUMNAS_EVENTOS})
        return pd.read_parquet(self.f_eventos)

    @staticmethod
    def _normalizar(df: pd.DataFrame) -> pd.DataFrame:
        df = df[COLUMNAS_INGESTAS].copy()
        for c in COLUMNAS_INGESTAS:
            if c in _ENTERAS:
                df[c] = pd.to_numeric(df[c]).astype("Int64")
            elif c in _REALES:
                df[c] = pd.to_numeric(df[c]).astype("float64")
            elif c in _BOOLEANAS:
                df[c] = df[c].fillna(False).astype(bool)
            elif c in _FECHAS:
                df[c] = pd.to_datetime(df[c])
            else:
                df[c] = df[c].astype(object).where(df[c].notna(), None)
        return df

    def guardar_ingestas(self, df: pd.DataFrame) -> None:
        _escribir_atomico(self._normalizar(df), self.f_ingestas)

    def evento(self, ingesta_id: str, evento: str, detalle: str = "") -> None:
        nuevo = pd.DataFrame([{"ts": ahora(), "ingesta_id": ingesta_id, "evento": evento, "detalle": detalle}])
        ev = self.eventos()
        _escribir_atomico(pd.concat([ev, nuevo], ignore_index=True) if len(ev) else nuevo, self.f_eventos)

    def fila(self, ingesta_id: str) -> dict | None:
        df = self.ingestas()
        sel = df[df["ingesta_id"] == ingesta_id]
        return None if sel.empty else sel.iloc[0].to_dict()

    def actualizar(self, ingesta_id: str, **campos) -> None:
        df = self.ingestas()
        i = df.index[df["ingesta_id"] == ingesta_id]
        for k, v in campos.items():
            if k not in df.columns:
                raise KeyError(k)
            df[k] = df[k].astype(object)
            df.loc[i, k] = v
        self.guardar_ingestas(df)

    def insertar(self, **campos) -> dict:
        df = self.ingestas()
        fila = {c: None for c in COLUMNAS_INGESTAS}
        fila.update(campos)
        fila["ingesta_seq"] = int(df["ingesta_seq"].max() + 1) if len(df) else 1
        nuevo = pd.DataFrame([fila])
        self.guardar_ingestas(pd.concat([df, nuevo], ignore_index=True) if len(df) else nuevo)
        return fila

    def version_datos(self) -> str:
        """Identificador de la versión de los datos: cambia cuando se completa una ingesta."""
        df = self.ingestas()
        comp = df[df["estado"] == "COMPLETADA"] if len(df) else df
        if comp.empty:
            return "vacio"
        return f"{len(comp)}:{pd.Timestamp(comp['ts_fin'].max()).isoformat()}"

    @contextmanager
    def bloqueo(self, espera: float = 5.0):
        """Exclusión mutua entre escritores (un único proceso de ingesta a la vez)."""
        self.rutas.control.mkdir(parents=True, exist_ok=True)
        ruta = self.rutas.control / ".lock"
        fin = time.time() + espera
        while True:
            try:
                fd = os.open(ruta, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                break
            except FileExistsError:
                if time.time() > fin:
                    raise RuntimeError("Hay otra ingesta en curso (bloqueo en control/.lock)")
                time.sleep(0.1)
        try:
            yield
        finally:
            os.close(fd)
            os.unlink(ruta)
