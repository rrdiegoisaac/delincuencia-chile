"""
Calcula los resultados de cada sección de la nota y los exporta como JSON resumidos en
export/, listos para los gráficos del portafolio.

Uso:
    python analisis/exportar.py
"""

import json

import numpy as np
import pandas as pd

from datos import (
    FAMILIA_RESIDUAL,
    FAMILIAS_CORTAS,
    POBLACION_MINIMA_RANKING,
    RAIZ_PROYECTO,
    ROBO_CON_VIOLENCIA,
    ROBO_VIOLENTO_VEHICULO,
    casos,
    censo_2024,
    comunas,
    delitos,
    meta,
    poblacion_comunas,
    poblacion_pais,
    poblacion_regiones,
    serie_mensual,
    tasa,
    ultimo_anio_completo,
    ultimo_mes,
)

EXPORT = RAIZ_PROYECTO / "export"

ANIO_REFERENCIA = 2019  # último año completo antes de la pandemia
ANIO_INICIO = 2005

# Regiones de norte a sur, con nombres cortos
REGIONES = [
    (15, "Arica y Parinacota"), (1, "Tarapacá"), (2, "Antofagasta"), (3, "Atacama"),
    (4, "Coquimbo"), (5, "Valparaíso"), (13, "Metropolitana"), (6, "O'Higgins"),
    (7, "Maule"), (16, "Ñuble"), (8, "Biobío"), (9, "La Araucanía"), (14, "Los Ríos"),
    (10, "Los Lagos"), (11, "Aysén"), (12, "Magallanes"),
]


