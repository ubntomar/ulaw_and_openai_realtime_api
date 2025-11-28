#!/bin/bash
##############################################################################
# Script de Monitoreo de Llamadas en Tiempo Real
##############################################################################
#
# Monitorea logs de Asterisk y OpenAI durante llamadas activas
# para observar el comportamiento del asistente durante consultas
#
# Uso: ./monitor_live_call.sh
#
# Autor: Omar
# Fecha: Nov 2025
##############################################################################

# Colores
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
MAGENTA='\033[0;35m'
BOLD='\033[1m'
NC='\033[0m' # No Color

# Archivos de log
ASTERISK_LOG="/var/log/asterisk/full"
OPENAI_LOG="/var/log/asterisk/inbound_openai.log"

# Función para timestamp
timestamp() {
    date '+%H:%M:%S.%3N'
}

# Función para log con color
log() {
    local color=$1
    shift
    echo -e "${color}[$(timestamp)] $@${NC}"
}

# Banner
clear
echo -e "${BOLD}${CYAN}"
echo "╔════════════════════════════════════════════════════════════════════╗"
echo "║                                                                    ║"
echo "║     MONITOR DE LLAMADAS EN TIEMPO REAL - OPENAI + MIKROTIK       ║"
echo "║                                                                    ║"
echo "╚════════════════════════════════════════════════════════════════════╝"
echo -e "${NC}\n"

log "$GREEN" "Iniciando monitoreo multi-ventana..."
log "$CYAN" "Presiona Ctrl+C para detener"
echo ""

# Verificar que los archivos de log existan
if [ ! -f "$ASTERISK_LOG" ]; then
    log "$RED" "ERROR: No se encuentra $ASTERISK_LOG"
    exit 1
fi

if [ ! -f "$OPENAI_LOG" ]; then
    log "$RED" "ERROR: No se encuentra $OPENAI_LOG"
    exit 1
fi

# Crear archivo temporal para salida combinada
TEMP_OUTPUT=$(mktemp)
trap "rm -f $TEMP_OUTPUT" EXIT

# Función para limpiar procesos al salir
cleanup() {
    echo ""
    log "$YELLOW" "Deteniendo monitoreo..."
    pkill -P $$ 2>/dev/null
    rm -f "$TEMP_OUTPUT"
    echo ""
    log "$GREEN" "Monitor detenido"
    exit 0
}

trap cleanup INT TERM

# Separador visual
print_separator() {
    echo -e "${BLUE}────────────────────────────────────────────────────────────────────${NC}"
}

# Función para monitorear eventos de llamada
monitor_call_events() {
    tail -f "$ASTERISK_LOG" | grep --line-buffered -E "(StasisStart|StasisEnd|Answer|Hangup|ChannelStateChange)" | while read line; do
        if echo "$line" | grep -q "StasisStart"; then
            print_separator
            log "$GREEN" "📞 LLAMADA INICIADA"
            echo "$line" | grep -oP 'channel":\{"id":"[^"]+' | cut -d'"' -f4 | xargs -I {} log "$CYAN" "   Canal: {}"
        elif echo "$line" | grep -q "Answer"; then
            log "$GREEN" "✓ LLAMADA CONTESTADA"
        elif echo "$line" | grep -q "StasisEnd\|Hangup"; then
            log "$RED" "📵 LLAMADA FINALIZADA"
            print_separator
        fi
    done &
}

# Función para monitorear consultas MikroTik
monitor_mikrotik_queries() {
    tail -f "$OPENAI_LOG" | grep --line-buffered -E "(Ejecutando función|función exitosa|función falló|Consultando|router)" | while read line; do
        if echo "$line" | grep -qi "ejecutando función"; then
            func_name=$(echo "$line" | grep -oP "función: \K\w+" || echo "desconocida")
            log "$MAGENTA" "🔧 FUNCIÓN LLAMADA: $func_name"
        elif echo "$line" | grep -qi "función exitosa"; then
            log "$GREEN" "   ✓ Función completada exitosamente"
        elif echo "$line" | grep -qi "función falló"; then
            log "$RED" "   ✗ Función falló"
        elif echo "$line" | grep -qi "consultando.*router"; then
            router=$(echo "$line" | grep -oP "router \K[\d\.]+" || echo "N/A")
            log "$CYAN" "   → Consultando router: $router"
        fi
    done &
}

