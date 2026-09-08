"""
Detección del borde provisional de la serie de consumo — EBSA
==============================================================

Por qué existe este módulo
--------------------------
Los clientes rurales se leen cada tres meses. En cualquier extracción, al
último mes solo le cayó la lectura de una parte de ellos: a los demás su
última lectura fue uno o dos meses antes y cubría hasta ahí, así que el mes
más reciente les queda descubierto hasta que llegue su próxima lectura.

El resultado es que el último mes NO está mal, está **provisional**: se va a
completar hacia arriba cuando lleguen las lecturas de los meses siguientes.
En la extracción de 2026-01 ese mes aparecía con el 47.9% del consumo normal
en rurales, mientras 2025-11 y 2025-12 estaban en 102.6% y 105.9%.

Esto se repite en TODAS las extracciones, no es un defecto de una entrega
puntual. Por eso la regla no puede ser un número escrito a mano: tiene que
salir de los datos en cada corrida.

La regla
--------
Leer hasta el último mes consolidado. Un mes se considera provisional cuando cae por debajo del umbral en DOS
pruebas a la vez, en cualquiera de los grupos evaluados (rural / urbano):

  1. contra la mediana de los meses previos, y
  2. contra el MISMO mes del año anterior.

La segunda prueba es la que descarta la estacionalidad: un mes que baja
porque siempre baja en esa época pasa la comparación año contra año, y no se
marca. Solo un mes que está bajo en ambas es un borde incompleto.

Se cuenta hacia atrás desde el final y se detiene en el primer mes sano: si
el último mes está provisional pero el anterior no, el retroceso es 1.

Uso
---
    from utilidades_borde import ultimo_periodo_consolidado

    periodo_corte, n_provisionales, detalle = ultimo_periodo_consolidado(
        serie, col_grupo="es_rural",
    )

Colocar este archivo junto a los notebooks para que el import funcione.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

__all__ = [
    "detectar_meses_provisionales",
    "periodos_provisionales",
    "ultimo_periodo_consolidado",
    "UMBRAL_MES_PROVISIONAL_PCT",
    "MAX_RETROCESO_PERMITIDO",
]

# Un mes por debajo de este % de la mediana de referencia se considera
# provisional. 85% es holgado a propósito: la estacionalidad normal no llega
# ahí, y el caso real que motivó esto estaba en 47.9%.
UMBRAL_MES_PROVISIONAL_PCT = 85.0

# Tope de seguridad. Si el detector quiere retroceder más que esto, algo más
# grave pasa con los datos y es mejor fallar ruidosamente que descartar media
# serie en silencio.
MAX_RETROCESO_PERMITIDO = 3

MESES_REFERENCIA = 12


def _resumen_mensual(serie, col_periodo, col_consumo, col_grupo):
    """Consumo medio por mes (y por grupo, si se pide)."""
    datos = serie[[c for c in (col_periodo, col_consumo, col_grupo) if c]].copy()
    datos[col_periodo] = pd.to_datetime(datos[col_periodo], errors="coerce")

    if col_grupo:
        datos[col_grupo] = datos[col_grupo].fillna(False).astype(bool)
        agrupado = datos.groupby([col_grupo, col_periodo])[col_consumo].mean()
        return agrupado.reset_index().rename(columns={col_grupo: "grupo"})

    agrupado = datos.groupby(col_periodo)[col_consumo].mean()
    salida = agrupado.reset_index()
    salida["grupo"] = "TODOS"
    return salida


def detectar_meses_provisionales(
    serie: pd.DataFrame,
    col_periodo: str = "periodo",
    col_consumo: str = "consumo_kwh_mensual",
    col_grupo: str | None = "es_rural",
    umbral_pct: float = UMBRAL_MES_PROVISIONAL_PCT,
    meses_referencia: int = MESES_REFERENCIA,
    max_retroceso: int = MAX_RETROCESO_PERMITIDO,
    verbose: bool = True,
):
    """Cuántos meses del final de la serie están provisionales.

    Devuelve (n_provisionales, detalle) donde `detalle` es un DataFrame con
    el nivel de cada mes evaluado respecto de su referencia, por grupo.
    """

    if col_grupo and col_grupo not in serie.columns:
        if verbose:
            print(
                f"  (sin columna '{col_grupo}': se evalúa la serie completa "
                "sin separar por zona)"
            )
        col_grupo = None

    resumen = _resumen_mensual(serie, col_periodo, col_consumo, col_grupo)
    meses = np.sort(resumen[col_periodo].unique())

    if len(meses) < meses_referencia + max_retroceso + 1:
        if verbose:
            print("  Serie demasiado corta para evaluar el borde. Retroceso = 0.")
        return 0, pd.DataFrame()

    filas = []

    for k in range(max_retroceso + 1):
        mes = meses[len(meses) - 1 - k]
        # Referencia: los `meses_referencia` anteriores a ESTE mes, que cubren
        # un ciclo estacional completo.
        ini = len(meses) - 1 - k - meses_referencia
        referencia_meses = meses[max(ini, 0): len(meses) - 1 - k]

        for grupo, g in resumen.groupby("grupo"):
            g = g.set_index(col_periodo)[col_consumo]
            if mes not in g.index:
                continue
            base = g.reindex(referencia_meses).median()
            if not np.isfinite(base) or base <= 0:
                continue

            valor = float(g.loc[mes])
            nivel = valor / float(base) * 100.0

            # Segunda prueba: mismo mes del año anterior, para que la
            # estacionalidad no se confunda con un borde incompleto.
            mes_anio_previo = pd.Timestamp(mes) - pd.DateOffset(months=12)
            nivel_anual = np.nan
            if mes_anio_previo in g.index:
                previo = float(g.loc[mes_anio_previo])
                if previo > 0:
                    nivel_anual = valor / previo * 100.0

            bajo_referencia = nivel < umbral_pct
            # Si no hay dato del año anterior, la prueba anual no puede
            # descartar nada y se apoya solo en la referencia.
            bajo_anual = (
                nivel_anual < umbral_pct if np.isfinite(nivel_anual) else True
            )

            filas.append({
                "posicion_desde_el_final": k,
                "periodo": pd.Timestamp(mes),
                "grupo": ("RURAL" if grupo is True else
                          "URBANO" if grupo is False else str(grupo)),
                "nivel_pct": round(nivel, 1),
                "nivel_vs_anio_pct": (round(nivel_anual, 1)
                                      if np.isfinite(nivel_anual) else np.nan),
                "provisional": bool(bajo_referencia and bajo_anual),
            })

    detalle = pd.DataFrame(filas)
    if detalle.empty:
        return 0, detalle

    # Un mes es provisional si lo es en CUALQUIER grupo: si los rurales están
    # incompletos, el mes no sirve para alimentar el modelo aunque los
    # urbanos estén bien.
    por_mes = (
        detalle.groupby(["posicion_desde_el_final", "periodo"])["provisional"]
        .any()
        .reset_index()
        .sort_values("posicion_desde_el_final")
    )

    # Contar hacia atrás, deteniéndose en el primer mes sano
    n_provisionales = 0
    for _, fila in por_mes.iterrows():
        if fila["provisional"]:
            n_provisionales += 1
        else:
            break

    # Marcar en el detalle qué meses quedaron realmente excluidos: solo los
    # del borde. Un mes bajo que NO está en el borde es un mes real y se queda.
    detalle["excluido_del_borde"] = (
        detalle["posicion_desde_el_final"] < n_provisionales
    )

    if verbose:
        print("DETECCIÓN DEL BORDE PROVISIONAL")
        print("-" * 70)
        print(f"Un mes es provisional si queda bajo el {umbral_pct:.0f}% en AMBAS "
              "pruebas (vs. mediana de los")
        print(f"{meses_referencia} meses previos y vs. el mismo mes del año "
              "anterior). Solo se excluye el borde:")
        print("meses provisionales CONSECUTIVOS al final. Un mes bajo que no está "
              "en el borde es un\nmes real y se conserva.\n")
        for _, f in detalle.sort_values(
            ["posicion_desde_el_final", "grupo"]
        ).iterrows():
            if f["excluido_del_borde"] and f["provisional"]:
                marca = "  <-- PROVISIONAL, excluido"
            elif f["provisional"]:
                marca = "  (bajo, pero es un mes real: se conserva)"
            else:
                marca = ""
            anual = (f"{f['nivel_vs_anio_pct']:6.1f}%"
                     if pd.notna(f["nivel_vs_anio_pct"]) else "     --")
            print(f"  {f['periodo']:%Y-%m}  {f['grupo']:<7} "
                  f"vs referencia {f['nivel_pct']:6.1f}%   "
                  f"vs año previo {anual}{marca}")
        print(f"\nMeses provisionales excluidos del borde: {n_provisionales}")

    if n_provisionales > max_retroceso:
        raise ValueError(
            f"El detector encontró {n_provisionales} meses provisionales, más "
            f"que el máximo permitido ({max_retroceso}). Revisa la extracción "
            "antes de continuar: no es un borde incompleto normal."
        )

    return n_provisionales, detalle


def periodos_provisionales(
    serie: pd.DataFrame,
    col_periodo: str = "periodo",
    col_consumo: str = "consumo_kwh_mensual",
    col_grupo: str | None = "es_rural",
    **kwargs,
):
    """Lista de periodos (Timestamp) que están provisionales en el borde.

    Sirve para excluir de cualquier métrica los targets que caen en esos
    meses: evaluar un pronóstico contra un mes incompleto castiga al modelo
    por un dato que todavía no existe.
    """
    n, _ = detectar_meses_provisionales(
        serie, col_periodo=col_periodo, col_consumo=col_consumo,
        col_grupo=col_grupo, verbose=False, **kwargs,
    )
    periodos = pd.to_datetime(serie[col_periodo], errors="coerce")
    periodo_max = periodos.max().to_period("M").to_timestamp()
    return [periodo_max - pd.DateOffset(months=k) for k in range(n)]


def ultimo_periodo_consolidado(
    serie: pd.DataFrame,
    col_periodo: str = "periodo",
    col_consumo: str = "consumo_kwh_mensual",
    col_grupo: str | None = "es_rural",
    verbose: bool = True,
    **kwargs,
):
    """El último mes que se puede usar para entrenar o predecir.

    Devuelve (periodo_corte, n_provisionales, detalle).
    """
    periodos = pd.to_datetime(serie[col_periodo], errors="coerce")
    periodo_max = periodos.max().to_period("M").to_timestamp()

    n, detalle = detectar_meses_provisionales(
        serie, col_periodo=col_periodo, col_consumo=col_consumo,
        col_grupo=col_grupo, verbose=verbose, **kwargs,
    )

    periodo_corte = periodo_max - pd.DateOffset(months=n)

    if verbose:
        print(f"\nÚltimo periodo de la serie   : {periodo_max:%Y-%m}")
        print(f"Último periodo CONSOLIDADO   : {periodo_corte:%Y-%m}")
        if n == 0:
            print("El borde llegó completo: no se retrocede.")
        else:
            print(f"Se retroceden {n} mes(es).")

    return periodo_corte, n, detalle
