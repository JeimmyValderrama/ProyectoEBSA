"""
pipeline_mensual.py — corre la cadena de notebooks del proyecto EBSA en orden
============================================================================

Este archivo soporta la siguiente estructura:

    Pipeline_Ebsa/
    ├── pipeline_mensual.py
    ├── notebooks/
    │   ├── 01_exploracion/
    │   ├── 02_preparacion_datos/
    │   ├── 03_desarrollo_prediccion/
    │   ├── 04_produccion_prediccion/
    │   ├── 05_segmentacion_clientes/
    │   ├── 06_analisis_caidas/
    │   ├── 07_riesgo_fuga/
    │   ├── 08_seguimiento/
    │   └── 09_exportes/
    └── utilidades/
        ├── utilidades_borde.py
        ├── utilidades_calidad.py
        ├── utilidades_glosario.py
        └── utilidades_versiones.py

Uso desde la carpeta Pipeline_Ebsa:

    python pipeline_mensual.py --modo aplicar
    python pipeline_mensual.py --modo reentrenar
    python pipeline_mensual.py --modo aplicar --desde 9
    python pipeline_mensual.py --solo 11,12
    python pipeline_mensual.py --lista
    python pipeline_mensual.py --modo aplicar --datos "D:\\otra\\ruta\\Datos_Ebsa"
    python pipeline_mensual.py --modo aplicar --corte-max 2025-09 --solo 3,8,9,10,11,12,13,14,15
    python pipeline_mensual.py --modo aplicar --version-modelo 2025-06

Qué hace
--------
Ejecuta los notebooks seleccionados con un kernel limpio y en el orden de
sus dependencias. Las rutas de los notebooks son relativas a la carpeta
"notebooks" y las utilidades se cargan desde la carpeta "utilidades".

Variables de entorno disponibles para los notebooks:

    EBSA_MODO       = aplicar | reentrenar
    EBSA_DATOS      = carpeta raíz de datos
    EBSA_CODIGO     = carpeta raíz de Pipeline_Ebsa
    EBSA_NOTEBOOKS  = carpeta de notebooks
    EBSA_UTILIDADES = carpeta de utilidades
    EBSA_CORTE_MAX  = AAAA-MM, si se utiliza --corte-max
    EBSA_VERSION_MODELO = AAAA-MM, si se utiliza --version-modelo

Cada notebook ejecutado queda guardado como registro en:

    <datos>/09_registro_corridas/<fecha-hora>_<modo>/NN_nombre.ipynb

Los notebooks originales no se modifican. Si un paso falla, el pipeline se
detiene y guarda el notebook parcial y el traceback.

Modos
-----
aplicar:
    Usa los modelos, segmentos y criterios guardados. Está pensado para la
    corrida mensual y normalmente tarda minutos.

reentrenar:
    Reentrena o recalcula los componentes que correspondan. Está pensado para
    una corrida trimestral/semestral o cuando el seguimiento indique deterioro.

Los notebooks de desarrollo de modelos no se ejecutan en esta cadena operativa.
Se ejecutan manualmente cuando se necesita volver a comparar algoritmos u
optimizar hiperparámetros.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path


# Windows: fuerza UTF-8 en la salida de este script para soportar símbolos
# como ✓, ⚠ y ✗ cuando la salida se redirige a un archivo o proceso.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------------------
# Rutas del proyecto
# ---------------------------------------------------------------------------

# Carpeta donde está este archivo. No depende de la carpeta desde la que se
# ejecute el comando.
CODIGO_DIR = Path(__file__).resolve().parent

# Subcarpetas del código.
NOTEBOOKS_DIR = CODIGO_DIR / "notebooks"
UTILIDADES_DIR = CODIGO_DIR / "utilidades"

# Ruta por defecto de los datos. Puede cambiarse con --datos o EBSA_DATOS.
DATOS_POR_DEFECTO = r"C:\Users\patri\Documents\Datos_Ebsa"


# ---------------------------------------------------------------------------
# Pasos operativos
# ---------------------------------------------------------------------------
#
# Formato:
# (número, ruta relativa dentro de notebooks, descripción,
#  corre_en_aplicar, corre_en_reentrenar)
#
# El número representa el orden lógico del pipeline. La carpeta del notebook
# puede tener otra numeración; no es obligatorio que ambas coincidan.

PASOS = [
    (
        1,
        Path("01_exploracion") / "Exploracion_inicial.ipynb",
        "Leer los XLSX/CSV y crear el histórico procesado",
        True,
        True,
    ),
    (
        2,
        Path("02_preparacion_datos")
        / "Reconstruccion_serie_tiempo_consumo_rural.ipynb",
        "Control de calidad del mes entrante y reconstrucción mensual",
        True,
        True,
    ),
    (
        3,
        Path("02_preparacion_datos")
        / "Preprocesamiento_serie_tiempo_para_modelado.ipynb",
        "Excluir Alumbrado Público, marcar rurales y preparar la serie",
        True,
        True,
    ),
    (
        8,
        Path("04_produccion_prediccion")
        / "Backtest_y_reentrenamiento_final_optimizado.ipynb",
        "Pronóstico a seis meses: modelos guardados o reentrenamiento",
        True,
        True,
    ),
    (
        9,
        Path("05_segmentacion_clientes")
        / "Agrupamiento_clientes_consumo.ipynb",
        "Segmentos de negocio: modelo guardado o nueva comparación",
        True,
        True,
    ),
    (
        10,
        Path("06_analisis_caidas") / "Estudio_caida_consumo.ipynb",
        "Calcular la caída de consumo por cliente",
        True,
        True,
    ),
    (
        11,
        Path("06_analisis_caidas") / "Priorizacion_gestion_caida.ipynb",
        "Crear listas de gestión por ciclo y ranking gerencial",
        True,
        True,
    ),
    (
        12,
        Path("08_seguimiento") / "Seguimiento_pronostico_mensual.ipynb",
        "Comparar pronósticos y listas anteriores contra la realidad",
        True,
        True,
    ),
    (
        13,
        Path("08_seguimiento")
        / "Evaluacion_retroalimentacion_gestion.ipynb",
        "Evaluar los resultados de las visitas de campo",
        True,
        True,
    ),
    (
        14,
        Path("07_riesgo_fuga") / "Riesgo_fuga_comercializador.ipynb",
        "Calcular el riesgo de fuga a otro comercializador",
        True,
        True,
    ),
    (
        15,
        Path("09_exportes") / "Exportes_negocio.ipynb",
        "Generar archivos por grupo de consumo para negocio",
        True,
        True,
    ),
]


# ---------------------------------------------------------------------------
# Utilidades internas
# ---------------------------------------------------------------------------


def ruta_notebook(archivo: Path) -> Path:
    """Devuelve la ruta absoluta de un notebook del proyecto."""
    return NOTEBOOKS_DIR / archivo


def preparar_entorno_notebooks() -> None:
    """Expone las rutas del proyecto y las utilidades a los notebooks."""
    os.environ["EBSA_CODIGO"] = str(CODIGO_DIR)
    os.environ["EBSA_NOTEBOOKS"] = str(NOTEBOOKS_DIR)
    os.environ["EBSA_UTILIDADES"] = str(UTILIDADES_DIR)

    # NotebookClient inicia un kernel separado. Por eso la carpeta de
    # utilidades debe viajar también en PYTHONPATH; modificar sys.path aquí
    # solo afecta al proceso del pipeline, no necesariamente al kernel.
    rutas_python = [str(UTILIDADES_DIR), str(CODIGO_DIR)]
    pythonpath_actual = os.environ.get("PYTHONPATH", "")
    rutas_existentes = [ruta for ruta in pythonpath_actual.split(os.pathsep) if ruta]
    for ruta in rutas_python:
        if ruta not in rutas_existentes:
            rutas_existentes.insert(0, ruta)
    os.environ["PYTHONPATH"] = os.pathsep.join(rutas_existentes)

    # Permite que los notebooks importen utilidades aunque estén dentro de
    # subcarpetas, por ejemplo:
    # from utilidades_borde import ultimo_periodo_consolidado
    for ruta in (CODIGO_DIR, UTILIDADES_DIR):
        ruta_texto = str(ruta)
        if ruta_texto not in sys.path:
            sys.path.insert(0, ruta_texto)


def listar() -> None:
    """Muestra los pasos y comprueba si cada notebook existe."""
    print("Pasos de la corrida (en orden):")
    print(f"Carpeta de notebooks: {NOTEBOOKS_DIR}")
    print(f"Carpeta de utilidades: {UTILIDADES_DIR}")
    print()

    for numero, archivo, descripcion, _, _ in PASOS:
        ruta = ruta_notebook(archivo)
        estado = "" if ruta.exists() else "   <-- NO ENCONTRADO"
        print(f"  {numero:>2}. {str(archivo):<85} {descripcion}{estado}")


def validar_utilidades() -> list[Path]:
    """Devuelve las utilidades obligatorias que no existen."""
    nombres = (
        "utilidades_borde.py",
        "utilidades_calidad.py",
        "utilidades_glosario.py",
        "utilidades_versiones.py",
    )
    return [UTILIDADES_DIR / nombre for nombre in nombres if not (UTILIDADES_DIR / nombre).exists()]


def ejecutar_notebook(ruta_nb: Path, ruta_salida: Path) -> None:
    """Ejecuta un notebook y guarda siempre una copia del resultado."""
    import nbformat
    from nbclient import NotebookClient

    preparar_entorno_notebooks()

    nb = nbformat.read(ruta_nb, as_version=4)
    celdas_codigo = [celda for celda in nb.cells if celda.cell_type == "code"]
    total = len(celdas_codigo)
    inicio_nb = time.time()

    def titulo_celda(celda) -> str:
        """Obtiene un título breve del encabezado de la celda."""
        lineas = [
            linea.strip()
            for linea in celda.source.splitlines()
            if linea.strip()
        ]

        for linea in lineas[:3]:
            if linea.startswith("#") and not linea.startswith("# ===") and len(linea) > 2:
                return linea.lstrip("# ").strip()[:70]

        return lineas[0][:70] if lineas else ""

    def al_terminar_celda(cell=None, cell_index=None, **kwargs):
        """Muestra el avance de ejecución celda por celda."""
        if cell is None or cell.cell_type != "code":
            return

        try:
            numero_celda = celdas_codigo.index(cell) + 1
        except ValueError:
            numero_celda = cell_index

        minutos = (time.time() - inicio_nb) / 60
        print(
            f"       celda {numero_celda:>2}/{total}"
            f"  {minutos:6.1f} min  {titulo_celda(cell)}",
            flush=True,
        )

    cliente = NotebookClient(
        nb,
        timeout=None,  # Algunos backtests pueden tardar horas.
        kernel_name="python3",
        # Los notebooks pueden importar módulos desde la raíz del código y
        # desde Pipeline_Ebsa/utilidades/.
        resources={"metadata": {"path": str(CODIGO_DIR)}},
        allow_errors=False,
        on_cell_executed=al_terminar_celda,
    )

    try:
        cliente.execute()
    except Exception as error:  # noqa: BLE001
        # Muestra la salida de la celda que falló antes de propagar el error.
        for celda in nb.cells:
            if celda.cell_type != "code":
                continue

            salidas_error = [
                salida
                for salida in celda.get("outputs", [])
                if salida.get("output_type") == "error"
            ]

            if not salidas_error:
                continue

            texto = "".join(
                "".join(salida.get("text", ""))
                for salida in celda.get("outputs", [])
                if salida.get("output_type") == "stream"
            )

            if texto.strip():
                print("\n     --- Salida de la celda que falló ---")
                for linea in texto.rstrip().splitlines()[-40:]:
                    print("     " + linea)
                print("     " + "-" * 55)
            break

        raise error
    finally:
        # Se guarda lo ejecutado incluso si el notebook termina con error.
        ruta_salida.parent.mkdir(parents=True, exist_ok=True)
        nbformat.write(nb, ruta_salida)


# ---------------------------------------------------------------------------
# Programa principal
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description="Corrida mensual del proyecto EBSA")

    parser.add_argument(
        "--modo",
        choices=["aplicar", "reentrenar"],
        default=None,
        help="aplicar = modelos guardados; reentrenar = entrenar de nuevo",
    )
    parser.add_argument(
        "--datos",
        default=os.environ.get("EBSA_DATOS", DATOS_POR_DEFECTO),
        help="carpeta raíz de datos; también puede definirse con EBSA_DATOS",
    )
    parser.add_argument(
        "--desde",
        type=int,
        default=None,
        help="reanudar desde este número de paso",
    )
    parser.add_argument(
        "--hasta",
        type=int,
        default=None,
        help="detenerse después de este número de paso",
    )
    parser.add_argument(
        "--solo",
        default=None,
        help="lista de pasos separados por coma, por ejemplo 11,12",
    )
    parser.add_argument(
        "--lista",
        action="store_true",
        help="mostrar los pasos y salir",
    )
    parser.add_argument(
        "--corte-max",
        default=None,
        metavar="AAAA-MM",
        help="simulación: usar los datos solo hasta este mes",
    )
    parser.add_argument(
        "--version-modelo",
        default=None,
        metavar="AAAA-MM",
        help="aplicar una versión guardada de los modelos",
    )

    args = parser.parse_args()

    preparar_entorno_notebooks()

    if args.lista:
        listar()
        return 0

    if args.modo is None:
        parser.error("indica --modo aplicar o --modo reentrenar")

    datos_dir = Path(args.datos).expanduser().resolve()
    if not datos_dir.exists():
        print(f"ERROR: no existe la carpeta de datos: {datos_dir}")
        return 1

    # Validación de formatos de parámetros.
    if args.corte_max and not re.match(r"^\d{4}-\d{2}$", args.corte_max):
        parser.error("--corte-max debe tener la forma AAAA-MM")

    if args.version_modelo:
        if args.modo != "aplicar":
            parser.error("--version-modelo solo tiene sentido con --modo aplicar")
        if not re.match(r"^\d{4}-\d{2}$", args.version_modelo):
            parser.error("--version-modelo debe tener la forma AAAA-MM")

    # Selección de pasos.
    try:
        solo = {int(x.strip()) for x in args.solo.split(",")} if args.solo else None
    except ValueError:
        parser.error("--solo debe contener números separados por coma, por ejemplo 11,12")

    seleccion = []
    for numero, archivo, descripcion, en_aplicar, en_reentrenar in PASOS:
        if solo is not None and numero not in solo:
            continue
        if args.desde is not None and numero < args.desde:
            continue
        if args.hasta is not None and numero > args.hasta:
            continue
        if args.modo == "aplicar" and not en_aplicar:
            continue
        if args.modo == "reentrenar" and not en_reentrenar:
            continue

        seleccion.append((numero, archivo, descripcion))

    # Validar notebooks seleccionados.
    faltantes = [
        archivo
        for _, archivo, _ in seleccion
        if not ruta_notebook(archivo).exists()
    ]

    if faltantes:
        print(f"ERROR: faltan notebooks en {NOTEBOOKS_DIR}")
        for archivo in faltantes:
            print(f"  • {archivo}")
        return 1

    # Validar utilidades compartidas.
    utilidades_faltantes = validar_utilidades()
    if utilidades_faltantes:
        print(f"ERROR: faltan utilidades en {UTILIDADES_DIR}")
        for ruta in utilidades_faltantes:
            print(f"  • {ruta.name}")
        return 1

    # Variables de entorno disponibles para todos los notebooks.
    os.environ["EBSA_MODO"] = args.modo
    os.environ["EBSA_DATOS"] = str(datos_dir)
    os.environ["EBSA_CODIGO"] = str(CODIGO_DIR)
    os.environ["EBSA_NOTEBOOKS"] = str(NOTEBOOKS_DIR)
    os.environ["EBSA_UTILIDADES"] = str(UTILIDADES_DIR)

    # Limpiar variables opcionales de ejecuciones anteriores.
    os.environ.pop("EBSA_CORTE_MAX", None)
    os.environ.pop("EBSA_VERSION_MODELO", None)

    sufijo = ""

    if args.corte_max:
        os.environ["EBSA_CORTE_MAX"] = args.corte_max
        sufijo += f"_corte{args.corte_max}"

    if args.version_modelo:
        os.environ["EBSA_VERSION_MODELO"] = args.version_modelo
        sufijo += f"_modelo{args.version_modelo}"

    # Carpeta de registro de la corrida.
    marca = datetime.now().strftime("%Y-%m-%d_%H%M")
    corrida_dir = datos_dir / "09_registro_corridas" / f"{marca}_{args.modo}{sufijo}"
    corrida_dir.mkdir(parents=True, exist_ok=True)
    resumen = corrida_dir / "resumen_corrida.txt"

    def log(linea: str) -> None:
        print(linea, flush=True)
        with open(resumen, "a", encoding="utf-8") as archivo_resumen:
            archivo_resumen.write(linea + "\n")

    log("=" * 78)
    log(
        f"CORRIDA EBSA  modo={args.modo}  datos={datos_dir}"
        + (f"  corte_max={args.corte_max}" if args.corte_max else "")
        + (
            f"  version_modelo={args.version_modelo}"
            if args.version_modelo
            else ""
        )
    )
    log(f"Código: {CODIGO_DIR}")
    log(f"Notebooks: {NOTEBOOKS_DIR}")
    log(f"Utilidades: {UTILIDADES_DIR}")
    log(f"Registro: {corrida_dir}")
    log(f"Pasos: {[numero for numero, _, _ in seleccion]}")
    log("=" * 78)

    inicio_total = time.time()

    for numero, archivo, descripcion in seleccion:
        log(f"\n[{numero:>2}] {archivo}")
        log(f"     {descripcion}")
        inicio = time.time()

        # El registro se guarda plano. Así no se crean subcarpetas dentro de
        # la carpeta de cada corrida por causa de la ruta original del notebook.
        nombre_salida = Path(archivo).name
        salida = corrida_dir / f"{numero:02d}_{nombre_salida}"
        origen = ruta_notebook(archivo)

        try:
            ejecutar_notebook(origen, salida)
        except Exception as error:  # noqa: BLE001
            minutos = (time.time() - inicio) / 60
            log(f"     ✗ FALLÓ a los {minutos:.1f} min")
            log(
                "     "
                + type(error).__name__
                + ": "
                + str(error).strip().splitlines()[-1][:300]
            )
            log(f"     El notebook con el error quedó en: {salida}")
            log(
                "     Corrige y reanuda con: "
                f"python pipeline_mensual.py --modo {args.modo} --desde {numero}"
            )

            with open(corrida_dir / "traceback.txt", "w", encoding="utf-8") as archivo_traceback:
                archivo_traceback.write(traceback.format_exc())

            return 1

        minutos = (time.time() - inicio) / 60
        log(f"     ✓ terminado en {minutos:.1f} min -> {salida.name}")

    log("\n" + "=" * 78)
    log(f"CORRIDA COMPLETA en {(time.time() - inicio_total) / 60:.1f} min")
    log("Salidas principales para la página:")
    log(f"  • {datos_dir / '07_gestion_caida'}")
    log(f"  • {datos_dir / '04_pronostico' / 'modelo_final'}")
    log(f"  • {datos_dir / '08_seguimiento'}")
    log(f"  • {datos_dir / '10_riesgo_fuga'}")
    log(
        f"  • {datos_dir / '11_exportes_negocio'}"
        "  (archivos por grupo de consumo para descargar)"
    )
    log("=" * 78)

    return 0


if __name__ == "__main__":
    sys.exit(main())
