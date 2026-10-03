"""
proyeccion_anual_consumo.py — consumo mensual por zona regional y proyección a varios años
==========================================================================================

Para la compra de energía: toma la serie mensual consolidada de todos los clientes, la
agrega por zona regional (y el total del departamento), ajusta modelos clásicos de series
de tiempo a cada zona (línea base estacional, 6 variantes de Holt-Winters y SARIMA con
búsqueda de hiperparámetros por AIC), mide con un backtest de orígenes móviles cuánto se
equivoca cada candidato a 1 y 2 años, verifica sesgo, cobertura de las bandas y residuos
(Ljung-Box), se queda con el mejor por zona y proyecta 36 meses con bandas de confianza. La página muestra
el consumo mes a mes, la proyección y una tabla por año con la marca de cuáles años son
confiables según el error medido.

Es un paso APARTE del pipeline mensual (como cruzar_ubicacion_tc1.py): no toca ningún
notebook ni salida existente. Se corre después de la corrida mensual, cuando se quiera
actualizar la proyección:

    python proyeccion_anual_consumo.py                 # 36 meses, umbral de confianza 5 %
    python proyeccion_anual_consumo.py --meses 48 --umbral 12

Entradas (carpeta EBSA_DATOS):
    03_serie_modelado/serie_mensual_modelado_preprocesada.parquet  (NIU, periodo, consumo_kwh_mensual, ciclo, estado_mes)
    03_serie_modelado/cortes_por_zona.csv                          (corte urbano / rural)
    04_pronostico/modelo_final/predicciones_segmentadas_optimizadas_6_meses.parquet  (opcional: comparación)

Salidas (carpeta nueva 14_proyeccion_anual/):
    serie_mensual_por_zona.csv        consumo real mes a mes por zona regional y TOTAL (GWh, clientes)
    proyeccion_mensual_por_zona.csv   real + proyección mensual con bandas 80 % y 95 %
    proyeccion_anual_por_zona.csv     suma por año calendario: real, proyectado, bandas, confiabilidad
    error_backtest_por_zona.csv       WAPE del backtest por zona y por año de horizonte, modelo elegido
    comparacion_pronostico_individual.csv  (si hay pred6) suma de los pronósticos individuales vs. el modelo agregado
"""
from __future__ import annotations

import argparse
import os
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
warnings.filterwarnings("ignore")
os.environ.setdefault("PYTHONWARNINGS", "ignore")

from utilidades_glosario import ZONA_REGIONAL_POR_CICLO, ZONAS_REGIONALES, CICLOS_INTERNOS

BASE = Path(os.environ.get("EBSA_DATOS", r"C:\Users\Home\Documents\Datos_Ebsa"))
RUTA_SERIE = BASE / "03_serie_modelado" / "serie_mensual_modelado_preprocesada.parquet"
RUTA_CORTES = BASE / "03_serie_modelado" / "cortes_por_zona.csv"
RUTA_PRED6 = BASE / "04_pronostico" / "modelo_final" / "predicciones_segmentadas_optimizadas_6_meses.parquet"
DIR_SALIDA = BASE / "14_proyeccion_anual"

MIN_MESES_AJUSTE = 24        # con menos de dos ciclos anuales no se ajusta estacionalidad
TOTAL = "TOTAL BOYACÁ"


