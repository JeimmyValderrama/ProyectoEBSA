"""
Arma una carpeta lista para compartir con quien solo va a ABRIR LA PÁGINA (no corre el pipeline).
La carpeta trae las DOS versiones de la página, que se abren por separado y leen los mismos datos:
    app_ebsa.py       la página original
    app_ebsa_v2.py    la página con la interfaz nueva (necesita componentes_v2.py y la carpeta recursos_v2)

    python empaquetar_app.py                      -> C:\\Users\\Home\\Documents\\EBSA_app_para_compartir
    python empaquetar_app.py --destino D:\\EBSA_app
    python empaquetar_app.py --sin-exportes       -> sin 11_exportes_negocio (la sección "Descargas" queda vacía; ahorra ~350 MB)
    python empaquetar_app.py --incluir-claves     -> copia también .streamlit\\secrets.toml (los usuarios y claves de ESTA máquina)

Qué deja en la carpeta destino:
    app_ebsa.py, app_ebsa_v2.py, componentes_v2.py, recursos_v2\\, utilidades_glosario.py
    requirements_app.txt, INICIAR_APP.bat (original), INICIAR_APP_V2.bat (interfaz nueva), LEEME.txt
    .streamlit\\config.toml  y  secrets.toml.ejemplo (plantilla de usuarios, SIN claves reales)
    datos\\  con SOLO lo que las páginas leen (sin archivos de la empresa, sin modelos .joblib, sin respaldos)

Claves: por seguridad el paquete NO lleva .streamlit\\secrets.toml. Quien lo recibe crea el suyo a partir de
secrets.toml.ejemplo (el LEEME.txt explica cómo). Con --incluir-claves se copia el de esta máquina, como hacía la
versión anterior de este programa: úsalo solo si el paquete va a alguien que deba tener esas mismas claves.

Datos: la carpeta datos\\ lleva información de clientes de la empresa (NIU, dirección, consumo). No es pública.

En el otro computador basta con: pip install -r requirements_app.txt, crear el archivo de usuarios y doble clic en
INICIAR_APP.bat o INICIAR_APP_V2.bat. Las páginas encuentran la carpeta datos\\ solas porque está junto a ellas.
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

CODIGO = Path(__file__).resolve().parent
DATOS = Path(os.environ.get("EBSA_DATOS", r"C:\Users\Home\Documents\Datos_Ebsa"))

ARCHIVOS_CODIGO = ["app_ebsa.py", "utilidades_glosario.py"]                 # la página original
ARCHIVOS_V2 = ["app_ebsa_v2.py", "componentes_v2.py"]                       # la página con la interfaz nueva
CARPETA_RECURSOS_V2 = "recursos_v2"                                         # tipografías y límites municipales de la V2
ARCHIVOS_CONFIG = [".streamlit/config.toml"]
ARCHIVO_CLAVES = ".streamlit/secrets.toml"                                  # solo con --incluir-claves
PLANTILLA_CLAVES = "secrets.toml.ejemplo"
# Nada de esto debe quedar nunca en el paquete (se revisa al final)
PROHIBIDOS_NOMBRE = {".git", ".gitignore", "__pycache__", ".ipynb_checkpoints", "00_formato_TC1", "00_formato_TC2", "00_otros_comercializadores"}
PROHIBIDOS_SUFIJO = {".joblib", ".pyc", ".ipynb", ".xlsx", ".xls", ".zip", ".docx", ".pptx", ".pdf"}

# Lo que la página lee de la carpeta de datos (ver clase Rutas en app_ebsa.py). Las carpetas se copian
# completas salvo las exclusiones; los archivos sueltos se copian uno a uno.
CARPETAS = {
    "03_serie_modelado": {"excluir": set()},
    "04_pronostico/modelo_final": {"excluir": {"modelos_ganadores_optimizados_final.joblib",
                                               "real_vs_pronosticado_sistema_optimizado_backtest.parquet",
                                               "predicciones_segmentadas_optimizadas_3_meses.parquet",
                                               "historial_pronosticos"}},
    "05_segmentos_clientes": {"excluir": {"features_clientes_consumo.parquet", "modelo_agrupamiento.joblib"}},
    "06_estudio_caida": {"excluir": {"criterios_caida_por_segmento.joblib"}},
    "07_gestion_caida": {"excluir": set()},
    "08_seguimiento": {"excluir": set()},
    "10_riesgo_fuga": {"excluir": {"modelo_riesgo_fuga.joblib", "etiquetas_salida_por_niu.csv", "historial", "optuna_ensayos_fuga.csv"}},
    "11_exportes_negocio": {"excluir": set()},          # se omite con --sin-exportes
    "12_versiones_modelos": {"excluir": set()},
    "13_ubicacion_clientes": {"excluir": set()},
    "14_proyeccion_anual": {"excluir": set()},
}
ARCHIVOS_SUELTOS = ["02_serie_reconstruida/control_calidad_mes_entrante.csv"]
# Del registro de corridas solo el resumen de texto de cada corrida (la página muestra las últimas 10)
REGISTRO = "09_registro_corridas"

BAT = """@echo off
cd /d "%~dp0"
echo Abriendo la pagina EBSA - Consumo, version original (se abre en el navegador; cierra esta ventana para apagarla)
python -m streamlit run app_ebsa.py --server.port 8501
pause
"""

BAT_V2 = """@echo off
cd /d "%~dp0"
echo Abriendo la pagina EBSA - Consumo, interfaz nueva (se abre en el navegador; cierra esta ventana para apagarla)
python -m streamlit run app_ebsa_v2.py --server.port 8502
pause
"""

LEEME = """EBSA - Consumo de clientes: paginas para consulta (sin pipeline)
====================================================================
Proyecto academico (Especializacion en Analitica Estrategica de Datos, UPTC). No es un producto oficial de EBSA.

