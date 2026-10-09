"""Catálogos ficticios: 50 países, 200 productos y jerarquía de sectores de dos niveles.

sector (10) → subsector (40) → producto (200). Los atributos numéricos (peso relativo, precio
unitario…) se derivan de una semilla fija propia, de modo que el catálogo es idéntico
sea cual sea la semilla del generador de operaciones.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

ANIO_INICIO = 2018
ANIO_FIN = 2025
SEMILLA_CATALOGO = 2018

# código -> (país, región, peso relativo, sesgo exportador: >1 más exportaciones)
PAISES: dict[str, tuple[str, str, float, float]] = {
    "DE": ("Alemania", "Unión Europea", 14, 0.9), "FR": ("Francia", "Unión Europea", 13, 1.3),
    "IT": ("Italia", "Unión Europea", 9, 1.0), "PT": ("Portugal", "Unión Europea", 9, 1.4),
    "GB": ("Reino Unido", "Resto de Europa", 7, 1.2), "NL": ("Países Bajos", "Unión Europea", 6, 0.8),
    "BE": ("Bélgica", "Unión Europea", 4, 1.0), "US": ("Estados Unidos", "América del Norte", 8, 1.1),
    "CN": ("China", "Asia", 10, 0.5), "MA": ("Marruecos", "África", 4, 1.2),
    "PL": ("Polonia", "Unión Europea", 3, 1.0), "TR": ("Turquía", "Resto de Europa", 3, 0.9),
    "MX": ("México", "América Latina", 3, 1.2), "BR": ("Brasil", "América Latina", 2.5, 1.0),
    "IN": ("India", "Asia", 2.5, 0.7), "JP": ("Japón", "Asia", 2.5, 0.9),
    "KR": ("Corea del Sur", "Asia", 2, 0.8), "SE": ("Suecia", "Unión Europea", 1.5, 1.0),
    "IE": ("Irlanda", "Unión Europea", 1.5, 0.7), "CH": ("Suiza", "Resto de Europa", 2, 1.1),
    "DZ": ("Argelia", "África", 2, 0.6), "AR": ("Argentina", "América Latina", 1.2, 1.1),
    "CL": ("Chile", "América Latina", 1.2, 1.0), "CA": ("Canadá", "América del Norte", 1.5, 1.1),
    "AE": ("Emiratos Árabes Unidos", "Oriente Medio", 1.5, 1.5),
    "SA": ("Arabia Saudí", "Oriente Medio", 1.5, 1.3), "VN": ("Vietnam", "Asia", 1.8, 0.5),
    "RO": ("Rumanía", "Unión Europea", 1.5, 1.1), "GR": ("Grecia", "Unión Europea", 1.0, 1.2),
    "AT": ("Austria", "Unión Europea", 1.2, 1.0), "DK": ("Dinamarca", "Unión Europea", 1.3, 0.9),
    "NO": ("Noruega", "Resto de Europa", 1.2, 0.8), "FI": ("Finlandia", "Unión Europea", 0.9, 1.0),
    "CZ": ("Chequia", "Unión Europea", 1.4, 0.9), "HU": ("Hungría", "Unión Europea", 1.0, 0.9),
    "SK": ("Eslovaquia", "Unión Europea", 0.7, 0.8), "BG": ("Bulgaria", "Unión Europea", 0.6, 1.2),
    "HR": ("Croacia", "Unión Europea", 0.5, 1.3), "SI": ("Eslovenia", "Unión Europea", 0.5, 1.0),
    "LU": ("Luxemburgo", "Unión Europea", 0.4, 1.1), "EG": ("Egipto", "África", 1.0, 1.3),
    "ZA": ("Sudáfrica", "África", 0.9, 1.0), "NG": ("Nigeria", "África", 0.7, 0.8),
    "CO": ("Colombia", "América Latina", 0.9, 1.1), "PE": ("Perú", "América Latina", 0.8, 0.9),
    "IL": ("Israel", "Oriente Medio", 0.8, 1.0), "SG": ("Singapur", "Asia", 1.0, 1.1),
    "TH": ("Tailandia", "Asia", 1.0, 0.7), "AU": ("Australia", "Oceanía", 1.1, 1.2),
    "ID": ("Indonesia", "Asia", 0.9, 0.6),
}

# sector -> (nombre, peso, [(subsector, [5 productos])…])
_JERARQUIA: dict[str, tuple[str, float, list[tuple[str, list[str]]]]] = {
    "S01": ("Agroalimentario", 16, [
        ("Aceites y grasas", ["Aceite de oliva virgen extra", "Aceite de girasol", "Aceite de oliva refinado", "Aceite de palma", "Grasas vegetales"]),
        ("Frutas y hortalizas", ["Cítricos", "Frutas de hueso", "Tomates", "Pimientos", "Patatas"]),
        ("Carnes y derivados", ["Carne porcina", "Embutidos curados", "Carne de ave", "Carne vacuna", "Jamón curado"]),
        ("Bebidas", ["Vino tinto", "Vino blanco", "Cerveza", "Aguas minerales", "Zumos"])]),
    "S02": ("Automoción", 14, [
        ("Vehículos", ["Turismos", "Furgonetas", "Camiones", "Autobuses", "Motocicletas"]),
        ("Componentes de motor", ["Pistones", "Cigüeñales", "Turbocompresores", "Filtros", "Inyectores"]),
        ("Chasis y carrocería", ["Frenos", "Amortiguadores", "Parachoques", "Llantas", "Asientos"]),
        ("Electrónica del automóvil", ["Baterías de vehículo", "Sensores de automoción", "Centralitas", "Cableado de automoción", "Faros LED"])]),
    "S03": ("Químico", 10, [
        ("Plásticos", ["Polietileno", "Polipropileno", "PVC", "Poliestireno", "Resinas epoxi"]),
        ("Fertilizantes y agroquímicos", ["Nitrato amónico", "Urea", "Fosfatos", "Herbicidas", "Fungicidas"]),
        ("Pinturas y recubrimientos", ["Pintura plástica", "Barnices", "Esmaltes", "Disolventes", "Pigmentos"]),
        ("Química de consumo", ["Detergentes", "Cosméticos", "Perfumes", "Jabones", "Limpiadores"])]),
    "S04": ("Energía", 9, [
        ("Hidrocarburos", ["Gas natural", "Petróleo crudo", "Gasóleo", "Gasolina", "GLP"]),
        ("Electricidad y redes", ["Electricidad", "Transformadores", "Cable de alta tensión", "Contadores inteligentes", "Subestaciones"]),
        ("Renovables", ["Paneles solares", "Inversores solares", "Aerogeneradores", "Biomasa", "Hidrógeno verde"]),
        ("Biocombustibles", ["Biodiésel", "Bioetanol", "Biogás", "Pellets", "Aceite vegetal usado"])]),
    "S05": ("Maquinaria", 10, [
        ("Maquinaria agrícola", ["Tractores", "Cosechadoras", "Sembradoras", "Sistemas de riego", "Pulverizadores"]),
        ("Maquinaria industrial", ["Bombas industriales", "Compresores", "Prensas", "Tornos CNC", "Robots industriales"]),
        ("Construcción y minería", ["Excavadoras", "Grúas", "Hormigoneras", "Perforadoras", "Cintas transportadoras"]),
        ("Herramienta y componentes", ["Herramientas eléctricas", "Herramientas manuales", "Equipos de soldadura", "Rodamientos", "Válvulas"])]),
    "S06": ("Textil y moda", 7, [
        ("Prendas", ["Camisas", "Pantalones", "Vestidos", "Ropa deportiva", "Abrigos"]),
        ("Calzado", ["Calzado deportivo", "Calzado de cuero", "Botas", "Sandalias", "Zapatillas de casa"]),
        ("Tejidos", ["Algodón", "Lana", "Seda", "Fibras sintéticas", "Tejidos técnicos"]),
        ("Accesorios y hogar", ["Bolsos", "Cinturones", "Ropa de cama", "Toallas", "Cortinas"])]),
    "S07": ("Tecnología", 11, [
        ("Semiconductores", ["Microprocesadores", "Memorias", "Sensores CMOS", "Circuitos integrados", "Obleas de silicio"]),
        ("Equipos informáticos", ["Portátiles", "Servidores", "Monitores", "Impresoras", "Tablets"]),
        ("Telecomunicaciones", ["Teléfonos móviles", "Routers", "Antenas 5G", "Fibra óptica", "Equipos de red"]),
        ("Electrónica de consumo", ["Televisores", "Auriculares", "Consolas", "Cámaras", "Altavoces"])]),
    "S08": ("Farmacéutico", 8, [
        ("Medicamentos", ["Antibióticos", "Analgésicos", "Antihipertensivos", "Oncológicos", "Insulinas"]),
        ("Biotecnología", ["Vacunas", "Anticuerpos monoclonales", "Reactivos biológicos", "Hemoderivados", "Terapias génicas"]),
        ("Material sanitario", ["Jeringuillas", "Mascarillas", "Guantes", "Apósitos", "Prótesis"]),
        ("Diagnóstico", ["Test rápidos", "Analizadores", "Reactivos PCR", "Equipos de imagen", "Monitores clínicos"])]),
    "S09": ("Metalurgia y materiales", 8, [
        ("Siderurgia", ["Acero laminado", "Acero inoxidable", "Alambrón", "Chapa galvanizada", "Perfiles de acero"]),
        ("Metales no férreos", ["Aluminio", "Cobre", "Zinc", "Níquel", "Plomo"]),
        ("Cerámica y vidrio", ["Azulejos", "Vidrio plano", "Envases de vidrio", "Porcelana", "Refractarios"]),
        ("Materiales de construcción", ["Cemento", "Áridos", "Mármol", "Ladrillos", "Prefabricados"])]),
    "S10": ("Transporte y logística", 7, [
        ("Naval", ["Buques mercantes", "Embarcaciones de recreo", "Contenedores", "Grúas portuarias", "Motores marinos"]),
        ("Aeronáutica", ["Aeronaves", "Componentes aeronáuticos", "Motores de aviación", "Aviónica", "Trenes de aterrizaje"]),
        ("Ferroviario", ["Locomotoras", "Vagones", "Carriles", "Señalización ferroviaria", "Tranvías"]),
        ("Embalaje", ["Cajas de cartón", "Palés", "Film plástico", "Envases metálicos", "Etiquetas"])]),
}


@dataclass(frozen=True)
class Catalogo:
    paises: pd.DataFrame      # pais_codigo, pais, region, peso, sesgo_export
    productos: pd.DataFrame   # producto_codigo, producto, subsector_codigo, subsector, sector_codigo, sector,
                              # peso, precio_unitario_eur, peso_unitario_kg, unidades_tipicas

    def dim_pais(self) -> pd.DataFrame:
        return self.paises[["pais_codigo", "pais", "region"]].copy()

    def dim_producto(self) -> pd.DataFrame:
        return self.productos[["producto_codigo", "producto", "subsector_codigo", "subsector",
                               "sector_codigo", "sector"]].copy()


def dim_mes(anio_inicio: int = ANIO_INICIO, anio_fin: int = ANIO_FIN) -> pd.DataFrame:
    """Calendario mensual completo (permite mostrar meses y años sin datos)."""
    meses = pd.date_range(f"{anio_inicio}-01-01", f"{anio_fin}-12-01", freq="MS")
    return pd.DataFrame({
        "mes_inicio": meses.date, "anio": meses.year.astype("int32"), "mes": meses.month.astype("int32"),
        "trimestre": ((meses.month - 1) // 3 + 1).astype("int32"),
    })


def construir_catalogo() -> Catalogo:
    paises = pd.DataFrame(
        [(c, n, r, p, s) for c, (n, r, p, s) in PAISES.items()],
        columns=["pais_codigo", "pais", "region", "peso", "sesgo_export"])

    rng = np.random.default_rng(SEMILLA_CATALOGO)
    filas = []
    contador = 0
    for sector_cod, (sector, peso_sector, subsectores) in _JERARQUIA.items():
        # escala de precio unitario ficticia por sector (€/unidad, en logaritmo)
        mu_precio = rng.uniform(4.0, 8.5)
        for k, (subsector, productos) in enumerate(subsectores, start=1):
            subsector_cod = f"{sector_cod}-{k}"
            for nombre in productos:
                contador += 1
                precio = float(np.exp(rng.normal(mu_precio, 0.7)))
                filas.append((
                    f"P{contador:03d}", nombre, subsector_cod, subsector, sector_cod, sector,
                    peso_sector * float(rng.lognormal(0, 0.8)),
                    precio,
                    float(np.exp(rng.normal(np.log(max(precio, 1.0)) * 0.55 - 1.0, 0.6))),
                    float(np.exp(rng.normal(3.0, 0.7))),
                ))
    productos = pd.DataFrame(filas, columns=[
        "producto_codigo", "producto", "subsector_codigo", "subsector", "sector_codigo", "sector",
        "peso", "precio_unitario_eur", "peso_unitario_kg", "unidades_tipicas"])
    # el peso de cada sector se reparte entre sus productos (suma = 20 × peso del sector)
    pesos_sector = {k: v[1] for k, v in _JERARQUIA.items()}
    suma = productos.groupby("sector_codigo")["peso"].transform("sum")
    productos["peso"] = productos["peso"] / suma * productos["sector_codigo"].map(pesos_sector) * 20
    assert len(paises) == 50 and len(productos) == 200
    return Catalogo(paises, productos)


CATALOGO = construir_catalogo()