# ----------------------------------------------------------------------------
# 1. Serie mensual por zona regional
# ----------------------------------------------------------------------------
def construir_series() -> tuple[pd.DataFrame, pd.Timestamp]:
    import pyarrow.parquet as pq
    cols = pq.ParquetFile(RUTA_SERIE).schema_arrow.names
    usar = [c for c in ["NIU", "periodo", "consumo_kwh_mensual", "ciclo", "es_rural", "estado_mes"] if c in cols]
    s = pd.read_parquet(RUTA_SERIE, columns=usar, engine="pyarrow")
    s["periodo"] = pd.to_datetime(s["periodo"]).dt.to_period("M").dt.to_timestamp()

    # Solo meses consolidados: los provisionales (rurales a la espera de lectura) distorsionan el agregado
    if "estado_mes" in s.columns:
        s = s[s["estado_mes"].astype(str).eq("CONSOLIDADO")]
    elif RUTA_CORTES.exists():
        cortes = pd.read_csv(RUTA_CORTES)
        corte = {str(z): pd.Timestamp(f) for z, f in zip(cortes["zona"], cortes["fecha_corte"])}
        es_rural = s["es_rural"].fillna(False).astype(bool) if "es_rural" in s.columns else pd.Series(False, index=s.index)
        lim = np.where(es_rural, corte.get("RURAL", s["periodo"].max()), corte.get("URBANO", s["periodo"].max()))
        s = s[s["periodo"].to_numpy() <= np.array(lim, dtype="datetime64[ns]")]

    # Fin de la serie: último mes en que TODAS las zonas están consolidadas (el corte rural)
    fin = s["periodo"].max()
    if "es_rural" in s.columns and s["es_rural"].fillna(False).astype(bool).any():
        fin = min(fin, s.loc[s["es_rural"].fillna(False).astype(bool), "periodo"].max())
    s = s[s["periodo"] <= fin]

    ciclo = pd.to_numeric(s["ciclo"], errors="coerce")
    s = s[~ciclo.isin(list(CICLOS_INTERNOS))]
    # Ciclos sin dirección regional (p. ej. 33 USUARIOS NO REGULADOS) quedan con su nombre de glosario, no como "OTROS"
    from utilidades_glosario import nombre_zona_regional
    s["zona_regional"] = nombre_zona_regional(s["ciclo"]).fillna("SIN ZONA")

    g = s.groupby(["zona_regional", "periodo"]).agg(consumo_kwh=("consumo_kwh_mensual", "sum"), clientes=("NIU", "nunique")).reset_index()
    tot = s.groupby("periodo").agg(consumo_kwh=("consumo_kwh_mensual", "sum"), clientes=("NIU", "nunique")).reset_index()
    tot["zona_regional"] = TOTAL
    g = pd.concat([tot, g], ignore_index=True)
    g["consumo_gwh"] = g["consumo_kwh"] / 1e6
    return g.sort_values(["zona_regional", "periodo"]).reset_index(drop=True), fin


# ----------------------------------------------------------------------------
# 2. Modelos clásicos: candidatos, hiperparámetros, backtest y diagnóstico
# ----------------------------------------------------------------------------
# Cada zona pasa por TODOS los candidatos y se queda con el de menor error a 1 año
# en el backtest de orígenes móviles. Los candidatos son:
#   · Línea base estacional (mismo mes del año anterior): la referencia que cualquier modelo debe superar.
#   · Holt-Winters / ETS: 6 variantes (tendencia aditiva, amortiguada o sin tendencia × estacionalidad
#     aditiva o multiplicativa). Sus parámetros de suavizado (alpha, beta, gamma, phi) se estiman por
#     máxima verosimilitud en cada ajuste.
#   · SARIMA: búsqueda de hiperparámetros (p,d,q)(P,1,Q)12 con p,q ∈ {0,1,2}, d ∈ {0,1}, P,Q ∈ {0,1}
#     (72 órdenes). Se preseleccionan los 3 de menor AIC sobre la serie completa y esos 3 van al backtest.
# Verificación de cada candidato: WAPE año 1 y año 2, sesgo (error medio con signo), cobertura real de la
# banda del 80 % en el backtest (debe acercarse a 80 %), y prueba de Ljung-Box sobre los residuos del
# modelo elegido (p > 0,05 = los residuos no tienen estructura que el modelo haya dejado por fuera).

