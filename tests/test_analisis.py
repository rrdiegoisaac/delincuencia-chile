"""Pruebas de las funciones principales. Ejecutar desde la raíz del proyecto: python -m pytest"""

import sys
from pathlib import Path

import pandas as pd
import pytest

RAIZ = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(RAIZ / "analisis"), str(RAIZ / "scraper")]

from datos import tasa  # noqa: E402
from exportar import cambio_pct, suma_movil_12  # noqa: E402
from scrape_cead import (  # noqa: E402
    a_entero,
    filas_esperadas,
    leer_catalogo,
    normalizar,
    parsear_tabla,
    ultimo_mes_publicado,
)

# Taxonomía mínima con los tres casos de la tabla del CEAD: un grupo con varios subgrupos,
# un grupo con un solo subgrupo y una familia con un solo grupo
DELITOS = [
    {"subgrupo_id": 10101, "subgrupo": "Homicidios", "grupo_id": 101, "grupo": "Homicidios y femicidios", "familia_id": 1, "familia": "Contra la vida"},
    {"subgrupo_id": 10102, "subgrupo": "Femicidios", "grupo_id": 101, "grupo": "Homicidios y femicidios", "familia_id": 1, "familia": "Contra la vida"},
    {"subgrupo_id": 10601, "subgrupo": "Amenazas", "grupo_id": 106, "grupo": "Amenazas", "familia_id": 1, "familia": "Contra la vida"},
    {"subgrupo_id": 99901, "subgrupo": "Abigeato", "grupo_id": 999, "grupo": "Otros delitos o faltas", "familia_id": 99, "familia": "Otros delitos o faltas"},
    {"subgrupo_id": 99902, "subgrupo": "Robo frustrado", "grupo_id": 999, "grupo": "Otros delitos o faltas", "familia_id": 99, "familia": "Otros delitos o faltas"},
]


def tabla_cead(filas: list[tuple[str, str, list[int]]]) -> str:
    """HTML con la estructura de la respuesta del CEAD: 2 años de enero y febrero."""
    encabezado = (
        "<tr><th></th><th colspan='2'>2024</th><th colspan='2'>2025</th></tr>"
        "<tr><th></th><th colspan='2'>TRIM 1</th><th colspan='2'>TRIM 1</th></tr>"
        "<tr><th>DELITOS O FALTAS</th><th>1</th><th>2</th><th>1</th><th>2</th></tr>"
    )
    cuerpo = "".join(
        f"<tr class='{clase}'><td>{nombre}</td>" + "".join(f"<td>{v:,}</td>".replace(",", ".") for v in valores) + "</tr>"
        for clase, nombre, valores in filas
    )
    return f"<div><table><thead>{encabezado}</thead><tbody>{cuerpo}</tbody></table></div>"


FILAS_OK = [
    ("formato_1", "Contra la vida", [1012, 5, 7, 9]),
    ("formato_2", "Homicidios y femicidios", [12, 5, 7, 9]),
    ("formato_4", "Homicidios", [10, 4, 7, 8]),
    ("formato_4", "Femicidios", [2, 1, 0, 1]),
    ("formato_2", "Amenazas", [1000, 0, 0, 0]),
    ("formato_1", "Otros delitos o faltas", [3, 0, 1, 0]),
    ("formato_4", "Abigeato", [3, 0, 0, 0]),
    ("formato_4", "Robo frustrado", [0, 0, 1, 0]),
]


# --- Scraper ----------------------------------------------------------------------

def test_normalizar_ignora_tildes_y_simbolos():
    assert normalizar("Riña Pública") == normalizar("Rina publica")
    assert normalizar("Porte / posesión de armas") == "porteposesiondearmas"


def test_a_entero_usa_punto_de_miles():
    assert a_entero("1.234") == 1234
    assert a_entero(" 12 ") == 12
    assert a_entero("") == 0


