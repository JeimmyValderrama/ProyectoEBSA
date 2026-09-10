"""
pipeline_mensual.py — corre la cadena de notebooks del proyecto EBSA en orden
============================================================================

Uso (desde la carpeta del código, C:\\Users\\Home\\Documents\\GitHub\\ProyectoEBSA\\Pipeline_Ebsa):

    python pipeline_mensual.py --modo aplicar        # corrida MENSUAL (llegó el archivo nuevo)
    python pipeline_mensual.py --modo reentrenar     # corrida TRIMESTRAL / cuando toque reentrenar
    python pipeline_mensual.py --modo aplicar --desde 9     # reanudar desde el paso 9
    python pipeline_mensual.py --solo 11,12                 # correr solo esos pasos
    python pipeline_mensual.py --lista                      # ver los pasos y salir
    python pipeline_mensual.py --modo aplicar --datos "D:\\otra\\ruta\\Datos_Ebsa"
    python pipeline_mensual.py --modo aplicar --corte-max 2025-09 --solo 3,8,9,10,11,12,13,14,15
                                                            # simulación: como si el archivo terminara en 2025-09
    python pipeline_mensual.py --modo aplicar --version-modelo 2025-06   # aplicar con los modelos de esa versión

Qué hace
--------
Ejecuta cada notebook de arriba abajo con un kernel limpio, en el orden de
dependencia, con dos variables de entorno que los notebooks ya leen:

    EBSA_MODO  = aplicar | reentrenar
    EBSA_DATOS = carpeta raíz de datos (por defecto C:\\Users\\Home\\Documents\\Datos_Ebsa)

Cada notebook ejecutado (con sus salidas) queda guardado como registro de la
corrida en  <datos>\\09_registro_corridas\\<fecha-hora>_<modo>\\NN_nombre.ipynb, junto con
un resumen_corrida.txt. Los notebooks originales NO se modifican.

Si un paso falla, el pipeline se detiene ahí, muestra el error y sale con
código 1. Se puede reanudar con --desde N una vez corregido.

Modo aplicar vs reentrenar
--------------------------
    aplicar     : usa los modelos guardados (pronóstico, agrupamiento y criterios
                  de caída) sin volver a entrenarlos. Tarda minutos.
    reentrenar  : backtest + reentrenamiento del pronóstico, nueva comparación de
                  algoritmos de agrupamiento y recálculo de criterios de caída.
                  Tarda horas. Hacerlo cada trimestre/semestre o cuando el
                  seguimiento mensual muestre que el error en vivo se degrada.

Los notebooks de desarrollo (4, 5, 6 y 7: primeros modelos, comparación de
algoritmos y Optuna) no forman parte de la corrida: se repiten solo si se
quiere volver a elegir algoritmos o hiperparámetros.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import time
import traceback

# Windows: si la salida va a un archivo o a otro proceso (simular_meses.py), Python usa
# cp1252 y no puede escribir "✓" / "✗". Se fuerza UTF-8 en la salida de este script.
import sys as _sys
for _s in (_sys.stdout, _sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
from datetime import datetime
from pathlib import Path

# Código: la carpeta donde está este archivo (GitHub\ProyectoEBSA\Pipeline_Ebsa).
# Datos: C:\Users\Home\Documents\Datos_Ebsa, salvo que se indique otra con
# --datos o con la variable de entorno EBSA_DATOS.
CODIGO_DIR = Path(__file__).resolve().parent
DATOS_POR_DEFECTO = r"C:\Users\Home\Documents\Datos_Ebsa"

# (número, archivo, descripción, corre en aplicar, corre en reentrenar)
PASOS = [
    (1, "Exploracion_inicial.ipynb", "Leer los XLSX/CSV (formato TC2) de 00_formato_TC2 -> 01_historico_procesado/historico_YYYY.parquet", True, True),
    (2, "Reconstruccion_serie_tiempo_consumo_rural.ipynb", "Control de calidad del mes entrante + serie mensual (lecturas trimestrales repartidas)", True, True),
    (3, "Preprocesamiento_serie_tiempo_para_modelado.ipynb", "Excluir alumbrado público, marcar rurales, dejar la serie lista", True, True),
    (8, "Backtest_y_reentrenamiento_final_optimizado.ipynb", "Pronóstico a 6 meses (aplicar: modelos guardados | reentrenar: backtest + entrenamiento)", True, True),
    (9, "Agrupamiento_clientes_consumo.ipynb", "Segmentos de negocio (aplicar: modelo guardado | reentrenar: nueva comparación)", True, True),
    (10, "Estudio_caida_consumo.ipynb", "Caída de consumo por cliente (aplicar: criterios guardados | reentrenar: recalcular)", True, True),
    (11, "Priorizacion_gestion_caida.ipynb", "Listas de gestión por ciclo y gerencial, con historial", True, True),
    (12, "Seguimiento_pronostico_mensual.ipynb", "Pronósticos y listas anteriores contra lo que realmente pasó", True, True),
    (13, "Evaluacion_retroalimentacion_gestion.ipynb", "Resultados de las visitas en campo contra las listas (si hay datos)", True, True),
    (14, "Riesgo_fuga_comercializador.ipynb", "Riesgo de fuga a otro comercializador (aplicar: modelo guardado | reentrenar: entrena y evalúa)", True, True),
    (15, "Exportes_negocio.ipynb", "Archivos por grupo de consumo con nombres de negocio (pronóstico, caída y fuga) -> 11_exportes_negocio", True, True),
]


def listar():
    print("Pasos de la corrida (en orden):")
    for n, archivo, desc, _, _ in PASOS:
        existe = "" if (CODIGO_DIR / archivo).exists() else "   <-- NO ENCONTRADO"
        print(f"  {n:>2}. {archivo:<55} {desc}{existe}")


def ejecutar_notebook(ruta_nb: Path, ruta_salida: Path) -> None:
    import nbformat
    from nbclient import NotebookClient

    nb = nbformat.read(ruta_nb, as_version=4)
    celdas_codigo = [c for c in nb.cells if c.cell_type == "code"]
    total = len(celdas_codigo)
    inicio_nb = time.time()

    def titulo_celda(celda) -> str:
        """Segunda línea del encabezado de la celda ('# 8. CALCULAR PERFIL ...'), si la hay."""
        lineas = [l.strip() for l in celda.source.splitlines() if l.strip()]
        for l in lineas[:3]:
            if l.startswith("#") and not l.startswith("# ===") and len(l) > 2:
                return l.lstrip("# ").strip()[:70]
        return (lineas[0][:70] if lineas else "")

    def al_terminar_celda(cell=None, cell_index=None, **kwargs):
        # Avance dentro del paso: una línea por celda, con el tiempo acumulado.
        if cell is None or cell.cell_type != "code":
            return
        n = celdas_codigo.index(cell) + 1 if cell in celdas_codigo else cell_index
        minutos = (time.time() - inicio_nb) / 60
        print(f"       celda {n:>2}/{total}  {minutos:6.1f} min  {titulo_celda(cell)}", flush=True)

    cliente = NotebookClient(
        nb,
        timeout=None,                 # el backtest puede tardar horas
        kernel_name="python3",
        resources={"metadata": {"path": str(CODIGO_DIR)}},  # para que funcione `import utilidades_borde`
        allow_errors=False,
        on_cell_executed=al_terminar_celda,
    )
    try:
        cliente.execute()
    except Exception as e:  # noqa: BLE001
        # Mostrar en consola lo que la celda alcanzó a imprimir antes de fallar:
        # casi siempre ahí está la explicación (p. ej. la tabla del control de calidad).
        for c in nb.cells:
            if c.cell_type != "code":
                continue
            if any(o.get("output_type") == "error" for o in c.get("outputs", [])):
                texto = "".join(
                    "".join(o.get("text", "")) for o in c.get("outputs", [])
                    if o.get("output_type") == "stream"
                )
                if texto.strip():
                    print("\n     --- Salida de la celda que falló (últimas líneas) ---")
                    for linea in texto.rstrip().splitlines()[-40:]:
                        print("     " + linea)
                    print("     " + "-" * 55)
                break
        raise e
    finally:
        # se guarda lo que alcanzó a ejecutarse, con error incluido, como registro
        ruta_salida.parent.mkdir(parents=True, exist_ok=True)
        nbformat.write(nb, ruta_salida)


def main() -> int:
    parser = argparse.ArgumentParser(description="Corrida mensual del proyecto EBSA")
    parser.add_argument("--modo", choices=["aplicar", "reentrenar"], default=None,
                        help="aplicar = modelos guardados (mensual); reentrenar = entrenar de nuevo")
    parser.add_argument("--datos", default=os.environ.get("EBSA_DATOS", DATOS_POR_DEFECTO),
                        help="carpeta raíz de datos (EBSA_DATOS)")
    parser.add_argument("--desde", type=int, default=None, help="reanudar desde este número de paso")
    parser.add_argument("--hasta", type=int, default=None, help="detenerse después de este paso")
    parser.add_argument("--solo", default=None, help="lista de pasos separados por coma, p. ej. 11,12")
    parser.add_argument("--lista", action="store_true", help="mostrar los pasos y salir")
    parser.add_argument("--corte-max", default=None, metavar="AAAA-MM",
                        help="simulación: usar solo datos hasta este mes (la serie se recorta en el paso 3)")
    parser.add_argument("--version-modelo", default=None, metavar="AAAA-MM",
                        help="aplicar con una versión guardada de los modelos (12_versiones_modelos) en vez de la vigente")
    args = parser.parse_args()

    if args.lista:
        listar()
        return 0

    if args.modo is None:
        parser.error("indica --modo aplicar (mensual) o --modo reentrenar")

    datos_dir = Path(args.datos)
    if not datos_dir.exists():
        print(f"ERROR: no existe la carpeta de datos: {datos_dir}")
        return 1

    # Selección de pasos
    seleccion = []
    solo = {int(x) for x in args.solo.split(",")} if args.solo else None
    for n, archivo, desc, en_aplicar, en_reentrenar in PASOS:
        if solo is not None and n not in solo:
            continue
        if args.desde is not None and n < args.desde:
            continue
        if args.hasta is not None and n > args.hasta:
            continue
        if args.modo == "aplicar" and not en_aplicar:
            continue
        if args.modo == "reentrenar" and not en_reentrenar:
            continue
        seleccion.append((n, archivo, desc))

    faltantes = [a for _, a, _ in seleccion if not (CODIGO_DIR / a).exists()]
    if faltantes:
        print("ERROR: faltan notebooks en", CODIGO_DIR)
        for a in faltantes:
            print("  •", a)
        return 1
    for modulo in ("utilidades_borde.py", "utilidades_calidad.py", "utilidades_glosario.py", "utilidades_versiones.py"):
        if not (CODIGO_DIR / modulo).exists():
            print(f"ERROR: {modulo} debe estar en", CODIGO_DIR)
            return 1

    os.environ["EBSA_MODO"] = args.modo
    os.environ["EBSA_DATOS"] = str(datos_dir)
    for var in ("EBSA_CORTE_MAX", "EBSA_VERSION_MODELO"):
        os.environ.pop(var, None)
    sufijo = ""
    if args.corte_max:
        if not re.match(r"^\d{4}-\d{2}$", args.corte_max):
            parser.error("--corte-max debe tener la forma AAAA-MM")
        os.environ["EBSA_CORTE_MAX"] = args.corte_max
        sufijo += f"_corte{args.corte_max}"
    if args.version_modelo:
        if args.modo != "aplicar":
            parser.error("--version-modelo solo tiene sentido con --modo aplicar")
        if not re.match(r"^\d{4}-\d{2}$", args.version_modelo):
            parser.error("--version-modelo debe tener la forma AAAA-MM")
        os.environ["EBSA_VERSION_MODELO"] = args.version_modelo
        sufijo += f"_modelo{args.version_modelo}"

    marca = datetime.now().strftime("%Y-%m-%d_%H%M")
    corrida_dir = datos_dir / "09_registro_corridas" / f"{marca}_{args.modo}{sufijo}"
    corrida_dir.mkdir(parents=True, exist_ok=True)
    resumen = corrida_dir / "resumen_corrida.txt"

    def log(linea: str):
        print(linea, flush=True)
        with open(resumen, "a", encoding="utf-8") as f:
            f.write(linea + "\n")

    log("=" * 78)
    log(f"CORRIDA EBSA  modo={args.modo}  datos={datos_dir}"
        + (f"  corte_max={args.corte_max}" if args.corte_max else "")
        + (f"  version_modelo={args.version_modelo}" if args.version_modelo else ""))
    log(f"Código: {CODIGO_DIR}")
    log(f"Registro: {corrida_dir}")
    log(f"Pasos: {[n for n, _, _ in seleccion]}")
    log("=" * 78)

    inicio_total = time.time()
    for n, archivo, desc in seleccion:
        log(f"\n[{n:>2}] {archivo}")
        log(f"     {desc}")
        inicio = time.time()
        salida = corrida_dir / f"{n:02d}_{archivo}"
        try:
            ejecutar_notebook(CODIGO_DIR / archivo, salida)
        except Exception as e:  # noqa: BLE001
            minutos = (time.time() - inicio) / 60
            log(f"     ✗ FALLÓ a los {minutos:.1f} min")
            log("     " + type(e).__name__ + ": " + str(e).strip().splitlines()[-1][:300])
            log(f"     El notebook con el error quedó en: {salida}")
            log(f"     Corrige y reanuda con:  python pipeline_mensual.py --modo {args.modo} --desde {n}")
            with open(corrida_dir / "traceback.txt", "w", encoding="utf-8") as f:
                f.write(traceback.format_exc())
            return 1
        minutos = (time.time() - inicio) / 60
        log(f"     ✓ terminado en {minutos:.1f} min -> {salida.name}")

    log("\n" + "=" * 78)
    log(f"CORRIDA COMPLETA en {(time.time() - inicio_total) / 60:.1f} min")
    log("Salidas para la página: ")
    log(f"  • {datos_dir / '07_gestion_caida'}")
    log(f"  • {datos_dir / '04_pronostico' / 'modelo_final'}")
    log(f"  • {datos_dir / '08_seguimiento'}")
    log(f"  • {datos_dir / '10_riesgo_fuga'}")
    log(f"  • {datos_dir / '11_exportes_negocio'}  (archivos por grupo de consumo para descargar)")
    log("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main())