ETS_VARIANTES = {
    "ETS(A,A,A)": dict(trend="add", damped_trend=False, seasonal="add"),
    "ETS(A,Ad,A)": dict(trend="add", damped_trend=True, seasonal="add"),
    "ETS(A,N,A)": dict(trend=None, damped_trend=False, seasonal="add"),
    "ETS(A,A,M)": dict(trend="add", damped_trend=False, seasonal="mul"),
    "ETS(A,Ad,M)": dict(trend="add", damped_trend=True, seasonal="mul"),
    "ETS(A,N,M)": dict(trend=None, damped_trend=False, seasonal="mul"),
}
SARIMA_GRID = [((p, d, q), (P, 1, Q, 12)) for p in (0, 1, 2) for d in (0, 1) for q in (0, 1, 2) for P in (0, 1) for Q in (0, 1)]
SARIMA_PRESELECCION = 3        # cuántos órdenes (por AIC) pasan al backtest
PASO_ORIGENES = 1              # 1 = todos los orígenes del backtest; 2 = uno de cada dos (más rápido)


def nombre_sarima(orden) -> str:
    (p, d, q), (P, D, Q, m) = orden
    return f"SARIMA({p},{d},{q})({P},{D},{Q}){m}"


def ajustar(y: pd.Series, modelo: str, orden=None):
    """Ajusta un candidato y devuelve el objeto de resultados de statsmodels (o None para la línea base)."""
    from statsmodels.tsa.holtwinters import ExponentialSmoothing
    from statsmodels.tsa.statespace.sarimax import SARIMAX
    warnings.simplefilter("ignore")
    if modelo == "BASE estacional":
        return None
    if modelo.startswith("ETS"):
        kw = dict(ETS_VARIANTES[modelo])
        if kw["seasonal"] == "mul" and not (y > 0).all():
            raise ValueError("estacionalidad multiplicativa requiere valores positivos")
        return ExponentialSmoothing(y, seasonal_periods=12, initialization_method="estimated", **kw).fit(optimized=True)
    return SARIMAX(y, order=orden[0], seasonal_order=orden[1], enforce_stationarity=False, enforce_invertibility=False).fit(disp=False)


def proyectar(y: pd.Series, modelo: str, pasos: int, orden=None, reps: int = 300):
    """(media, inf80, sup80, inf95, sup95) para `pasos` meses adelante."""
    y = y.astype(float)
    if modelo == "BASE estacional":
        ult = y.iloc[-12:].to_numpy()
        media = np.array([ult[k % 12] for k in range(pasos)])
        return media, media, media, media, media
    m = ajustar(y, modelo, orden)
    if modelo.startswith("ETS"):
        media = m.forecast(pasos).to_numpy()
        sims = m.simulate(pasos, repetitions=reps, error="add", random_state=42)
        return (media, sims.quantile(0.10, axis=1).to_numpy(), sims.quantile(0.90, axis=1).to_numpy(),
                sims.quantile(0.025, axis=1).to_numpy(), sims.quantile(0.975, axis=1).to_numpy())
    f = m.get_forecast(pasos)
    ci80, ci95 = f.conf_int(alpha=0.20), f.conf_int(alpha=0.05)
    return (f.predicted_mean.to_numpy(), ci80.iloc[:, 0].to_numpy(), ci80.iloc[:, 1].to_numpy(),
            ci95.iloc[:, 0].to_numpy(), ci95.iloc[:, 1].to_numpy())


