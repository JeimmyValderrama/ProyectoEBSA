r"""
Experimento de evidencia para el informe (sección 3.2.2): reproduce la "primera corrida" del
agrupamiento SIN las correcciones (sin winsorización, con StandardScaler y sin penalizar clusters
diminutos) y la compara con la versión robusta que quedó en el notebook 9, sobre los mismos datos.

    python experimento_agrupamiento_sin_robustez.py

Lee  05_segmentos_clientes\features_clientes_consumo.parquet (lo deja el notebook 9) y escribe
     05_segmentos_clientes\experimento_primera_corrida_sin_robustez.csv

No toca ningún archivo del pipeline. Tarda alrededor de un minuto.
"""
from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.cluster import MiniBatchKMeans
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import RobustScaler, StandardScaler

BASE = Path(os.environ.get("EBSA_DATOS", r"C:\Users\Home\Documents\Datos_Ebsa"))
RUTA = BASE / "05_segmentos_clientes" / "features_clientes_consumo.parquet"
SALIDA = BASE / "05_segmentos_clientes" / "experimento_primera_corrida_sin_robustez.csv"
SEED = 42
COLUMNAS = ["mediana_12m_kwh_log", "cv_interno", "pct_ceros_12m", "pendiente_pct_mensual_12m", "cv_vs_semestral"]
WINSOR = ["cv_interno", "pendiente_pct_mensual_12m", "cv_vs_semestral"]


def tamanos(etq):
    v, c = np.unique(etq, return_counts=True)
    return "; ".join(f"{int(a)}:{int(b):,} ({b / len(etq) * 100:.1f}%)" for a, b in zip(v, c)), int(c.min())


def correr(X_fit, X_val, k, variante):
    km = MiniBatchKMeans(n_clusters=k, random_state=SEED, n_init=5, batch_size=4096).fit(X_fit)
    etq = km.predict(X_val)
    sil = silhouette_score(X_val, etq) if len(np.unique(etq)) > 1 else np.nan
    txt, minimo = tamanos(etq)
    return {"variante": variante, "k": k, "silhouette_validacion": round(float(sil), 4), "tamanos_validacion": txt,
            "cluster_mas_pequeno": minimo, "degenerado (< 0,5 %)": minimo < 0.005 * len(etq)}


def main():
    if not RUTA.exists():
        raise SystemExit(f"No existe {RUTA}. Corre antes el notebook 9 (pipeline_mensual.py --solo 9).")
    f = pd.read_parquet(RUTA)
    f = f[f["historia_suficiente"]].copy()
    f["mediana_12m_kwh_log"] = np.log1p(f["mediana_12m_kwh"].clip(lower=0))
    f = f[f["pct_ceros_12m"] < 1.0]  # cero permanente va por regla, como en el notebook
    for col in COLUMNAS:
        f[col] = f[col].fillna(f.groupby("es_rural_final")[col].transform("median"))

    filas = []
    for zona, grupo in [("URBANO", f[~f["es_rural_final"]]), ("RURAL", f[f["es_rural_final"]])]:
        rng = np.random.default_rng(SEED)
        idx = rng.permutation(len(grupo))
        fit = grupo.iloc[idx[:60_000]]
        val = grupo.iloc[idx[60_000:72_000]]
        print(f"\n{zona}: {len(grupo):,} activos; ajuste {len(fit):,}, validación {len(val):,}")

        # --- Variante A: primera corrida (StandardScaler, sin winsorizar, sin penalización)
        sc = StandardScaler().fit(fit[COLUMNAS])
        Xf, Xv = sc.transform(fit[COLUMNAS]), sc.transform(val[COLUMNAS])
        for k in (3, 4, 5, 6):
            r = correr(Xf, Xv, k, "A. primera corrida: StandardScaler, sin winsorizar"); r["zona"] = zona; filas.append(r)
            print(f"  A k={k}: silhouette {r['silhouette_validacion']:.3f} | tamaños {r['tamanos_validacion']}")

        # --- Variante B: versión robusta del notebook (winsor p1-p99 + RobustScaler)
        lim = {c: (fit[c].quantile(0.01), fit[c].quantile(0.99)) for c in WINSOR}
        def prep(d):
            X = d[COLUMNAS].copy()
            for c, (lo, hi) in lim.items():
                X[c] = X[c].clip(lo, hi)
            return X
        rs = RobustScaler().fit(prep(fit))
        Xf, Xv = rs.transform(prep(fit)), rs.transform(prep(val))
        for k in (3, 4, 5, 6):
            r = correr(Xf, Xv, k, "B. versión final: winsor p1-p99 + RobustScaler"); r["zona"] = zona; filas.append(r)
            print(f"  B k={k}: silhouette {r['silhouette_validacion']:.3f} | tamaños {r['tamanos_validacion']}")

    out = pd.DataFrame(filas)[["zona", "variante", "k", "silhouette_validacion", "tamanos_validacion", "cluster_mas_pequeno", "degenerado (< 0,5 %)"]]
    out.to_csv(SALIDA, index=False, encoding="utf-8-sig")
    print("\nGuardado:", SALIDA)
    print("\nLectura: en la variante A el silhouette suele ser alto PERO con uno o dos clusters de un puñado de clientes extremos "
          "(columna 'degenerado'); en la B los clusters tienen tamaño razonable. Esa es la evidencia que cita la sección 3.2.2 del informe.")


if __name__ == "__main__":
    main()
