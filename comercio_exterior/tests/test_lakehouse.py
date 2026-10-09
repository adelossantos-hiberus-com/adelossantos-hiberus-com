"""Pruebas unitarias e de integración del pipeline bronze → silver → gold."""

import shutil

import duckdb
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import pytest

from comercio_exterior.catalogos import CATALOGO
from comercio_exterior.lakehouse import Lakehouse, Rutas, calidad
from conftest import hacer_entrega

OK = (1, "2020-02-10", "EXPORTACION", "FR", "P001", 100.0)


def leer(ruta, patron="*/part.parquet"):
    """Lee los ficheros uno a uno (sin inferir particiones Hive a partir de la ruta)."""
    ficheros = sorted(ruta.glob(patron))
    if not ficheros:
        return pd.DataFrame()
    return pd.concat([pq.ParquetFile(f).read().to_pandas() for f in ficheros], ignore_index=True)


def silver(lk):
    df = leer(lk.rutas.silver)
    return df if df.empty else df.sort_values("operacion_id").reset_index(drop=True)


def rechazos(lk):
    return leer(lk.rutas.rechazados)


def descartes(lk):
    return leer(lk.rutas.descartes)


def gold(lk):
    df = leer(lk.rutas.hechos)
    return df if df.empty else df.sort_values(["mes_inicio", "pais_codigo", "producto_codigo"]).reset_index(drop=True)


# ----------------------------------------------------------------------------- reglas de validación
DEFECTOS = [
    ("ID_INVALIDO", dict(operacion_id="XX-1")),
    ("FECHA_INVALIDA", dict(fecha="2020-02-30")),
    ("FECHA_INVALIDA", dict(fecha="15/03/2020")),
    ("FECHA_INVALIDA", dict(fecha="")),
    ("FECHA_INVALIDA", dict(fecha="2020-3-1")),
    ("FECHA_FUERA_DE_RANGO", dict(fecha="2017-12-31")),
    ("FECHA_FUERA_DE_RANGO", dict(fecha="2026-01-01")),
    ("FLUJO_INVALIDO", dict(flujo="TRANSITO")),
    ("FLUJO_INVALIDO", dict(flujo="export")),
    ("PAIS_DESCONOCIDO", dict(pais_codigo="ZZ")),
    ("PRODUCTO_DESCONOCIDO", dict(producto_codigo="P999")),
    ("IMPORTE_NULO", dict(importe_eur=np.nan)),
    ("IMPORTE_NEGATIVO", dict(importe_eur=-0.01)),
    ("PESO_INVALIDO", dict(peso_kg=-1.0)),
    ("PESO_INVALIDO", dict(peso_kg=np.nan)),
    ("UNIDADES_INVALIDAS", dict(unidades=-1)),
    ("UNIDADES_INVALIDAS", dict(unidades=pd.NA)),
]


@pytest.mark.parametrize("motivo,cambio", DEFECTOS, ids=[f"{m}-{list(c.values())[0]}" for m, c in DEFECTOS])
def test_registro_invalido_se_rechaza_con_su_motivo(lago_vacio, motivo, cambio):
    e = hacer_entrega([OK, (2, "2020-03-01", "IMPORTACION", "DE", "P002", 50.0)])
    for k, v in cambio.items():
        e.datos.loc[0, k] = v
    r = lago_vacio.ingestar(e)
    assert r.filas_rechazadas == 1 and r.rechazos_por_motivo == {motivo: 1}
    rj = rechazos(lago_vacio)
    assert len(rj) == 1 and rj.iloc[0]["motivo"] == motivo and rj.iloc[0]["fila_origen"] == 1
    assert list(silver(lago_vacio)["operacion_id"]) == ["OP-00000002"]


def test_importe_cero_y_unidades_cero_son_validos(lago_vacio):
    e = hacer_entrega([(1, "2020-02-10", "EXPORTACION", "FR", "P001", 0.0, 0.0, 0)])
    assert lago_vacio.ingestar(e).filas_rechazadas == 0
    assert len(silver(lago_vacio)) == 1