def backtest(y: pd.Series, modelo: str, orden=None, h_max: int = 24) -> dict:
    """Orígenes móviles desde el mes 24: WAPE y sesgo por banda de horizonte (año 1 = h 1–12, año 2 = h 13–24)
    y cobertura de la banda del 80 % en el año 1."""
    n = len(y)
    ae = {1: [], 2: []}; ar = {1: [], 2: []}; err = {1: [], 2: []}
    dentro80 = []; total80 = 0; ratio_banda = []
    for origen in range(MIN_MESES_AJUSTE, n - 1, PASO_ORIGENES):
        pasos = min(h_max, n - origen)
        try:
            media, i80, s80, *_ = proyectar(y.iloc[:origen], modelo, pasos, orden, reps=100)
        except Exception:
            continue
        real = y.iloc[origen:origen + pasos].to_numpy()
        for h in range(pasos):
            banda = 1 if h < 12 else 2
            ae[banda].append(abs(real[h] - media[h])); ar[banda].append(abs(real[h])); err[banda].append(media[h] - real[h])
            if banda == 1 and modelo != "BASE estacional":
                dentro80.append(i80[h] <= real[h] <= s80[h]); total80 += 1
                semi = (s80[h] - i80[h]) / 2
                if semi > 0:
                    ratio_banda.append(abs(real[h] - media[h]) / semi)
    out = {}
    for banda in (1, 2):
        out[f"wape_anio{banda}_pct"] = (sum(ae[banda]) / sum(ar[banda]) * 100) if sum(ar[banda]) > 0 else np.nan
        out[f"sesgo_anio{banda}_pct"] = (np.mean(err[banda]) / np.mean(ar[banda]) * 100) if ar[banda] else np.nan
        out[f"puntos_anio{banda}"] = len(ae[banda])
    out["cobertura_banda80_pct"] = (np.mean(dentro80) * 100) if total80 else np.nan
    # Factor para que la banda del 80 % cubra de verdad el 80 % de los errores vistos en el backtest
    # (1 = la banda ya es honesta; > 1 = había que ensancharla)
    out["factor_calibracion_banda"] = float(max(1.0, np.quantile(ratio_banda, 0.80))) if len(ratio_banda) >= 10 else 1.0
    return out


def preseleccionar_sarima(y: pd.Series) -> list:
    """Los SARIMA_PRESELECCION órdenes de menor AIC sobre la serie completa."""
    res = []
    for orden in SARIMA_GRID:
        try:
            m = ajustar(y, "SARIMA", orden)
            if np.isfinite(m.aic):
                res.append((m.aic, orden))
        except Exception:
            continue
    res.sort(key=lambda t: t[0])
    return res[:SARIMA_PRESELECCION]


def ljung_box_p(y: pd.Series, modelo: str, orden=None) -> float:
    """p-valor de Ljung-Box (12 rezagos) sobre los residuos del ajuste final; NaN para la línea base."""
    from statsmodels.stats.diagnostic import acorr_ljungbox
    if modelo == "BASE estacional":
        return np.nan
    try:
        m = ajustar(y, modelo, orden)
        res = pd.Series(np.asarray(m.resid)).dropna()
        res = res.iloc[12:] if len(res) > 24 else res      # los primeros residuos de SARIMA son de arranque
        return float(acorr_ljungbox(res, lags=[12], return_df=True)["lb_pvalue"].iloc[0])
    except Exception:
        return np.nan


