-- Consultas de exploración sobre data/delitos.db (SQLite 3.25 o superior, por las funciones de ventana).
-- Se pueden ejecutar en DB Browser for SQLite, DBeaver o con: sqlite3 data/delitos.db < consultas.sql
--
-- Recordatorio: la tabla casos solo guarda cantidades mayores a 0, y casos policiales = denuncias + detenciones.


-- 1. Casos policiales por año y familia de delitos en el total del país
SELECT c.anio,
       d.familia,
       SUM(c.cantidad) AS casos
FROM casos c
JOIN delitos d USING (subgrupo_id)
WHERE c.nivel = 'pais'
GROUP BY c.anio, d.familia
ORDER BY c.anio, casos DESC;


-- 2. Tasa de robos violentos por cada 100.000 habitantes, por región y año,
--    y variación respecto del año anterior (LAG)
WITH robos AS (
    SELECT c.codigo AS region_codigo,
           c.anio,
           SUM(c.cantidad) AS casos
    FROM casos c
    JOIN delitos d USING (subgrupo_id)
    WHERE c.nivel = 'region' AND d.familia_id = 2
    GROUP BY c.codigo, c.anio
),
poblacion_region AS (
    SELECT co.region_codigo,
           p.anio,
           SUM(p.poblacion) AS poblacion
    FROM poblacion p
    JOIN comunas co USING (cut)
    GROUP BY co.region_codigo, p.anio
),
tasas AS (
    SELECT t.nombre AS region,
           r.anio,
           ROUND(r.casos * 100000.0 / pr.poblacion, 1) AS tasa
    FROM robos r
    JOIN poblacion_region pr USING (region_codigo, anio)
    JOIN territorios t ON t.nivel = 'region' AND t.codigo = r.region_codigo
)
SELECT region,
       anio,
       tasa,
       ROUND(tasa - LAG(tasa) OVER (PARTITION BY region ORDER BY anio), 1) AS cambio_vs_anio_anterior
FROM tasas
ORDER BY region, anio;


-- 3. Las 5 comunas con más robos violentos por habitante en cada región, último año completo
--    (ROW_NUMBER por partición, solo comunas de 50.000 habitantes o más)
WITH robos AS (
    SELECT c.codigo AS cut,
           SUM(c.cantidad) AS casos
    FROM casos c
    JOIN delitos d USING (subgrupo_id)
    WHERE c.nivel = 'comuna' AND d.familia_id = 2 AND c.anio = 2025
    GROUP BY c.codigo
),
ranking AS (
    SELECT co.region,
           co.comuna,
           p.poblacion,
           ROUND(r.casos * 100000.0 / p.poblacion, 1) AS tasa,
           ROW_NUMBER() OVER (PARTITION BY co.region ORDER BY r.casos * 1.0 / p.poblacion DESC) AS puesto
    FROM robos r
    JOIN comunas co USING (cut)
    JOIN poblacion p ON p.cut = r.cut AND p.anio = 2025
    WHERE p.poblacion >= 50000
)
SELECT region, puesto, comuna, poblacion, tasa
FROM ranking
WHERE puesto <= 5
ORDER BY region, puesto;


-- 4. Qué parte de cada subgrupo son detenciones en flagrancia (y no denuncias), último año completo
SELECT d.familia,
       d.subgrupo,
       SUM(c.cantidad) AS casos,
       ROUND(100.0 * SUM(CASE WHEN c.tipo_dato = 'detenciones' THEN c.cantidad ELSE 0 END) / SUM(c.cantidad), 1) AS pct_detenciones
FROM casos c
JOIN delitos d USING (subgrupo_id)
WHERE c.nivel = 'pais' AND c.anio = 2025
GROUP BY d.subgrupo_id
ORDER BY pct_detenciones DESC;


-- 5. Homicidios: suma móvil de 12 meses en el total del país (ventana de filas)
WITH mensual AS (
    SELECT c.anio,
           c.mes,
           SUM(c.cantidad) AS casos
    FROM casos c
    JOIN delitos d USING (subgrupo_id)
    WHERE c.nivel = 'pais' AND d.grupo_id = 101
    GROUP BY c.anio, c.mes
)
SELECT printf('%d-%02d', anio, mes) AS periodo,
       casos,
       SUM(casos) OVER (ORDER BY anio, mes ROWS BETWEEN 11 PRECEDING AND CURRENT ROW) AS ultimos_12_meses
FROM mensual
ORDER BY anio, mes;


-- 6. Control de calidad: total del país contra la suma de las regiones y de las comunas, por año
SELECT anio,
       SUM(CASE WHEN nivel = 'pais' THEN cantidad END)   AS pais,
       SUM(CASE WHEN nivel = 'region' THEN cantidad END) AS suma_regiones,
       SUM(CASE WHEN nivel = 'comuna' THEN cantidad END) AS suma_comunas
FROM casos
GROUP BY anio
ORDER BY anio;