# ----------------------------------------------------------------------------- duplicados y correcciones
def test_duplicado_exacto_en_la_misma_entrega(lago_vacio):
    e = hacer_entrega([OK, OK, (2, "2020-02-11", "IMPORTACION", "DE", "P002", 5.0)])
    r = lago_vacio.ingestar(e)
    assert r.descartes_por_motivo == {"DUPLICADO_EXACTO": 1}
    s, d = silver(lago_vacio), descartes(lago_vacio)
    assert len(s) == 2 and len(d) == 1
    assert s.loc[s.operacion_id == "OP-00000001", "fila_origen"].iloc[0] == 1      # se conserva la primera
    assert d.iloc[0]["fila_fila" if False else "fila_origen"] == 2 and d.iloc[0]["ingesta_id_ganadora"] == "ING-0001"


def test_correccion_posterior_sustituye_y_conserva_la_ingesta_primera(lago_vacio):
    lago_vacio.ingestar(hacer_entrega([OK]))
    corr = hacer_entrega([(1, "2020-02-10", "EXPORTACION", "FR", "P001", 80.0, 9.0, 3)], "ING-0002",
                         version=2, tipo="CORRECCION")
    r = lago_vacio.ingestar(corr)
    assert r.correcciones_aplicadas == 1 and r.nuevas_operaciones == 0
    s = silver(lago_vacio).iloc[0]
    assert (s.version, s.importe_eur, s.ingesta_id, s.ingesta_id_primera) == (2, 80.0, "ING-0002", "ING-0001")
    d = descartes(lago_vacio).iloc[0]
    assert (d.motivo, d.origen_descartado, d.ingesta_id, d.ingesta_id_ganadora, d.ingesta_id_proceso) == \
        ("VERSION_ANTIGUA", "SILVER", "ING-0001", "ING-0002", "ING-0002")
    # gold refleja el importe corregido
    assert gold(lago_vacio)["exportaciones_eur"].sum() == pytest.approx(80.0)


def test_version_antigua_que_llega_tarde_no_sobrescribe(lago_vacio):
    lago_vacio.ingestar(hacer_entrega([(1, "2020-02-10", "EXPORTACION", "FR", "P001", 80.0)], version=2, tipo="CORRECCION"))
    lago_vacio.ingestar(hacer_entrega([OK], "ING-0002"))      # llega la versión 1 después
    s = silver(lago_vacio).iloc[0]
    assert s.version == 2 and s.importe_eur == 80.0
    d = descartes(lago_vacio).iloc[0]
    assert (d.motivo, d.origen_descartado, d.ingesta_id) == ("VERSION_ANTIGUA", "NUEVO", "ING-0002")


def test_correccion_invalida_se_rechaza_y_conserva_el_original(lago_vacio):
    lago_vacio.ingestar(hacer_entrega([OK]))
    mala = hacer_entrega([(1, "2020-02-10", "EXPORTACION", "FR", "P001", -5.0)], "ING-0002", version=2, tipo="CORRECCION")
    r = lago_vacio.ingestar(mala)
    assert r.rechazos_por_motivo == {"IMPORTE_NEGATIVO": 1}
    assert silver(lago_vacio).iloc[0][["version", "importe_eur"]].tolist() == [1, 100.0]


def test_conflicto_en_la_misma_version_gana_la_ultima_entrega(lago_vacio):
    lago_vacio.ingestar(hacer_entrega([OK]))
    lago_vacio.ingestar(hacer_entrega([(1, "2020-02-10", "EXPORTACION", "FR", "P001", 111.0)], "ING-0002"))
    assert silver(lago_vacio).iloc[0]["importe_eur"] == 111.0
    assert descartes(lago_vacio).iloc[0]["motivo"] == "CONFLICTO_MISMA_VERSION"


