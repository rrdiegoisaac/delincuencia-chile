"""
Scraper de las estadísticas delictuales del CEAD (Centro de Estudios y Análisis del Delito,
Ministerio de Seguridad Pública).

Fuente: https://cead.minsegpublica.gob.cl/estadisticas-delictuales/
Destino: base SQLite (por defecto data/delitos.db)

Descarga los casos policiales mensuales de los 48 subgrupos de delitos, desde 2005, para el
total del país, las 16 regiones y las 346 comunas. Cada territorio se pide dos veces: una para
las denuncias y otra para las detenciones en flagrancia. Su suma son los casos policiales.

Es reanudable: cada descarga queda registrada en la tabla descargas, así que si el proceso se
corta, al volver a ejecutarlo sigue donde quedó.

Uso:
    python scraper/scrape_cead.py                  # país, regiones y comunas
    python scraper/scrape_cead.py --solo regiones  # solo país y regiones (~1 minuto)
    python scraper/scrape_cead.py --rehacer        # vuelve a descargar todo (el CEAD corrige cifras pasadas)
"""

import argparse
import logging
import re
import sqlite3
import time
import unicodedata
from datetime import date, datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://cead.minsegpublica.gob.cl"
PAGINA_URL = BASE_URL + "/estadisticas-delictuales/"
DATOS_URL = BASE_URL + "/wp-content/themes/gobcl-wp-master/data/get_estadisticas_delictuales.php"
USER_AGENT = "delincuencia-chile/1.0 (proyecto de portafolio; github.com/rrdiegoisaac)"

RAIZ_PROYECTO = Path(__file__).resolve().parent.parent
DB_POR_DEFECTO = RAIZ_PROYECTO / "data" / "delitos.db"

ANIO_INICIAL = 2005  # primer año que publica el CEAD
CODIGO_PAIS = 99  # código del total país en el formulario del CEAD

# Valores del campo tipoVal del formulario. Casos policiales ('1,2') = denuncias + detenciones.
TIPOS_DATO = {"denuncias": "2", "detenciones": "1"}

MESES = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto",
         "Septiembre", "Octubre", "Noviembre", "Diciembre"]

ESQUEMA = """
CREATE TABLE IF NOT EXISTS delitos (
    subgrupo_id   INTEGER PRIMARY KEY,      -- código del CEAD, ej. 10101
    subgrupo      TEXT NOT NULL,            -- ej. 'Homicidios'
    grupo_id      INTEGER NOT NULL,         -- ej. 101
    grupo         TEXT NOT NULL,            -- ej. 'Homicidios y femicidios'
    familia_id    INTEGER NOT NULL,         -- ej. 1
    familia       TEXT NOT NULL             -- ej. 'Delitos contra la vida o integridad de las personas'
);

CREATE TABLE IF NOT EXISTS territorios (
    nivel         TEXT NOT NULL,            -- 'pais', 'region' o 'comuna'
    codigo        INTEGER NOT NULL,         -- 99 (país), código de región o código comunal (CUT)
    nombre        TEXT NOT NULL,
    PRIMARY KEY (nivel, codigo)
);

-- Solo se guardan las cantidades mayores a 0. Un mes sin fila en una descarga completa = 0 casos.
CREATE TABLE IF NOT EXISTS casos (
    nivel         TEXT NOT NULL,
    codigo        INTEGER NOT NULL,
    subgrupo_id   INTEGER NOT NULL REFERENCES delitos (subgrupo_id),
    anio          INTEGER NOT NULL,
    mes           INTEGER NOT NULL,
    tipo_dato     TEXT NOT NULL,            -- 'denuncias' o 'detenciones'
    cantidad      INTEGER NOT NULL,
    PRIMARY KEY (nivel, codigo, tipo_dato, subgrupo_id, anio, mes)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS descargas (
    nivel         TEXT NOT NULL,
    codigo        INTEGER NOT NULL,
    tipo_dato     TEXT NOT NULL,
    filas         INTEGER NOT NULL,         -- filas guardadas (cantidades > 0)
    total         INTEGER NOT NULL,         -- suma de todos los casos descargados
    descargado_en TEXT NOT NULL,            -- timestamp UTC
    PRIMARY KEY (nivel, codigo, tipo_dato)
);

CREATE TABLE IF NOT EXISTS meta (
    clave         TEXT PRIMARY KEY,
    valor         TEXT NOT NULL
);
"""

