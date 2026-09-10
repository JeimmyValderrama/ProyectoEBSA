"""
simular_meses.py — corre el pipeline mes a mes como si cada mes fuera "hoy"
===========================================================================

Sirve para dos cosas:
  1. Probar la operación mensual completa con varios meses que ya están en el
     histórico (p. ej. marzo a junio) sin esperar a que pasen de verdad.
  2. Mostrar cómo se deteriora un modelo con el tiempo y cómo mejora al reentrenar:
     se entrena en un corte, se aplica mes a mes sin reentrenar, se reentrena en
     otro corte y se sigue aplicando. El seguimiento en vivo (paso 12) queda con
     una fila por corte y por versión de modelo, y comparar_modelos.py arma la
     comparación.

Requisitos: los meses a simular ya deben estar en el histórico y en la serie
(pasos 1 y 2 corridos con todos los archivos TC2). La simulación corre los pasos
3, 8..15 con --corte-max en cada mes, así que nunca ve datos posteriores al corte.

Se recomienda correrla sobre una COPIA de la carpeta de datos (--datos), porque
sobreescribe las salidas y los modelos vigentes.

Uso (desde Pipeline_Ebsa):

    python simular_meses.py --desde 2025-06 --hasta 2026-06 --reentrenar-en 2025-06,2026-02 --datos "C:\\...\\Datos_Ebsa_simulacion"

    --desde / --hasta      primer y último corte a simular (AAAA-MM)
    --reentrenar-en        cortes en los que se reentrena (el primero debería ser --desde,
                           para que exista un modelo); los demás meses van en modo aplicar
    --cada N               simular cada N meses (por defecto 1)
    --solo-fuga            reentrenar solo el riesgo de fuga en los cortes de reentrenamiento
                           (rápido; el pronóstico se reentrena completo solo si no existe)
    --comparar-version AAAA-MM
                           después de la simulación, vuelve a pronosticar los cortes posteriores al
                           último reentrenamiento con esa versión vieja del modelo, y guarda esos
                           pronósticos aparte (historial_pronosticos\\comparacion) para que
                           comparar_modelos.py enfrente modelo viejo y nuevo sobre los MISMOS meses.
    --datos ruta           carpeta de datos (recomendado: una copia)

Deja en <datos>\\09_registro_corridas\\simulacion\\: el log de cada corte, la salida de
verificar_corrida.py y estado_modelos.py de cada corte, y resumen_simulacion.csv.
Después: python comparar_modelos.py --datos <la misma carpeta>
"""
import argparse
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd

# Windows: salida en UTF-8 aunque se redirija a un archivo (para "✓" / "✗").
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

CODIGO_DIR = Path(__file__).resolve().parent
PASOS_SIMULACION = "3,8,9,10,11,12,13,14,15"
PASOS_SOLO_FUGA = "3,8,9,10,11,12,13,14,15"   # en reentrenar "solo fuga" se reentrena 14; el resto va en aplicar


def meses_entre(a, b):
    r, cur = [], pd.Timestamp(a + "-01")
    fin = pd.Timestamp(b + "-01")
    while cur <= fin:
        r.append(cur.strftime("%Y-%m"))
        cur = cur + pd.DateOffset(months=1)
    return r


def correr(cmd, log_path, env):
    with open(log_path, "w", encoding="utf-8") as f:
        f.write("$ " + " ".join(cmd) + "\n\n")
        p = subprocess.run(cmd, cwd=str(CODIGO_DIR), env=env, stdout=f, stderr=subprocess.STDOUT,
                           text=True, encoding="utf-8", errors="replace")
    return p.returncode


