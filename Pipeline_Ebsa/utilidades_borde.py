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
Leer hasta el último mes consolidado. Para cada grupo (rural / urbano) se
miran dos cosas del mes:

  NIVEL     : el consumo promedio de los clientes que tienen fila ese mes
              (detecta lecturas parciales: filas con valores bajos), y
  COBERTURA : cuántos clientes tienen fila ese mes
              (detecta clientes enteros que faltan, p. ej. un archivo que llegó
              sin rurales: los pocos con fila tienen promedio normal).

Cada una se considera baja solo si cae por debajo de su umbral en DOS
comparaciones a la vez:

  1. contra la mediana de los meses previos, y
  2. contra el MISMO mes del año anterior.

La segunda comparación es la que descarta la estacionalidad: un mes que baja
porque siempre baja en esa época pasa la comparación año contra año, y no se
marca. Un mes es provisional si falla el nivel o la cobertura.

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
    "cortes_por_zona",
    "leer_cortes_por_zona",
    "MAX_RETROCESO_RURAL",
    "UMBRAL_MES_PROVISIONAL_PCT",
    "UMBRAL_COBERTURA_PCT",
    "MAX_RETROCESO_PERMITIDO",
]

# Un mes por debajo de este % de la mediana de referencia se considera
# provisional. 85% es holgado a propósito: la estacionalidad normal no llega
# ahí, y el caso real que motivó esto estaba en 47.9%.
UMBRAL_MES_PROVISIONAL_PCT = 85.0

# Segunda prueba, de COBERTURA: un mes en el que tienen fila menos de este % de
# los clientes habituales del grupo está incompleto aunque el promedio de los
# que sí tienen fila sea normal. Caso real: febrero de 2026 llegó sin rurales y
# solo 89 de ~219.000 rurales tenían fila; su promedio era normal y la prueba de
# nivel lo dio por consolidado. Se deja en 60% porque los rurales, leídos por
# cohortes cada tres meses, pueden estar en ~2/3 en el penúltimo mes sin que el
# mes esté "vacío"; el nivel se encarga de ese caso cuando aplica.
UMBRAL_COBERTURA_PCT = 60.0

# Tope de seguridad. Si el detector quiere retroceder más que esto, algo más
# grave pasa con los datos y es mejor fallar ruidosamente que descartar media
# serie en silencio.
MAX_RETROCESO_PERMITIDO = 3

# Para el corte POR ZONA: los rurales se leen cada tres meses y, si un archivo
# mensual llega sin lecturas rurales, pueden acumular hasta tres meses
# provisionales seguidos de forma normal. Se les permite uno más de margen.
MAX_RETROCESO_RURAL = 4

MESES_REFERENCIA = 12


def _resumen_mensual(serie, col_periodo, col_consumo, col_grupo):
    """Consumo medio y número de clientes con fila, por mes (y por grupo, si se pide).

    Las dos medidas hacen falta: el promedio detecta un mes con lecturas
    parciales (filas con valores bajos); el conteo detecta un mes al que le
    faltan clientes enteros (p. ej. un archivo que llegó sin rurales: los pocos
    rurales que sí traen fila tienen un promedio normal y engañarían al detector).
    """
    datos = serie[[c for c in (col_periodo, col_consumo, col_grupo) if c]].copy()
    datos[col_periodo] = pd.to_datetime(datos[col_periodo], errors="coerce")

    if col_grupo:
        datos[col_grupo] = datos[col_grupo].fillna(False).astype(bool)
        agrupado = datos.groupby([col_grupo, col_periodo])[col_consumo].agg(["mean", "size"])
        agrupado.columns = [col_consumo, "clientes"]
        return agrupado.reset_index().rename(columns={col_grupo: "grupo"})

    agrupado = datos.groupby(col_periodo)[col_consumo].agg(["mean", "size"])
    agrupado.columns = [col_consumo, "clientes"]
    salida = agrupado.reset_index()
    salida["grupo"] = "TODOS"
    return salida


def _linea_detalle(f) -> str:
    """Una línea legible del detalle: nivel y cobertura de un mes de un grupo."""
    def pct(v):
        return f"{v:6.1f}%" if pd.notna(v) else "     --"
    causa = ""
    if f.get("provisional_por_nivel", False) and f.get("provisional_por_cobertura", False):
        causa = " [nivel y cobertura]"
    elif f.get("provisional_por_nivel", False):
        causa = " [nivel]"
    elif f.get("provisional_por_cobertura", False):
        causa = " [cobertura]"
    return (f"{f['periodo']:%Y-%m}  {f['grupo']:<7} consumo prom. vs ref {pct(f['nivel_pct'])} "
            f"vs año {pct(f['nivel_vs_anio_pct'])} | clientes {int(f['clientes']):>9,} "
            f"cobertura {pct(f.get('cobertura_pct', np.nan))}{causa}")


