@echo off
title Visualizador de Modulacao Externa
cd /d "%~dp0"

echo Verificando se o servidor ja esta rodando na porta 8080...
py -c "import socket,sys; s=socket.socket(); s.settimeout(0.3); r=s.connect_ex(('127.0.0.1',8080)); s.close(); sys.exit(0 if r==0 else 1)" >nul 2>&1
if %errorlevel%==0 (
    echo Servidor ja estava rodando - so' abrindo o navegador.
    start "" "http://localhost:8080/"
    goto fim
)

echo Iniciando o servidor local (janela minimizada "Servidor - Visualizador de Modulacao")...
start "Servidor - Visualizador de Modulacao" /min py server.py 8080

echo Aguardando o servidor subir...
timeout /t 2 /nobreak >nul

start "" "http://localhost:8080/"

echo.
echo O visualizador deve abrir no navegador em alguns instantes.
echo O servidor continua rodando na janela minimizada "Servidor - Visualizador de Modulacao"
echo (procure na barra de tarefas). Para PARAR, feche aquela janela.
echo.

:fim
pause