def capturar(cmd, env):
    p = subprocess.run(cmd, cwd=str(CODIGO_DIR), env=env, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return p.stdout + p.stderr


def main():
    ap = argparse.ArgumentParser(description="Simulación mes a mes del pipeline EBSA")
    ap.add_argument("--desde", required=True, metavar="AAAA-MM")
    ap.add_argument("--hasta", required=True, metavar="AAAA-MM")
    ap.add_argument("--reentrenar-en", default="", help="cortes separados por coma en los que se reentrena")
    ap.add_argument("--cada", type=int, default=1)
    ap.add_argument("--solo-fuga", action="store_true")
    ap.add_argument("--comparar-version", default=None, metavar="AAAA-MM")
    ap.add_argument("--datos", default=os.environ.get("EBSA_DATOS", r"C:\Users\Home\Documents\Datos_Ebsa"))
    args = ap.parse_args()

    datos = Path(args.datos)
    if not datos.exists():
        print("ERROR: no existe la carpeta de datos:", datos)
        return 1
    cortes = meses_entre(args.desde, args.hasta)[:: max(1, args.cada)]
    reentrenar_en = {c.strip() for c in args.reentrenar_en.split(",") if c.strip()}
    sim_dir = datos / "09_registro_corridas" / "simulacion"
    sim_dir.mkdir(parents=True, exist_ok=True)
    resumen_path = sim_dir / "resumen_simulacion.csv"

    print("=" * 78)
    print(f"SIMULACIÓN MES A MES  datos={datos}")
    print(f"Cortes: {cortes}")
    print(f"Reentrenar en: {sorted(reentrenar_en) or 'ninguno (solo aplicar; debe existir un modelo)'}")
    print(f"Registro: {sim_dir}")
    print("=" * 78)

    env = dict(os.environ)
    env["EBSA_DATOS"] = str(datos)
    env["PYTHONIOENCODING"] = "utf-8"     # Windows: que los hijos escriban UTF-8 al log
    env["PYTHONUTF8"] = "1"
    env.pop("EBSA_CORTE_MAX", None); env.pop("EBSA_VERSION_MODELO", None)
    filas = []
    for k, corte in enumerate(cortes, start=1):
        modo = "reentrenar" if corte in reentrenar_en else "aplicar"
        t0 = time.time()
        print(f"\n[{k}/{len(cortes)}] corte {corte}  modo {modo}", flush=True)
        if modo == "reentrenar" and args.solo_fuga and (datos / "04_pronostico" / "modelo_final" / "modelos_ganadores_optimizados_final.joblib").exists():
            # pronóstico/agrupamiento/caída en aplicar, riesgo de fuga reentrenado
            rc = correr([sys.executable, "pipeline_mensual.py", "--modo", "aplicar", "--corte-max", corte,
                         "--solo", "3,8,9,10,11,12,13", "--datos", str(datos)], sim_dir / f"{corte}_aplicar.log", env)
            if rc == 0:
                rc = correr([sys.executable, "pipeline_mensual.py", "--modo", "reentrenar", "--corte-max", corte,
                             "--solo", "14,15", "--datos", str(datos)], sim_dir / f"{corte}_reentrenar_fuga.log", env)
        else:
            rc = correr([sys.executable, "pipeline_mensual.py", "--modo", modo, "--corte-max", corte,
                         "--solo", PASOS_SIMULACION, "--datos", str(datos)], sim_dir / f"{corte}_{modo}.log", env)
        minutos = (time.time() - t0) / 60
        if rc != 0:
            print(f"   ✗ falló (ver {sim_dir / f'{corte}_{modo}.log'}). Se detiene la simulación.")
            return 1
        print(f"   ✓ {minutos:.1f} min", flush=True)

        # verificación y estado, guardados por corte
        (sim_dir / f"{corte}_verificar.txt").write_text(capturar([sys.executable, "verificar_corrida.py"], env), encoding="utf-8")
        estado = capturar([sys.executable, "estado_modelos.py"], env)
        (sim_dir / f"{corte}_estado.txt").write_text(estado, encoding="utf-8")

        # resumen del corte
        fila = {"corte": corte, "modo": modo, "minutos": round(minutos, 1), "hecho_el": datetime.now().strftime("%Y-%m-%d %H:%M")}
        try:
            g = pd.read_csv(datos / "07_gestion_caida" / "gestion_caida_operativa.csv", encoding="utf-8-sig")
            fila["clientes_lista_caida"] = len(g)
            fila["valor_riesgo_caida_mes"] = round(float(g["valor_riesgo_mes"].sum()), 0)
        except Exception:
            pass
        try:
            f = pd.read_csv(datos / "10_riesgo_fuga" / "riesgo_fuga_clientes.csv", encoding="utf-8-sig")
            fila["fuga_alto"] = int((f["nivel_riesgo"] == "ALTO").sum())
            fila["fuga_medio"] = int((f["nivel_riesgo"] == "MEDIO").sum())
        except Exception:
            pass
        try:
            p = pd.read_parquet(datos / "04_pronostico" / "modelo_final" / "predicciones_segmentadas_optimizadas_6_meses.parquet",
                                columns=["fecha_corte_modelo", "pred_1m_kwh"])
            fila["modelo_pronostico"] = str(p["fecha_corte_modelo"].iloc[0])[:7]
            fila["pronostico_total_1m_kwh"] = round(float(p["pred_1m_kwh"].sum()), 0)
        except Exception:
            pass
        try:
            s = pd.read_csv(datos / "08_seguimiento" / "seguimiento_pronostico_global.csv", encoding="utf-8-sig")
            s1 = s[s["horizonte"].eq(1)]
            if len(s1):
                fila["wape_vivo_h1_ultimo_evaluado"] = round(float(s1.sort_values("fecha_corte")["WAPE_pct"].iloc[-1]), 2)
        except Exception:
            pass
        for linea in estado.splitlines():
            if "Pronóstico" in linea and ("MANTENER" in linea or "REENTRENAR" in linea or "REVISAR" in linea):
                fila["veredicto_pronostico"] = linea.split()[2] if len(linea.split()) > 2 else ""
        filas.append(fila)
        pd.DataFrame(filas).to_csv(resumen_path, index=False, encoding="utf-8-sig")

    # --- Comparación cabeza a cabeza: la versión vieja pronosticando los cortes del modelo nuevo ---
    if args.comparar_version:
        ultimo_re = max((c for c in cortes if c in reentrenar_en), default=None)
        cortes_cmp = [c for c in cortes if ultimo_re is None or c >= ultimo_re]
        hist = datos / "04_pronostico" / "modelo_final" / "historial_pronosticos"
        cmp_dir = hist / "comparacion"
        cmp_dir.mkdir(parents=True, exist_ok=True)
        print(f"\nComparación con la versión {args.comparar_version} en los cortes {cortes_cmp}")
        for corte in cortes_cmp:
            principal = hist / f"predicciones_6_meses_corte_{corte}.parquet"
            respaldo = None
            if principal.exists():
                respaldo = principal.read_bytes()
            rc = correr([sys.executable, "pipeline_mensual.py", "--modo", "aplicar", "--corte-max", corte,
                         "--version-modelo", args.comparar_version, "--solo", "3,8", "--datos", str(datos)],
                        sim_dir / f"{corte}_comparar_{args.comparar_version}.log", env)
            if rc == 0 and principal.exists():
                (cmp_dir / f"predicciones_6_meses_corte_{corte}_modelo{args.comparar_version}.parquet").write_bytes(principal.read_bytes())
                print(f"   ✓ corte {corte} pronosticado con la versión {args.comparar_version}")
            else:
                print(f"   ✗ corte {corte}: falló (ver log)")
            if respaldo is not None:
                principal.write_bytes(respaldo)      # se restaura el pronóstico del modelo nuevo
        # dejar las salidas vigentes como las dejó el último corte de la simulación
        correr([sys.executable, "pipeline_mensual.py", "--modo", "aplicar", "--corte-max", cortes[-1],
                "--solo", "3,8", "--datos", str(datos)], sim_dir / f"{cortes[-1]}_restaurar.log", env)

    print("\n" + "=" * 78)
    print("SIMULACIÓN TERMINADA")
    print(pd.DataFrame(filas).to_string(index=False))
    print("\nResumen:", resumen_path)
    print("Siguiente paso:  python comparar_modelos.py --datos", f'"{datos}"')
    return 0


if __name__ == "__main__":
    sys.exit(main())