# Función para monitorear audio/RTP
monitor_audio() {
    tail -f "$OPENAI_LOG" | grep --line-buffered -E "(RTP|audio|chunk|response\.audio\.delta|conversation\.item\.created)" | while read line; do
        if echo "$line" | grep -qi "paquetes RTP enviados"; then
            packets=$(echo "$line" | grep -oP "\d+ paquetes" | awk '{print $1}')
            # Solo mostrar cada 5 segundos para no saturar
            if [ $((RANDOM % 5)) -eq 0 ]; then
                log "$BLUE" "🔊 RTP: ~$packets paquetes/s"
            fi
        elif echo "$line" | grep -qi "response\.audio\.delta"; then
            log "$GREEN" "🎤 Audio recibido de OpenAI"
        elif echo "$line" | grep -qi "conversation\.item\.created"; then
            if echo "$line" | grep -qi "assistant"; then
                log "$CYAN" "💬 Asistente respondiendo..."
            fi
        fi
    done &
}

# Función para monitorear errores
monitor_errors() {
    tail -f "$OPENAI_LOG" "$ASTERISK_LOG" | grep --line-buffered -iE "(error|exception|failed|timeout|warning)" | while read line; do
        # Ignorar errores conocidos no críticos
        if echo "$line" | grep -qiE "(404|Unauthorized|401|403)"; then
            continue
        fi

        if echo "$line" | grep -qi "error"; then
            log "$RED" "❌ ERROR: $(echo $line | grep -oP '(ERROR|Error).*')"
        elif echo "$line" | grep -qi "warning"; then
            log "$YELLOW" "⚠ WARNING: $(echo $line | grep -oP '(WARNING|Warning).*')"
        elif echo "$line" | grep -qi "timeout"; then
            log "$RED" "⏱ TIMEOUT detectado"
        fi
    done &
}

# Función para mostrar estadísticas periódicas
show_stats() {
    while true; do
        sleep 30
        print_separator
        log "$CYAN" "📊 ESTADÍSTICAS (últimos 30s):"

        # Contar eventos recientes
        calls=$(tail -n 1000 "$ASTERISK_LOG" | grep -c "StasisStart" || echo 0)
        functions=$(tail -n 1000 "$OPENAI_LOG" | grep -c "Ejecutando función" || echo 0)
        errors=$(tail -n 1000 "$OPENAI_LOG" | grep -ic "error" || echo 0)

        echo -e "   ${GREEN}Llamadas iniciadas: $calls${NC}"
        echo -e "   ${MAGENTA}Funciones ejecutadas: $functions${NC}"
        echo -e "   ${RED}Errores: $errors${NC}"
        print_separator
    done &
}

# Iniciar todos los monitores
log "$CYAN" "Iniciando monitores..."
echo ""

monitor_call_events
monitor_mikrotik_queries
monitor_audio
monitor_errors
show_stats

# Mensaje informativo
echo -e "${BOLD}${YELLOW}"
echo "╔════════════════════════════════════════════════════════════════════╗"
echo "║  MONITOREANDO:                                                     ║"
echo "║    📞 Eventos de llamada (inicio/fin)                             ║"
echo "║    🔧 Consultas a routers MikroTik                                ║"
echo "║    🔊 Tráfico de audio RTP                                        ║"
echo "║    ❌ Errores y warnings                                          ║"
echo "║    📊 Estadísticas periódicas                                     ║"
echo "║                                                                    ║"
echo "║  AHORA PUEDES REALIZAR TU LLAMADA DE PRUEBA                       ║"
echo "╚════════════════════════════════════════════════════════════════════╝"
echo -e "${NC}\n"

# Mantener el script corriendo
wait
