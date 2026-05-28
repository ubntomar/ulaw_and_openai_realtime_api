#!/bin/bash

# ============================================================================
# Script de Activacion Mensual de Llamadas Salientes
# ============================================================================
# Este script activa outbound_call = 1 para clientes activos que lo tengan
# en 0 o NULL, permitiendo que sean evaluados por el sistema de llamadas
# ============================================================================

# Asegurar que HOME este definido (importante para cron)
if [ -z "$HOME" ]; then
    HOME="/home/omar"
    export HOME
fi

# Funcion para registrar logs con timestamp
log_message() {
    local message="$1"
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    echo "[$timestamp] $message"
    echo "[$timestamp] $message" >> $HOME/enable_outbound_calls.log
}

# Funcion principal del script
main() {
    # Cargar las variables de entorno del usuario
    if [ -f "$HOME/.bash_profile" ]; then
        source $HOME/.bash_profile
        log_message "Variables de entorno cargadas desde $HOME/.bash_profile"
    else
        log_message "Archivo $HOME/.bash_profile no encontrado"
    fi

    log_message "INICIANDO SCRIPT DE ACTIVACION MENSUAL DE OUTBOUND_CALL"
    log_message "Ejecutado el dia $(date '+%d') del mes $(date '+%m/%Y')"

    # Navegar al directorio del script
    cd /usr/local/asterisk/outbound_calls

    if [ $? -eq 0 ]; then
        log_message "Cambiado al directorio: $(pwd)"
    else
        log_message "ERROR: No se pudo cambiar al directorio /usr/local/asterisk/outbound_calls"
        return 1
    fi

    # Verificar que el script Python existe
    script_path="/usr/local/asterisk/outbound_calls/enable_outbound_calls.py"
    if [ -f "$script_path" ]; then
        log_message "Script Python encontrado: $script_path"
    else
        log_message "ERROR: Script $script_path no encontrado"
        return 1
    fi

    # Ejecutar el script Python
    log_message "EJECUTANDO: $script_path"
    python3 $script_path >> $HOME/enable_outbound_calls_detailed.log 2>&1
    python_exit_code=$?

    if [ $python_exit_code -eq 0 ]; then
        log_message "Script Python ejecutado exitosamente"
    else
        log_message "ERROR: Script Python termino con codigo de error: $python_exit_code"
        log_message "Revisar logs en: $HOME/enable_outbound_calls_detailed.log"
    fi

    log_message "Logs detallados disponibles en: $HOME/enable_outbound_calls_detailed.log"
    log_message "SCRIPT DE ACTIVACION FINALIZADO"
    echo ""
}

# ============================================================================
# EJECUCION PRINCIPAL
# ============================================================================

main

# ============================================================================
# INFORMACION DEL SCRIPT
# ============================================================================
# Este script se ejecuta a traves de cron el dia 1 de cada mes.
#
# Configuracion de cron sugerida:
# 0 1 1 * * /usr/local/asterisk/enable_outbound_calls.sh
# (Se ejecuta a la 1:00 AM el dia 1 de cada mes, ANTES del reset de contadores)
#
# El script realiza:
# 1. Activa outbound_call = 1 para clientes con outbound_call = 0 o NULL
# 2. Solo afecta clientes activos (activo = 1) y no eliminados (eliminar = 0)
#
# Logs generados:
# - $HOME/enable_outbound_calls.log: Log principal del script bash
# - $HOME/enable_outbound_calls_detailed.log: Log detallado del script Python
# - /tmp/enable_outbound_calls.log: Log interno del script Python
# ============================================================================
