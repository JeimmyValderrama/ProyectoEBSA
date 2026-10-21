@echo off
cd /d "%~dp0"
echo Abriendo la pagina EBSA - Consumo, interfaz nueva (se abre en el navegador; cierra esta ventana para apagarla)
python -m streamlit run app_ebsa_v2.py --server.port 8502
pause
