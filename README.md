# Delitos en Chile: qué dicen (y qué no) los registros policiales, 2005–2026

¿Hay más delitos en Chile que antes? ¿Dónde se concentran? Este proyecto responde esas preguntas con los **casos policiales** que publica el **Centro de Estudios y Análisis del Delito (CEAD)**: mes a mes desde enero de 2005, para 48 subgrupos de delitos, el total del país, las 16 regiones y las 346 comunas. Los datos se obtienen con web scraping, se guardan en SQLite y se analizan con Python, junto con la población del INE.

No soy experto en seguridad: soy analista de datos. Por eso la mitad del trabajo es entender qué miden estos registros y qué cambios del propio registro hay que tener en cuenta antes de sacar conclusiones.

El resultado es una nota interactiva, con gráficos y explicación de cada hallazgo, publicada en mi portafolio.

- **Nota interactiva:** _(enlace al portafolio, próximamente)_

> En 2024 hice una primera versión ([rrdiegoisaac/delincuencia](https://github.com/rrdiegoisaac/delincuencia)): una aplicación en Streamlit con 35 delitos por región hasta 2023. Esta la rehice desde cero: el CEAD cambió de sitio y de clasificación de delitos, y ahora el análisis llega a nivel de comuna y trata explícitamente los límites de los datos.

## Hallazgos principales

- **Los casos policiales no han vuelto al nivel de antes de la pandemia.** En 2025, las 7 familias de delitos sumaron 5.678 casos por cada 100.000 habitantes: un 17% menos que en 2019 y un 35% menos que el máximo de 2011.
- **Pero no todo baja.** Los homicidios pasaron de 3,7 a 4,9 casos por 100.000 habitantes entre 2019 y 2025, y los delitos de drogas están en su nivel más alto. Los delitos contra la propiedad no violentos (hurtos, robos en casas) y las incivilidades cayeron con la pandemia y no volvieron.
- **Los robos violentos se concentran en la Región Metropolitana**, con una tasa 1,9 veces la de la región que le sigue.
- **El registro cambia, no solo los delitos.** Hay subgrupos que empiezan a registrarse a mitad del período (robo violento de vehículos desde diciembre de 2019), saltos que no son delitos (otras infracciones a la ley de armas se triplican desde mayo de 2024, casi todo por denuncias) y una categoría residual, *otros delitos o faltas*, que ya es el 42% de todos los casos.
- **Un caso policial no es un delito ocurrido.** En drogas, el 77% de los casos son detenciones en flagrancia: miden también la actividad policial. Y según la ENUSC 2024, el 55% de los hogares víctimas de un delito violento no lo denunció.

## Cómo está hecho

```
cead.minsegpublica.gob.cl ──► scraper (requests + BeautifulSoup) ──► SQLite ◄── población INE (xlsx + Censo 2024)
                                                                       │
                                                                       ▼
                                                   análisis (pandas) ──► JSON ──► gráficos (React + Recharts)
```

1. **Scraping.** El formulario de estadísticas del CEAD consulta una API que devuelve una tabla HTML. El scraper pide, para cada territorio y tipo de dato (denuncias y detenciones), los 48 subgrupos de delitos en todos los meses desde 2005.
   - **Control de calidad:** compara cada fila con la clasificación esperada y verifica que el total de cada familia sea la suma de sus subgrupos. Si algo no cuadra, se detiene en vez de guardar datos mal asignados.
   - **Consultas pesadas:** si el servidor no alcanza a responder (pasa con el país y las regiones grandes), divide los años en dos mitades y las pide por separado.
   - **Reanudable:** cada territorio se guarda en una sola transacción junto con su registro de descarga.
2. **Población.** Proyecciones del INE por comuna y año (base Censo 2017), las mismas que usa el CEAD en sus tasas, y la población censada en 2024 por comuna, para medir la sensibilidad de los rankings.
3. **Análisis.**
   - Revisión de cambios de registro: subgrupos nuevos, saltos de un mes a otro y la categoría residual.
   - Tasas por 100.000 habitantes por familia, de 2005 a 2025, con 2019 como referencia prepandemia.
   - Delitos violentos: homicidios y robos, con sumas móviles de 12 meses.
   - Peso de las detenciones en flagrancia en cada subgrupo.
   - Regiones y comunas: tasas, concentración y sensibilidad al denominador de población.
4. **Exportación.** Cada sección genera un JSON resumido que consumen los gráficos de la nota.

## Estructura

```
scraper/
  scrape_cead.py       Descarga los casos policiales del CEAD a SQLite
  poblacion.py         Población por comuna del INE (proyecciones y Censo 2024)
analisis/
  datos.py             Carga de casos, población y definiciones comunes
  exportar.py          Calcula cada sección y exporta los JSON
  exportar_kaggle.py   Genera los archivos para publicar el dataset
tests/                 Pruebas del parser y de las funciones del análisis (pytest)
consultas.sql          Consultas de exploración con CTE y funciones de ventana
data/
  delitos.db           Base SQLite (no se incluye en el repo: se regenera con los scripts de scraper/)
export/                Resultados resumidos (JSON) para los gráficos
```

La base `delitos.db` tiene estas tablas:

| Tabla | Contenido |
|---|---|
| `casos` | Cantidad de casos por territorio (`nivel`: país, región o comuna; `codigo`), subgrupo de delito, año, mes y tipo de dato (`denuncias` o `detenciones`). Solo guarda cantidades mayores a 0: un mes sin fila en una descarga completa es 0. |
| `delitos` | Clasificación del CEAD: subgrupo, grupo y familia, con sus códigos. |
| `territorios` | País, regiones y comunas, con el código y el nombre que usa el CEAD. |
| `descargas` | Control de avance del scraper: territorio, tipo de dato, filas y total descargado. |
| `meta` | Último mes publicado y fecha de descarga. |
| `comunas` | Código comunal (CUT), nombre, provincia y región según el INE. |
| `poblacion` | Proyección del INE por comuna y año, 2002–2035 (base Censo 2017). |
| `poblacion_censo2024` | Población censada en 2024 por comuna. |

## Cómo reproducirlo

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows  (en macOS/Linux: source .venv/bin/activate)
pip install -r requirements.txt

python scraper/scrape_cead.py --solo regiones   # país y regiones (~5 minutos)
python scraper/scrape_cead.py                   # además, las 346 comunas (~1 hora)
python scraper/poblacion.py                     # población del INE
python analisis/exportar.py                     # genera export/*.json

pip install -r requirements-dev.txt
python -m pytest                                # pruebas
```

Si la descarga se interrumpe, al volver a ejecutarla sigue desde el último territorio guardado. El CEAD corrige cifras pasadas, así que para actualizar todo se usa `--rehacer`.

## Decisiones de análisis

- **Casos policiales** = denuncias + detenciones en flagrancia, en Carabineros y la PDI. Se descargan por separado para medir qué parte de cada delito llega por cada vía.
- **Tasas** por 100.000 habitantes, con las proyecciones de población del INE (base Censo 2017). Comprobé que son las mismas que usa el CEAD: con ellas se reproduce su tasa nacional publicada.
- **Categoría residual.** *Otros delitos o faltas* no dice qué delitos agrupa y su tamaño cambia mucho entre años: se muestra aparte y no entra en los totales.
- **Robos violentos** = robos con violencia o intimidación + robos violentos de vehículos + robos por sorpresa. Los de vehículos se registran aparte desde diciembre de 2019; para comparar en el tiempo se suman con los robos con violencia.
- **Año de referencia:** 2019, el último año completo antes de la pandemia. Las comparaciones anuales llegan hasta 2025; el primer semestre de 2026 se compara con el mismo período de 2025.
- **Comunas.** Los rankings solo incluyen comunas de 50.000 habitantes o más. Los homicidios por comuna y región se promedian en 3 años.

## Limitaciones conocidas

- **Un caso policial no es un delito ocurrido.** Los delitos que no se denuncian no aparecen, y los que dependen de detenciones en flagrancia (drogas, porte de armas) también reflejan la actividad policial.
- **Cambios de registro.** Subgrupos que aparecen a mitad del período, saltos de un mes a otro sin explicación en los datos y una categoría residual que crece. Se documentan en la nota y en `01_registro.json`.
- **Homicidios.** Son casos conocidos por las policías, preliminares según el propio CEAD. La cifra oficial de víctimas la publica el Centro para la Prevención de Homicidios y Delitos Violentos.
- **Población.** Las proyecciones comunales base 2017 se reemplazarán por unas basadas en el Censo 2024 (el INE las anunció para el segundo semestre de 2026). En algunas comunas la población censada difiere bastante de la proyectada, lo que puede cambiar sus tasas.
- **Población flotante.** Las tasas se calculan con los residentes de cada comuna; en comunas con mucho comercio y oficinas, la tasa sube porque muchas de las personas que circulan no viven ahí.
- **Revisiones.** El CEAD actualiza sus cifras: una descarga posterior puede dar valores algo distintos.

## Fuentes

- **Casos policiales:** Centro de Estudios y Análisis del Delito (CEAD), Ministerio de Seguridad Pública. <https://cead.minsegpublica.gob.cl/estadisticas-delictuales/>
- **Definición de casos policiales y nota sobre homicidios:** CEAD, informe de casos policiales enero–junio 2026. <https://cead.minsegpublica.gob.cl/wp-content/uploads/download-manager-files/casos-policiales-ene-jun-2026.pdf>
- **Población por comuna:** INE, estimaciones y proyecciones 2002–2035, base Censo 2017. <https://www.ine.gob.cl/docs/default-source/proyecciones-de-poblacion/cuadros-estadisticos/base-2017/estimaciones-y-proyecciones-2002-2035-comunas.xlsx>
- **Censo 2024:** INE, resultados por comuna. <https://censo2024.ine.gob.cl/resultados/>
- **Omisión censal y población base 2024:** INE, estimaciones y proyecciones de población base 2024 (enero de 2026). <https://www.ine.gob.cl/docs/default-source/prensa-y-comunicacion/eepp2024.pdf>
- **Denuncia de delitos violentos:** INE, ENUSC 2024. <https://www.ine.gob.cl/sala-de-prensa/prensa/general/noticia/2025/07/07/subsecretar%C3%ADa-de-prevenci%C3%B3n-del-delito-e-ine-presentan-los-resultados-de-la-encuesta-nacional-urbana-de-seguridad-ciudadana-(enusc)-2024>
- **Homicidios (cifra oficial):** Centro para la Prevención de Homicidios y Delitos Violentos. <https://prevenciondehomicidios.cl/estadisticas>

## Autor

**Diego Riquelme**, Data Analyst · [GitHub](https://github.com/rrdiegoisaac)