def test_filas_esperadas_omite_las_filas_repetidas():
    filas = [(nivel, codigo) for nivel, codigo, _ in filas_esperadas(DELITOS)]
    assert filas == [
        ("familia", 1),
        ("grupo", 101), ("subgrupo", 10101), ("subgrupo", 10102),
        ("grupo", 106),  # un solo subgrupo: solo aparece la fila del grupo
        ("familia", 99),  # un solo grupo: no aparece su fila
        ("subgrupo", 99901), ("subgrupo", 99902),
    ]


def test_parsear_tabla_asigna_cada_valor_a_su_subgrupo_y_mes():
    datos = parsear_tabla(tabla_cead(FILAS_OK), DELITOS)
    como_dict = {(s, a, m): v for s, a, m, v in datos}
    assert len(datos) == 5 * 4  # 5 subgrupos x 4 meses
    assert como_dict[(10101, 2024, 1)] == 10
    assert como_dict[(10102, 2025, 2)] == 1
    assert como_dict[(10601, 2024, 1)] == 1000  # el grupo de un solo subgrupo cuenta como el subgrupo
    assert como_dict[(99902, 2025, 1)] == 1


def test_parsear_tabla_falla_si_el_total_de_la_familia_no_cuadra():
    filas = [list(f) for f in FILAS_OK]
    filas[2][2] = [11, 4, 7, 8]  # un homicidio de más
    with pytest.raises(ValueError, match="no coincide"):
        parsear_tabla(tabla_cead([tuple(f) for f in filas]), DELITOS)


def test_parsear_tabla_falla_si_cambia_el_orden_de_las_filas():
    filas = FILAS_OK.copy()
    filas[2], filas[3] = filas[3], filas[2]
    with pytest.raises(ValueError, match="Fila inesperada"):
        parsear_tabla(tabla_cead(filas), DELITOS)


def test_leer_catalogo_arma_la_jerarquia_desde_los_codigos():
    html = """
    <select id="delitos-select">
      <option value="1" data-section="Familia de delitos">Contra la vida</option>
      <option value="99" data-section="Familia de delitos">Otros delitos o faltas</option>
      <option value="101" data-section="Grupo">Homicidios y femicidios</option>
      <option value="999" data-section="Grupo">Otros delitos o faltas</option>
      <option value="10101" data-section="Subgrupo">Homicidios</option>
      <option value="99901" data-section="Subgrupo">Abigeato</option>
    </select>
    <select id="territorial-select">
      <option value="99" data-section="Regiones">TOTAL PAÍS</option>
      <option value="13" data-section="Regiones">Región Metropolitana</option>
      <option value="131" data-section="Provincias">Provincia de Santiago</option>
      <option value="13101" data-section="Comunas">Santiago</option>
    </select>
    """
    delitos, territorios = leer_catalogo(html)
    abigeato = next(d for d in delitos if d["subgrupo_id"] == 99901)
    assert (abigeato["grupo_id"], abigeato["familia_id"]) == (999, 99)
    assert [(t["nivel"], t["codigo"]) for t in territorios] == [("pais", 99), ("region", 13), ("comuna", 13101)]


def test_ultimo_mes_publicado_ignora_los_meses_en_cero():
    datos = [(10101, 2026, 5, 3), (10101, 2026, 6, 2), (10101, 2026, 7, 0), (10102, 2026, 7, 0)]
    assert ultimo_mes_publicado(datos) == (2026, 6)


# --- Análisis ---------------------------------------------------------------------

def test_tasa_por_100_mil():
    assert tasa(50, 1_000_000) == 5.0


def test_cambio_pct():
    assert cambio_pct(200, 150) == -25.0
    assert cambio_pct(0, 10) is None


def test_suma_movil_12_necesita_un_anio_completo():
    serie = pd.Series(range(1, 25))
    movil = suma_movil_12(serie)
    assert movil.iloc[:11].isna().all()
    assert movil.iloc[11] == sum(range(1, 13))