def detectar_meses_provisionales(
    serie: pd.DataFrame,
    col_periodo: str = "periodo",
    col_consumo: str = "consumo_kwh_mensual",
    col_grupo: str | None = "es_rural",
    umbral_pct: float = UMBRAL_MES_PROVISIONAL_PCT,
    meses_referencia: int = MESES_REFERENCIA,
    max_retroceso: int = MAX_RETROCESO_PERMITIDO,
    verbose: bool = True,
    umbral_cobertura_pct: float = UMBRAL_COBERTURA_PCT,
):
    """Cuántos meses del final de la serie están provisionales.

    Un mes es provisional para un grupo si falla la prueba de NIVEL (consumo
    promedio bajo frente a la mediana previa Y frente al mismo mes del año
    anterior) o la prueba de COBERTURA (clientes con fila por debajo de
    `umbral_cobertura_pct` en las mismas dos comparaciones).

    Devuelve (n_provisionales, detalle) donde `detalle` es un DataFrame con
    el nivel y la cobertura de cada mes evaluado respecto de su referencia,
    por grupo.
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
            g = g.set_index(col_periodo)[[col_consumo, "clientes"]]
            if mes not in g.index:
                # El grupo no tiene ninguna fila ese mes (p. ej. un archivo que
                # llegó solo con urbanos): para ese grupo el mes está vacío,
                # que es el caso extremo de provisional.
                g = g.copy()
                g.loc[pd.Timestamp(mes)] = [0.0, 0]

            # ---- Prueba A: nivel de consumo promedio (lecturas parciales)
            base = g[col_consumo].reindex(referencia_meses).median()
            if not np.isfinite(base) or base <= 0:
                continue
            valor = float(g.loc[mes, col_consumo])
            nivel = valor / float(base) * 100.0

            # Segunda comparación: mismo mes del año anterior, para que la
            # estacionalidad no se confunda con un borde incompleto.
            mes_anio_previo = pd.Timestamp(mes) - pd.DateOffset(months=12)
            nivel_anual = np.nan
            if mes_anio_previo in g.index:
                previo = float(g.loc[mes_anio_previo, col_consumo])
                if previo > 0:
                    nivel_anual = valor / previo * 100.0

            bajo_referencia = nivel < umbral_pct
            # Si no hay dato del año anterior, la prueba anual no puede
            # descartar nada y se apoya solo en la referencia.
            bajo_anual = (
                nivel_anual < umbral_pct if np.isfinite(nivel_anual) else True
            )
            provisional_nivel = bool(bajo_referencia and bajo_anual)

            # ---- Prueba B: cobertura de clientes (clientes enteros que faltan)
            base_cl = g["clientes"].reindex(referencia_meses).median()
            cobertura = cobertura_anual = np.nan
            provisional_cobertura = False
            if np.isfinite(base_cl) and base_cl > 0:
                n_cl = float(g.loc[mes, "clientes"])
                cobertura = n_cl / float(base_cl) * 100.0
                if mes_anio_previo in g.index and float(g.loc[mes_anio_previo, "clientes"]) > 0:
                    cobertura_anual = n_cl / float(g.loc[mes_anio_previo, "clientes"]) * 100.0
                provisional_cobertura = bool(
                    cobertura < umbral_cobertura_pct
                    and (cobertura_anual < umbral_cobertura_pct if np.isfinite(cobertura_anual) else True)
                )

            filas.append({
                "posicion_desde_el_final": k,
                "periodo": pd.Timestamp(mes),
                "grupo": ("RURAL" if grupo is True else
                          "URBANO" if grupo is False else str(grupo)),
                "nivel_pct": round(nivel, 1),
                "nivel_vs_anio_pct": (round(nivel_anual, 1)
                                      if np.isfinite(nivel_anual) else np.nan),
                "clientes": int(g.loc[mes, "clientes"]),
                "cobertura_pct": (round(cobertura, 1) if np.isfinite(cobertura) else np.nan),
                "cobertura_vs_anio_pct": (round(cobertura_anual, 1)
                                          if np.isfinite(cobertura_anual) else np.nan),
                "provisional_por_nivel": provisional_nivel,
                "provisional_por_cobertura": provisional_cobertura,
                "provisional": provisional_nivel or provisional_cobertura,
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
        print(f"Un mes es provisional si su consumo promedio queda bajo el {umbral_pct:.0f}% "
              f"o su cobertura de clientes bajo el {umbral_cobertura_pct:.0f}%,")
        print(f"en AMBAS comparaciones (vs. mediana de los {meses_referencia} meses previos "
              "y vs. el mismo mes del año anterior). Solo se excluye el borde:")
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
            print("  " + _linea_detalle(f) + marca)
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


def cortes_por_zona(
    serie: pd.DataFrame,
    col_periodo: str = "periodo",
    col_consumo: str = "consumo_kwh_mensual",
    col_grupo: str = "es_rural",
    verbose: bool = True,
    max_retroceso_urbano: int = MAX_RETROCESO_PERMITIDO,
    max_retroceso_rural: int = MAX_RETROCESO_RURAL,
    **kwargs,
):
    """Último mes consolidado de CADA zona, por separado.

    Los urbanos se leen todos los meses: su corte suele ser el último mes del
    archivo. Los rurales se leen por trimestres: su corte es el último mes que
    ya recibió todas sus lecturas. Con esto los urbanos avanzan cada mes sin
    esperar a los rurales.

    Devuelve (cortes, detalle) donde cortes es un dict
        {"URBANO": Timestamp, "RURAL": Timestamp, "TODOS": Timestamp (el menor)}
    y detalle es el DataFrame del detector con la columna 'excluido_del_borde'
    calculada por zona.
    """
    periodos = pd.to_datetime(serie[col_periodo], errors="coerce")
    periodo_max = periodos.max().to_period("M").to_timestamp()

    # Detectar con el tope más alto (rural) y sin lanzar error aquí; el tope se
    # aplica por zona más abajo.
    max_r = max(max_retroceso_urbano, max_retroceso_rural)
    _, detalle = detectar_meses_provisionales(
        serie, col_periodo=col_periodo, col_consumo=col_consumo, col_grupo=col_grupo,
        verbose=False, max_retroceso=max_r + 1, **kwargs,
    )

    cortes = {}
    n_por_zona = {}
    if detalle.empty:
        for zona in ("URBANO", "RURAL"):
            cortes[zona] = periodo_max
            n_por_zona[zona] = 0
    else:
        detalle = detalle.copy()
        detalle["excluido_del_borde"] = False
        for zona in ("URBANO", "RURAL"):
            d = detalle[detalle["grupo"].eq(zona)].sort_values("posicion_desde_el_final")
            n = 0
            for _, f in d.iterrows():
                if f["provisional"]:
                    n += 1
                else:
                    break
            tope = max_retroceso_rural if zona == "RURAL" else max_retroceso_urbano
            if n > tope:
                raise ValueError(
                    f"Zona {zona}: el detector encontró {n} meses provisionales, más que el "
                    f"máximo permitido ({tope}). Revisa la extracción antes de continuar."
                )
            n_por_zona[zona] = n
            cortes[zona] = periodo_max - pd.DateOffset(months=n)
            detalle.loc[detalle["grupo"].eq(zona) & (detalle["posicion_desde_el_final"] < n),
                        "excluido_del_borde"] = True
    cortes["TODOS"] = min(cortes["URBANO"], cortes["RURAL"])

    if verbose:
        print("DETECCIÓN DEL BORDE PROVISIONAL — POR ZONA")
        print("-" * 70)
        print(f"Un mes es provisional si su consumo promedio queda bajo el {UMBRAL_MES_PROVISIONAL_PCT:.0f}% "
              f"o su cobertura de clientes bajo el {UMBRAL_COBERTURA_PCT:.0f}%,")
        print("en AMBAS comparaciones (vs. mediana de 12 meses y vs. el mismo mes del año anterior).")
        print("Cada zona retrocede por su cuenta: los urbanos no esperan a los rurales.\n")
        if not detalle.empty:
            for _, f in detalle.sort_values(["posicion_desde_el_final", "grupo"]).iterrows():
                marca = "  <-- PROVISIONAL, excluido" if f["excluido_del_borde"] else ""
                print("  " + _linea_detalle(f) + marca)
        print(f"\nÚltimo periodo de la serie : {periodo_max:%Y-%m}")
        print(f"Corte URBANO               : {cortes['URBANO']:%Y-%m}  (retrocede {n_por_zona['URBANO']})")
        print(f"Corte RURAL                : {cortes['RURAL']:%Y-%m}  (retrocede {n_por_zona['RURAL']})")

    return cortes, detalle


def leer_cortes_por_zona(ruta_csv, serie=None, verbose=True, **kwargs):
    """Lee cortes_por_zona.csv (lo escribe el notebook 3). Si no existe y se pasa
    la serie, los calcula. Devuelve el dict {"URBANO", "RURAL", "TODOS"}."""
    import os
    if ruta_csv is not None and os.path.exists(ruta_csv):
        t = pd.read_csv(ruta_csv)
        cortes = {str(z): pd.Timestamp(f) for z, f in zip(t["zona"], t["fecha_corte"])}
        cortes["TODOS"] = min(cortes["URBANO"], cortes["RURAL"])
        if verbose:
            print(f"Cortes por zona (de {os.path.basename(str(ruta_csv))}): "
                  f"URBANO {cortes['URBANO']:%Y-%m} | RURAL {cortes['RURAL']:%Y-%m}")
        return cortes
    if serie is None:
        raise FileNotFoundError(f"No existe {ruta_csv} y no se pasó la serie para calcular los cortes.")
    cortes, _ = cortes_por_zona(serie, verbose=verbose, **kwargs)
    return cortes
