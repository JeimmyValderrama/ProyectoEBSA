@echo off
cd /d "%~dp0"
echo Abriendo la pagina EBSA - Consumo (se abre en el navegador; cierra esta ventana para apagarla)
python -m streamlit run app_ebsa.py
pause