def test_duplicado_de_fila_ya_cargada_en_otra_ingesta(lago_vacio):
    lago_vacio.ingestar(hacer_entrega([OK]))
    r = lago_vacio.ingestar(hacer_entrega([OK, (2, "2020-02-11", "IMPORTACION", "DE", "P002", 5.0)], "ING-0002"))
    assert r.descartes_por_motivo == {"DUPLICADO_EXACTO": 1} and r.nuevas_operaciones == 1
    assert silver(lago_vacio).loc[0, "ingesta_id"] == "ING-0001"        # el linaje apunta a la primera carga


def test_trazabilidad_cada_fila_de_silver_existe_en_bronze(lago_vacio):
    lago_vacio.ingestar(hacer_entrega([OK, (2, "2020-05-01", "IMPORTACION", "DE", "P002", 5.0)]))
    b = leer(lago_vacio.rutas.bronze, "*/part-0.parquet")
    s = silver(lago_vacio)
    m = s.merge(b, on=["ingesta_id", "fila_origen"], suffixes=("", "_b"))
    assert len(m) == len(s) and (m["operacion_id"] == m["operacion_id_b"]).all()
    assert {"ingesta_ts", "fichero_origen", "ingesta_seq"} <= set(b.columns)


def test_entrega_completamente_invalida(lago_vacio):
    e = hacer_entrega([OK])
    e.datos.loc[0, "flujo"] = "X"
    r = lago_vacio.ingestar(e)
    assert r.filas_validas == 0 and r.estado == "COMPLETADA"
    assert silver(lago_vacio).empty
    assert gold(lago_vacio).empty


# ----------------------------------------------------------------------------- idempotencia y robustez
def test_misma_ingesta_dos_veces_no_cambia_nada(lago_vacio):
    e = hacer_entrega([OK, (2, "2020-05-01", "IMPORTACION", "DE", "P002", 5.0)])
    lago_vacio.ingestar(e)
    antes = (silver(lago_vacio), gold(lago_vacio), lago_vacio.control.ingestas().copy())
    r = lago_vacio.ingestar(e)
    assert r.estado == "OMITIDA" and r.motivo_omision == "INGESTA_ID_YA_CARGADA"
    pd.testing.assert_frame_equal(antes[0], silver(lago_vacio))
    pd.testing.assert_frame_equal(antes[1], gold(lago_vacio))
    pd.testing.assert_frame_equal(antes[2], lago_vacio.control.ingestas())
    assert lago_vacio.control.eventos()["evento"].tolist().count("OMITIDA") == 1


def test_mismo_contenido_con_otro_identificador_se_omite(lago_vacio):
    e = hacer_entrega([OK])
    lago_vacio.ingestar(e)
    otra = hacer_entrega([OK], "ING-0099")
    r = lago_vacio.ingestar(otra)
    assert r.estado == "OMITIDA" and r.motivo_omision == "CONTENIDO_YA_CARGADO"
    assert len(lago_vacio.control.ingestas()) == 1 and len(silver(lago_vacio)) == 1


@pytest.mark.parametrize("paso", ["bronce", "silver", "gold"])
def test_fallo_a_mitad_y_reanudacion(tmp_path, paso):
    entregas = [hacer_entrega([OK, (2, "2020-05-01", "IMPORTACION", "DE", "P002", 5.0)]),
                hacer_entrega([(1, "2020-02-10", "EXPORTACION", "FR", "P001", 80.0)], "ING-0002", version=2, tipo="CORRECCION")]
    limpio = Lakehouse(tmp_path / "limpio")
    for e in entregas:
        limpio.ingestar(e)

    lk = Lakehouse(tmp_path / "roto")
    lk.ingestar(entregas[0])
    with pytest.raises(RuntimeError):
        lk.ingestar(entregas[1], _fallo_en=paso)
    assert lk.control.fila("ING-0002")["estado"] == "FALLIDA"
    r = lk.ingestar(entregas[1])                                    # reintento
    assert r.estado == "COMPLETADA" and lk.control.fila("ING-0002")["estado"] == "COMPLETADA"
    pd.testing.assert_frame_equal(silver(lk).drop(columns=["ingesta_ts"], errors="ignore"),
                                  silver(limpio).drop(columns=["ingesta_ts"], errors="ignore"))
    pd.testing.assert_frame_equal(gold(lk), gold(limpio))
    eventos = lk.control.eventos()["evento"].tolist()
    assert "FALLIDA" in eventos and "REANUDADA" in eventos


