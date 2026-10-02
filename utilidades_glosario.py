"""
utilidades_glosario.py — nombres de negocio para códigos del formato TC2 (GLOSARIO_EBSA.xlsx)
============================================================================================

Un solo lugar para traducir códigos a texto, de modo que las listas, los exportes
y la página muestren lo mismo:

  • ciclo            -> zona_nombre            (0 CENTRO, 1 TUNDAMA, ..., 9 y 19 CENTRO SECCIONALES urbano/rural,
                                                 33 USUARIOS NO REGULADOS, 50 AUTOGENERADORES, 97 OTROS COMERCIALIZADORES)
  • clase_servicio   -> clase_servicio_nombre  (RS RESIDENCIAL, CR COMERCIAL, ID INDUSTRIAL, IR NO REGULADO, 0 SIN CLASIFICAR, ...)
  • tipo_medidor     -> tipo_medidor_nombre    (1 Electromecánico, 2 Electrónico, 6 Usuario sin medidor)
  • tipo_lectura     -> tipo_lectura_nombre    (1 REAL, 2 ESTIMADA, 3 NO TIENE MEDIDOR)
  • tipo_factura     -> tipo_factura_nombre    (1 Facturación real del mes, 6 Refacturación)
  • perfil P0..P4    -> grupo_consumo          (Intermitente, Pequeño, Mediano, Grande, Sin historia suficiente)
  • valor facturado  -> valor_facturado_mes    (columna Q del TC2 si existe; si no, consumo × tarifa real)

Si un código no está en el glosario, el texto queda como "CICLO 9 (sin nombre en glosario)"
o "CLASE XX (sin nombre en glosario)": nunca se inventa un nombre.

Uso:
    from utilidades_glosario import enriquecer_glosario, atributos_ultimo_mes, GRUPOS_CONSUMO_ORDEN
    df = enriquecer_glosario(df)                     # agrega las columnas de texto que pueda
    atrib = atributos_ultimo_mes(DATOS / "01_historico_procesado")   # última fila por NIU (ligero)
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

# ------------------------------------------------------------------------------
# Tablas del glosario (GLOSARIO_EBSA.xlsx, hojas "COLUMNA BR" y "COLUMNA BT")
# ------------------------------------------------------------------------------

ZONA_POR_CICLO = {
    0: "CENTRO", 1: "TUNDAMA", 2: "SUGAMUXI", 3: "OCCIDENTE", 4: "ORIENTE",
    5: "NORTE", 6: "RICAURTE", 7: "PUERTO BOYACA",
    9: "CENTRO (SECCIONALES - URBANO)",          # confirmado por la empresa 2026-09-09
    10: "CENTRO RURAL", 11: "TUNDAMA RURAL", 12: "SUGAMUXI RURAL", 13: "ORIENTE RURAL",
    15: "ALUMBRADO PUBLICO",
    19: "CENTRO (SECCIONALES - RURAL)",          # confirmado por la empresa 2026-09-09
    21: "NORTE RURAL", 22: "OCCIDENTE RURAL", 23: "RICAURTE RURAL",
    33: "USUARIOS NO REGULADOS", 38: "PUERTO BOYACA RURAL",
    50: "AUTOGENERADORES",                        # confirmado por la empresa 2026-09-09
    90: "SERVICIOS EBSA", 91: "ARRENDAMIENTO INMUEBLES", 94: "OTROS SERVICIOS",
    96: "ARRENDAMIENTO INFRAESTRUCTURA", 97: "OTROS COMERCIALIZADORES",
    98: "AREAS DE DISTRIBUCION", 99: "CARGOS PARA EL USO DEL STR",
}

CLASE_SERVICIO_NOMBRE = {
    "AA": "ACUEDUCTOS", "AC": "AREA COMUN", "AP": "ALUMBRADO PUBLICO", "AU": "AUTOCONSUMOS-EBSA",
    "CR": "COMERCIAL", "ID": "INDUSTRIAL", "IR": "NO REGULADO", "OF": "OFICIAL",
    "PR": "PROVISIONAL", "RI": "DISTRITO DE RIEGO", "RS": "RESIDENCIAL",
    "0": "SIN CLASIFICAR",                        # confirmado por la empresa 2026-09-09
}

TIPO_MEDIDOR_NOMBRE = {1: "Electromecánico", 2: "Electrónico", 6: "Usuario sin medidor"}
TIPO_LECTURA_NOMBRE = {1: "REAL", 2: "ESTIMADA", 3: "NO TIENE MEDIDOR"}
TIPO_FACTURA_NOMBRE = {1: "Facturación real del mes", 6: "Refacturación"}

# Ciclos que no son clientes atendibles comercialmente (servicios internos, alumbrado, etc.)
CICLOS_INTERNOS = {15, 90, 91, 94, 96, 98, 99}
CICLO_OTROS_COMERCIALIZADORES = 97
CICLO_NO_REGULADOS = 33
# Autogeneradores (ciclo 50): generan su propia energía, así que consumen menos de la red
# por diseño. Una "caída" o una "fuga" en ellos no es gestionable. Decisión de la empresa
# (2026-09-09): se retiran del universo de modelado igual que el alumbrado público
# (notebook 3 los excluye de la serie; el 14 los excluye de la población de fuga).
CICLO_AUTOGENERADORES = 50
CICLOS_SIN_GESTION = {CICLO_AUTOGENERADORES}

# ------------------------------------------------------------------------------
# Grupos de consumo para negocio (mismos umbrales del perfil P0..P4 del pronóstico:
# mediana de 12 meses; Pequeño < 500 kWh/mes, Mediano 500 a < 5.000, Grande >= 5.000)
# ------------------------------------------------------------------------------

GRUPO_CONSUMO_NOMBRE = {
    "P0_INTERMITENTE": "Intermitente",
    "P1_REGULAR": "Pequeño",
    "P2_ALTO": "Mediano",
    "P3_GRANDE": "Grande",
    "P4_INSUFICIENTE": "Sin historia suficiente",
}
GRUPOS_CONSUMO_ORDEN = ["Grande", "Mediano", "Pequeño", "Intermitente", "Sin historia suficiente"]
GRUPO_CONSUMO_DESCRIPCION = {
    "Intermitente": "Mediana de 12 meses ≤ 10 kWh o la mitad o más de los meses en cero",
    "Pequeño": "Mediana de 12 meses entre 10 y 500 kWh/mes",
    "Mediano": "Mediana de 12 meses entre 500 y 5.000 kWh/mes",
    "Grande": "Mediana de 12 meses de 5.000 kWh/mes o más",
    "Sin historia suficiente": "Menos de 6 meses válidos en el último año (no se pronostica)",
}
UMBRAL_PEQUENO_KWH = 500.0
UMBRAL_GRANDE_KWH = 5_000.0
UMBRAL_INTERMITENTE_KWH = 10.0
PCT_CEROS_INTERMITENTE = 0.50


def nombre_archivo_grupo(grupo: str) -> str:
    """'Sin historia suficiente' -> 'sin_historia_suficiente' (para nombres de archivo)."""
    return (str(grupo).lower()
            .replace("ñ", "n").replace("á", "a").replace("é", "e").replace("í", "i").replace("ó", "o").replace("ú", "u")
            .replace(" ", "_"))


def grupo_desde_perfil(perfil: pd.Series) -> pd.Series:
    return perfil.astype("string").map(GRUPO_CONSUMO_NOMBRE).fillna(perfil.astype("string"))


def grupo_desde_mediana(mediana_12m: pd.Series, pct_ceros_12m: pd.Series | None = None,
                        meses_validos_12m: pd.Series | None = None, min_meses: int = 6) -> pd.Series:
    """Mismo criterio del perfil P0..P4 pero a partir de las medidas, para tablas que no traen 'perfil'."""
    m = pd.to_numeric(mediana_12m, errors="coerce")
    out = pd.Series("Sin historia suficiente", index=m.index, dtype="object")
    ok = m.notna()
    if meses_validos_12m is not None:
        ok &= pd.to_numeric(meses_validos_12m, errors="coerce").fillna(0) >= min_meses
    ceros = pd.to_numeric(pct_ceros_12m, errors="coerce").fillna(0) if pct_ceros_12m is not None else pd.Series(0.0, index=m.index)
    out[ok & ((m <= UMBRAL_INTERMITENTE_KWH) | (ceros >= PCT_CEROS_INTERMITENTE))] = "Intermitente"
    out[ok & (m > UMBRAL_INTERMITENTE_KWH) & (m < UMBRAL_PEQUENO_KWH) & (ceros < PCT_CEROS_INTERMITENTE)] = "Pequeño"
    out[ok & (m >= UMBRAL_PEQUENO_KWH) & (m < UMBRAL_GRANDE_KWH) & (ceros < PCT_CEROS_INTERMITENTE)] = "Mediano"
    out[ok & (m >= UMBRAL_GRANDE_KWH) & (ceros < PCT_CEROS_INTERMITENTE)] = "Grande"
    return out


# ------------------------------------------------------------------------------
# Traducciones
# ------------------------------------------------------------------------------

def _a_entero(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce").round().astype("Int64")


def nombre_zona(ciclo: pd.Series) -> pd.Series:
    c = _a_entero(ciclo)
    nombres = c.map(ZONA_POR_CICLO)
    sin = c.notna() & nombres.isna()
    nombres = nombres.astype("object")
    nombres[sin] = "CICLO " + c[sin].astype(str) + " (sin nombre en glosario)"
    return nombres


def nombre_clase(clase: pd.Series) -> pd.Series:
    c = clase.astype("string").str.strip().str.upper()
    c = c.str.replace(r"^0+(\.0+)?$", "0", regex=True)      # 0, 00, 0.0 -> "0" (SIN CLASIFICAR)
    nombres = c.map(CLASE_SERVICIO_NOMBRE)
    sin = c.notna() & (c != "") & nombres.isna()
    nombres = nombres.astype("object")
    nombres[sin] = "CLASE " + c[sin].astype(str) + " (sin nombre en glosario)"
    return nombres


def _nombre_codigo(s: pd.Series, tabla: dict) -> pd.Series:
    c = _a_entero(s)
    nombres = c.map(tabla)
    sin = c.notna() & nombres.isna()
    nombres = nombres.astype("object")
    nombres[sin] = "CÓDIGO " + c[sin].astype(str) + " (sin nombre en glosario)"
    return nombres


def enriquecer_glosario(df: pd.DataFrame, consumo_col: str | None = None) -> pd.DataFrame:
    """
    Agrega, cuando existan las columnas fuente, las columnas de texto del glosario.
    No modifica columnas existentes; devuelve una copia.

    consumo_col: columna de consumo mensual (kWh) para calcular valor_facturado_mes
                 cuando el TC2 no trae 'valor_facturado_consumo'. Si no se indica,
                 se prueba con las habituales.
    """
    d = df.copy()
    if "ciclo" in d.columns and "zona_nombre" not in d.columns:
        d["zona_nombre"] = nombre_zona(d["ciclo"])
    if "clase_servicio" in d.columns and "clase_servicio_nombre" not in d.columns:
        d["clase_servicio_nombre"] = nombre_clase(d["clase_servicio"])
    if "tipo_medidor" in d.columns and "tipo_medidor_nombre" not in d.columns:
        d["tipo_medidor_nombre"] = _nombre_codigo(d["tipo_medidor"], TIPO_MEDIDOR_NOMBRE)
    if "tipo_lectura" in d.columns and "tipo_lectura_nombre" not in d.columns:
        d["tipo_lectura_nombre"] = _nombre_codigo(d["tipo_lectura"], TIPO_LECTURA_NOMBRE)
    if "tipo_factura" in d.columns and "tipo_factura_nombre" not in d.columns:
        d["tipo_factura_nombre"] = _nombre_codigo(d["tipo_factura"], TIPO_FACTURA_NOMBRE)
    if "perfil" in d.columns and "grupo_consumo" not in d.columns:
        d["grupo_consumo"] = grupo_desde_perfil(d["perfil"])

    # Valor facturado del mes, FILA POR FILA: el dato real del TC2 (columna Q) cuando la fila
    # lo trae; si no (histórico anterior a esa columna), consumo × tarifa real del cliente.
    # valor_facturado_origen dice cuál de los dos es. Nunca una tarifa imputada.
    if "valor_facturado_mes" not in d.columns:
        tc2 = (pd.to_numeric(d["valor_facturado_consumo"], errors="coerce")
               if "valor_facturado_consumo" in d.columns else pd.Series(np.nan, index=d.index))
        tarifa_col = next((c for c in ["tarifa_aplicada_kwh", "tarifa_kwh"] if c in d.columns), None)
        if consumo_col is None:
            consumo_col = next((c for c in ["consumo_kwh_raw", "consumo_kwh_mensual", "consumo_reciente_kwh",
                                            "consumo_actual_kwh", "consumo_prom_6m_kwh"] if c in d.columns), None)
        if tarifa_col and consumo_col:
            calculado = (pd.to_numeric(d[consumo_col], errors="coerce") * pd.to_numeric(d[tarifa_col], errors="coerce")).round(0)
        else:
            calculado = pd.Series(np.nan, index=d.index)
        if tc2.notna().any() or calculado.notna().any():
            d["valor_facturado_mes"] = tc2.where(tc2.notna(), calculado)
            d["valor_facturado_origen"] = np.select(
                [tc2.notna(), calculado.notna()],
                ["TC2 (columna Q)", f"{consumo_col} × tarifa real" if consumo_col else ""], default="")
    return d


# ------------------------------------------------------------------------------
# Atributos del último mes por NIU, leyendo solo lo necesario del histórico
# ------------------------------------------------------------------------------

COLUMNAS_ATRIBUTOS = [
    "NIU", "periodo", "ciclo", "clase_servicio", "estrato", "tipo_medidor", "tipo_lectura", "tipo_factura",
    "tarifa_aplicada_kwh", "consumo_promedio_semestral_kwh", "consumo_kwh_raw", "valor_facturado_consumo",
    "dias_facturados_max",
]


def atributos_ultimo_mes(historico_dir: Path | str, meses_atras: int = 3, nius=None, hasta=None) -> pd.DataFrame:
    """
    Última fila disponible de cada NIU en los últimos `meses_atras` meses del histórico
    (01_historico_procesado/historico_YYYY.parquet), con las columnas de atributos y sus
    nombres del glosario. Se leen solo los archivos de los años necesarios.
    hasta: último mes a considerar (p. ej. la fecha de corte consolidada); por defecto el último del histórico.
    """
    historico_dir = Path(historico_dir)
    archivos = sorted(historico_dir.glob("historico_*.parquet"))
    if not archivos:
        return pd.DataFrame(columns=COLUMNAS_ATRIBUTOS)
    # último periodo global: leer solo la columna periodo del archivo más reciente
    ultimo = pd.to_datetime(pd.read_parquet(archivos[-1], columns=["periodo"], engine="pyarrow")["periodo"]).max()
    if hasta is not None:
        ultimo = min(ultimo, pd.Timestamp(hasta))
    desde = (ultimo.to_period("M") - (meses_atras - 1)).to_timestamp()
    partes = []
    for ruta in archivos:
        anio = int(ruta.stem.split("_")[-1]) if ruta.stem.split("_")[-1].isdigit() else None
        if anio is not None and anio < desde.year:
            continue
        esquema = pq.ParquetFile(ruta).schema_arrow.names  # columnas sin cargar el archivo
        cols = [c for c in COLUMNAS_ATRIBUTOS if c in esquema]
        parte = pd.read_parquet(ruta, columns=cols, engine="pyarrow",
                                filters=[("periodo", ">=", desde), ("periodo", "<=", ultimo)])
        if nius is not None:
            parte = parte[parte["NIU"].astype("string").str.strip().isin(pd.Index(nius).astype("string"))]
        partes.append(parte)
    if not partes:
        return pd.DataFrame(columns=COLUMNAS_ATRIBUTOS)
    h = pd.concat(partes, ignore_index=True)
    h["NIU"] = h["NIU"].astype("string").str.strip()
    h["periodo"] = pd.to_datetime(h["periodo"])
    h = h.sort_values(["NIU", "periodo"]).groupby("NIU", as_index=False).last()
    h = h.rename(columns={"periodo": "periodo_atributos", "consumo_kwh_raw": "consumo_ultimo_mes_kwh",
                          "tarifa_aplicada_kwh": "tarifa_kwh_glosario"})
    h = enriquecer_glosario(h.rename(columns={"tarifa_kwh_glosario": "tarifa_aplicada_kwh"}),
                            consumo_col="consumo_ultimo_mes_kwh")
    return h


COLUMNAS_GLOSARIO_SALIDA = [
    "zona_nombre", "clase_servicio_nombre", "grupo_consumo", "tipo_medidor_nombre", "tipo_lectura_nombre",
    "tipo_factura_nombre", "consumo_promedio_semestral_kwh", "valor_facturado_mes", "valor_facturado_origen",
]


def agregar_atributos_a_lista(lista: pd.DataFrame, atributos: pd.DataFrame, perfiles: pd.DataFrame | None = None) -> pd.DataFrame:
    """
    Une a una lista (con columna NIU) las columnas del glosario tomadas de `atributos`
    (salida de atributos_ultimo_mes) y, si se pasa, el grupo de consumo desde `perfiles`
    (NIU, perfil). Las columnas que la lista ya tiene no se pisan.
    """
    d = lista.copy()
    d["NIU"] = d["NIU"].astype("string").str.strip()
    if perfiles is not None and "perfil" in perfiles.columns and "grupo_consumo" not in d.columns:
        p = perfiles[["NIU", "perfil"]].copy()
        p["NIU"] = p["NIU"].astype("string").str.strip()
        p["grupo_consumo"] = grupo_desde_perfil(p["perfil"])
        d = d.merge(p[["NIU", "grupo_consumo"]].drop_duplicates("NIU"), on="NIU", how="left")
    if "grupo_consumo" not in d.columns and "perfil" in d.columns:
        d["grupo_consumo"] = grupo_desde_perfil(d["perfil"])
    if "grupo_consumo" not in d.columns:
        d["grupo_consumo"] = pd.NA
    d["grupo_consumo"] = d["grupo_consumo"].fillna("Sin historia suficiente")
    if atributos is not None and len(atributos):
        a = atributos.copy()
        a["NIU"] = a["NIU"].astype("string").str.strip()
        a = a.rename(columns={"periodo_atributos": "mes_valor_facturado"})
        if "mes_valor_facturado" in a.columns:
            a["mes_valor_facturado"] = pd.to_datetime(a["mes_valor_facturado"]).dt.strftime("%Y-%m")
        nuevas = [c for c in COLUMNAS_GLOSARIO_SALIDA + ["mes_valor_facturado", "tipo_medidor", "tipo_lectura", "tipo_factura",
                                                         "ciclo", "clase_servicio", "estrato"]
                  if c in a.columns and c not in d.columns]
        d = d.merge(a[["NIU"] + nuevas].drop_duplicates("NIU"), on="NIU", how="left")
    d = enriquecer_glosario(d)
    return d
