"""
Control de calidad del mes entrante — EBSA
==========================================

Por qué existe
--------------
Cada mes llega un archivo nuevo de la empresa y el pipeline lo procesa de
corrido. Si ese archivo llega mal (la mitad de los clientes, tarifas en cero,
un ciclo nuevo que nadie clasificó como rural o urbano, una columna
renombrada), nada lo detiene hoy: el error entra al pronóstico y a las listas
de gestión en silencio.

Este módulo mira el ÚLTIMO mes del histórico unido y lo compara con los 12
anteriores. Si algo se sale de lo razonable, falla ruidosamente ANTES de
reconstruir la serie. Es preferible parar y mirar el archivo a producir
salidas equivocadas.

Uso (Reconstruccion_serie_tiempo_consumo_rural.ipynb, después de unir los
historico_YYYY.parquet):

    from utilidades_calidad import validar_mes_entrante

    reporte = validar_mes_entrante(historico, ciclos_conocidos=CICLOS_CONOCIDOS)
    reporte.to_csv(ruta_reporte, index=False, encoding="utf-8-sig")

Qué revisa (cada chequeo dice si es ERROR o AVISO)
--------------------------------------------------
  columnas_esenciales   ERROR si falta alguna columna que usa el pipeline.
  clientes_caida        ERROR si el número de NIU del mes cae más de 10% frente
                        a la mediana de los 12 previos (archivo truncado).
  clientes_subida       AVISO si sube más de 15%. No es error: el archivo del mes
                        más reciente suele traer fila para todos los clientes,
                        rurales sin lectura trimestral incluidos (enero 2026:
                        579 mil frente a 358 mil de un mes normal).
  consumo_total         ERROR si el consumo total del mes queda por debajo del
                        55% de la mediana previa. (El último mes siempre llega
                        algo bajo por las lecturas trimestrales pendientes de
                        los rurales: el detector del borde se encarga de eso.
                        Este tope solo atrapa un archivo truncado de verdad.)
  consumo_nulo          ERROR si más del 5% de las filas del mes no traen consumo.
  tarifa                ERROR si la mediana de la tarifa del mes queda fuera del
                        rango plausible o si más del 5% viene nula o en cero.
  ciclos_nuevos         ERROR si aparece un ciclo que no está en la lista de
                        ciclos conocidos (hay que clasificarlo rural/urbano en
                        Preprocesamiento antes de seguir).
  clase_servicio_nueva  AVISO si aparece una clase de servicio nueva.
  duplicados            ERROR si hay NIU repetidos dentro del mes.
  fechas_lectura        AVISO si más del 20% de las filas del mes no traen
                        fecha de lectura (la reconstrucción rural las usa).
  periodo_esperado      AVISO si el último mes no es el siguiente al anterior
                        (mes saltado).

Los umbrales se pueden ajustar con los parámetros de la función.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

__all__ = ["validar_mes_entrante", "CICLOS_CONOCIDOS"]

# Ciclos vistos en las extracciones hasta 2026-01 (Preprocesamiento, celda de
# distribución por ciclo). Si aparece uno nuevo hay que decidir si es rural
# (lectura trimestral) o urbano y añadirlo en Preprocesamiento (CICLOS_RURALES).
CICLOS_CONOCIDOS = [0, 1, 2, 3, 4, 5, 6, 7, 9, 10, 11, 12, 13, 15, 19, 21, 22, 23, 33, 38, 50, 90]

COLUMNAS_ESENCIALES = [
    "NIU", "periodo", "consumo_kwh_raw", "dias_facturados_max",
    "fecha_lectura_anterior", "fecha_lectura_actual",
    "tarifa_aplicada_kwh", "ciclo", "clase_servicio",
]


def _fila(chequeo, nivel, ok, valor, referencia, detalle):
    return {
        "chequeo": chequeo,
        "nivel": nivel,
        "resultado": "OK" if ok else nivel,
        "valor_mes": valor,
        "referencia": referencia,
        "detalle": detalle,
    }


def validar_mes_entrante(
    historico: pd.DataFrame,
    col_periodo: str = "periodo",
    ciclos_conocidos=CICLOS_CONOCIDOS,
    meses_referencia: int = 12,
    caida_max_clientes_pct: float = 10.0,
    subida_max_clientes_pct: float = 15.0,
    consumo_min_pct: float = 55.0,
    nulos_max_consumo_pct: float = 5.0,
    tarifa_min: float = 100.0,
    tarifa_max: float = 3000.0,
    tarifa_nula_max_pct: float = 5.0,
    fechas_faltantes_max_pct: float = 20.0,
    estricto: bool = True,
    verbose: bool = True,
) -> pd.DataFrame:
    """Valida el último mes del histórico contra los previos.

    Devuelve un DataFrame con un chequeo por fila. Si `estricto` y algún
    chequeo de nivel ERROR falla, lanza ValueError con el resumen.
    """
    filas = []

    # --- columnas esenciales ---
    faltan = [c for c in COLUMNAS_ESENCIALES if c not in historico.columns]
    filas.append(_fila(
        "columnas_esenciales", "ERROR", not faltan,
        len(COLUMNAS_ESENCIALES) - len(faltan), len(COLUMNAS_ESENCIALES),
        "faltan: " + ", ".join(faltan) if faltan else "todas presentes",
    ))
    if faltan:
        reporte = pd.DataFrame(filas)
        if verbose:
            _imprimir(reporte, None)
        if estricto:
            raise ValueError(f"Faltan columnas esenciales en el histórico: {faltan}")
        return reporte

    datos = historico[[c for c in COLUMNAS_ESENCIALES if c in historico.columns]].copy()
    datos[col_periodo] = pd.to_datetime(datos[col_periodo], errors="coerce")
    datos = datos.dropna(subset=[col_periodo])
    datos["mes"] = datos[col_periodo].dt.to_period("M").dt.to_timestamp()

    meses = np.sort(datos["mes"].unique())
    mes_actual = pd.Timestamp(meses[-1])
    previos = meses[-1 - meses_referencia:-1] if len(meses) > 1 else []
    actual = datos[datos["mes"].eq(mes_actual)]
    ref = datos[datos["mes"].isin(previos)] if len(previos) else datos.iloc[0:0]

    # --- periodo esperado ---
    if len(meses) > 1:
        esperado = pd.Timestamp(meses[-2]) + pd.DateOffset(months=1)
        filas.append(_fila(
            "periodo_esperado", "AVISO", mes_actual == esperado,
            f"{mes_actual:%Y-%m}", f"{esperado:%Y-%m}",
            "el último mes sigue al anterior" if mes_actual == esperado
            else "hay un salto de meses entre el archivo anterior y este",
        ))

    # --- clientes vs previos ---
    # Una CAÍDA de clientes es lo peligroso (archivo truncado): ERROR.
    # Un AUMENTO no daña nada y es normal en el archivo real: el mes más
    # reciente puede traer fila para todos los clientes (rurales incluidos,
    # aunque su lectura trimestral aún no haya llegado). Solo se avisa.
    n_actual = int(actual["NIU"].nunique())
    if len(ref):
        n_ref = float(ref.groupby("mes")["NIU"].nunique().median())
        cambio = (n_actual - n_ref) / n_ref * 100
        filas.append(_fila(
            "clientes_caida", "ERROR", cambio >= -caida_max_clientes_pct, n_actual, int(n_ref),
            f"{cambio:+.1f}% frente a la mediana de los {len(previos)} meses previos "
            f"(error si cae más de {caida_max_clientes_pct:.0f}%)",
        ))
        filas.append(_fila(
            "clientes_subida", "AVISO", cambio <= subida_max_clientes_pct, n_actual, int(n_ref),
            f"{cambio:+.1f}% frente a la mediana previa (aviso si sube más de "
            f"{subida_max_clientes_pct:.0f}%: suele ser que el archivo del mes trae a todos "
            "los clientes, rurales sin lectura incluidos)",
        ))
    else:
        filas.append(_fila("clientes_caida", "AVISO", True, n_actual, np.nan,
                           "sin meses previos para comparar"))

    # --- duplicados dentro del mes ---
    dup = int(actual.duplicated(subset=["NIU"]).sum())
    filas.append(_fila("duplicados", "ERROR", dup == 0, dup, 0,
                       "NIU repetidos dentro del mes" if dup else "sin repetidos"))

    # --- consumo total y nulos ---
    consumo = pd.to_numeric(actual["consumo_kwh_raw"], errors="coerce")
    pct_nulos = float(consumo.isna().mean() * 100)
    filas.append(_fila(
        "consumo_nulo", "ERROR", pct_nulos <= nulos_max_consumo_pct,
        round(pct_nulos, 2), nulos_max_consumo_pct,
        "% de filas del mes sin consumo",
    ))
    if len(ref):
        total_ref = float(
            ref.assign(c=pd.to_numeric(ref["consumo_kwh_raw"], errors="coerce"))
            .groupby("mes")["c"].sum().median()
        )
        total_actual = float(consumo.sum())
        pct = total_actual / total_ref * 100 if total_ref > 0 else np.nan
        filas.append(_fila(
            "consumo_total", "ERROR", pct >= consumo_min_pct,
            round(total_actual), round(total_ref),
            f"{pct:.1f}% de la mediana previa (mínimo {consumo_min_pct:.0f}%). "
            "Algo por debajo de 100% es normal: a los rurales les falta la lectura trimestral.",
        ))

    # --- tarifa ---
    tarifa = pd.to_numeric(actual["tarifa_aplicada_kwh"], errors="coerce")
    pct_tarifa_mala = float(((tarifa.isna()) | (tarifa <= 0)).mean() * 100)
    mediana_tarifa = float(tarifa[tarifa > 0].median()) if (tarifa > 0).any() else np.nan
    ok_tarifa = (
        pct_tarifa_mala <= tarifa_nula_max_pct
        and np.isfinite(mediana_tarifa)
        and tarifa_min <= mediana_tarifa <= tarifa_max
    )
    filas.append(_fila(
        "tarifa", "ERROR", ok_tarifa,
        round(mediana_tarifa, 2) if np.isfinite(mediana_tarifa) else np.nan,
        f"{tarifa_min:.0f}-{tarifa_max:.0f}",
        f"mediana $/kWh del mes; {pct_tarifa_mala:.2f}% nula o en cero "
        f"(máximo {tarifa_nula_max_pct:.0f}%)",
    ))

    # --- ciclos nuevos ---
    ciclos_mes = pd.to_numeric(actual["ciclo"], errors="coerce").dropna().astype(int).unique()
    nuevos = sorted(int(c) for c in ciclos_mes if int(c) not in set(int(x) for x in ciclos_conocidos))
    filas.append(_fila(
        "ciclos_nuevos", "ERROR", not nuevos, len(ciclos_mes), len(ciclos_conocidos),
        f"ciclos no clasificados: {nuevos} -> añadirlos a CICLOS_RURALES o dejarlos urbanos en "
        "Preprocesamiento, y a CICLOS_CONOCIDOS en utilidades_calidad.py"
        if nuevos else "todos los ciclos del mes son conocidos",
    ))

    # --- clases de servicio nuevas ---
    clases_mes = set(actual["clase_servicio"].astype("string").str.strip().str.upper().dropna())
    clases_ref = set(ref["clase_servicio"].astype("string").str.strip().str.upper().dropna()) if len(ref) else clases_mes
    clases_nuevas = sorted(clases_mes - clases_ref)
    filas.append(_fila(
        "clase_servicio_nueva", "AVISO", not clases_nuevas, len(clases_mes), len(clases_ref),
        f"clases nuevas: {clases_nuevas}" if clases_nuevas else "sin clases nuevas",
    ))

    # --- fechas de lectura ---
    sin_fecha = float(
        (pd.to_datetime(actual["fecha_lectura_actual"], errors="coerce", dayfirst=True).isna()
         | pd.to_datetime(actual["fecha_lectura_anterior"], errors="coerce", dayfirst=True).isna()).mean() * 100
    )
    filas.append(_fila(
        "fechas_lectura", "AVISO", sin_fecha <= fechas_faltantes_max_pct,
        round(sin_fecha, 2), fechas_faltantes_max_pct,
        "% de filas del mes sin alguna fecha de lectura (la reconstrucción rural usa el respaldo por días)",
    ))

    reporte = pd.DataFrame(filas)
    reporte.insert(0, "mes_evaluado", f"{mes_actual:%Y-%m}")

    if verbose:
        _imprimir(reporte, mes_actual)

    errores = reporte[(reporte["nivel"] == "ERROR") & (reporte["resultado"] != "OK")]
    if estricto and len(errores):
        raise ValueError(
            "El archivo del mes entrante no pasó el control de calidad:\n"
            + "\n".join(f"  • {r.chequeo}: {r.detalle}" for r in errores.itertuples())
            + "\nRevisa el archivo de la empresa antes de continuar. Si el valor es legítimo, "
            "ajusta el umbral correspondiente en validar_mes_entrante()."
        )
    return reporte


def _imprimir(reporte, mes_actual):
    print("CONTROL DE CALIDAD DEL MES ENTRANTE" + (f" — {mes_actual:%Y-%m}" if mes_actual is not None else ""))
    print("-" * 78)
    for r in reporte.itertuples():
        marca = "✓" if r.resultado == "OK" else ("✗" if r.nivel == "ERROR" else "⚠")
        print(f"  {marca} {r.chequeo:<22} {str(r.valor_mes):>14}  (ref {r.referencia})  {r.detalle}")
    n_err = int(((reporte["nivel"] == "ERROR") & (reporte["resultado"] != "OK")).sum())
    n_av = int(((reporte["nivel"] == "AVISO") & (reporte["resultado"] != "OK")).sum())
    print(f"\nErrores: {n_err} | Avisos: {n_av}")