def test_no_se_puede_reanudar_con_otro_contenido(tmp_path):
    lk = Lakehouse(tmp_path / "x")
    with pytest.raises(RuntimeError):
        lk.ingestar(hacer_entrega([OK]), _fallo_en="silver")
    with pytest.raises(ValueError, match="contenido distinto"):
        lk.ingestar(hacer_entrega([(5, "2020-02-10", "EXPORTACION", "FR", "P001", 1.0)]))


def test_no_se_puede_cambiar_la_unidad_de_particion(tmp_path):
    Lakehouse(tmp_path / "x", "anio").ingestar(hacer_entrega([OK]))
    with pytest.raises(ValueError, match="unidad_particion"):
        Lakehouse(tmp_path / "x", "trimestre")


def test_bloqueo_impide_escrituras_concurrentes(tmp_path):
    lk = Lakehouse(tmp_path / "x")
    with lk.control.bloqueo():
        with pytest.raises(RuntimeError, match="otra ingesta"):
            with lk.control.bloqueo(espera=0.2):
                pass
    with lk.control.bloqueo():          # se libera correctamente
        pass


# ----------------------------------------------------------------------------- integración con 60.000 operaciones
def test_silver_coincide_con_la_verdad(lago):
    s = silver(lago.lakehouse)
    v = lago.sim.verdad.sort_values("operacion_id").reset_index(drop=True)
    assert len(s) == len(v) == 60_000
    assert (s["operacion_id"].to_numpy() == v["operacion_id"].to_numpy()).all()
    assert (s["version"].to_numpy() == v["version"].to_numpy()).all()
    for col in ("importe_eur", "peso_kg"):
        np.testing.assert_allclose(s[col], v[col], rtol=0, atol=1e-9)
    assert (s["unidades"].to_numpy() == v["unidades"].to_numpy()).all()
    assert (pd.to_datetime(s["fecha"]).to_numpy() == pd.to_datetime(v["fecha"]).to_numpy()).all()
    assert (s["flujo"] == v["flujo"].to_numpy()).all() and (s["pais_codigo"] == v["pais_codigo"].to_numpy()).all()


def test_conservacion_de_filas_y_conteos_de_ruido(lago):
    lk, inj = lago.lakehouse, lago.sim.inyectados
    b = leer(lk.rutas.bronze, "*/part-0.parquet")
    n_s, n_r, n_d = len(silver(lk)), len(rechazos(lk)), len(descartes(lk))
    assert len(b) == inj["filas_entregadas"] == n_s + n_r + n_d
    assert n_r == inj["invalidos"] + inj["correcciones_invalidas"]
    # claves de linaje únicas: ninguna fila de bronze acaba en dos sitios
    claves = pd.concat([silver(lk)[["ingesta_id", "fila_origen"]], rechazos(lk)[["ingesta_id", "fila_origen"]],
                        descartes(lk)[["ingesta_id", "fila_origen"]]])
    assert not claves.duplicated().any()
    assert descartes(lk)["motivo"].isin({"DUPLICADO_EXACTO", "VERSION_ANTIGUA", "CONFLICTO_MISMA_VERSION"}).all()


