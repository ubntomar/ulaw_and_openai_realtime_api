#!/bin/bash
# Script para monitorear las llamadas a funciones y sus tiempos
# Uso: ./monitor_function_calls.sh [opción]

LOG_FILE="/var/log/asterisk/inbound_openai.log"

# Colores
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m' # Sin color

echo -e "${BLUE}=== Monitor de Function Calls - MikroTik API ===${NC}\n"

case "$1" in
    "live")
        echo -e "${GREEN}Monitoreando en tiempo real...${NC}"
        echo -e "Presiona Ctrl+C para salir\n"
        tail -f "$LOG_FILE" | grep --line-buffered -E "(Function call|Tiempo de ejecución|consultar_mikrotik|Conexión cerrada)" | while read line; do
            if echo "$line" | grep -q "tardó más de 30s"; then
                echo -e "${RED}$line${NC}"
            elif echo "$line" | grep -q "⏱️"; then
                echo -e "${YELLOW}$line${NC}"
            elif echo "$line" | grep -q "🔧"; then
                echo -e "${GREEN}$line${NC}"
            else
                echo "$line"
            fi
        done
        ;;

    "stats")
        echo -e "${GREEN}Estadísticas de Function Calls:${NC}\n"

        TOTAL=$(grep -c "Function call completada: consultar_mikrotik" "$LOG_FILE" 2>/dev/null || echo 0)
        echo -e "Total de consultas: ${YELLOW}${TOTAL}${NC}"

        SLOW=$(grep -c "tardó más de 30s" "$LOG_FILE" 2>/dev/null || echo 0)
        echo -e "Consultas lentas (>30s): ${RED}${SLOW}${NC}"

        echo -e "\n${BLUE}Últimas 10 consultas con tiempos:${NC}"
        grep "⏱️ Tiempo de ejecución" "$LOG_FILE" | tail -10

        echo -e "\n${BLUE}Consultas más lentas:${NC}"
        grep "⚠️ Function call tardó más de 30s" "$LOG_FILE" | tail -5
        ;;

    "keepalive")
        echo -e "${GREEN}Monitoreando keepalive (PING/PONG)...${NC}"
        echo -e "Presiona Ctrl+C para salir\n"
        tail -f "$LOG_FILE" | grep --line-buffered -E "(PING|PONG|ping|pong|keepalive|timeout)"
        ;;

    "errors")
        echo -e "${RED}Últimos 20 errores:${NC}\n"
        grep -E "(ERROR|WARNING|Conexión cerrada)" "$LOG_FILE" | tail -20
        ;;

    "last")
        echo -e "${GREEN}Última llamada con function call:${NC}\n"

        # Encontrar la última función ejecutada
        LAST_FUNCTION=$(grep "Function call completada: consultar_mikrotik" "$LOG_FILE" | tail -1)

        if [ -z "$LAST_FUNCTION" ]; then
            echo -e "${RED}No se encontraron function calls en los logs${NC}"
            exit 1
        fi

        # Extraer timestamp
        TIMESTAMP=$(echo "$LAST_FUNCTION" | cut -d' ' -f1-2)

        echo -e "${BLUE}Timestamp:${NC} $TIMESTAMP"
        echo -e "\n${BLUE}Detalles de la consulta:${NC}"

        # Mostrar contexto de esa función
        grep -A 5 "$TIMESTAMP" "$LOG_FILE" | head -20
        ;;

    "help"|"")
        echo "Uso: $0 [opción]"
        echo ""
        echo "Opciones:"
        echo "  live       - Monitorear function calls en tiempo real"
        echo "  stats      - Mostrar estadísticas de consultas"
        echo "  keepalive  - Monitorear PING/PONG del WebSocket"
        echo "  errors     - Mostrar últimos errores"
        echo "  last       - Ver detalles de la última consulta"
        echo "  help       - Mostrar esta ayuda"
        echo ""
        echo "Ejemplos:"
        echo "  $0 live      # Monitoreo en tiempo real"
        echo "  $0 stats     # Ver estadísticas"
        ;;

    *)
        echo -e "${RED}Opción no reconocida: $1${NC}"
        echo "Use '$0 help' para ver las opciones disponibles"
        exit 1
        ;;
esac
