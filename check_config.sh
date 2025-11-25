#!/bin/bash

# ====================================================================
# Script de Verificación de Configuración
# Sistema de Llamadas Entrantes OpenAI
# ====================================================================

set -e

# Colores
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

# Contadores
ERRORS=0
WARNINGS=0
SUCCESS=0

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Verificación de Configuración${NC}"
echo -e "${BLUE}Sistema de Llamadas Entrantes OpenAI${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Función para mostrar éxito
check_success() {
    echo -e "${GREEN}✓${NC} $1"
    ((SUCCESS++))
}

# Función para mostrar error
check_error() {
    echo -e "${RED}✗${NC} $1"
    ((ERRORS++))
}

# Función para mostrar advertencia
check_warning() {
    echo -e "${YELLOW}⚠${NC} $1"
    ((WARNINGS++))
}

echo -e "${CYAN}[1/8] Verificando archivos de configuración...${NC}"
echo ""

# Verificar que existe .env
if [ -f "/usr/local/asterisk/.env" ]; then
    check_success "Archivo .env encontrado"
else
    check_error "Archivo .env NO encontrado"
    echo "      Ejecuta: cp /usr/local/asterisk/.env.example /usr/local/asterisk/.env"
fi

# Verificar que existe .gitignore
if [ -f "/usr/local/asterisk/.gitignore" ]; then
    if grep -q "^.env$" /usr/local/asterisk/.gitignore; then
        check_success "Archivo .gitignore protege .env"
    else
        check_warning "Archivo .gitignore no protege .env"
    fi
else
    check_warning "Archivo .gitignore NO encontrado"
fi

echo ""
echo -e "${CYAN}[2/8] Cargando y verificando variables de entorno...${NC}"
echo ""

# Cargar variables
if [ -f "/usr/local/asterisk/.env" ]; then
    set -a
    source /usr/local/asterisk/.env 2>/dev/null || true
    set +a
fi

# Variables requeridas
REQUIRED_VARS=(
    "ASTERISK_USERNAME"
    "ASTERISK_PASSWORD"
    "ASTERISK_HOST"
    "ASTERISK_PORT"
    "OPENAI_API_KEY"
    "LOCAL_IP_ADDRESS"
    "LOG_FILE_PATH"
)

for var in "${REQUIRED_VARS[@]}"; do
    if [ ! -z "${!var}" ]; then
        # Verificar que no sea un placeholder
        value="${!var}"
        if [[ "$value" == *"TU-KEY-AQUI"* ]] || [[ "$value" == *"your_"* ]] || [[ "$value" == *"tu_"* ]]; then
            check_error "$var está configurada pero con valor placeholder"
            echo "      Valor actual: ${value:0:30}..."
        else
            check_success "$var está configurada"
        fi
    else
        check_error "$var NO está configurada"
    fi
done

echo ""
echo -e "${CYAN}[3/8] Verificando servicios del sistema...${NC}"
echo ""

# Verificar Asterisk
if systemctl is-active --quiet asterisk; then
    check_success "Asterisk está corriendo"
else
    check_error "Asterisk NO está corriendo"
    echo "      Ejecuta: sudo systemctl start asterisk"
fi

# Verificar Python 3
if command -v python3 &> /dev/null; then
    check_success "Python 3 instalado: $(python3 --version 2>&1 | awk '{print $2}')"
else
    check_error "Python 3 NO está instalado"
fi

echo ""
echo -e "${CYAN}[4/8] Verificando conectividad con Asterisk...${NC}"
echo ""

if [ ! -z "$ASTERISK_USERNAME" ] && [ ! -z "$ASTERISK_PASSWORD" ] && [ ! -z "$ASTERISK_HOST" ] && [ ! -z "$ASTERISK_PORT" ]; then
    # Verificar API REST de Asterisk
    if curl -s -u "$ASTERISK_USERNAME:$ASTERISK_PASSWORD" "http://$ASTERISK_HOST:$ASTERISK_PORT/ari/asterisk/info" > /dev/null 2>&1; then
        check_success "Conexión ARI REST exitosa"
    else
        check_error "No se pudo conectar a ARI REST en $ASTERISK_HOST:$ASTERISK_PORT"
        echo "      Verifica credenciales y que Asterisk esté corriendo"
    fi
else
    check_warning "Saltando verificación de ARI (variables no configuradas)"
fi

echo ""
echo -e "${CYAN}[5/8] Verificando dialplan de Asterisk...${NC}"
echo ""

# Verificar que existe el contexto from-voip
if sudo asterisk -rx "dialplan show from-voip" 2>/dev/null | grep -q "3241000752"; then
    check_success "Dialplan configurado para número 3241000752"
else
    check_warning "No se encontró extensión 3241000752 en dialplan"
fi

# Verificar que existe Stasis(openai-app)
if sudo asterisk -rx "dialplan show from-voip" 2>/dev/null | grep -q "Stasis(openai-app)"; then
    check_success "Stasis(openai-app) configurado en dialplan"