def proyectar_zona(y: pd.Series, meses: int, umbral: float) -> tuple[pd.DataFrame, dict]:
    """Todos los candidatos por el backtest; gana el de menor WAPE a 1 año; proyecta `meses` adelante."""
    candidatos = [("BASE estacional", None)] + [(k, None) for k in ETS_VARIANTES] + \
                 [(nombre_sarima(o), o) for _, o in preseleccionar_sarima(y)]
    aic_por_orden = {nombre_sarima(o): a for a, o in preseleccionar_sarima(y)}
    filas = []
    for nombre, orden in candidatos:
        if nombre.startswith("ETS") and ETS_VARIANTES[nombre]["seasonal"] == "mul" and not (y > 0).all():
            continue
        bt = backtest(y, nombre, orden)
        bt["modelo"] = nombre
        bt["aic"] = aic_por_orden.get(nombre, np.nan)
        bt["_orden"] = orden
        filas.append(bt)
    tabla = pd.DataFrame(filas).sort_values("wape_anio1_pct", na_position="last").reset_index(drop=True)
    # El ganador no puede ser la línea base: si ningún modelo la supera, se avisa y se usa el mejor modelo igual
    modelos = tabla[tabla["modelo"] != "BASE estacional"]
    mejor = modelos.iloc[0]
    base = tabla[tabla["modelo"] == "BASE estacional"].iloc[0]
    supera_base = bool(mejor["wape_anio1_pct"] < base["wape_anio1_pct"]) if np.isfinite(base["wape_anio1_pct"]) else True
    def _proyeccion_calibrada(fila):
        media, i80, s80, i95, s95 = proyectar(y, fila["modelo"], meses, fila["_orden"], reps=500)
        # Calibración: se ensanchan las bandas con el factor medido en el backtest (solo si cubrían menos del 80 %)
        f = float(fila.get("factor_calibracion_banda", 1.0) or 1.0)
        if f > 1.0:
            i80, s80 = media - f * (media - i80), media + f * (s80 - media)
            i95, s95 = media - f * (media - i95), media + f * (s95 - media)
        fechas = pd.date_range(y.index[-1] + pd.offsets.MonthBegin(1), periods=meses, freq="MS")
        return f, pd.DataFrame({"periodo": fechas, "proyeccion_gwh": np.clip(media, 0, None),
                                "inf80_gwh": np.clip(i80, 0, None), "sup80_gwh": np.clip(s80, 0, None),
                                "inf95_gwh": np.clip(i95, 0, None), "sup95_gwh": np.clip(s95, 0, None)})

    f, proy = _proyeccion_calibrada(mejor)
    proy["escenario"] = "BASE"
    # Escenario alternativo: si el ganador no tiene tendencia, el mejor candidato CON tendencia (qué pasa si el
    # crecimiento de los primeros años continúa); si el ganador tiene tendencia, el mejor SIN tendencia (qué pasa
    # si el consumo se estanca). Así comercial siempre ve las dos hipótesis con su error medido.
    tiene_tend = modelos["modelo"].str.contains(r"ETS\(A,A", regex=True) | modelos["modelo"].str.contains(r"SARIMA\(\d,1,", regex=True)
    ganador_con_tend = bool(tiene_tend.loc[modelos.index[0]])
    alternativos = modelos[~tiene_tend] if ganador_con_tend else modelos[tiene_tend]
    info_tend = None
    if len(alternativos):
        alt = alternativos.iloc[0]
        try:
            _, proy_t = _proyeccion_calibrada(alt)
            proy_t["escenario"] = "ALTERNATIVO"
            proy = pd.concat([proy, proy_t], ignore_index=True)
            info_tend = {"modelo": alt["modelo"], "tipo": "sin tendencia" if ganador_con_tend else "con tendencia",
                         "wape_anio1_pct": float(alt["wape_anio1_pct"]), "wape_anio2_pct": float(alt["wape_anio2_pct"])}
        except Exception:
            info_tend = None
    info = {"modelo": mejor["modelo"], "wape_anio1_pct": float(mejor["wape_anio1_pct"]), "wape_anio2_pct": float(mejor["wape_anio2_pct"]),
            "sesgo_anio1_pct": float(mejor["sesgo_anio1_pct"]), "cobertura_banda80_pct": float(mejor["cobertura_banda80_pct"]),
            "puntos_anio1": int(mejor["puntos_anio1"]), "puntos_anio2": int(mejor["puntos_anio2"]),
            "factor_calibracion_banda": f, "tendencia": info_tend,
            "wape_base_anio1_pct": float(base["wape_anio1_pct"]), "supera_base": supera_base,
            "ljung_box_p": ljung_box_p(y, mejor["modelo"], mejor["_orden"]), "umbral_pct": umbral,
            "comparacion_modelos": tabla.drop(columns=["_orden"])}
    return proy, info


def confiabilidad(anio_horizonte: int, info: dict) -> str:
    """Etiqueta por año de horizonte según el error medido en el backtest."""
    u = info["umbral_pct"]
    if anio_horizonte <= 0:
        return "REAL"
    if anio_horizonte == 1:
        e = info["wape_anio1_pct"]
        return "CONFIABLE" if np.isfinite(e) and e <= u else "ORIENTATIVO"
    if anio_horizonte == 2:
        e = info["wape_anio2_pct"]
        if not np.isfinite(e) or info["puntos_anio2"] < 12:
            return "NO VERIFICABLE"
        return "CONFIABLE" if e <= u else "ORIENTATIVO"
    return "NO VERIFICABLE"


