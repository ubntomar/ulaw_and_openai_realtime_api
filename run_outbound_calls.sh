#!/bin/bash

# ============================================================================
# Script de Llamadas Automáticas con Validación de Trunk SIP
# ============================================================================
# Este script valida la conectividad del trunk SIP antes de ejecutar llamadas
# y puede reiniciar Asterisk automáticamente para restaurar la conexión
# ============================================================================

# Función para registrar logs con timestamp
log_message() {
    local message="$1"
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    echo "[$timestamp] $message"
    echo "[$timestamp] $message" >> $HOME/cron_jobs.log
}

# Función para validar el estado del trunk SIP
validate_trunk_status() {
    local max_attempts=3
    local attempt=1
    local wait_after_restart=30
    local final_wait=10
    
    log_message "🔍 INICIANDO VALIDACIÓN DEL TRUNK SIP voip_issabel"
    
    while [ $attempt -le $max_attempts ]; do
        log_message "📡 Intento $attempt/$max_attempts - Verificando estado del trunk voip_issabel..."
        
        # Obtener estado del trunk SIP
        trunk_status=$(sudo asterisk -rx "sip show peers" | grep voip_issabel 2>/dev/null)
        
        # Verificar si el comando fue exitoso
        if [ $? -eq 0 ] && [ -n "$trunk_status" ]; then
            # Analizar si el trunk está en estado OK
            if echo "$trunk_status" | grep -q "OK"; then
                local response_time=$(echo "$trunk_status" | grep -o "([0-9]* ms)" | head -1)
                log_message "✅ TRUNK ACTIVO: voip_issabel está funcionando correctamente $response_time"
                log_message "📋 Estado completo: $trunk_status"
                
                if [ $attempt -gt 1 ]; then
                    log_message "🎉 RECUPERACIÓN EXITOSA: Trunk restaurado después de $((attempt-1)) reinicio(s) de Asterisk"
                fi
                
                # Espera adicional para asegurar estabilidad antes de proceder
                log_message "⏳ Esperando ${final_wait}s adicionales para asegurar estabilidad..."
                sleep $final_wait
                
                return 0  # Éxito
            else
                log_message "⚠️ TRUNK INACTIVO: $trunk_status"
            fi
        else
            log_message "❌ ERROR: No se pudo obtener información del trunk o Asterisk no responde"
        fi
        
        # Si no es el último intento, reiniciar Asterisk
        if [ $attempt -lt $max_attempts ]; then
            log_message "🔄 REINICIANDO ASTERISK (intento $attempt de $((max_attempts-1)))..."
            
            # Registrar estado antes del reinicio
            log_message "📊 Estado de Asterisk antes del reinicio:"
            sudo systemctl status asterisk --no-pager -l >> $HOME/cron_jobs.log 2>&1
            
            # Reiniciar Asterisk
            sudo systemctl restart asterisk
            restart_exit_code=$?
            
            if [ $restart_exit_code -eq 0 ]; then
                log_message "✅ Comando de reinicio de Asterisk ejecutado correctamente"
            else
                log_message "❌ ERROR: Fallo en el comando de reinicio de Asterisk (código: $restart_exit_code)"
            fi
            
            log_message "⏳ Esperando ${wait_after_restart}s para que Asterisk se reinicie completamente..."
            sleep $wait_after_restart
            
            # Verificar que Asterisk esté funcionando
            log_message "🔍 Verificando que Asterisk esté activo después del reinicio..."
            if sudo systemctl is-active --quiet asterisk; then
                log_message "✅ Asterisk está activo después del reinicio"
            else
                log_message "❌ ERROR: Asterisk no está activo después del reinicio"
                sudo systemctl status asterisk --no-pager -l >> $HOME/cron_jobs.log 2>&1
            fi
        else
            log_message "❌ FALLO CRÍTICO: Se alcanzó el máximo de intentos sin restaurar la conexión"
        fi
        
        ((attempt++))
    done
    
    log_message "🛑 ERROR CRÍTICO: No se pudo establecer conexión con el trunk voip_issabel después de $max_attempts intentos"
    log_message "📞 CANCELANDO EJECUCIÓN: Las llamadas automáticas no se realizarán"
    
    # Registrar estado final para diagnóstico
    log_message "📊 Estado final de Asterisk para diagnóstico:"
    sudo systemctl status asterisk --no-pager -l >> $HOME/cron_jobs.log 2>&1
    
    return 1  # Fallo
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
    
    log_message "🚀 INICIANDO SCRIPT DE LLAMADAS AUTOMÁTICAS"
    log_message "⏰ Ejecutado desde cron a las 16:47"
    
    # Validar trunk SIP antes de proceder
    if validate_trunk_status; then
        log_message "✅ VALIDACIÓN EXITOSA: Procediendo con las llamadas automáticas"
        
        # Navegar al directorio correcto del script
        cd /usr/local/bin/outbound_calls
        
        if [ $? -eq 0 ]; then
            log_message "📁 Cambiado al directorio: $(pwd)"
        else
            log_message "❌ ERROR: No se pudo cambiar al directorio /usr/local/bin/outbound_calls"
            return 1
        fi
        
        # Verificar que el script Python existe
        file_path="/usr/local/bin/outbound_calls/mysql_overdue_client_call.py"
        file2_path="/usr/local/bin/outbound_calls/test_single_call.py"
        active_path=$file_path
        if [ -f "$active_path" ]; then
            log_message "📄 Script Python encontrado: $active_path"
        else
            log_message "❌ ERROR: Script $active_path no encontrado"
            return 1
        fi
        
        # Ejecutar el script Python de llamadas automáticas
        log_message "🐍 EJECUTANDO: $active_path"
        python3 $active_path >> $HOME/outbound_calls.log 2>&1
        python_exit_code=$?
        
        if [ $python_exit_code -eq 0 ]; then
            log_message "✅ Script Python ejecutado exitosamente"
        else
            log_message "❌ ERROR: Script Python terminó con código de error: $python_exit_code"
        fi
        
        log_message "📋 Logs detallados disponibles en: $HOME/outbound_calls.log"
        
    else
        log_message "🛑 EJECUCIÓN CANCELADA: Trunk SIP no disponible después de múltiples intentos"
        log_message "🔧 RECOMENDACIÓN: Revisar configuración de red y trunk SIP manualmente"
        return 1
    fi
    
    log_message "🏁 SCRIPT DE LLAMADAS AUTOMÁTICAS FINALIZADO"
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
# Este script se ejecuta a través de cron para realizar llamadas salientes 
# a clientes con facturas pendientes de pago.
#
# Configuración de cron actual:
# 47 16 * * * /usr/local/bin/run_outbound_calls.sh
#
# El script realiza las siguientes validaciones:
# 1. Verifica que el trunk SIP voip_issabel esté activo
# 2. Si no está activo, reinicia Asterisk hasta 3 veces
# 3. Solo procede con las llamadas si el trunk está operativo
# 4. Registra todo el proceso en logs detallados
#
# Logs generados:
# - $HOME/cron_jobs.log: Log principal del script bash
# - $HOME/outbound_calls.log: Log detallado del script Python
# ============================================================================