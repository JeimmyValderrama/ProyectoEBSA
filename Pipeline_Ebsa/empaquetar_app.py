"""
Arma una carpeta lista para compartir con quien solo va a ABRIR LA PÁGINA (no corre el pipeline).

    python empaquetar_app.py                      -> C:\\Users\\Home\\Documents\\EBSA_app_para_compartir
    python empaquetar_app.py --destino D:\\EBSA_app
    python empaquetar_app.py --sin-exportes       -> sin 11_exportes_negocio (la sección "Descargas" queda vacía; ahorra ~350 MB)

Qué deja en la carpeta destino:
    app_ebsa.py, utilidades_glosario.py, requirements_app.txt, INICIAR_APP.bat, LEEME.txt
    .streamlit\\config.toml y .streamlit\\secrets.toml (los usuarios y claves de esta máquina)
    datos\\  con SOLO lo que la página lee (sin archivos de la empresa, sin modelos .joblib, sin respaldos)

En el otro computador basta con: pip install -r requirements_app.txt  y doble clic en INICIAR_APP.bat.
La app encuentra la carpeta datos\\ sola porque está junto a ella.
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

CODIGO = Path(__file__).resolve().parent
DATOS = Path(os.environ.get("EBSA_DATOS", r"C:\Users\Home\Documents\Datos_Ebsa"))

ARCHIVOS_CODIGO = ["app_ebsa.py", "utilidades_glosario.py"]
ARCHIVOS_CONFIG = [".streamlit/config.toml", ".streamlit/secrets.toml"]

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
echo Abriendo la pagina EBSA - Consumo (se abre en el navegador; cierra esta ventana para apagarla)
python -m streamlit run app_ebsa.py
pause
"""

LEEME = """EBSA - Consumo de clientes: pagina para consulta (sin pipeline)
=================================================================
1. Instalar Python 3.10 o superior (https://www.python.org, marcar "Add python to PATH").
2. En esta carpeta abrir una consola y correr una sola vez:   pip install -r requirements_app.txt
3. Doble clic en INICIAR_APP.bat (o en consola: python -m streamlit run app_ebsa.py).
   Se abre en el navegador en http://localhost:8501
4. Usuarios y claves: estan en .streamlit\\secrets.toml (comercial / soporte / admin). Se pueden cambiar ahi.

La carpeta datos\\ es una copia de las salidas del pipeline a la fecha indicada abajo. No se actualiza sola:
cuando haya un mes nuevo, pedir la carpeta otra vez. Los archivos de la empresa (TC1, TC2) y los modelos
entrenados NO vienen en esta copia; la pagina no los necesita.
"""

REQUIREMENTS = """streamlit>=1.38
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
                    ignore=lambda d, names: [n for n in names if n in excluir or n == "__pycache__"])
    return tamano(destino)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--destino", default=str(DATOS.parent / "EBSA_app_para_compartir"))
    ap.add_argument("--sin-exportes", action="store_true", help="no copiar 11_exportes_negocio (~350 MB)")
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
    for a in ARCHIVOS_CONFIG:
        o = CODIGO / a
        if o.exists():
            (destino / a).parent.mkdir(exist_ok=True)
            shutil.copy2(o, destino / a)
        else:
            print(f"  ⚠ falta {a}: la página pedirá el archivo de usuarios (copiar secrets.toml.ejemplo como .streamlit\\secrets.toml)")
    (destino / "requirements_app.txt").write_text(REQUIREMENTS, encoding="utf-8")
    (destino / "INICIAR_APP.bat").write_text(BAT, encoding="utf-8")

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

    print(f"\nListo: {destino}")
    print(f"Tamaño total: {tamano(destino) / 1e6:,.0f} MB (datos: {total / 1e6:,.0f} MB)")
    print("Comprimir la carpeta y enviarla; en el otro PC: pip install -r requirements_app.txt y doble clic en INICIAR_APP.bat")


if __name__ == "__main__":
    main()
