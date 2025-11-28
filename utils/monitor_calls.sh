#!/bin/bash
# Script para monitorear llamadas en tiempo real

echo "=== Monitor de Llamadas OpenAI + MikroTik ==="
echo "Presiona Ctrl+C para salir"
echo ""

# Función para mostrar canales activos
show_channels() {
    CHANNELS=$(sudo asterisk -rx "core show channels" | grep -E "active channel|active call")
    echo -e "\n📞 Canales Asterisk: $CHANNELS"
}

# Función para limpiar canales atascados
cleanup_channels() {
    echo -e "\n🧹 Limpiando canales atascados..."
    sudo asterisk -rx "channel request hangup all"
}

# Trap para limpiar al salir
trap cleanup_channels EXIT

# Loop principal
while true; do
    clear
    echo "=== Monitor de Llamadas - $(date '+%H:%M:%S') ==="
    echo ""

    # Mostrar canales
    show_channels

    # Mostrar últimos logs relevantes
    echo -e "\n📊 Últimos eventos:"
    sudo journalctl -u openai-inbound-calls --since "30 seconds ago" -n 10 --no-pager | \
        grep --color=never -E "Function|🔧|⚙️|📤|Resultado|success|ERROR|StasisEnd|Canal.*cerrado" | \
        tail -8

    echo -e "\n⏱️  Esperando eventos... (actualiza cada 5s)"
    sleep 5
done
