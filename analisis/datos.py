"""Carga de datos y definiciones compartidas por todo el análisis."""

import sqlite3
from pathlib import Path

import pandas as pd

RAIZ_PROYECTO = Path(__file__).resolve().parent.parent
DB = RAIZ_PROYECTO / "data" / "delitos.db"

TIPOS_DATO = ["denuncias", "detenciones"]

# 'Otros delitos o faltas' es una categoría residual del CEAD: no dice qué delitos agrupa y
# su tamaño cambia mucho entre años. Se muestra aparte y no entra en los totales del análisis.
FAMILIA_RESIDUAL = 99

# Nombres cortos de las familias, para gráficos y tablas
FAMILIAS_CORTAS = {
    1: "Contra la vida o integridad",
    2: "Robos violentos",
    3: "Violencia intrafamiliar",
    4: "Drogas",
    5: "Armas",
    6: "Contra la propiedad no violentos",
    7: "Incivilidades",
    99: "Otros delitos o faltas",
}

# Subgrupos que el CEAD empezó a registrar por separado a mitad del período. Para comparar
# en el tiempo se suman con el subgrupo del que se separaron.
ROBO_VIOLENTO_VEHICULO = 20102
ROBO_CON_VIOLENCIA = 20101

# Población mínima para mostrar una comuna en los rankings: en comunas muy pequeñas,
# unos pocos casos cambian mucho la tasa
POBLACION_MINIMA_RANKING = 50_000


def conectar() -> sqlite3.Connection:
    if not DB.exists():
        raise FileNotFoundError(f"No existe {DB}. Ejecuta primero scraper/scrape_cead.py y scraper/poblacion.py")
    return sqlite3.connect(f"file:{DB}?mode=ro", uri=True)


def meta() -> dict:
    with conectar() as conn:
        return dict(conn.execute("SELECT clave, valor FROM meta"))


def ultimo_mes() -> tuple[int, int]:
    """Último (año, mes) publicado por el CEAD en la descarga."""
    anio, mes = meta()["ultimo_mes"].split("-")
    return int(anio), int(mes)


def ultimo_anio_completo() -> int:
    anio, mes = ultimo_mes()
    return anio if mes == 12 else anio - 1


def delitos() -> pd.DataFrame:
    with conectar() as conn:
        df = pd.read_sql("SELECT * FROM delitos ORDER BY subgrupo_id", conn)
    df["familia_corta"] = df.familia_id.map(FAMILIAS_CORTAS)
    return df


def casos(nivel: str, agrupar: list[str], filtro: str = "", desde: int | None = None) -> pd.DataFrame:
    """Casos policiales agregados, con una columna por tipo de dato y su suma (casos).

    agrupar: columnas de la tabla casos o de delitos, sin prefijo (ej. ['anio', 'familia_id']).
    filtro: condición SQL adicional (ej. 'subgrupo_id = 10101').
    Las combinaciones sin filas en la base tienen 0 casos (la base solo guarda cantidades > 0).
    """
    columnas = ", ".join(agrupar)
    donde = [f"c.nivel = '{nivel}'"]
    if filtro:
        donde.append(f"({filtro})")
    if desde:
        donde.append(f"c.anio >= {int(desde)}")
    sql = f"""
        SELECT {columnas}, c.tipo_dato, SUM(c.cantidad) AS cantidad
        FROM casos c JOIN delitos d USING (subgrupo_id)
        WHERE {' AND '.join(donde)}
        GROUP BY {columnas}, c.tipo_dato
    """
    with conectar() as conn:
        largo = pd.read_sql(sql, conn)
    ancho = largo.pivot_table(index=agrupar, columns="tipo_dato", values="cantidad", aggfunc="sum", fill_value=0)
    ancho = ancho.reindex(columns=TIPOS_DATO, fill_value=0)
    ancho.columns.name = None
    ancho["casos"] = ancho.denuncias + ancho.detenciones
    return ancho.reset_index()


def serie_mensual(nivel: str = "pais", filtro: str = "", codigo: int | None = None) -> pd.DataFrame:
    """Casos por mes, con todos los meses del período (también los que tienen 0 casos)."""
    condiciones = [f for f in [filtro, f"c.codigo = {codigo}" if codigo is not None else ""] if f]
    df = casos(nivel, ["anio", "mes"], " AND ".join(condiciones))
    hasta_anio, hasta_mes = ultimo_mes()
    meses = pd.period_range("2005-01", f"{hasta_anio}-{hasta_mes:02d}", freq="M")
    completo = pd.DataFrame({"anio": meses.year, "mes": meses.month})
    df = completo.merge(df, on=["anio", "mes"], how="left").fillna(0)
    for col in TIPOS_DATO + ["casos"]:
        df[col] = df[col].astype(int)
    return df


def poblacion_comunas() -> pd.DataFrame:
    """Proyección del INE (base 2017) por comuna y año, con su región."""
    with conectar() as conn:
        return pd.read_sql(
            "SELECT p.cut, p.anio, p.poblacion, c.comuna, c.region_codigo, c.region "
            "FROM poblacion p JOIN comunas c USING (cut)",
            conn,
        )


def poblacion_pais() -> pd.Series:
    pob = poblacion_comunas()
    return pob.groupby("anio").poblacion.sum()


def poblacion_regiones() -> pd.DataFrame:
    pob = poblacion_comunas()
    return pob.groupby(["region_codigo", "anio"]).poblacion.sum().reset_index()


def censo_2024() -> pd.DataFrame:
    with conectar() as conn:
        return pd.read_sql("SELECT * FROM poblacion_censo2024", conn)


def comunas() -> pd.DataFrame:
    with conectar() as conn:
        return pd.read_sql("SELECT * FROM comunas", conn)


def regiones() -> pd.DataFrame:
    with conectar() as conn:
        return pd.read_sql("SELECT codigo AS region_codigo, nombre FROM territorios WHERE nivel = 'region'", conn)


def tasa(casos_: pd.Series | float, poblacion: pd.Series | float) -> pd.Series | float:
    """Casos por cada 100.000 habitantes."""
    return casos_ / poblacion * 100_000
