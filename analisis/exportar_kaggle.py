"""
Genera los archivos del dataset para Kaggle en kaggle/:
- casos_policiales_comunas.csv: casos por comuna, subgrupo de delito y mes (solo códigos, para que pese menos)
- casos_policiales_pais_regiones.csv: lo mismo para el total del país y las 16 regiones, con nombres
- delitos.csv: clasificación de delitos del CEAD (familia, grupo y subgrupo)
- comunas.csv: nombre, provincia, región, proyecciones del INE (base 2017) y Censo 2024 por comuna
- delitos.db: copia de la base SQLite
- resumen.json: cifras para la descripción del dataset

A diferencia de la base, los CSV incluyen los meses con 0 casos, para que cada combinación
de territorio, subgrupo y mes tenga su fila.

Uso:
    python analisis/exportar_kaggle.py
"""

import json
import shutil

import pandas as pd

from datos import DB, RAIZ_PROYECTO, conectar, meta, ultimo_mes

SALIDA = RAIZ_PROYECTO / "kaggle"


def casos_completos(nivel: str) -> pd.DataFrame:
    """Casos en formato ancho (denuncias y detenciones), con todos los meses y subgrupos."""
    with conectar() as conn:
        largo = pd.read_sql("SELECT * FROM casos WHERE nivel = ?", conn, params=(nivel,))
        delitos = pd.read_sql("SELECT * FROM delitos", conn)
        territorios = pd.read_sql("SELECT codigo, nombre AS territorio FROM territorios WHERE nivel = ?", conn, params=(nivel,))

    ancho = (
        largo.pivot_table(index=["codigo", "subgrupo_id", "anio", "mes"], columns="tipo_dato",
                          values="cantidad", aggfunc="sum", fill_value=0)
        .reindex(columns=["denuncias", "detenciones"], fill_value=0)
    )

    hasta_anio, hasta_mes = ultimo_mes()
    meses = pd.period_range("2005-01", f"{hasta_anio}-{hasta_mes:02d}", freq="M")
    indice = pd.MultiIndex.from_product(
        [territorios.codigo, delitos.subgrupo_id, range(len(meses))], names=["codigo", "subgrupo_id", "i"]
    ).to_frame(index=False)
    indice["anio"] = meses.year[indice.i]
    indice["mes"] = meses.month[indice.i]
    completo = indice.drop(columns="i").merge(ancho.reset_index(), how="left", on=["codigo", "subgrupo_id", "anio", "mes"])
    completo[["denuncias", "detenciones"]] = completo[["denuncias", "detenciones"]].fillna(0).astype(int)
    completo["casos_policiales"] = completo.denuncias + completo.detenciones

    completo = completo.merge(territorios, on="codigo").merge(
        delitos[["subgrupo_id", "subgrupo", "grupo", "familia"]], on="subgrupo_id"
    )
    columnas = ["codigo", "territorio", "familia", "grupo", "subgrupo_id", "subgrupo", "anio", "mes",
                "denuncias", "detenciones", "casos_policiales"]
    return completo[columnas].sort_values(["codigo", "subgrupo_id", "anio", "mes"])


def main() -> None:
    SALIDA.mkdir(exist_ok=True)

    comunas = casos_completos("comuna").rename(columns={"codigo": "cut"})
    columnas = ["cut", "subgrupo_id", "anio", "mes", "denuncias", "detenciones", "casos_policiales"]
    comunas[columnas].to_csv(SALIDA / "casos_policiales_comunas.csv", index=False, encoding="utf-8")

    with conectar() as conn:
        info_comunas = pd.read_sql("SELECT cut, comuna, provincia, region_codigo, region FROM comunas", conn)
        poblacion = pd.read_sql("SELECT * FROM poblacion WHERE anio BETWEEN 2005 AND 2026", conn)
        censo = pd.read_sql("SELECT cut, poblacion AS poblacion_censo_2024 FROM poblacion_censo2024", conn)
        pd.read_sql("SELECT * FROM delitos ORDER BY subgrupo_id", conn).to_csv(SALIDA / "delitos.csv", index=False, encoding="utf-8")

    pais = casos_completos("pais").assign(nivel="pais")
    regiones = casos_completos("region").assign(nivel="region")
    pais_regiones = pd.concat([pais, regiones])
    pais_regiones = pais_regiones[["nivel"] + [c for c in pais_regiones.columns if c != "nivel"]]
    pais_regiones.to_csv(SALIDA / "casos_policiales_pais_regiones.csv", index=False, encoding="utf-8")

    pob = (
        poblacion.pivot(index="cut", columns="anio", values="poblacion")
        .add_prefix("proyeccion_")
        .reset_index()
        .merge(censo, on="cut")
        .merge(info_comunas, on="cut")
    )
    pob = pob[["cut", "comuna", "provincia", "region_codigo", "region", "poblacion_censo_2024"]
              + [c for c in pob.columns if c.startswith("proyeccion_")]]
    pob.to_csv(SALIDA / "comunas.csv", index=False, encoding="utf-8")

    shutil.copy2(DB, SALIDA / "delitos.db")

    resumen = {
        "filas_comunas": len(comunas),
        "filas_pais_regiones": len(pais_regiones),
        "desde": "2005-01",
        "hasta": meta()["ultimo_mes"],
        "descargado_en": meta()["descargado_en"],
        "comunas": int(comunas.cut.nunique()),
        "subgrupos": int(comunas.subgrupo_id.nunique()),
        "casos_policiales_pais": int(pais.casos_policiales.sum()),
        "tamanos_mb": {p.name: round(p.stat().st_size / 1e6, 1) for p in sorted(SALIDA.iterdir()) if p.suffix in (".csv", ".db")},
    }
    (SALIDA / "resumen.json").write_text(json.dumps(resumen, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(resumen, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