log = logging.getLogger("scraper")


def conectar(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.executescript(ESQUEMA)
    return conn


def normalizar(texto: str) -> str:
    """Minúsculas, sin tildes ni símbolos: para comparar nombres aunque cambie la codificación."""
    sin_tildes = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", sin_tildes.lower())


def a_entero(texto: str) -> int:
    """'1.234' -> 1234 (el CEAD usa punto como separador de miles)."""
    limpio = texto.strip().replace(".", "")
    return int(limpio) if limpio else 0


# --- Catálogo del formulario -------------------------------------------------------

def leer_catalogo(html: str) -> tuple[list[dict], list[dict]]:
    """Taxonomía de delitos y territorios, tal como los ofrece el formulario del CEAD."""
    soup = BeautifulSoup(html, "html.parser")

    nombres = {}
    for opcion in soup.find(id="delitos-select").find_all("option"):
        nombres[int(opcion["value"])] = opcion.get_text(strip=True)

    # Los códigos son jerárquicos: subgrupo 10101 -> grupo 101 -> familia 1 (99901 -> 999 -> 99)
    delitos = []
    for codigo, nombre in sorted(nombres.items()):
        if codigo < 10_000:
            continue
        grupo_id = codigo // 100
        familia_id = grupo_id // 100 if grupo_id < 900 else grupo_id // 10
        delitos.append({
            "subgrupo_id": codigo,
            "subgrupo": nombre,
            "grupo_id": grupo_id,
            "grupo": nombres[grupo_id],
            "familia_id": familia_id,
            "familia": nombres[familia_id],
        })

    territorios = []
    for opcion in soup.find(id="territorial-select").find_all("option"):
        seccion = opcion.get("data-section")
        codigo = int(opcion["value"])
        if seccion == "Regiones":
            nivel = "pais" if codigo == CODIGO_PAIS else "region"
        elif seccion == "Comunas":
            nivel = "comuna"
        else:
            continue  # provincias: no se usan
        territorios.append({"nivel": nivel, "codigo": codigo, "nombre": opcion.get_text(strip=True)})
    return delitos, territorios


def guardar_catalogo(conn: sqlite3.Connection, delitos: list[dict], territorios: list[dict]) -> None:
    with conn:
        conn.executemany(
            "INSERT OR REPLACE INTO delitos VALUES (:subgrupo_id, :subgrupo, :grupo_id, :grupo, :familia_id, :familia)",
            delitos,
        )
        conn.executemany("INSERT OR REPLACE INTO territorios VALUES (:nivel, :codigo, :nombre)", territorios)


# --- Tabla de resultados -----------------------------------------------------------

def filas_esperadas(delitos: list[dict]) -> list[tuple[str, int, str]]:
    """Orden de las filas de la tabla del CEAD: (nivel de la fila, código, nombre).

    La tabla muestra cada familia, sus grupos y sus subgrupos. Si un grupo tiene un solo
    subgrupo, la fila del subgrupo se omite; si una familia tiene un solo grupo, se omite
    la fila del grupo (pasa con 'Otros delitos o faltas').
    """
    filas = []
    for familia_id in sorted({d["familia_id"] for d in delitos}):
        de_familia = [d for d in delitos if d["familia_id"] == familia_id]
        filas.append(("familia", familia_id, de_familia[0]["familia"]))
        grupos = sorted({d["grupo_id"] for d in de_familia})
        for grupo_id in grupos:
            subgrupos = [d for d in de_familia if d["grupo_id"] == grupo_id]
            if len(grupos) > 1:
                filas.append(("grupo", grupo_id, subgrupos[0]["grupo"]))
            if len(subgrupos) > 1 or len(grupos) == 1:
                filas.extend(("subgrupo", d["subgrupo_id"], d["subgrupo"]) for d in subgrupos)
    return filas


def columnas_periodo(tabla) -> list[tuple[int, int]]:
    """(año, mes) de cada columna de datos, a partir de los encabezados de años y meses."""
    encabezados = tabla.find_all("tr")
    anios = []
    for celda in encabezados[0].find_all("th")[1:]:
        anios.extend([int(celda.get_text(strip=True))] * int(celda.get("colspan", 1)))
    meses = [int(c.get_text(strip=True)) for c in encabezados[2].find_all(["th", "td"])[1:]]
    if len(anios) != len(meses):
        raise ValueError(f"Encabezados inconsistentes: {len(anios)} años y {len(meses)} meses")
    return list(zip(anios, meses))


def parsear_tabla(html: str, delitos: list[dict]) -> list[tuple[int, int, int, int]]:
    """Cantidades por (subgrupo_id, año, mes, cantidad), con todos los meses (también los 0).

    Comprueba que las filas lleguen en el orden esperado y que el total de cada familia sea la
    suma de sus subgrupos: si el CEAD cambia la tabla, falla en vez de guardar datos mal asignados.
    """
    soup = BeautifulSoup(html, "html.parser")
    tabla = soup.find("table")
    if tabla is None:
        raise ValueError("La respuesta no tiene la tabla de resultados")
    periodos = columnas_periodo(tabla)

    esperadas = filas_esperadas(delitos)
    filas = tabla.find_all("tr")[3:]
    if len(filas) != len(esperadas):
        raise ValueError(f"Se esperaban {len(esperadas)} filas de delitos y llegaron {len(filas)}")

    grupo_unico = {}  # grupos que la tabla muestra en una sola fila: grupo_id -> subgrupo_id
    for d in delitos:
        grupo_unico.setdefault(d["grupo_id"], []).append(d["subgrupo_id"])

    resultado = []
    total_familia: dict[int, list[int]] = {}
    suma_hojas: dict[int, list[int]] = {}
    familia_actual = None
    for (nivel, codigo, nombre), fila in zip(esperadas, filas):
        celdas = fila.find_all(["td", "th"])
        etiqueta = celdas[0].get_text(strip=True)
        if normalizar(etiqueta) != normalizar(nombre):
            raise ValueError(f"Fila inesperada: llegó {etiqueta!r} donde se esperaba {nombre!r}")
        valores = [a_entero(c.get_text()) for c in celdas[1:]]
        if len(valores) != len(periodos):
            raise ValueError(f"{nombre}: {len(valores)} valores para {len(periodos)} meses")

        if nivel == "familia":
            familia_actual = codigo
            total_familia[codigo] = valores
            suma_hojas[codigo] = [0] * len(valores)
            continue
        if nivel == "grupo":
            if len(grupo_unico[codigo]) > 1:
                continue  # sus subgrupos vienen en las filas siguientes
            codigo = grupo_unico[codigo][0]

        suma_hojas[familia_actual] = [a + b for a, b in zip(suma_hojas[familia_actual], valores)]
        resultado.extend((codigo, anio, mes, v) for (anio, mes), v in zip(periodos, valores))

    for familia_id, totales in total_familia.items():
        if totales != suma_hojas[familia_id]:
            raise ValueError(f"El total de la familia {familia_id} no coincide con la suma de sus subgrupos")
    return resultado


# --- Descarga ----------------------------------------------------------------------

def parametros(territorio: dict, tipo_dato: str, delitos: list[dict], anios: list[int]) -> dict:
    datos = {
        "medida": "1",  # frecuencia (la tasa se calcula aparte, con la población del INE)
        "tipoVal": TIPOS_DATO[tipo_dato],
        "anio[]": [str(a) for a in anios],
        "trimestre[]": ["1", "2", "3", "4"],
        "mes[]": [str(m) for m in range(1, 13)],
        "mes_nombres[]": MESES,
        "subgrupo[]": [str(d["subgrupo_id"]) for d in delitos],
        "subgrupo_nombres[]": [d["subgrupo"] for d in delitos],
        "seleccion": "2",  # tabla por delito
        "descarga": "false",
    }
    campo = {"pais": "region", "region": "region", "comuna": "comuna"}[territorio["nivel"]]
    nombres = {"region": "region_nombres", "comuna": "comuna_nombres"}[campo]
    datos[f"{campo}[]"] = [str(territorio["codigo"])]
    datos[f"{nombres}[]"] = [territorio["nombre"]]
    return datos


def descargar(session: requests.Session, datos: dict, intentos: int = 4) -> str:
    for intento in range(1, intentos + 1):
        try:
            resp = session.post(DATOS_URL, data=datos, timeout=180)
            resp.raise_for_status()
            return resp.content.decode("utf-8", errors="replace")
        except requests.RequestException as err:
            if intento == intentos:
                raise
            espera = 10 * 2 ** (intento - 1)  # 10, 20, 40 s
            log.warning("Error en la descarga (%s). Reintento %d en %d s", err, intento, espera)
            time.sleep(espera)
    raise RuntimeError("inalcanzable")


def descargar_territorio(session: requests.Session, territorio: dict, tipo_dato: str,
                         delitos: list[dict], anios: list[int]) -> list[tuple[int, int, int, int]]:
    """Cantidades de todos los años. Si el servidor no alcanza a responder (pasa con el país y
    las regiones grandes), divide los años en dos mitades y las pide por separado."""
    datos = parametros(territorio, tipo_dato, delitos, anios)
    if len(anios) == 1:
        return parsear_tabla(descargar(session, datos), delitos)
    try:
        resp = session.post(DATOS_URL, data=datos, timeout=180)
        resp.raise_for_status()
        return parsear_tabla(resp.content.decode("utf-8", errors="replace"), delitos)
    except requests.RequestException as err:
        log.info("%s %s, %d-%d: %s. Se divide en dos consultas",
                 territorio["nombre"], tipo_dato, anios[0], anios[-1], err.__class__.__name__)
        mitad = len(anios) // 2
        return (descargar_territorio(session, territorio, tipo_dato, delitos, anios[:mitad])
                + descargar_territorio(session, territorio, tipo_dato, delitos, anios[mitad:]))


def ultimo_mes_publicado(cantidades: list[tuple[int, int, int, int]]) -> tuple[int, int]:
    """Último (año, mes) con casos en el total del país: los meses siguientes aún no se publican."""
    por_mes: dict[tuple[int, int], int] = {}
    for _, anio, mes, v in cantidades:
        por_mes[(anio, mes)] = por_mes.get((anio, mes), 0) + v
    return max(p for p, total in por_mes.items() if total > 0)


def guardar_descarga(conn: sqlite3.Connection, territorio: dict, tipo_dato: str,
                     cantidades: list[tuple[int, int, int, int]], hasta: tuple[int, int]) -> int:
    """Reemplaza los datos del territorio y tipo, y registra la descarga, en una sola transacción."""
    filas = [
        (territorio["nivel"], territorio["codigo"], subgrupo, anio, mes, tipo_dato, v)
        for subgrupo, anio, mes, v in cantidades
        if v > 0 and (anio, mes) <= hasta
    ]
    clave = (territorio["nivel"], territorio["codigo"], tipo_dato)
    with conn:
        conn.execute("DELETE FROM casos WHERE nivel = ? AND codigo = ? AND tipo_dato = ?", clave)
        conn.executemany("INSERT INTO casos VALUES (?, ?, ?, ?, ?, ?, ?)", filas)
        conn.execute(
            "INSERT OR REPLACE INTO descargas VALUES (?, ?, ?, ?, ?, ?)",
            (*clave, len(filas), sum(f[-1] for f in filas), datetime.now(timezone.utc).isoformat(timespec="seconds")),
        )
    return len(filas)


def pendientes(conn: sqlite3.Connection, territorios: list[dict]) -> list[tuple[dict, str]]:
    hechas = set(conn.execute("SELECT nivel, codigo, tipo_dato FROM descargas"))
    return [
        (t, tipo)
        for t in territorios
        for tipo in TIPOS_DATO
        if (t["nivel"], t["codigo"], tipo) not in hechas
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--solo", choices=["regiones", "comunas"], help="limitar la descarga a un nivel")
    parser.add_argument("--pausa", type=float, default=1.5, help="segundos entre peticiones (default 1,5)")
    parser.add_argument("--rehacer", action="store_true", help="borrar el registro de descargas y bajar todo de nuevo")
    parser.add_argument("--db", type=Path, default=DB_POR_DEFECTO)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")

    conn = conectar(args.db)
    if args.rehacer:
        with conn:
            conn.execute("DELETE FROM descargas")

    session = requests.Session()
    session.headers.update({
        "User-Agent": USER_AGENT,
        "X-Requested-With": "XMLHttpRequest",
        "Referer": PAGINA_URL,
    })

    resp = session.get(PAGINA_URL, timeout=60)
    resp.raise_for_status()
    delitos, territorios = leer_catalogo(resp.content.decode("utf-8", errors="replace"))
    guardar_catalogo(conn, delitos, territorios)
    anios = list(range(ANIO_INICIAL, date.today().year + 1))
    log.info("Catálogo: %d subgrupos de delitos, %d territorios, años %d-%d",
             len(delitos), len(territorios), anios[0], anios[-1])

    # El total del país va primero: define hasta qué mes hay datos publicados
    pais = next(t for t in territorios if t["nivel"] == "pais")
    nacional = {tipo: descargar_territorio(session, pais, tipo, delitos, anios) for tipo in TIPOS_DATO}
    hasta = max(ultimo_mes_publicado(c) for c in nacional.values())
    with conn:
        conn.execute("INSERT OR REPLACE INTO meta VALUES ('ultimo_mes', ?)", (f"{hasta[0]}-{hasta[1]:02d}",))
        conn.execute("INSERT OR REPLACE INTO meta VALUES ('descargado_en', ?)", (date.today().isoformat(),))
    for tipo, cantidades in nacional.items():
        guardar_descarga(conn, pais, tipo, cantidades, hasta)
    log.info("Datos publicados hasta %d-%02d", *hasta)

    niveles = {"regiones": {"region"}, "comunas": {"comuna"}}.get(args.solo, {"region", "comuna"})
    cola = pendientes(conn, [t for t in territorios if t["nivel"] in niveles])
    log.info("%d descargas pendientes (base: %s)", len(cola), args.db)

    inicio = time.monotonic()
    for i, (territorio, tipo) in enumerate(cola, start=1):
        cantidades = descargar_territorio(session, territorio, tipo, delitos, anios)
        guardar_descarga(conn, territorio, tipo, cantidades, hasta)

        if i % 20 == 0 or i == len(cola):
            transcurrido = time.monotonic() - inicio
            restante = transcurrido / i * (len(cola) - i)
            log.info("%d/%d descargas (%s %s, %s) · faltan ~%.0f min",
                     i, len(cola), territorio["nivel"], territorio["nombre"], tipo, restante / 60)
        time.sleep(args.pausa)

    conn.close()
    log.info("Listo.")


if __name__ == "__main__":
    main()
