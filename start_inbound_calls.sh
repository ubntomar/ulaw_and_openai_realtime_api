#!/bin/bash

# ====================================================================
# Script de Inicialización - Sistema de Llamadas Entrantes OpenAI
# ====================================================================
# Este script carga las variables de entorno y ejecuta el handler
# de llamadas entrantes con OpenAI Realtime API
# ====================================================================

set -e  # Salir si hay algún error

# Colores para output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Sistema de Llamadas Entrantes OpenAI${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""

# Directorio del script
SCRIPT_DIR="/usr/local/asterisk"
ENV_FILE="$SCRIPT_DIR/.env"

# Verificar que el archivo .env existe
if [ ! -f "$ENV_FILE" ]; then
    echo -e "${RED}ERROR: No se encontró el archivo .env${NC}"
    echo ""
    echo "Por favor, crea el archivo .env con la configuración necesaria:"
    echo ""
    echo -e "${YELLOW}  cd $SCRIPT_DIR${NC}"
    echo -e "${YELLOW}  cp .env.example .env${NC}"
    echo -e "${YELLOW}  nano .env${NC}"
    echo ""
    echo "Luego edita el archivo con tus credenciales."
    exit 1
fi

echo -e "${GREEN}✓${NC} Archivo .env encontrado"

# Cargar variables de entorno desde .env
echo -e "${GREEN}✓${NC} Cargando variables de entorno..."
set -a  # Exportar automáticamente todas las variables
source "$ENV_FILE"
set +a

# Verificar variables críticas
REQUIRED_VARS=(
    "ASTERISK_USERNAME"
    "ASTERISK_PASSWORD"
    "ASTERISK_HOST"
    "ASTERISK_PORT"
    "OPENAI_API_KEY"
    "LOCAL_IP_ADDRESS"
    "LOG_FILE_PATH"
)

MISSING_VARS=()

for var in "${REQUIRED_VARS[@]}"; do
    if [ -z "${!var}" ]; then
        MISSING_VARS+=("$var")
    fi
done

if [ ${#MISSING_VARS[@]} -gt 0 ]; then
    echo -e "${RED}ERROR: Variables de entorno faltantes:${NC}"
    for var in "${MISSING_VARS[@]}"; do
        echo -e "${RED}  - $var${NC}"
    done
    echo ""
    echo "Por favor, edita el archivo .env y completa todas las variables."
    exit 1
fi

echo -e "${GREEN}✓${NC} Todas las variables de entorno están configuradas"

# Verificar que el directorio de logs existe
LOG_DIR=$(dirname "$LOG_FILE_PATH")
if [ ! -d "$LOG_DIR" ]; then
    echo -e "${YELLOW}⚠${NC} Creando directorio de logs: $LOG_DIR"
    sudo mkdir -p "$LOG_DIR"
    sudo chown asterisk:asterisk "$LOG_DIR" 2>/dev/null || true
fi

echo -e "${GREEN}✓${NC} Directorio de logs verificado: $LOG_DIR"

# Verificar que Asterisk está corriendo
if ! systemctl is-active --quiet asterisk; then
    echo -e "${RED}ERROR: Asterisk no está corriendo${NC}"
    echo ""
    echo "Inicia Asterisk primero:"
    echo -e "${YELLOW}  sudo systemctl start asterisk${NC}"
    exit 1
fi

echo -e "${GREEN}✓${NC} Asterisk está corriendo"

# Verificar que Python 3 está instalado
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}ERROR: Python 3 no está instalado${NC}"
    exit 1
fi

echo -e "${GREEN}✓${NC} Python 3 encontrado: $(python3 --version)"

# Mostrar configuración (ocultando credenciales)
echo ""
echo -e "${GREEN}Configuración:${NC}"
echo "  Asterisk: $ASTERISK_HOST:$ASTERISK_PORT"
echo "  Usuario ARI: $ASTERISK_USERNAME"
echo "  IP Local: $LOCAL_IP_ADDRESS"
echo "  Log File: $LOG_FILE_PATH"
echo "  OpenAI Key: ${OPENAI_API_KEY:0:7}...${OPENAI_API_KEY: -4}"
if [ ! -z "$OPENAI_REALTIME_MODEL" ]; then
    echo "  OpenAI Model: $OPENAI_REALTIME_MODEL"
else
    echo "  OpenAI Model: gpt-4o-realtime-preview-2024-12-17 (default)"
fi

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Iniciando sistema de llamadas entrantes...${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo -e "${YELLOW}Presiona Ctrl+C para detener${NC}"
echo ""

# Cambiar al directorio del proyecto
cd "$SCRIPT_DIR"

# Ejecutar el script Python
exec python3 inbound_calls/handle_incoming_call.py