# ----------------------------------------------------------------------------
# 3. Programa principal
# ----------------------------------------------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--meses", type=int, default=36, help="meses a proyectar (36 = tres años)")
    ap.add_argument("--umbral", type=float, default=5.0, help="WAPE máximo (%%) para llamar CONFIABLE a un año (5 por defecto)")
    ap.add_argument("--rapido", action="store_true", help="backtest con uno de cada dos orígenes (la mitad de tiempo)")
    args = ap.parse_args()
    global PASO_ORIGENES
    if args.rapido:
        PASO_ORIGENES = 2

    print("PROYECCIÓN ANUAL DEL CONSUMO POR ZONA REGIONAL")
    print("=" * 78)
    series, fin = construir_series()
    zonas = [TOTAL] + [z for z in ZONAS_REGIONALES if z in set(series["zona_regional"])] + \
            sorted(set(series["zona_regional"]) - set(ZONAS_REGIONALES) - {TOTAL})
    n_meses = series.groupby("zona_regional")["periodo"].nunique().max()
    print(f"Serie consolidada: {series['periodo'].min():%Y-%m} → {fin:%Y-%m} ({n_meses} meses) · {len(zonas)} series")
    if n_meses < MIN_MESES_AJUSTE + 6:
        raise SystemExit(f"Hacen falta al menos {MIN_MESES_AJUSTE + 6} meses consolidados para proyectar; hay {n_meses}.")

    DIR_SALIDA.mkdir(parents=True, exist_ok=True)
    series.to_csv(DIR_SALIDA / "serie_mensual_por_zona.csv", index=False, encoding="utf-8-sig")

    mensual, anual, errores, comparaciones = [], [], [], []
    series_y = {}
    for z in zonas:
        y = series[series["zona_regional"] == z].set_index("periodo")["consumo_gwh"].asfreq("MS")
        y = y.interpolate(limit=2).fillna(0.0)
        if len(y) < MIN_MESES_AJUSTE + 6 or y.sum() <= 0:
            print(f"  {z:<16} sin datos suficientes, se omite")
            continue
        series_y[z] = y
    # Las zonas se procesan en paralelo (una por núcleo): cada una prueba todos los candidatos
    try:
        from joblib import Parallel, delayed
        resultados = Parallel(n_jobs=-1, prefer="processes")(delayed(proyectar_zona)(y, args.meses, args.umbral) for y in series_y.values())
    except Exception:
        resultados = [proyectar_zona(y, args.meses, args.umbral) for y in series_y.values()]
    for z, (proy, info) in zip(series_y, resultados):
        y = series_y[z]
        aviso = "" if info["supera_base"] else "  ⚠ no supera la línea base estacional"
        lb = info["ljung_box_p"]
        print(f"  {z:<16} {info['modelo']:<22} WAPE año 1 {info['wape_anio1_pct']:5.1f} % (base {info['wape_base_anio1_pct']:5.1f} %) · "
              f"año 2 {info['wape_anio2_pct']:5.1f} % · sesgo {info['sesgo_anio1_pct']:+5.1f} % · banda 80 % cubre {info['cobertura_banda80_pct']:4.0f} %"
              f"{' (ensanchada ×' + format(info['factor_calibracion_banda'], '.2f') + ')' if info['factor_calibracion_banda'] > 1.0 else ''} · "
              f"Ljung-Box p={lb:.2f}{' ✓' if np.isfinite(lb) and lb > 0.05 else ' ⚠'}{aviso}")
        real = pd.DataFrame({"periodo": y.index, "real_gwh": y.to_numpy(), "escenario": "BASE"})
        proy_base = proy[proy["escenario"] == "BASE"]
        proy_tend = proy[proy["escenario"] == "ALTERNATIVO"]
        m = pd.concat([real.assign(tipo="REAL"), proy_base.assign(tipo="PROYECCION")], ignore_index=True)
        m.insert(0, "zona_regional", z)
        m["modelo"] = info["modelo"]
        if len(proy_tend):
            mt = pd.concat([real.assign(tipo="REAL", escenario="ALTERNATIVO"), proy_tend.assign(tipo="PROYECCION")], ignore_index=True)
            mt.insert(0, "zona_regional", z)
            mt["modelo"] = info["tendencia"]["modelo"]
            mensual.append(mt)
            if info["tendencia"]:
                print(f"  {'':<16} ↳ alternativo {z} ({info['tendencia']['tipo']}): {info['tendencia']['modelo']} "
                      f"(WAPE año 1 {info['tendencia']['wape_anio1_pct']:.1f} %, año 2 {info['tendencia']['wape_anio2_pct']:.1f} %)")
        mensual.append(m)

        # Año calendario: real + proyección; año de horizonte = años después del último mes real
        m["anio"] = m["periodo"].dt.year
        anio_fin = fin.year
        for esc, mm_ in [("BASE", m)] + ([("ALTERNATIVO", mt.assign(anio=mt["periodo"].dt.year))] if len(proy_tend) else []):
          for anio, g in mm_.groupby("anio"):
              n_real = int(g["tipo"].eq("REAL").sum()); n_proy = int(g["tipo"].eq("PROYECCION").sum())
              if n_real + n_proy < 12 and anio != m["anio"].min():
                  continue  # año incompleto al final del horizonte
              # año de horizonte: 1 = el año en curso (resto del año) y el siguiente se cuenta como 2, etc.
              hor = (anio - anio_fin + 1) if n_proy else 0
              anual.append({
                  "zona_regional": z, "escenario": esc, "anio": anio, "meses_reales": n_real, "meses_proyectados": n_proy,
                  "real_gwh": g["real_gwh"].sum(), "proyeccion_gwh": g["proyeccion_gwh"].sum(),
                  "total_gwh": g["real_gwh"].fillna(0).sum() + g["proyeccion_gwh"].fillna(0).sum(),
                  "inf80_gwh": g["real_gwh"].fillna(0).sum() + g["inf80_gwh"].fillna(0).sum(),
                  "sup80_gwh": g["real_gwh"].fillna(0).sum() + g["sup80_gwh"].fillna(0).sum(),
                  "inf95_gwh": g["real_gwh"].fillna(0).sum() + g["inf95_gwh"].fillna(0).sum(),
                  "sup95_gwh": g["real_gwh"].fillna(0).sum() + g["sup95_gwh"].fillna(0).sum(),
                  "anio_horizonte": hor, "confiabilidad": confiabilidad(hor, info) if n_proy else "REAL",
                  "error_backtest_pct": ((info["wape_anio1_pct"] if esc == "BASE" else info["tendencia"]["wape_anio1_pct"]) if hor == 1
                                         else ((info["wape_anio2_pct"] if esc == "BASE" else info["tendencia"]["wape_anio2_pct"]) if hor == 2 else np.nan)),
                  "modelo": info["modelo"] if esc == "BASE" else info["tendencia"]["modelo"],
              })
        errores.append({"zona_regional": z, "modelo_elegido": info["modelo"], "wape_anio1_pct": info["wape_anio1_pct"],
                        "wape_anio2_pct": info["wape_anio2_pct"], "wape_base_anio1_pct": info["wape_base_anio1_pct"],
                        "supera_linea_base": info["supera_base"], "sesgo_anio1_pct": info["sesgo_anio1_pct"],
                        "cobertura_banda80_pct": info["cobertura_banda80_pct"], "factor_calibracion_banda": info["factor_calibracion_banda"],
                        "ljung_box_p": info["ljung_box_p"],
                        "modelo_alternativo": info["tendencia"]["modelo"] if info["tendencia"] else "",
                        "tipo_alternativo": info["tendencia"]["tipo"] if info["tendencia"] else "",
                        "wape_alternativo_anio1_pct": info["tendencia"]["wape_anio1_pct"] if info["tendencia"] else np.nan,
                        "wape_alternativo_anio2_pct": info["tendencia"]["wape_anio2_pct"] if info["tendencia"] else np.nan,
                        "residuos_sin_estructura": (np.isfinite(info["ljung_box_p"]) and info["ljung_box_p"] > 0.05),
                        "puntos_anio1": info["puntos_anio1"], "puntos_anio2": info["puntos_anio2"],
                        "umbral_confiable_pct": args.umbral, "ultimo_mes_real": f"{fin:%Y-%m}", "meses_proyectados": args.meses})
        comparaciones.append(info["comparacion_modelos"].assign(zona_regional=z))

    mensual_df = pd.concat(mensual, ignore_index=True)
    anual_df = pd.DataFrame(anual)
    err_df = pd.DataFrame(errores)
    mensual_df.to_csv(DIR_SALIDA / "proyeccion_mensual_por_zona.csv", index=False, encoding="utf-8-sig")
    anual_df.to_csv(DIR_SALIDA / "proyeccion_anual_por_zona.csv", index=False, encoding="utf-8-sig")
    err_df.to_csv(DIR_SALIDA / "error_backtest_por_zona.csv", index=False, encoding="utf-8-sig")
    pd.concat(comparaciones, ignore_index=True).to_csv(DIR_SALIDA / "comparacion_modelos_por_zona.csv", index=False, encoding="utf-8-sig")

    # Comparación con la suma de los pronósticos individuales (6 meses), si existen
    if RUTA_PRED6.exists():
        try:
            p6 = pd.read_parquet(RUTA_PRED6, engine="pyarrow")
            filas = []
            tot_zona = {}
            for h in range(1, 7):
                if f"pred_{h}m_kwh" not in p6.columns or f"fecha_pred_{h}m" not in p6.columns:
                    continue
                fecha = pd.to_datetime(p6[f"fecha_pred_{h}m"]).dt.to_period("M").dt.to_timestamp().mode().iloc[0]
                filas.append({"periodo": fecha, "suma_individual_gwh": p6[f"pred_{h}m_kwh"].sum() / 1e6})
            ind = pd.DataFrame(filas)
            agg = mensual_df[(mensual_df["zona_regional"] == TOTAL) & (mensual_df["tipo"] == "PROYECCION") & (mensual_df["escenario"] == "BASE")][["periodo", "proyeccion_gwh"]]
            comp = ind.merge(agg, on="periodo", how="inner")
            comp["diferencia_pct"] = ((comp["suma_individual_gwh"] - comp["proyeccion_gwh"]) / comp["proyeccion_gwh"] * 100).round(1)
            comp.to_csv(DIR_SALIDA / "comparacion_pronostico_individual.csv", index=False, encoding="utf-8-sig")
            if len(comp):
                print(f"\nSuma de pronósticos individuales vs modelo agregado (TOTAL), {len(comp)} meses en común: "
                      f"diferencia media {comp['diferencia_pct'].mean():+.1f} %")
        except Exception as e:
            print("⚠ No se pudo comparar con el pronóstico individual:", e)

    print("\nPROYECCIÓN ANUAL — TOTAL BOYACÁ (GWh)  [CONFIABLE: error del backtest ≤ umbral; ORIENTATIVO: por encima; "
          "NO VERIFICABLE: horizonte que la historia no alcanza a probar]")
    for esc in ["BASE", "ALTERNATIVO"]:
        t = anual_df[(anual_df["zona_regional"] == TOTAL) & (anual_df["escenario"] == esc)][["anio", "meses_reales", "meses_proyectados", "total_gwh", "inf80_gwh", "sup80_gwh", "confiabilidad", "modelo"]]
        if len(t):
            print(f"\n  Escenario {esc}:")
            print(t.round(1).to_string(index=False))
    print("\nGuardado en", DIR_SALIDA)


if __name__ == "__main__":
    main()
