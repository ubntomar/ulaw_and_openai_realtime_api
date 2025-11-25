#!/bin/bash

# ============================================================================
# Script de Reinicio Mensual de Contadores de Llamadas
# ============================================================================
# Este script reinicia los contadores de llamadas el día 1 de cada mes
# para permitir contactar nuevamente a los clientes morosos
# ============================================================================

# Asegurar que HOME esté definido (importante para cron)
if [ -z "$HOME" ]; then
    HOME="/home/omar"
    export HOME
fi

# Función para registrar logs con timestamp
log_message() {
    local message="$1"
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    echo "[$timestamp] $message"
    echo "[$timestamp] $message" >> $HOME/monthly_reset.log
}

# Función principal del script
main() {
    # Cargar las variables de entorno del usuario
    if [ -f "$HOME/.bash_profile" ]; then
        source $HOME/.bash_profile
        log_message "✅ Variables de entorno cargadas desde $HOME/.bash_profile"
    else
        log_message "⚠️ Archivo $HOME/.bash_profile no encontrado"
    fi

    log_message "🚀 INICIANDO SCRIPT DE REINICIO MENSUAL"
    log_message "📅 Ejecutado el día $(date '+%d') del mes $(date '+%m/%Y')"

    # Verificar que estamos en el día 1 del mes
    current_day=$(date '+%d')
    if [ "$current_day" != "01" ]; then
        log_message "⚠️ ADVERTENCIA: Este script debería ejecutarse el día 1 del mes"
        log_message "   Día actual: $current_day"
    fi

    # Navegar al directorio del script
    cd /usr/local/asterisk/outbound_calls

    if [ $? -eq 0 ]; then
        log_message "📁 Cambiado al directorio: $(pwd)"
    else
        log_message "❌ ERROR: No se pudo cambiar al directorio /usr/local/asterisk/outbound_calls"
        return 1
    fi

    # Verificar que el script Python existe
    script_path="/usr/local/asterisk/outbound_calls/reset_monthly_counters.py"
    if [ -f "$script_path" ]; then
        log_message "📄 Script Python encontrado: $script_path"
    else
        log_message "❌ ERROR: Script $script_path no encontrado"
        return 1
    fi

    # Ejecutar el script Python de reinicio
    log_message "🐍 EJECUTANDO: $script_path"
    python3 $script_path >> $HOME/monthly_reset_detailed.log 2>&1
    python_exit_code=$?

    if [ $python_exit_code -eq 0 ]; then
        log_message "✅ Script Python ejecutado exitosamente"
        log_message "📊 Contadores reiniciados correctamente"
    else
        log_message "❌ ERROR: Script Python terminó con código de error: $python_exit_code"
        log_message "🔍 Revisar logs en: $HOME/monthly_reset_detailed.log"
    fi

    log_message "📋 Logs detallados disponibles en: $HOME/monthly_reset_detailed.log"
    log_message "🏁 SCRIPT DE REINICIO MENSUAL FINALIZADO"
    echo ""
}

# ============================================================================
# EJECUCIÓN PRINCIPAL
# ============================================================================

# Ejecutar función principal
main

# ============================================================================
# INFORMACIÓN DEL SCRIPT
# ============================================================================
# Este script se ejecuta a través de cron el día 1 de cada mes.
#
# Configuración de cron sugerida:
# 0 2 1 * * /usr/local/asterisk/reset_monthly_counters.sh
# (Se ejecuta a las 2:00 AM el día 1 de cada mes)
#
# El script realiza:
# 1. Reinicia outbound_call_is_sent a 0
# 2. Reinicia outbound_call_attempts a 0
# 3. Limpia outbound_call_completed_at (NULL)
#
# Para todos los clientes activos con outbound_call = 1
#
# Logs generados:
# - $HOME/monthly_reset.log: Log principal del script bash
# - $HOME/monthly_reset_detailed.log: Log detallado del script Python
# - /tmp/monthly_reset.log: Log interno del script Python
# ============================================================================
