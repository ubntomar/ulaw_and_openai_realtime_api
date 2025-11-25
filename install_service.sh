#!/bin/bash

# ====================================================================
# Script de Instalación del Servicio systemd
# Sistema de Llamadas Entrantes OpenAI
# ====================================================================

set -e

# Colores
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Instalador del Servicio OpenAI Inbound${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Verificar que se ejecuta como root
if [[ $EUID -ne 0 ]]; then
   echo -e "${RED}ERROR: Este script debe ejecutarse como root${NC}"
   echo "Usa: sudo ./install_service.sh"
   exit 1
fi

SCRIPT_DIR="/usr/local/asterisk"
SERVICE_FILE="$SCRIPT_DIR/openai-inbound-calls.service"
ENV_FILE="$SCRIPT_DIR/.env"
ENV_EXAMPLE="$SCRIPT_DIR/.env.example"

# Paso 1: Verificar que existe .env.example
if [ ! -f "$ENV_EXAMPLE" ]; then
    echo -e "${RED}ERROR: No se encontró $ENV_EXAMPLE${NC}"
    exit 1
fi

echo -e "${GREEN}✓${NC} Archivo .env.example encontrado"

# Paso 2: Crear .env si no existe
if [ ! -f "$ENV_FILE" ]; then
    echo -e "${YELLOW}⚠${NC} Creando archivo .env desde .env.example..."
    cp "$ENV_EXAMPLE" "$ENV_FILE"
    echo -e "${GREEN}✓${NC} Archivo .env creado"
    echo ""
    echo -e "${YELLOW}IMPORTANTE: Debes editar el archivo .env con tus credenciales:${NC}"
    echo -e "${YELLOW}  nano $ENV_FILE${NC}"
    echo ""
    echo -e "${YELLOW}Configura las siguientes variables:${NC}"
    echo "  - ASTERISK_USERNAME"
    echo "  - ASTERISK_PASSWORD"
    echo "  - ASTERISK_HOST"
    echo "  - ASTERISK_PORT"
    echo "  - OPENAI_API_KEY"
    echo "  - LOCAL_IP_ADDRESS"
    echo "  - LOG_FILE_PATH"
    echo ""
    read -p "¿Quieres editar el archivo ahora? (s/n): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Ss]$ ]]; then
        nano "$ENV_FILE"
    else
        echo -e "${YELLOW}Recuerda editar el archivo antes de iniciar el servicio${NC}"
    fi
else
    echo -e "${GREEN}✓${NC} Archivo .env ya existe"
fi

# Paso 3: Crear directorio de logs
LOG_FILE_PATH=$(grep "^LOG_FILE_PATH=" "$ENV_FILE" | cut -d'=' -f2)
if [ ! -z "$LOG_FILE_PATH" ]; then
    LOG_DIR=$(dirname "$LOG_FILE_PATH")
    if [ ! -d "$LOG_DIR" ]; then
        echo -e "${YELLOW}⚠${NC} Creando directorio de logs: $LOG_DIR"
        mkdir -p "$LOG_DIR"
        chown asterisk:asterisk "$LOG_DIR" 2>/dev/null || true
        echo -e "${GREEN}✓${NC} Directorio de logs creado"
    else
        echo -e "${GREEN}✓${NC} Directorio de logs ya existe: $LOG_DIR"
    fi
fi

# Paso 4: Copiar archivo de servicio a systemd
if [ ! -f "$SERVICE_FILE" ]; then
    echo -e "${RED}ERROR: No se encontró el archivo de servicio: $SERVICE_FILE${NC}"
    exit 1
fi

echo -e "${YELLOW}⚠${NC} Copiando archivo de servicio a /etc/systemd/system/..."
cp "$SERVICE_FILE" /etc/systemd/system/openai-inbound-calls.service

echo -e "${GREEN}✓${NC} Archivo de servicio copiado"

# Paso 5: Recargar systemd
echo -e "${YELLOW}⚠${NC} Recargando configuración de systemd..."
systemctl daemon-reload
echo -e "${GREEN}✓${NC} Systemd recargado"

# Paso 6: Habilitar servicio
echo -e "${YELLOW}⚠${NC} Habilitando servicio para inicio automático..."
systemctl enable openai-inbound-calls.service
echo -e "${GREEN}✓${NC} Servicio habilitado"

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Instalación completada exitosamente${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo -e "${BLUE}Comandos disponibles:${NC}"
echo ""
echo "  Iniciar servicio:"
echo -e "    ${YELLOW}sudo systemctl start openai-inbound-calls${NC}"
echo ""
echo "  Detener servicio:"
echo -e "    ${YELLOW}sudo systemctl stop openai-inbound-calls${NC}"
echo ""
echo "  Ver estado del servicio:"
echo -e "    ${YELLOW}sudo systemctl status openai-inbound-calls${NC}"
echo ""
echo "  Ver logs en tiempo real:"
echo -e "    ${YELLOW}sudo journalctl -u openai-inbound-calls -f${NC}"
echo ""
echo "  Reiniciar servicio:"
echo -e "    ${YELLOW}sudo systemctl restart openai-inbound-calls${NC}"
echo ""
echo "  Deshabilitar inicio automático:"
echo -e "    ${YELLOW}sudo systemctl disable openai-inbound-calls${NC}"
echo ""
echo -e "${BLUE}Siguiente paso:${NC}"
echo -e "  1. Edita el archivo .env si no lo hiciste: ${YELLOW}nano $ENV_FILE${NC}"
echo -e "  2. Inicia el servicio: ${YELLOW}sudo systemctl start openai-inbound-calls${NC}"
echo -e "  3. Verifica que funciona: ${YELLOW}sudo systemctl status openai-inbound-calls${NC}"
echo ""