else
    check_error "Stasis(openai-app) NO configurado en dialplan"
    echo "      Verifica /etc/asterisk/extensions.conf"
fi

echo ""
echo -e "${CYAN}[6/8] Verificando directorios y permisos...${NC}"
echo ""

# Verificar directorio de logs
if [ ! -z "$LOG_FILE_PATH" ]; then
    LOG_DIR=$(dirname "$LOG_FILE_PATH")
    if [ -d "$LOG_DIR" ]; then
        check_success "Directorio de logs existe: $LOG_DIR"

        # Verificar permisos
        if [ -w "$LOG_DIR" ]; then
            check_success "Directorio de logs tiene permisos de escritura"
        else
            check_warning "Directorio de logs no tiene permisos de escritura"
            echo "      Ejecuta: sudo chown asterisk:asterisk $LOG_DIR"
        fi
    else
        check_warning "Directorio de logs NO existe: $LOG_DIR"
        echo "      Ejecuta: sudo mkdir -p $LOG_DIR"
    fi
fi

echo ""
echo -e "${CYAN}[7/8] Verificando dependencias Python...${NC}"
echo ""

PYTHON_DEPS=(
    "websockets"
    "aiohttp"
    "numpy"
    "scipy"
    "webrtcvad"
    "websocket"
)

for dep in "${PYTHON_DEPS[@]}"; do
    if python3 -c "import $dep" 2>/dev/null; then
        check_success "Módulo Python '$dep' instalado"
    else
        check_error "Módulo Python '$dep' NO instalado"
        echo "      Ejecuta: pip3 install $dep"
    fi
done

echo ""
echo -e "${CYAN}[8/8] Verificando conectividad de red...${NC}"
echo ""

# Verificar IP local
if [ ! -z "$LOCAL_IP_ADDRESS" ]; then
    if ip addr | grep -q "$LOCAL_IP_ADDRESS"; then
        check_success "IP local configurada correctamente: $LOCAL_IP_ADDRESS"
    else
        check_warning "IP local $LOCAL_IP_ADDRESS no encontrada en interfaces"
        DETECTED_IP=$(hostname -I | awk '{print $1}')
        echo "      IP detectada: $DETECTED_IP"
        echo "      Considera cambiar LOCAL_IP_ADDRESS=$DETECTED_IP en .env"
    fi
fi

# Verificar conectividad con OpenAI
if ping -c 1 -W 2 api.openai.com > /dev/null 2>&1; then
    check_success "Conectividad con api.openai.com exitosa"
else
    check_warning "No se pudo hacer ping a api.openai.com"
    echo "      Verifica la conexión a internet"
fi

# Resumen
echo ""
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Resumen de Verificación${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""
echo -e "${GREEN}✓ Exitosas:     $SUCCESS${NC}"
echo -e "${YELLOW}⚠ Advertencias: $WARNINGS${NC}"
echo -e "${RED}✗ Errores:      $ERRORS${NC}"
echo ""

if [ $ERRORS -eq 0 ] && [ $WARNINGS -eq 0 ]; then
    echo -e "${GREEN}┌────────────────────────────────────────┐${NC}"
    echo -e "${GREEN}│  ✓ CONFIGURACIÓN CORRECTA             │${NC}"
    echo -e "${GREEN}│  Todo listo para iniciar el servicio  │${NC}"
    echo -e "${GREEN}└────────────────────────────────────────┘${NC}"
    echo ""
    echo -e "${CYAN}Siguiente paso:${NC}"
    echo "  sudo systemctl start openai-inbound-calls"
    echo ""
    exit 0
elif [ $ERRORS -eq 0 ]; then
    echo -e "${YELLOW}┌────────────────────────────────────────┐${NC}"
    echo -e "${YELLOW}│  ⚠ CONFIGURACIÓN CON ADVERTENCIAS     │${NC}"
    echo -e "${YELLOW}│  Puedes continuar pero revisa warnings │${NC}"
    echo -e "${YELLOW}└────────────────────────────────────────┘${NC}"
    echo ""
    exit 0
else
    echo -e "${RED}┌────────────────────────────────────────┐${NC}"
    echo -e "${RED}│  ✗ ERRORES EN CONFIGURACIÓN           │${NC}"
    echo -e "${RED}│  Corrige los errores antes de iniciar │${NC}"
    echo -e "${RED}└────────────────────────────────────────┘${NC}"
    echo ""
    echo -e "${CYAN}Pasos para corregir:${NC}"
    echo "  1. Edita el archivo .env:"
    echo "     nano /usr/local/asterisk/.env"
    echo ""
    echo "  2. Configura las variables marcadas como error"
    echo ""
    echo "  3. Ejecuta este script nuevamente:"
    echo "     ./check_config.sh"
    echo ""
    exit 1
fi
