"""EJEMPLO ILUSTRATIVO de la retroalimentación de visitas — RESULTADOS SIMULADOS, no son visitas reales.

Para qué sirve: el proyecto es académico y no hubo visitas de campo, así que la página "Resultados de las
visitas contra la lista" sale vacía. Este script arma un ejemplo para mostrar cómo se vería esa página (y
cómo se mediría la lista) si la empresa registrara lo que encuentra en cada visita.

Qué hace:
  1. Toma una muestra al azar (semilla fija) de clientes de la lista de caída vigente con prioridad GESTIONAR.
  2. Le asigna a cada uno un hallazgo AL AZAR del mismo catálogo que usa Evaluacion_retroalimentacion_gestion.ipynb.
     Las probabilidades son SUPUESTAS e iguales para todos los grupos: las diferencias que se vean entre grupos
     son azar, y ninguna cifra del ejemplo mide la calidad de la lista.
  3. Calcula las mismas tablas que el notebook de evaluación.

Dónde escribe (carpeta aparte, con el nombre EJEMPLO_SIMULADO en cada archivo):
    07_gestion_caida/retroalimentacion/ejemplo_simulado/EJEMPLO_SIMULADO_resultado_gestion.csv
    07_gestion_caida/retroalimentacion/ejemplo_simulado/EJEMPLO_SIMULADO_evaluacion_resumen.csv
El notebook de evaluación NO lee esa subcarpeta: el ejemplo nunca se mezcla con visitas reales. La página
solo lo muestra, con un aviso, mientras no existan resultados reales.

Uso:  python generar_ejemplo_retroalimentacion.py
      python generar_ejemplo_retroalimentacion.py --clientes 500 --datos "D:\\otra\\Datos_Ebsa"
Para quitar el ejemplo: borrar la carpeta ejemplo_simulado.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

try:  # la consola de Windows (cp1252) no representa algunos símbolos
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

DATOS_POR_DEFECTO = Path(os.environ.get("EBSA_DATOS", r"C:\Users\Home\Documents\Datos_Ebsa"))
SEMILLA = 2026

# Mismo catálogo que Evaluacion_retroalimentacion_gestion.ipynb
CATALOGO_HALLAZGOS = {
    "MEDIDOR_DANADO": "CON_CAUSA_GESTIONABLE",
    "MEDIDOR_MANIPULADO_O_FRAUDE": "CON_CAUSA_GESTIONABLE",
    "ERROR_DE_LECTURA_O_FACTURACION": "CON_CAUSA_GESTIONABLE",
    "ACOMETIDA_O_RED_CON_FALLA": "CON_CAUSA_GESTIONABLE",
    "CONEXION_IRREGULAR": "CON_CAUSA_GESTIONABLE",
    "PREDIO_DESOCUPADO": "CAIDA_REAL_SIN_GESTION",
    "CAMBIO_DE_ACTIVIDAD_O_HABITO": "CAIDA_REAL_SIN_GESTION",
    "AUTOGENERACION": "CAIDA_REAL_SIN_GESTION",
    "CLIENTE_RETIRADO": "CAIDA_REAL_SIN_GESTION",
    "SIN_NOVEDAD": "SIN_NOVEDAD",
    "NO_UBICADO": "NO_VERIFICADO",
    "PENDIENTE": "NO_VERIFICADO",
}

# Probabilidades SUPUESTAS (no salen de ningún dato): solo dan forma al ejemplo. Suman 1.
PROBABILIDADES_SUPUESTAS = {
    "MEDIDOR_DANADO": 0.08, "MEDIDOR_MANIPULADO_O_FRAUDE": 0.04, "ERROR_DE_LECTURA_O_FACTURACION": 0.07,
    "ACOMETIDA_O_RED_CON_FALLA": 0.03, "CONEXION_IRREGULAR": 0.03,
    "PREDIO_DESOCUPADO": 0.17, "CAMBIO_DE_ACTIVIDAD_O_HABITO": 0.20, "AUTOGENERACION": 0.04, "CLIENTE_RETIRADO": 0.04,
    "SIN_NOVEDAD": 0.20, "NO_UBICADO": 0.07, "PENDIENTE": 0.03,
}


def resumen_por(df: pd.DataFrame, claves: list[str], etiqueta: str) -> pd.DataFrame:
    """Misma tabla que la celda 4 de Evaluacion_retroalimentacion_gestion.ipynb."""
    g = df.groupby(claves)
    out = pd.DataFrame({
        "visitados": g.size(),
        "verificados": g["verificado"].sum(),
        "con_causa_gestionable": g["acierto_gestionable"].sum(),
        "caida_real_sin_gestion": g["caida_real"].sum() - g["acierto_gestionable"].sum(),
        "sin_novedad": g["falso_positivo"].sum(),
        "valor_riesgo_gestionable_mes": g["valor_gestionable"].sum(),
    }).reset_index()
    out["precision_gestionable_pct"] = (out["con_causa_gestionable"] / out["verificados"] * 100).round(1)
    out["precision_caida_real_pct"] = ((out["con_causa_gestionable"] + out["caida_real_sin_gestion"]) / out["verificados"] * 100).round(1)
    out["corte_por"] = etiqueta
    out["valor_corte"] = out[claves[-1]].astype(str) if len(claves) > 1 else "TOTAL"
    return out[["corte_por", "valor_corte", "fecha_corte_lista", "visitados", "verificados", "con_causa_gestionable",
                "caida_real_sin_gestion", "sin_novedad", "precision_gestionable_pct", "precision_caida_real_pct",
                "valor_riesgo_gestionable_mes"]]


def main() -> int:
    ap = argparse.ArgumentParser(description="Ejemplo ilustrativo (simulado) de la retroalimentación de visitas")
    ap.add_argument("--datos", default=str(DATOS_POR_DEFECTO), help="Carpeta de datos (por defecto EBSA_DATOS o Documentos\\Datos_Ebsa)")
    ap.add_argument("--clientes", type=int, default=300, help="Cuántos clientes de la lista simular como visitados (por defecto 300)")
    args = ap.parse_args()
    assert abs(sum(PROBABILIDADES_SUPUESTAS.values()) - 1) < 1e-9 and set(PROBABILIDADES_SUPUESTAS) == set(CATALOGO_HALLAZGOS)

    gestion = Path(args.datos) / "07_gestion_caida"
    ruta_lista = gestion / "gestion_caida_operativa.csv"
    if not ruta_lista.exists():
        print(f"No existe {ruta_lista}. Corre primero el pipeline (paso 11).")
        return 1
    lista = pd.read_csv(ruta_lista, dtype={"NIU": "string", "ciclo_etiqueta": "string"}, low_memory=False)
    corte = str(lista["fecha_corte"].iloc[0])[:7]
    base = lista[lista["prioridad_gestion"].eq("GESTIONAR")] if "prioridad_gestion" in lista.columns else lista
    n = min(args.clientes, len(base))
    rng = np.random.default_rng(SEMILLA)
    muestra = base.sample(n=n, random_state=SEMILLA).copy()
    hallazgos = list(PROBABILIDADES_SUPUESTAS)
    muestra["hallazgo"] = rng.choice(hallazgos, size=n, p=[PROBABILIDADES_SUPUESTAS[h] for h in hallazgos])
    muestra["grupo_hallazgo"] = muestra["hallazgo"].map(CATALOGO_HALLAZGOS)
    muestra["fecha_corte_lista"] = corte
    inicio = pd.Period(corte, freq="M").to_timestamp() + pd.offsets.MonthBegin(2)
    muestra["fecha_visita"] = (inicio + pd.to_timedelta(rng.integers(0, 28, size=n), unit="D")).strftime("%Y-%m-%d")

    destino = gestion / "retroalimentacion" / "ejemplo_simulado"
    destino.mkdir(parents=True, exist_ok=True)
    visitas = muestra[["NIU", "fecha_corte_lista", "fecha_visita", "hallazgo"]].copy()
    visitas["accion"] = "EJEMPLO SIMULADO"
    visitas["observaciones"] = "EJEMPLO SIMULADO: no es una visita real"
    ruta_visitas = destino / "EJEMPLO_SIMULADO_resultado_gestion.csv"
    visitas.to_csv(ruta_visitas, index=False, encoding="utf-8-sig")

    muestra["verificado"] = muestra["grupo_hallazgo"].ne("NO_VERIFICADO")
    muestra["acierto_gestionable"] = muestra["grupo_hallazgo"].eq("CON_CAUSA_GESTIONABLE")
    muestra["caida_real"] = muestra["grupo_hallazgo"].isin(["CON_CAUSA_GESTIONABLE", "CAIDA_REAL_SIN_GESTION"])
    muestra["falso_positivo"] = muestra["grupo_hallazgo"].eq("SIN_NOVEDAD")
    muestra["valor_gestionable"] = np.where(muestra["acierto_gestionable"], muestra["valor_riesgo_mes"].fillna(0), 0.0)
    tablas = [resumen_por(muestra, ["fecha_corte_lista"], "TOTAL")]
    for col in ["severidad", "trayectoria", "estado_en_lista", "tramo_consumo", "zona", "cluster_id", "clase_servicio", "ciclo_etiqueta"]:
        if col in muestra.columns and muestra[col].notna().any():
            tablas.append(resumen_por(muestra, ["fecha_corte_lista", col], col))
    resumen = pd.concat(tablas, ignore_index=True)
    resumen.insert(0, "AVISO", "EJEMPLO SIMULADO - no son visitas reales")
    ruta_resumen = destino / "EJEMPLO_SIMULADO_evaluacion_resumen.csv"
    resumen.to_csv(ruta_resumen, index=False, encoding="utf-8-sig")

    print("EJEMPLO ILUSTRATIVO DE RETROALIMENTACIÓN — RESULTADOS SIMULADOS (no son visitas reales)")
    print("=" * 90)
    print(f"Lista del corte {corte}: {n:,} clientes con prioridad GESTIONAR elegidos al azar (semilla {SEMILLA}).")
    print("Hallazgos asignados al azar con probabilidades supuestas, iguales para todos los grupos.")
    print(resumen[resumen["corte_por"].eq("TOTAL")].drop(columns=["AVISO", "corte_por"]).to_string(index=False))
    print("\nGuardado:")
    print(" *", ruta_visitas)
    print(" *", ruta_resumen)
    print("La página lo muestra en 'Resultados de las visitas' con un aviso, mientras no haya visitas reales.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