def test_silver_incremental_igual_a_calculo_global_independiente(lago):
    """Recalcula silver de una sola vez con pandas sobre todo bronze y compara con la carga incremental."""
    lk = lago.lakehouse
    b = leer(lk.rutas.bronze, "*/part-0.parquet")
    f = pd.to_datetime(b["fecha"], format="%Y-%m-%d", errors="coerce")
    ok = (b["operacion_id"].str.match(r"^OP-\d{8}$") & f.notna() & (f >= "2018-01-01") & (f <= "2025-12-31")
          & b["flujo"].isin(["EXPORTACION", "IMPORTACION"]) & b["pais_codigo"].isin(CATALOGO.paises["pais_codigo"])
          & b["producto_codigo"].isin(CATALOGO.productos["producto_codigo"]) & (b["importe_eur"] >= 0)
          & b["peso_kg"].ge(0) & b["unidades"].ge(0))
    validas = b[ok.fillna(False)]
    contenido = ["operacion_id", "version", "fecha", "flujo", "pais_codigo", "producto_codigo", "importe_eur",
                 "peso_kg", "unidades"]
    # 1) duplicados exactos: se conserva la primera aparición; 2) versión más alta (a igualdad, la última entrega)
    validas = validas.sort_values(["ingesta_seq", "fila_origen"]).drop_duplicates(contenido)
    v = validas.sort_values(["operacion_id", "version", "ingesta_seq", "fila_origen"],
                            ascending=[True, False, False, True])
    ganadoras = v.drop_duplicates("operacion_id").sort_values("operacion_id").reset_index(drop=True)
    s = silver(lk)
    assert len(ganadoras) == len(s)
    for col in ("operacion_id", "version", "importe_eur", "peso_kg", "unidades", "ingesta_id", "fila_origen"):
        assert (ganadoras[col].to_numpy() == s[col].to_numpy()).all(), col
    assert len(b) - ok.sum() == len(rechazos(lk))


def test_gold_coincide_con_agregacion_independiente_de_la_verdad(lago):
    v = lago.sim.verdad.copy()
    v["mes_inicio"] = pd.to_datetime(v["fecha"]).dt.to_period("M").dt.start_time.dt.date
    v["exp"] = np.where(v["flujo"] == "EXPORTACION", v["importe_eur"], 0.0)
    v["imp"] = np.where(v["flujo"] == "IMPORTACION", v["importe_eur"], 0.0)
    esperado = v.groupby(["mes_inicio", "pais_codigo", "producto_codigo"], as_index=False)[["exp", "imp"]].sum() \
        .sort_values(["mes_inicio", "pais_codigo", "producto_codigo"]).reset_index(drop=True)
    g = gold(lago.lakehouse)
    assert len(g) == len(esperado)
    assert (g["pais_codigo"].to_numpy() == esperado["pais_codigo"].to_numpy()).all()
    np.testing.assert_allclose(g["exportaciones_eur"], esperado["exp"], atol=1e-6)
    np.testing.assert_allclose(g["importaciones_eur"], esperado["imp"], atol=1e-6)
    assert (g["n_op_exportacion"] + g["n_op_importacion"]).sum() == 60_000


def test_control_de_ingestas_registra_todo(lago):
    ing = lago.lakehouse.control.ingestas()
    assert len(ing) == 32 and (ing["estado"] == "COMPLETADA").all()
    assert ing[["bronze_ok", "silver_ok", "gold_ok"]].all().all() and ing["ingesta_seq"].tolist() == list(range(1, 33))
    assert ing["hash_contenido"].is_unique
    assert ing["filas_recibidas"].sum() == lago.sim.inyectados["filas_entregadas"]
    assert ing["filas_rechazadas"].sum() == len(rechazos(lago.lakehouse))
    assert (ing["dur_silver_s"] > 0).all()


def test_recarga_de_todas_las_entregas_es_idempotente(lago, tmp_path):
    """Copia el lago, vuelve a ingestar las 32 entregas y comprueba que no cambia nada."""
    copia = tmp_path / "copia"
    shutil.copytree(lago.raiz, copia)
    lk = Lakehouse(copia)
    antes = (silver(lk), gold(lk), lk.control.ingestas().copy())
    res = [lk.ingestar(e) for e in lago.sim.entregas]
    assert all(r.estado == "OMITIDA" for r in res)
    pd.testing.assert_frame_equal(antes[0], silver(lk))
    pd.testing.assert_frame_equal(antes[1], gold(lk))
    pd.testing.assert_frame_equal(antes[2], lk.control.ingestas())
    lk.cerrar()