Esta carpeta trae DOS versiones de la misma pagina. Muestran las mismas cifras; cambia la presentacion.
    INICIAR_APP.bat      pagina original           -> http://localhost:8501
    INICIAR_APP_V2.bat   pagina con interfaz nueva -> http://localhost:8502
Se pueden abrir las dos al tiempo (cada una en su ventana de consola).

Como ponerla a funcionar
1. Instalar Python 3.10 o superior (https://www.python.org, marcar "Add python to PATH").
2. En esta carpeta abrir una consola y correr una sola vez:   pip install -r requirements_app.txt
3. Crear el archivo de usuarios (una sola vez):
       mkdir .streamlit                                   (si la carpeta no existe)
       copy secrets.toml.ejemplo .streamlit\\secrets.toml
   y abrir .streamlit\\secrets.toml con el Bloc de notas para cambiar cada clave "CAMBIAR" por una propia.
   Mientras una clave diga CAMBIAR, ese usuario no puede entrar. Si el paquete ya trae .streamlit\\secrets.toml,
   este paso no hace falta: quien lo envio dira las claves por otro medio.
4. Doble clic en INICIAR_APP.bat o en INICIAR_APP_V2.bat.

Usuarios: comercial (vista Comercial), soporte (Comercial y Soporte), admin (las tres vistas).

Si algo falla
- "Falta el archivo de usuarios": falta el paso 3.
- "Usuario o clave incorrectos": la clave sigue en CAMBIAR o no coincide con la del archivo.
- La interfaz nueva se ve sin estilos o sin mapa: falta la carpeta recursos_v2 o el archivo componentes_v2.py.
- "No module named streamlit": falta el paso 2.
- El puerto esta ocupado: cerrar la otra ventana de consola o abrir con otro puerto:
       python -m streamlit run app_ebsa_v2.py --server.port 8503

Datos y confidencialidad
La carpeta datos\\ es una copia de las salidas del pipeline a la fecha indicada abajo. No se actualiza sola:
cuando haya un mes nuevo, pedir la carpeta otra vez. Los archivos de la empresa (TC1, TC2) y los modelos
entrenados NO vienen en esta copia; las paginas no los necesitan.
La carpeta datos\\ contiene informacion de clientes de la empresa (NIU, direccion, consumo): es para uso interno
del equipo. No publicarla ni subirla a internet. La interfaz nueva tiene la opcion "Ocultar NIU y direcciones"
(en Datos y sesion) para presentar en pantalla sin mostrar identificadores.
"""

REQUIREMENTS = """streamlit>=1.40
pandas>=2.0
numpy
pyarrow
plotly
altair
"""


def tamano(p: Path) -> int:
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file()) if p.is_dir() else p.stat().st_size


def copiar_carpeta(origen: Path, destino: Path, excluir: set) -> int:
    if not origen.exists():
        print(f"  (no existe {origen.relative_to(DATOS)}, se omite)")
        return 0
    shutil.copytree(origen, destino, dirs_exist_ok=True,
                    ignore=lambda d, names: [n for n in names if n in excluir or n == "__pycache__"
                                             or n.lower().endswith((".joblib", ".pyc"))])   # nunca modelos entrenados ni temporales
    return tamano(destino)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--destino", default=str(DATOS.parent / "EBSA_app_para_compartir"))
    ap.add_argument("--sin-exportes", action="store_true", help="no copiar 11_exportes_negocio (~350 MB)")
    ap.add_argument("--incluir-claves", action="store_true",
                    help="copiar también .streamlit\\secrets.toml (usuarios y claves de esta máquina); por defecto NO se copia")
    args = ap.parse_args()

    destino = Path(args.destino)
    if not DATOS.exists():
        sys.exit(f"No existe la carpeta de datos {DATOS} (o fija EBSA_DATOS).")
    if destino.exists():
        print(f"La carpeta {destino} ya existe: se reemplaza su contenido.")
        shutil.rmtree(destino)
    destino.mkdir(parents=True)
    (destino / "datos").mkdir()

    print("Código y configuración")
    for a in ARCHIVOS_CODIGO:
        shutil.copy2(CODIGO / a, destino / a)
    # Interfaz nueva (V2): se incluye si están sus tres piezas; si falta alguna, el paquete sale solo con la original
    faltan_v2 = [a for a in ARCHIVOS_V2 if not (CODIGO / a).exists()] + ([] if (CODIGO / CARPETA_RECURSOS_V2).is_dir() else [CARPETA_RECURSOS_V2])
    con_v2 = not faltan_v2
    if con_v2:
        for a in ARCHIVOS_V2:
            shutil.copy2(CODIGO / a, destino / a)
        shutil.copytree(CODIGO / CARPETA_RECURSOS_V2, destino / CARPETA_RECURSOS_V2,
                        ignore=lambda d, names: [n for n in names if n == "__pycache__" or n.endswith(".pyc")])
        print("  página original e interfaz nueva (V2)")
    else:
        print(f"  ⚠ no se incluye la interfaz nueva (V2): falta {', '.join(faltan_v2)}. El paquete sale solo con la página original.")
    for a in ARCHIVOS_CONFIG:
        o = CODIGO / a
        if o.exists():
            (destino / a).parent.mkdir(exist_ok=True)
            shutil.copy2(o, destino / a)
    if (CODIGO / PLANTILLA_CLAVES).exists():
        shutil.copy2(CODIGO / PLANTILLA_CLAVES, destino / PLANTILLA_CLAVES)
    else:
        print(f"  ⚠ falta {PLANTILLA_CLAVES}: quien reciba el paquete no tendrá plantilla para crear sus usuarios")
    if args.incluir_claves:
        o = CODIGO / ARCHIVO_CLAVES
        if o.exists():
            (destino / ARCHIVO_CLAVES).parent.mkdir(exist_ok=True)
            shutil.copy2(o, destino / ARCHIVO_CLAVES)
            print("  ⚠ --incluir-claves: el paquete LLEVA los usuarios y claves de esta máquina. Envíalo solo a quien deba tenerlos.")
        else:
            print(f"  ⚠ --incluir-claves: no existe {ARCHIVO_CLAVES}; el paquete sale sin claves")
    else:
        print("  sin claves: quien reciba el paquete crea .streamlit\\secrets.toml desde secrets.toml.ejemplo (ver LEEME.txt)")
    (destino / "requirements_app.txt").write_text(REQUIREMENTS, encoding="utf-8")
    (destino / "INICIAR_APP.bat").write_text(BAT, encoding="utf-8")
    if con_v2:
        (destino / "INICIAR_APP_V2.bat").write_text(BAT_V2, encoding="utf-8")

    print("Datos que lee la página")
    total = 0
    for carpeta, cfg in CARPETAS.items():
        if args.sin_exportes and carpeta == "11_exportes_negocio":
            print(f"  {carpeta:<28} omitida (--sin-exportes)")
            continue
        n = copiar_carpeta(DATOS / carpeta, destino / "datos" / carpeta, cfg["excluir"])
        total += n
        print(f"  {carpeta:<28} {n / 1e6:8.1f} MB")
    for a in ARCHIVOS_SUELTOS:
        o = DATOS / a
        if o.exists():
            (destino / "datos" / a).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(o, destino / "datos" / a)
            total += o.stat().st_size
    reg = DATOS / REGISTRO
    if reg.exists():
        for c in sorted([p for p in reg.iterdir() if p.is_dir()], reverse=True)[:10]:
            r = c / "resumen_corrida.txt"
            if r.exists():
                (destino / "datos" / REGISTRO / c.name).mkdir(parents=True, exist_ok=True)
                shutil.copy2(r, destino / "datos" / REGISTRO / c.name / r.name)

    cortes = DATOS / "03_serie_modelado" / "cortes_por_zona.csv"
    fecha = cortes.read_text(encoding="utf-8-sig").splitlines()[1].split(",")[1][:7] if cortes.exists() else "?"
    (destino / "LEEME.txt").write_text(LEEME + f"\nCorte de los datos: {fecha}\n", encoding="utf-8")

    # Revisión final: nada sensible ni sobrante dentro del paquete
    malos = []
    for f in destino.rglob("*"):
        if f.name in PROHIBIDOS_NOMBRE or (f.is_file() and f.suffix.lower() in PROHIBIDOS_SUFIJO):
            malos.append(f)
        elif f.is_file() and f.name == "secrets.toml" and not args.incluir_claves:
            malos.append(f)
    if malos:
        print("\n⚠ REVISAR antes de enviar: el paquete contiene archivos que no deberían ir:")
        for f in malos[:20]:
            print("   ", f.relative_to(destino))
    else:
        print("\nRevisión: sin claves" + (" (salvo las pedidas con --incluir-claves)" if args.incluir_claves else "")
              + ", sin modelos .joblib, sin archivos de la empresa, sin notebooks y sin carpetas temporales.")
    print("Recuerda: datos\\ lleva información de clientes (NIU, dirección, consumo). Es para el equipo; no publicarla.")

    print(f"\nListo: {destino}")
    print(f"Tamaño total: {tamano(destino) / 1e6:,.0f} MB (datos: {total / 1e6:,.0f} MB)")
    print("Comprimir la carpeta y enviarla; en el otro PC: pip install -r requirements_app.txt, crear el archivo de usuarios"
          " (LEEME.txt) y doble clic en INICIAR_APP.bat o INICIAR_APP_V2.bat")


if __name__ == "__main__":
    main()
