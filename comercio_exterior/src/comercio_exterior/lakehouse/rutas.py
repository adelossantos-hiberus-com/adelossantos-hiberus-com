"""Estructura de directorios del lakehouse."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Rutas:
    raiz: Path

    def __post_init__(self):
        object.__setattr__(self, "raiz", Path(self.raiz))

    # bronze: datos tal como llegan + columnas de linaje, una carpeta inmutable por ingesta
    @property
    def bronze(self) -> Path: return self.raiz / "bronze" / "operaciones"
    # silver: versión vigente de cada operación válida, particionada por periodo
    @property
    def silver(self) -> Path: return self.raiz / "silver" / "operaciones"
    @property
    def rechazados(self) -> Path: return self.raiz / "silver" / "rechazados"
    @property
    def descartes(self) -> Path: return self.raiz / "silver" / "descartes"
    # gold: modelo dimensional para análisis
    @property
    def gold(self) -> Path: return self.raiz / "gold"
    @property
    def hechos(self) -> Path: return self.gold / "hechos_mensual"
    @property
    def control(self) -> Path: return self.raiz / "control"

    def bronze_ingesta(self, ingesta_id: str) -> Path: return self.bronze / f"ingesta_id={ingesta_id}"
    def silver_periodo(self, p: str) -> Path: return self.silver / f"periodo={p}"
    def hechos_periodo(self, p: str) -> Path: return self.hechos / f"periodo={p}"

    @staticmethod
    def glob(carpeta: Path, fichero: str = "*.parquet") -> str:
        return str(carpeta / "*" / fichero)

    def existe_gold(self) -> bool:
        return self.hechos.exists() and any(self.hechos.glob("*/part.parquet"))
