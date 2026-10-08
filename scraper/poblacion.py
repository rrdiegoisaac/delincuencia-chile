"""
Población por comuna, para calcular tasas por 100.000 habitantes. Guarda tres tablas en la
misma base de los delitos:

- comunas: código comunal (CUT), nombre, provincia y región, según el INE.
- poblacion: estimaciones y proyecciones del INE, base Censo 2017, por comuna y año (2002-2035).
- poblacion_censo2024: población efectivamente censada en el Censo 2024, por comuna.

Uso:
    python scraper/poblacion.py
"""

import argparse
import io
import logging
import sqlite3
from pathlib import Path

import pandas as pd
import requests

PROYECCIONES_URL = (
    "https://www.ine.gob.cl/docs/default-source/proyecciones-de-poblacion/cuadros-estadisticos/"
    "base-2017/estimaciones-y-proyecciones-2002-2035-comunas.xlsx"
)
# Servicio público del visor de resultados del Censo 2024 (INE): indicadores por comuna
CENSO_2024_URL = (
    "https://services5.arcgis.com/hUyD8u3TeZLKPe4T/arcgis/rest/services/"
    "CENSO2024_V2_gdb/FeatureServer/0/query"
)
POBLACION_CENSO_2024 = 18_480_432  # total país publicado por el INE, para validar la descarga
USER_AGENT = "delincuencia-chile/1.0 (proyecto de portafolio; github.com/rrdiegoisaac)"

RAIZ_PROYECTO = Path(__file__).resolve().parent.parent
DB_POR_DEFECTO = RAIZ_PROYECTO / "data" / "delitos.db"

ESQUEMA = """
CREATE TABLE IF NOT EXISTS comunas (
    cut            INTEGER PRIMARY KEY,     -- código único territorial, ej. 13101
    comuna         TEXT NOT NULL,
    provincia      TEXT NOT NULL,
    region_codigo  INTEGER NOT NULL,
    region         TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS poblacion (
    cut            INTEGER NOT NULL REFERENCES comunas (cut),
    anio           INTEGER NOT NULL,
    poblacion      INTEGER NOT NULL,        -- proyección del INE al 30 de junio, base Censo 2017
    PRIMARY KEY (cut, anio)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS poblacion_censo2024 (
    cut            INTEGER PRIMARY KEY REFERENCES comunas (cut),
    poblacion      INTEGER NOT NULL         -- población efectivamente censada
);
"""

log = logging.getLogger("poblacion")


def descargar_proyecciones(session: requests.Session) -> pd.DataFrame:
    resp = session.get(PROYECCIONES_URL, timeout=180)
    resp.raise_for_status()
    df = pd.read_excel(io.BytesIO(resp.content))
    df = df.rename(columns={
        "Region": "region_codigo", "Nombre Region": "region", "Nombre Provincia": "provincia",
        "Comuna": "cut", "Nombre Comuna": "comuna",
    })
    return df


def tabla_comunas(df: pd.DataFrame) -> pd.DataFrame:
    return (
        df[["cut", "comuna", "provincia", "region_codigo", "region"]]
        .drop_duplicates("cut")
        .sort_values("cut")
        .reset_index(drop=True)
    )


def tabla_poblacion(df: pd.DataFrame) -> pd.DataFrame:
    """Suma hombres, mujeres y todas las edades: una fila por comuna y año."""
    columnas = [c for c in df.columns if str(c).startswith("Poblacion ")]
    largo = df.groupby("cut")[columnas].sum().reset_index().melt(
        id_vars="cut", var_name="anio", value_name="poblacion"
    )
    largo["anio"] = largo.anio.str.removeprefix("Poblacion ").astype(int)
    return largo.sort_values(["cut", "anio"]).reset_index(drop=True)


def descargar_censo_2024(session: requests.Session) -> pd.DataFrame:
    params = {
        "where": "1=1",
        "outFields": "CUT,Ind_005_TPob",
        "returnGeometry": "false",
        "resultRecordCount": 2000,
        "f": "json",
    }
    resp = session.get(CENSO_2024_URL, params=params, timeout=120)
    resp.raise_for_status()
    filas = [f["attributes"] for f in resp.json()["features"]]
    df = pd.DataFrame(filas).rename(columns={"CUT": "cut", "Ind_005_TPob": "poblacion"})
    total = int(df.poblacion.sum())
    if total != POBLACION_CENSO_2024:
        raise ValueError(f"El Censo 2024 descargado suma {total:,} personas, no {POBLACION_CENSO_2024:,}")
    return df[["cut", "poblacion"]].astype(int)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", type=Path, default=DB_POR_DEFECTO)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")

    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT

    proyecciones = descargar_proyecciones(session)
    comunas = tabla_comunas(proyecciones)
    poblacion = tabla_poblacion(proyecciones)
    censo = descargar_censo_2024(session)
    faltantes = set(comunas.cut) ^ set(censo.cut)
    if faltantes:
        raise ValueError(f"Comunas que no cruzan entre proyecciones y Censo 2024: {sorted(faltantes)}")

    args.db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(args.db)
    conn.executescript(ESQUEMA)
    with conn:
        conn.execute("DELETE FROM poblacion")
        conn.execute("DELETE FROM poblacion_censo2024")
        conn.executemany("INSERT OR REPLACE INTO comunas VALUES (?, ?, ?, ?, ?)", comunas.itertuples(index=False))
        conn.executemany("INSERT INTO poblacion VALUES (?, ?, ?)", poblacion.itertuples(index=False))
        conn.executemany("INSERT INTO poblacion_censo2024 VALUES (?, ?)", censo.itertuples(index=False))
    conn.close()

    log.info("%d comunas · proyecciones %d-%d · Censo 2024: %s personas",
             len(comunas), poblacion.anio.min(), poblacion.anio.max(), f"{censo.poblacion.sum():,}")


if __name__ == "__main__":
    main()
