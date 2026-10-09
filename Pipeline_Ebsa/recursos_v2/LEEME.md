# recursos_v2 — archivos que usa `app_ebsa_v2.py`

Esta carpeta va junto a `app_ebsa_v2.py` y `componentes_v2.py`. La página original (`app_ebsa.py`) no la usa.

## limites_municipios_boyaca.geojson

Límites de los 123 municipios de Boyacá para el mapa.

- **Fuente de los límites:** Departamento Administrativo Nacional de Estadística (DANE), Marco Geoestadístico Nacional (MGN), nivel municipio.
- **De dónde se descargaron:** del proyecto geoBoundaries (conjunto *gbOpen*, Colombia, nivel ADM2, año de referencia 2020), que redistribuye
  los límites del DANE. Sus metadatos registran: fuente "Departamento Administrativo Nacional de Estadistica", licencia
  "Creative Commons Attribution 4.0 International (CC BY 4.0)" y como origen la página de descarga del MGN en el geoportal del DANE.
  Archivo: `https://github.com/wmgeolab/geoBoundaries` → `releaseData/gbOpen/COL/ADM2/`.
- **Licencia:** CC BY 4.0 (permite usar, copiar y adaptar citando la fuente e indicando los cambios).
- **Cambios hechos para este proyecto:** se dejaron solo los 123 municipios de Boyacá; la geometría se simplificó (tolerancia de 0,002 grados,
  unos 220 m, conservando los bordes compartidos entre municipios vecinos) y se redondeó a 4 decimales para que el archivo pese unos 250 KB;
  a cada municipio se le añadió su código DANE de cinco dígitos. El contorno del departamento es la unión de sus municipios.
- **Cómo se emparejó cada polígono con su municipio:** el archivo de geoBoundaries trae el nombre del municipio pero no su código. A cada uno de
  los 123 municipios de `13_ubicacion_clientes/municipios_zona.csv` se le asignó el polígono que contiene el centro de sus clientes, y se comprobó
  que el nombre coincidiera: 120 coinciden letra por letra y 3 solo difieren en la forma de escribirlo (Santa Rosa de Viterbo, San Pablo de
  Borbur, Labranzagrande). Ningún polígono quedó asignado a dos municipios.
- **Lo que NO se pudo verificar directamente:** la página "Licencia y condiciones de uso" del geoportal del DANE no permite la lectura
  automática, así que la licencia se tomó de los metadatos de geoBoundaries y no de la página del DANE. Antes de publicar el mapa fuera del
  ámbito académico conviene abrir esa página en el navegador y confirmarla: `https://geoportal.dane.gov.co/acerca-del-geoportal/licencia-y-condiciones-de-uso/`
- **Precisión:** son límites simplificados para verse en pantalla. No sirven para medir áreas ni para decidir a qué municipio pertenece un predio.

El archivo no contiene ningún dato de clientes.

Si el archivo falta, la página sigue funcionando: dibuja el mapa de círculos de la versión anterior (su fondo necesita internet) y lo avisa.

## fuentes/

Tipografías de la página (Barlow Semi Condensed y Source Sans 3), con licencia SIL Open Font License 1.1. Ver `fuentes/LICENCIAS_FUENTES.txt`.
Se cargan desde aquí, sin internet. Si faltan, la página usa las tipografías del sistema.
