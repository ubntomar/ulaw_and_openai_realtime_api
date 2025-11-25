#!/bin/bash
#
# Script simple para ver las llamadas programadas para hoy
# Uso: ./ver_llamadas.sh o simplemente: ver_llamadas.sh
#

# Cambiar al directorio del proyecto
cd /usr/local/asterisk

# Cargar variables de entorno
if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs)
fi

# Ejecutar el script de Python
python3 ver_llamadas_hoy.py