def test_reconstruccion_desde_bronze_reproduce_silver_y_gold(lago, tmp_path):
    copia = tmp_path / "copia"
    shutil.copytree(lago.raiz, copia)
    lk = Lakehouse(copia)
    antes = (silver(lk), gold(lk), descartes(lk).sort_values(["ingesta_id", "fila_origen"]).reset_index(drop=True))
    lk.reconstruir_silver_y_gold()
    pd.testing.assert_frame_equal(antes[0], silver(lk))
    pd.testing.assert_frame_equal(antes[1], gold(lk))
    pd.testing.assert_frame_equal(antes[2], descartes(lk).sort_values(["ingesta_id", "fila_origen"]).reset_index(drop=True))
    lk.cerrar()


def test_particion_anual_da_el_mismo_resultado(lago, tmp_path):
    lk = Lakehouse(tmp_path / "anual", "anio")
    for e in lago.sim.entregas:
        lk.ingestar(e)
    cols = ["operacion_id", "version", "importe_eur", "peso_kg", "unidades", "ingesta_id", "fila_origen"]
    pd.testing.assert_frame_equal(silver(lk)[cols], silver(lago.lakehouse)[cols])
    pd.testing.assert_frame_equal(gold(lk), gold(lago.lakehouse))
    assert len(list(lk.rutas.silver.glob("*/part.parquet"))) == 8
    lk.cerrar()


# ----------------------------------------------------------------------------- calidad
def test_informe_de_calidad_sobre_datos_correctos(lago):
    inf = calidad.informe_calidad(lago.raiz)
    fallos = [c for c in inf["checks"] if not c["ok"]]
    assert not fallos, fallos
    nombres = {c["nombre"] for c in inf["checks"]}
    assert {"conservacion_de_filas", "silver_ids_unicos", "silver_trazable_a_bronze", "gold_cuadra_con_silver",
            "gold_operaciones_cuadran", "ingestas_completadas"} <= nombres
    assert inf["conservacion"]["diferencia"] == 0
    assert sum(m["filas"] for m in inf["rechazos_por_motivo"]) == len(rechazos(lago.lakehouse))


def test_informe_de_calidad_detecta_problemas(lago, tmp_path):
    copia = tmp_path / "copia"
    shutil.copytree(lago.raiz, copia)
    r = Rutas(copia)
    # 1) duplicar una fila de silver y 2) dañar un hecho de gold
    f = sorted(r.silver.glob("*/part.parquet"))[0]
    df = pd.read_parquet(f)
    pd.concat([df, df.iloc[[0]]]).to_parquet(f, index=False)
    g = sorted(r.hechos.glob("*/part.parquet"))[0]
    dg = pd.read_parquet(g)
    dg.loc[0, "exportaciones_eur"] += 1000.0
    dg.to_parquet(g, index=False)
    nombres = {c["nombre"] for c in calidad.informe_calidad(copia)["checks"] if not c["ok"]}
    assert {"silver_ids_unicos", "conservacion_de_filas", "gold_cuadra_con_silver"} <= nombres


def test_informe_sin_datos(tmp_path):
    inf = calidad.informe_calidad(tmp_path / "vacio")
    assert inf["resumen"]["error"] == 1


def test_rechazados_paginados_y_detalle_de_ingesta(lago):
    p1 = calidad.rechazados_paginados(lago.raiz, 1, 10)
    assert p1["total"] == len(rechazos(lago.lakehouse)) and len(p1["filas"]) == 10
    uno = calidad.rechazados_paginados(lago.raiz, 1, 50, motivo="FLUJO_INVALIDO")
    assert uno["total"] > 0 and {f["motivo"] for f in uno["filas"]} == {"FLUJO_INVALIDO"}
    assert calidad.rechazados_paginados(lago.raiz, 9999, 10)["filas"] == []
    det = calidad.detalle_ingesta(lago.raiz, "ING-0005")
    assert det["ingesta"]["estado"] == "COMPLETADA" and det["eventos"][0]["evento"] == "INICIO"
    assert sum(m["filas"] for m in det["rechazos_por_motivo"]) == det["ingesta"]["filas_rechazadas"]
    assert calidad.detalle_ingesta(lago.raiz, "ING-9999") is None