def guardar(nombre: str, datos: dict) -> None:
    EXPORT.mkdir(exist_ok=True)
    ruta = EXPORT / nombre
    ruta.write_text(json.dumps(datos, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"  {ruta.relative_to(RAIZ_PROYECTO)}  ({ruta.stat().st_size / 1024:.0f} KB)")


def pct(parte, total) -> float:
    return round(float(parte) / float(total) * 100, 1) if total else 0.0


def cambio_pct(antes, despues) -> float:
    return round((float(despues) / float(antes) - 1) * 100, 1) if antes else None


def r1(v) -> float:
    return round(float(v), 1)


def suma_movil_12(serie: pd.Series) -> pd.Series:
    """Suma de los últimos 12 meses: quita la estacionalidad sin perder el detalle mensual."""
    return serie.rolling(12).sum()


def periodo(anio: int, mes: int) -> str:
    return f"{anio}-{mes:02d}"


# --- Los datos -------------------------------------------------------------------

def seccion_datos() -> dict:
    anio_fin = ultimo_anio_completo()
    hasta = ultimo_mes()
    d = delitos()

    por_familia = casos("pais", ["familia_id"], f"anio = {anio_fin}")
    total = por_familia.casos.sum()
    familias = []
    for f in por_familia.itertuples():
        familias.append({
            "familia_id": int(f.familia_id),
            "familia": FAMILIAS_CORTAS[f.familia_id],
            "familia_cead": d.loc[d.familia_id == f.familia_id, "familia"].iloc[0],
            "casos": int(f.casos),
            "denuncias": int(f.denuncias),
            "detenciones": int(f.detenciones),
            "pct_detenciones": pct(f.detenciones, f.casos),
            "pct_del_total": pct(f.casos, total),
            "subgrupos": int((d.familia_id == f.familia_id).sum()),
        })

    # Participación de la categoría residual en el total, por año
    anual = casos("pais", ["anio", "familia_id"])
    anual = anual[anual.anio <= anio_fin]
    residual = []
    for anio, sub in anual.groupby("anio"):
        residual.append({
            "anio": int(anio),
            "pct_residual": pct(sub.loc[sub.familia_id == FAMILIA_RESIDUAL, "casos"].sum(), sub.casos.sum()),
        })

    # Consistencia: el total del país contra la suma de regiones y de comunas
    pais = casos("pais", ["anio"]).set_index("anio").casos
    regiones = casos("region", ["anio"]).set_index("anio").casos
    comunas_ = casos("comuna", ["anio"]).set_index("anio").casos
    consistencia = [
        {
            "anio": int(a),
            "pais": int(pais[a]),
            "suma_regiones": int(regiones.get(a, 0)),
            "suma_comunas": int(comunas_.get(a, 0)),
        }
        for a in pais.index
    ]
    dif_regiones = max(abs(c["pais"] - c["suma_regiones"]) / c["pais"] for c in consistencia) * 100
    dif_comunas = max(abs(c["pais"] - c["suma_comunas"]) / c["pais"] for c in consistencia) * 100

    todos = casos("pais", ["familia_id"])
    pob = poblacion_pais()
    return {
        "periodo": {"desde": periodo(ANIO_INICIO, 1), "hasta": periodo(*hasta)},
        "ultimo_anio_completo": anio_fin,
        "descargado_en": meta()["descargado_en"],
        "subgrupos": len(d),
        "familias": d.familia_id.nunique(),
        "comunas": int(len(comunas())),
        "casos_total": int(todos.casos.sum()),
        "casos_ultimo_anio": int(total),
        "pct_detenciones_ultimo_anio": pct(por_familia.detenciones.sum(), total),
        "por_familia": familias,
        "residual_anual": residual,
        "consistencia": consistencia,
        "max_diferencia_regiones_pct": round(dif_regiones, 2),
        "max_diferencia_comunas_pct": round(dif_comunas, 2),
        "poblacion": {
            "proyeccion_2024": int(pob[2024]),
            "censo_2024_censada": int(censo_2024().poblacion.sum()),
            # Publicado por el INE (Estimaciones y proyecciones base 2024, enero de 2026)
            "base_2024_fecha_censo": 19_871_764,
            "omision_censal_pct": 7.0,
        },
    }


# --- Cambios en el registro ------------------------------------------------------

def serie_subgrupos(subgrupos: list[int]) -> pd.DataFrame:
    filtro = f"subgrupo_id IN ({', '.join(map(str, subgrupos))})"
    return serie_mensual("pais", filtro)


def seccion_registro() -> dict:
    d = delitos().set_index("subgrupo_id")

    # Primer mes con casos de cada subgrupo: los que empiezan después de 2005 se crearon a mitad del período
    con_casos = casos("pais", ["subgrupo_id", "anio", "mes"])
    con_casos = con_casos[con_casos.casos > 0]
    primero = con_casos.assign(p=con_casos.anio * 100 + con_casos.mes).groupby("subgrupo_id").p.min()
    nuevos = [
        {"subgrupo_id": int(s), "subgrupo": d.loc[s, "subgrupo"], "desde": f"{p // 100}-{p % 100:02d}"}
        for s, p in primero.items()
        if p > (ANIO_INICIO + 1) * 100 + 12
    ]

    def mensual(subgrupos, nombre):
        s = serie_subgrupos(subgrupos)
        return {
            "nombre": nombre,
            "meses": [
                {"periodo": periodo(r.anio, r.mes), "casos": int(r.casos), "detenciones": int(r.detenciones)}
                for r in s.itertuples()
            ],
        }

    # 1. Robos con violencia: desde diciembre de 2019 los de vehículos se registran aparte
    rvi = serie_subgrupos([ROBO_CON_VIOLENCIA]).casos.to_numpy()
    rvv = serie_subgrupos([ROBO_VIOLENTO_VEHICULO])
    robos = [
        {"periodo": periodo(r.anio, r.mes), "robo_con_violencia": int(v), "robo_violento_vehiculo": int(r.casos)}
        for r, v in zip(rvv.itertuples(), rvi)
    ]

    # 2. Otras infracciones a la ley de armas: salto en mayo de 2024
    armas = serie_subgrupos([50103])
    armas_idx = armas.set_index(["anio", "mes"]).casos
    antes = armas_idx.loc[(2023, 5):(2024, 4)].mean()
    despues = armas_idx.loc[(2024, 5):(2025, 4)].mean()

    # 3. Consumo de alcohol en la vía pública: cae desde noviembre de 2019
    alcohol = serie_subgrupos([70204]).set_index(["anio", "mes"]).casos
    alcohol_antes = alcohol.loc[(2018, 11):(2019, 10)].sum()
    alcohol_despues = alcohol.loc[(2022, 1):(2025, 12)].sum() / 4

    # 4. La categoría residual
    otros = serie_subgrupos([99903]).set_index(["anio", "mes"]).casos

    anio_fin = ultimo_anio_completo()
    del_anio = [r for r in robos if r["periodo"].startswith(str(anio_fin))]
    vehiculo = sum(r["robo_violento_vehiculo"] for r in del_anio)
    suma = vehiculo + sum(r["robo_con_violencia"] for r in del_anio)

    return {
        "subgrupos_nuevos": nuevos,
        "robos_violentos_mensual": robos,
        "pct_robo_vehiculo": pct(vehiculo, suma),
        "armas_otras_infracciones": mensual([50103], d.loc[50103, "subgrupo"]),
        "armas_salto": {
            "promedio_mensual_antes": round(float(antes)),
            "promedio_mensual_despues": round(float(despues)),
            "veces": r1(despues / antes),
            "pct_detenciones_despues": pct(
                armas.set_index(["anio", "mes"]).loc[(2024, 5):(2025, 4)].detenciones.sum(),
                armas.set_index(["anio", "mes"]).loc[(2024, 5):(2025, 4)].casos.sum(),
            ),
        },
        "alcohol": mensual([70204], d.loc[70204, "subgrupo"]),
        "alcohol_cambio": {
            "anual_antes": int(alcohol_antes),
            "anual_despues": round(float(alcohol_despues)),
            "pct": cambio_pct(alcohol_antes, alcohol_despues),
        },
        "otros_mensual": mensual([99903], d.loc[99903, "subgrupo"]),
        "otros_anual": {
            str(a): int(v) for a, v in otros.groupby(level=0).sum().items() if a <= ultimo_anio_completo()
        },
    }


# --- ¿Hay más delitos que antes? -----------------------------------------------

def seccion_tendencia() -> dict:
    anio_fin = ultimo_anio_completo()
    pob = poblacion_pais()
    f = casos("pais", ["anio", "familia_id"])
    f = f[f.anio <= anio_fin].copy()
    f["tasa"] = tasa(f.casos, f.anio.map(pob))

    anual = []
    for anio, sub in f.groupby("anio"):
        fila = {"anio": int(anio), "poblacion": int(pob[anio])}
        for r in sub.itertuples():
            fila[f"f{r.familia_id}"] = r1(r.tasa)
        nucleo = sub[sub.familia_id != FAMILIA_RESIDUAL]
        fila["total"] = r1(tasa(nucleo.casos.sum(), pob[anio]))
        fila["casos_total"] = int(nucleo.casos.sum())
        anual.append(fila)
    anual_df = pd.DataFrame(anual).set_index("anio")

    familias = []
    for fid, corta in FAMILIAS_CORTAS.items():
        col = f"f{fid}"
        serie = anual_df[col]
        familias.append({
            "familia_id": fid,
            "familia": corta,
            "tasa_inicio": serie[ANIO_INICIO],
            "tasa_referencia": serie[ANIO_REFERENCIA],
            "tasa_fin": serie[anio_fin],
            "max_anio": int(serie.idxmax()),
            "max_tasa": serie.max(),
            "cambio_vs_referencia": cambio_pct(serie[ANIO_REFERENCIA], serie[anio_fin]),
        })
    total = anual_df.total

    # Primer semestre del último año contra el mismo período del año anterior
    hasta_anio, hasta_mes = ultimo_mes()
    semestre = casos("pais", ["anio", "familia_id"], f"mes <= {hasta_mes} AND anio IN ({hasta_anio - 1}, {hasta_anio})")
    acumulado = []
    for fid, corta in FAMILIAS_CORTAS.items():
        sub = semestre[semestre.familia_id == fid].set_index("anio").casos
        acumulado.append({
            "familia_id": fid, "familia": corta,
            "anterior": int(sub.get(hasta_anio - 1, 0)), "actual": int(sub.get(hasta_anio, 0)),
            "cambio": cambio_pct(sub.get(hasta_anio - 1, 0), sub.get(hasta_anio, 0)),
        })

    return {
        "periodo": {"desde": ANIO_INICIO, "hasta": anio_fin, "referencia": ANIO_REFERENCIA},
        "anual": anual,
        "familias": familias,
        "total": {
            "max_anio": int(total.idxmax()),
            "max_tasa": total.max(),
            "tasa_referencia": total[ANIO_REFERENCIA],
            "tasa_fin": total[anio_fin],
            "cambio_vs_referencia": cambio_pct(total[ANIO_REFERENCIA], total[anio_fin]),
            "cambio_vs_max": cambio_pct(total.max(), total[anio_fin]),
            "min_anio": int(total.idxmin()),
            "min_tasa": total.min(),
        },
        "acumulado_semestre": {"meses": hasta_mes, "anio": hasta_anio, "familias": acumulado},
    }


# --- Delitos violentos -----------------------------------------------------------

SERIES_VIOLENTAS = {
    "homicidios": ("Homicidios y femicidios", "grupo_id = 101"),
    "robos_violentos": ("Robos con violencia o intimidación (incluye vehículos)", f"subgrupo_id IN ({ROBO_CON_VIOLENCIA}, {ROBO_VIOLENTO_VEHICULO})"),
    "robo_sorpresa": ("Robo por sorpresa", "subgrupo_id = 20201"),
    "violaciones": ("Violaciones", "subgrupo_id = 10201"),
    "lesiones_graves": ("Lesiones graves o gravísimas", "subgrupo_id = 10301"),
}


def seccion_violencia() -> dict:
    anio_fin = ultimo_anio_completo()
    pob = poblacion_pais()
    series = {}
    resumen = {}
    for clave, (nombre, filtro) in SERIES_VIOLENTAS.items():
        s = serie_mensual("pais", filtro)
        s["movil"] = suma_movil_12(s.casos)
        anual = s[s.anio <= anio_fin].groupby("anio")[["casos", "detenciones"]].sum()
        anual["tasa"] = tasa(anual.casos, anual.index.map(pob))
        series[clave] = {
            "nombre": nombre,
            "anual": [
                {"anio": int(a), "casos": int(r.casos), "tasa": round(float(r.tasa), 2), "pct_detenciones": pct(r.detenciones, r.casos)}
                for a, r in anual.iterrows()
            ],
            "movil_12": [
                {"periodo": periodo(r.anio, r.mes), "casos": int(r.movil)}
                for r in s.itertuples() if not np.isnan(r.movil)
            ],
        }
        tasa_ = anual.tasa
        resumen[clave] = {
            "tasa_inicio": round(float(tasa_[ANIO_INICIO]), 2),
            "tasa_referencia": round(float(tasa_[ANIO_REFERENCIA]), 2),
            "tasa_fin": round(float(tasa_[anio_fin]), 2),
            "max_anio": int(tasa_.idxmax()),
            "max_tasa": round(float(tasa_.max()), 2),
            "cambio_vs_referencia": cambio_pct(tasa_[ANIO_REFERENCIA], tasa_[anio_fin]),
            "casos_fin": int(anual.casos[anio_fin]),
            "casos_max_anio": int(anual.casos.idxmax()),
            "casos_max": int(anual.casos.max()),
        }
    return {"series": series, "resumen": resumen, "anio_fin": anio_fin}


# --- Drogas y armas: lo que depende de la actividad policial ----------------------

def seccion_drogas_armas() -> dict:
    anio_fin = ultimo_anio_completo()
    d = delitos().set_index("subgrupo_id")
    sub = casos("pais", ["subgrupo_id"], f"anio = {anio_fin}")
    sub = sub[sub.casos >= 100]
    por_subgrupo = [
        {
            "subgrupo_id": int(r.subgrupo_id),
            "subgrupo": d.loc[r.subgrupo_id, "subgrupo"],
            "familia_id": int(d.loc[r.subgrupo_id, "familia_id"]),
            "familia": FAMILIAS_CORTAS[d.loc[r.subgrupo_id, "familia_id"]],
            "casos": int(r.casos),
            "pct_detenciones": pct(r.detenciones, r.casos),
        }
        for r in sub.sort_values("detenciones", ascending=False).itertuples()
    ]
    por_subgrupo.sort(key=lambda x: -x["pct_detenciones"])

    pob = poblacion_pais()
    elegidos = {
        "microtrafico": 40102,
        "trafico": 40101,
        "porte_arma_cortante": 50201,
        "disparo_injustificado": 50101,
        "porte_posesion_armas": 50102,
        "consumo_drogas_via_publica": 70201,
    }
    anual = casos("pais", ["anio", "subgrupo_id"], f"subgrupo_id IN ({', '.join(map(str, elegidos.values()))})")
    anual = anual[anual.anio <= anio_fin]
    series = {}
    for clave, sid in elegidos.items():
        s = anual[anual.subgrupo_id == sid].set_index("anio").reindex(range(ANIO_INICIO, anio_fin + 1), fill_value=0)
        series[clave] = {
            "subgrupo": d.loc[sid, "subgrupo"],
            "anual": [
                {"anio": int(a), "casos": int(r.casos), "tasa": round(float(tasa(r.casos, pob[a])), 2), "pct_detenciones": pct(r.detenciones, r.casos)}
                for a, r in s.iterrows()
            ],
        }
    return {"anio": anio_fin, "por_subgrupo": por_subgrupo, "series": series}


# --- Regiones --------------------------------------------------------------------

def seccion_regiones() -> dict:
    anio_fin = ultimo_anio_completo()
    pob = poblacion_regiones().set_index(["region_codigo", "anio"]).poblacion
    pob_pais = poblacion_pais()
    f = casos("region", ["codigo", "anio", "familia_id"], f"anio IN ({ANIO_REFERENCIA}, {anio_fin - 2}, {anio_fin - 1}, {anio_fin})")
    hom = casos("region", ["codigo", "anio"], f"grupo_id = 101 AND anio BETWEEN {anio_fin - 2} AND {anio_fin}")
    rv = casos("region", ["codigo", "anio"], f"subgrupo_id IN ({ROBO_CON_VIOLENCIA}, {ROBO_VIOLENTO_VEHICULO}, 20201) AND anio IN ({ANIO_REFERENCIA}, {anio_fin})")

    filas = []
    for codigo, nombre in REGIONES:
        fr = f[f.codigo == codigo]
        fin = fr[fr.anio == anio_fin]
        ref = fr[fr.anio == ANIO_REFERENCIA]
        p_fin = pob[(codigo, anio_fin)]
        p_ref = pob[(codigo, ANIO_REFERENCIA)]
        nucleo_fin = fin[fin.familia_id != FAMILIA_RESIDUAL].casos.sum()
        nucleo_ref = ref[ref.familia_id != FAMILIA_RESIDUAL].casos.sum()
        hom_r = hom[hom.codigo == codigo]
        pob_3 = sum(pob[(codigo, a)] for a in range(anio_fin - 2, anio_fin + 1))
        rv_r = rv[rv.codigo == codigo].set_index("anio").casos
        fila = {
            "region_codigo": codigo,
            "region": nombre,
            "poblacion": int(p_fin),
            "tasa_total": r1(tasa(nucleo_fin, p_fin)),
            "tasa_total_referencia": r1(tasa(nucleo_ref, p_ref)),
            "cambio_total": cambio_pct(tasa(nucleo_ref, p_ref), tasa(nucleo_fin, p_fin)),
            # Homicidios: promedio de 3 años, porque en regiones pequeñas son pocos casos al año
            "tasa_homicidios_3a": round(float(tasa(hom_r.casos.sum(), pob_3)), 2),
            "homicidios_3a": int(hom_r.casos.sum()),
            "tasa_robos_violentos": r1(tasa(rv_r.get(anio_fin, 0), p_fin)),
            "tasa_robos_violentos_referencia": r1(tasa(rv_r.get(ANIO_REFERENCIA, 0), p_ref)),
        }
        for r in fin.itertuples():
            fila[f"f{r.familia_id}"] = r1(tasa(r.casos, p_fin))
        filas.append(fila)

    # Referencia nacional, con los mismos indicadores
    nac = casos("pais", ["anio", "familia_id"], f"anio IN ({ANIO_REFERENCIA}, {anio_fin})")
    nac_hom = casos("pais", ["anio"], f"grupo_id = 101 AND anio BETWEEN {anio_fin - 2} AND {anio_fin}").casos.sum()
    nac_rv = casos("pais", ["anio"], f"subgrupo_id IN ({ROBO_CON_VIOLENCIA}, {ROBO_VIOLENTO_VEHICULO}, 20201) AND anio IN ({ANIO_REFERENCIA}, {anio_fin})").set_index("anio").casos
    nucleo = nac[nac.familia_id != FAMILIA_RESIDUAL].groupby("anio").casos.sum()
    pais = {
        "region": "Chile",
        "poblacion": int(pob_pais[anio_fin]),
        "tasa_total": r1(tasa(nucleo[anio_fin], pob_pais[anio_fin])),
        "tasa_total_referencia": r1(tasa(nucleo[ANIO_REFERENCIA], pob_pais[ANIO_REFERENCIA])),
        "tasa_homicidios_3a": round(float(tasa(nac_hom, sum(pob_pais[a] for a in range(anio_fin - 2, anio_fin + 1)))), 2),
        "tasa_robos_violentos": r1(tasa(nac_rv[anio_fin], pob_pais[anio_fin])),
        "tasa_robos_violentos_referencia": r1(tasa(nac_rv[ANIO_REFERENCIA], pob_pais[ANIO_REFERENCIA])),
    }
    for r in nac[nac.anio == anio_fin].itertuples():
        pais[f"f{r.familia_id}"] = r1(tasa(r.casos, pob_pais[anio_fin]))
    pais["tasa_vif"] = pais["f3"]

    return {"anio": anio_fin, "referencia": ANIO_REFERENCIA, "anios_homicidios": [anio_fin - 2, anio_fin], "regiones": filas, "pais": pais}


# --- Comunas ---------------------------------------------------------------------

def seccion_comunas() -> dict:
    anio_fin = ultimo_anio_completo()
    pob = poblacion_comunas()
    pob_fin = pob[pob.anio == anio_fin].set_index("cut")
    censo = censo_2024().set_index("cut").poblacion
    pob_2024 = pob[pob.anio == 2024].set_index("cut").poblacion
    pob_3 = pob[pob.anio.between(anio_fin - 2, anio_fin)].groupby("cut").poblacion.sum()

    total = casos("comuna", ["codigo", "familia_id"], f"anio = {anio_fin}")
    nucleo = total[total.familia_id != FAMILIA_RESIDUAL].groupby("codigo").casos.sum()
    rv = casos("comuna", ["codigo"], f"subgrupo_id IN ({ROBO_CON_VIOLENCIA}, {ROBO_VIOLENTO_VEHICULO}, 20201) AND anio = {anio_fin}").set_index("codigo").casos
    hom = casos("comuna", ["codigo"], f"grupo_id = 101 AND anio BETWEEN {anio_fin - 2} AND {anio_fin}").set_index("codigo").casos
    vif = casos("comuna", ["codigo"], f"familia_id = 3 AND anio = {anio_fin}").set_index("codigo").casos

    region_corta = dict(REGIONES)
    filas = []
    for cut, r in pob_fin.iterrows():
        p = r.poblacion
        filas.append({
            "cut": int(cut),
            "comuna": r.comuna,
            "region": region_corta[r.region_codigo],
            "poblacion": int(p),
            "tasa_total": r1(tasa(nucleo.get(cut, 0), p)),
            "tasa_robos_violentos": r1(tasa(rv.get(cut, 0), p)),
            "robos_violentos": int(rv.get(cut, 0)),
            "tasa_homicidios_3a": round(float(tasa(hom.get(cut, 0), pob_3[cut])), 2),
            "homicidios_3a": int(hom.get(cut, 0)),
            "tasa_vif": r1(tasa(vif.get(cut, 0), p)),
            # Diferencia entre lo censado en 2024 y lo proyectado por el INE para 2024 (base 2017)
            "censo_vs_proyeccion_pct": cambio_pct(pob_2024[cut], censo[cut]),
            "tasa_robos_violentos_censo": r1(tasa(rv.get(cut, 0), censo[cut])),
        })
    df = pd.DataFrame(filas)
    grandes = df[df.poblacion >= POBLACION_MINIMA_RANKING].copy()

    def ranking(col, n=15):
        top = grandes.sort_values(col, ascending=False).head(n)
        return top.to_dict(orient="records")

    # ¿Cambia el ranking de robos violentos si se usa la población censada en 2024?
    grandes["puesto_proyeccion"] = grandes.tasa_robos_violentos.rank(ascending=False, method="min")
    grandes["puesto_censo"] = grandes.tasa_robos_violentos_censo.rank(ascending=False, method="min")
    top15_proy = set(grandes.nsmallest(15, "puesto_proyeccion").cut)
    top15_censo = set(grandes.nsmallest(15, "puesto_censo").cut)
    correlacion = grandes[["tasa_robos_violentos", "tasa_robos_violentos_censo"]].corr(method="spearman").iloc[0, 1]

    # Concentración: qué parte de los robos violentos ocurre en pocas comunas
    orden = df.sort_values("robos_violentos", ascending=False)
    acumulado = orden.robos_violentos.cumsum() / orden.robos_violentos.sum()
    n_mitad = int((acumulado < 0.5).sum() + 1)
    pob_mitad = orden.head(n_mitad).poblacion.sum() / df.poblacion.sum()

    return {
        "anio": anio_fin,
        "anios_homicidios": [anio_fin - 2, anio_fin],
        "poblacion_minima": POBLACION_MINIMA_RANKING,
        "n_comunas_ranking": int(len(grandes)),
        "ranking_robos_violentos": ranking("tasa_robos_violentos"),
        "ranking_homicidios": ranking("tasa_homicidios_3a"),
        "ranking_total": ranking("tasa_total"),
        "sensibilidad_censo": {
            "coinciden_top15": len(top15_proy & top15_censo),
            "correlacion_rangos": round(float(correlacion), 3),
            "censo_vs_proyeccion_min": grandes.censo_vs_proyeccion_pct.min(),
            "censo_vs_proyeccion_max": grandes.censo_vs_proyeccion_pct.max(),
            "censo_vs_proyeccion_mediana": r1(grandes.censo_vs_proyeccion_pct.median()),
        },
        "concentracion_robos_violentos": {
            "comunas_mitad": n_mitad,
            "pct_poblacion": r1(pob_mitad * 100),
        },
        "comunas": df.to_dict(orient="records"),
    }


def main() -> None:
    print("Exportando:")
    guardar("00_datos.json", seccion_datos())
    guardar("01_registro.json", seccion_registro())
    guardar("02_tendencia.json", seccion_tendencia())
    guardar("03_violencia.json", seccion_violencia())
    guardar("04_drogas_armas.json", seccion_drogas_armas())
    guardar("05_regiones.json", seccion_regiones())
    guardar("06_comunas.json", seccion_comunas())


if __name__ == "__main__":
    main()
