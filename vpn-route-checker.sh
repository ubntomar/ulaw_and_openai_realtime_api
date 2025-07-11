#!/bin/bash
# Script para asegurar que las rutas VPN están presentes

LOG_FILE="/var/log/vpn-route-checker.log"
DATE_FORMAT="+%Y-%m-%d %H:%M:%S"

# Redirigir toda la salida a nuestro archivo de log
exec >> "$LOG_FILE" 2>&1

echo "$(date "$DATE_FORMAT"): Starting VPN route check."

# Function to add a route if the peer is active and the route doesn't exist
add_vpn_route() {
    local PEER_IP="$1"
    local NETWORK="$2"
    local DESCRIPTION="$3"

    echo "$(date "$DATE_FORMAT"): Checking for peer $PEER_IP for network $NETWORK ($DESCRIPTION)."

    # Check if the peer IP is currently active via a ppp interface
    # This uses `ip -o a` for stable output and greps for the peer IP.
    if ip -o a show | grep -q "inet 192\.168\.164\.1 peer $PEER_IP\/32"; then
        echo "$(date "$DATE_FORMAT"): Peer $PEER_IP is active."

        # Check if the route already exists
        if ip r show | grep -q "$NETWORK via $PEER_IP"; then
            echo "$(date "$DATE_FORMAT"): Route $NETWORK via $PEER_IP already exists. Skipping."
        else
            echo "$(date "$DATE_FORMAT"): Route $NETWORK via $PEER_IP not found. Adding now..."
            ip r add "$NETWORK" via "$PEER_IP"
            if [ $? -eq 0 ]; then
                echo "$(date "$DATE_FORMAT"): Successfully added route $NETWORK via $PEER_IP."
            else
                echo "$(date "$DATE_FORMAT"): ERROR: Failed to add route $NETWORK via $PEER_IP."
                # Optionally, log more details on failure:
                # ip r add "$NETWORK" via "$PEER_IP" 2>&1 | tee -a "$LOG_FILE"
            fi
        fi
    else
        echo "$(date "$DATE_FORMAT"): Peer $PEER_IP is NOT active. Route $NETWORK not added/checked."
    fi
    echo
}

# --- Define tus rutas y sus peers correspondientes ---
# Revisa tus IPs de peer y redes remotas
# Basado en tu última salida de 'ip a' y tus necesidades anteriores:
# 1. Red 192.168.4.0/24 via peer 192.168.164.2
# 2. Red 192.168.5.0/24 via peer 192.168.164.30
# 3. Red 192.168.85.0/24 via peer 192.168.164.10

add_vpn_route "192.168.164.2" "192.168.4.0/24" "Client 1 Network"
add_vpn_route "192.168.164.30" "192.168.5.0/24" "Client 2 Network"
add_vpn_route "192.168.164.10" "192.168.85.0/24" "Client 3 Network"

echo "$(date "$DATE_FORMAT"): VPN route check finished."
