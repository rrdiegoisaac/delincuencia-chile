"""
Límites de las regiones de Chile y de las comunas de la Región Metropolitana, para los mapas
de la nota. Se descargan del servicio público del visor del Censo 2024 (INE), simplificados
por el propio servidor, y se guardan como GeoJSON en data/limites/.

Uso:
    python scraper/limites.py
"""

import json
import logging
from pathlib import Path

import requests

SERVICIO = "https://services5.arcgis.com/hUyD8u3TeZLKPe4T/arcgis/rest/services/CENSO2024_V2_gdb/FeatureServer"
CAPA_COMUNAS = 0
CAPA_REGIONES = 1
USER_AGENT = "delincuencia-chile/1.0 (proyecto de portafolio; github.com/rrdiegoisaac)"

RAIZ_PROYECTO = Path(__file__).resolve().parent.parent
SALIDA = RAIZ_PROYECTO / "data" / "limites"

# Tolerancia de simplificación, en grados: ~2 km para el país y ~200 m para las comunas
SIMPLIFICACION_REGIONES = 0.02
SIMPLIFICACION_COMUNAS = 0.002
REGION_METROPOLITANA = 13

log = logging.getLogger("limites")


def descargar(session: requests.Session, capa: int, donde: str, campos: str, tolerancia: float) -> dict:
    params = {
        "where": donde,
        "outFields": campos,
        "returnGeometry": "true",
        "outSR": 4326,
        "maxAllowableOffset": tolerancia,
        "geometryPrecision": 4,
        "f": "geojson",
    }
    resp = session.get(f"{SERVICIO}/{capa}/query", params=params, timeout=180)
    resp.raise_for_status()
    datos = resp.json()
    if not datos.get("features"):
        raise ValueError(f"La capa {capa} no devolvió polígonos")
    return datos


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    SALIDA.mkdir(parents=True, exist_ok=True)

    regiones = descargar(session, CAPA_REGIONES, "1=1", "COD_REGION", SIMPLIFICACION_REGIONES)
    comunas = descargar(session, CAPA_COMUNAS, f"CUT >= {REGION_METROPOLITANA * 1000} AND CUT < {(REGION_METROPOLITANA + 1) * 1000}",
                        "CUT", SIMPLIFICACION_COMUNAS)

    for nombre, datos in [("regiones.geojson", regiones), ("comunas_rm.geojson", comunas)]:
        ruta = SALIDA / nombre
        ruta.write_text(json.dumps(datos, separators=(",", ":")), encoding="utf-8")
        log.info("%s: %d polígonos (%.0f KB)", ruta.relative_to(RAIZ_PROYECTO), len(datos["features"]), ruta.stat().st_size / 1024)


if __name__ == "__main__":
    main()
