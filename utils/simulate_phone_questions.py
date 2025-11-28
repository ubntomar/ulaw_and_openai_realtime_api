#!/usr/bin/env python3
"""
Simulador de Preguntas Telefónicas
===================================

Simula las preguntas que un usuario haría por teléfono al asistente OpenAI.
Envía directamente function calls a la API de MikroTik para medir tiempos
y comportamiento.

Casos de prueba:
1. Consulta simple: "Dame la lista de dispositivos activos del router 152.1"
2. Consulta media: "Dame el tráfico de las interfaces SFP del router 152.1"
3. Consulta compleja: "Dame el tráfico de las interfaces SFP de todos los routers"
4. Consulta muy compleja: "Dame un reporte completo de la red"

Autor: Omar
Fecha: Nov 2025
"""

import os
import sys
import time
import json
import requests
from datetime import datetime
from mikrotik_api_client import MikroTikAPIClient

# Colores
class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    END = '\033[0m'
    BOLD = '\033[1m'

def log(message, color=Colors.CYAN):
    """Log con timestamp"""
    timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    print(f"{color}[{timestamp}] {message}{Colors.END}")

def print_banner():
    """Banner del script"""
    print(f"\n{Colors.BOLD}{Colors.HEADER}")
    print("="*80)
    print("  SIMULADOR DE PREGUNTAS TELEFÓNICAS - OPENAI + MIKROTIK")
    print("="*80)
    print(f"{Colors.END}\n")

def test_question(number, question, function_name, params, expected_time=None):
    """
    Simula una pregunta telefónica

    Args:
        number: Número de la pregunta
        question: Pregunta en lenguaje natural
        function_name: Nombre de la función a ejecutar
        params: Parámetros de la función
        expected_time: Tiempo esperado en segundos
    """
    print(f"\n{Colors.BOLD}{Colors.BLUE}")
    print("─" * 80)
    print(f"PREGUNTA #{number}")
    print("─" * 80)
    print(f"{Colors.END}")

    log(f"Usuario pregunta: \"{question}\"", Colors.CYAN)
    log(f"OpenAI llama función: {function_name}", Colors.MAGENTA)
    log(f"Parámetros: {json.dumps(params)}", Colors.BLUE)

    # Inicializar cliente
    api_url = os.getenv("MIKROTIK_API_URL", "http://10.0.0.9:5050")
    client = MikroTikAPIClient(api_url)

    try:
        start_time = time.time()
        log("⏱ Iniciando consulta...", Colors.YELLOW)

        # Ejecutar función según el tipo
        if function_name == "query_router_sfp_traffic":
            result = client.query_router_sfp_traffic(params.get("router_id"))
        elif function_name == "query_router_active_devices":
            result = client.query_router_active_devices(params.get("router_id"))
        elif function_name == "query_all_routers_sfp":
            result = client.query_all_routers_sfp_traffic()
        elif function_name == "query_network_summary":
            result = client.query_network_summary()
        else:
            log(f"Función desconocida: {function_name}", Colors.RED)
            return False

        duration = time.time() - start_time

        if result and result.get("success"):
            log(f"✓ Consulta exitosa en {duration:.2f}s", Colors.GREEN)

            # Analizar resultado
            if "data" in result:
                data_size = len(json.dumps(result["data"]))
                items_count = len(result["data"]) if isinstance(result["data"], list) else 1
                log(f"Datos recibidos: {items_count} items ({data_size} bytes)", Colors.GREEN)

            # Comparar con tiempo esperado
            if expected_time:
                if duration > expected_time * 1.5:
                    log(f"⚠ MÁS LENTO de lo esperado (esperado: {expected_time}s)", Colors.YELLOW)
                    log(f"Diferencia: +{duration - expected_time:.2f}s", Colors.YELLOW)
                elif duration < expected_time * 0.7:
                    log(f"⚡ MÁS RÁPIDO de lo esperado (esperado: {expected_time}s)", Colors.CYAN)
                else:
                    log(f"✓ Tiempo dentro de lo esperado ({expected_time}s ±30%)", Colors.GREEN)

            # Simular respuesta del asistente
            log("🎤 Asistente responde:", Colors.HEADER)
            print(f"{Colors.GREEN}   \"He consultado la información solicitada.\"")
            if items_count:
                print(f"   \"Encontré {items_count} resultado(s).\"")
            print(f"   \"La consulta tomó aproximadamente {int(duration)} segundos.\"{Colors.END}")

            return True, duration

        else:
            duration = time.time() - start_time
            error_msg = result.get("error", "Error desconocido") if result else "Sin respuesta"
            log(f"✗ Error en {duration:.2f}s: {error_msg}", Colors.RED)
            log("🎤 Asistente responde:", Colors.HEADER)
            print(f"{Colors.RED}   \"Lo siento, hubo un error al consultar la información.\"")
            print(f"   \"Error: {error_msg}\"{Colors.END}")
            return False, duration

    except Exception as e:
        duration = time.time() - start_time
        log(f"✗ Excepción en {duration:.2f}s: {str(e)}", Colors.RED)
        log("🎤 Asistente responde:", Colors.HEADER)
        print(f"{Colors.RED}   \"Ocurrió un problema técnico: {str(e)}\"{Colors.END}")
        return False, duration

def main():
    """Ejecuta simulación de llamada telefónica"""
    print_banner()

    log("Simulando una llamada telefónica con diferentes tipos de preguntas...", Colors.CYAN)
    print()

    results = []

    # ========================================================================
    # PREGUNTA 1: Simple - Dispositivos activos de un router
    # ========================================================================
    success, duration = test_question(
        number=1,
        question="Dame la lista de dispositivos activos del router 152.1",
        function_name="query_router_active_devices",
        params={"router_id": "152.1"},
        expected_time=1.5
    )
    results.append(("Dispositivos activos (1 router)", success, duration))

    input(f"\n{Colors.YELLOW}Presiona ENTER para continuar con la siguiente pregunta...{Colors.END}\n")

    # ========================================================================
    # PREGUNTA 2: Media - SFP de un router específico
    # ========================================================================
    success, duration = test_question(
        number=2,
        question="Dame el tráfico de las interfaces SFP del router 152.1",
        function_name="query_router_sfp_traffic",
        params={"router_id": "152.1"},
        expected_time=2.0
    )
    results.append(("Tráfico SFP (1 router)", success, duration))

    input(f"\n{Colors.YELLOW}Presiona ENTER para continuar con la siguiente pregunta...{Colors.END}\n")

    # ========================================================================
    # PREGUNTA 3: Compleja - SFP de todos los routers
    # ========================================================================
    success, duration = test_question(
        number=3,
        question="Dame el tráfico de las interfaces SFP de todos los routers",
        function_name="query_all_routers_sfp",
        params={},
        expected_time=5.0
    )
    results.append(("Tráfico SFP (todos los routers)", success, duration))

    input(f"\n{Colors.YELLOW}Presiona ENTER para continuar con la siguiente pregunta...{Colors.END}\n")

    # ========================================================================
    # PREGUNTA 4: Muy compleja - Resumen completo de red
    # ========================================================================
    success, duration = test_question(
        number=4,
        question="Dame un resumen completo del estado de la red",
        function_name="query_network_summary",
        params={},
        expected_time=8.0
    )
    results.append(("Resumen completo de red", success, duration))

    # ========================================================================
    # RESUMEN
    # ========================================================================
    print(f"\n\n{Colors.BOLD}{Colors.HEADER}")
    print("="*80)
    print("  RESUMEN DE LA SIMULACIÓN")
    print("="*80)
    print(f"{Colors.END}\n")

    total = len(results)
    passed = sum(1 for _, s, _ in results if s)
    failed = total - passed
    total_time = sum(d for _, _, d in results)

    print(f"{Colors.BOLD}Total de preguntas: {total}{Colors.END}")
    print(f"{Colors.GREEN}Exitosas: {passed}{Colors.END}")
    print(f"{Colors.RED}Fallidas: {failed}{Colors.END}")
    print(f"{Colors.CYAN}Tiempo total: {total_time:.2f}s{Colors.END}\n")

    print(f"{Colors.BOLD}Detalle:{Colors.END}\n")
    for name, success, duration in results:
        status = f"{Colors.GREEN}✓" if success else f"{Colors.RED}✗"
        print(f"  {status} {name:35s} | {duration:6.2f}s{Colors.END}")

    # Análisis de experiencia de usuario
    print(f"\n{Colors.BOLD}Análisis de Experiencia de Usuario:{Colors.END}\n")

    if any(d > 10 for _, _, d in results):
        print(f"{Colors.RED}⚠ ALERTA: Hay consultas que toman más de 10 segundos{Colors.END}")
        print(f"{Colors.YELLOW}  Recomendación: Implementar mensajes intermedios durante consultas largas{Colors.END}")
    elif any(d > 5 for _, _, d in results):
        print(f"{Colors.YELLOW}⚠ ADVERTENCIA: Algunas consultas toman más de 5 segundos{Colors.END}")
        print(f"{Colors.CYAN}  Recomendación: Mantener informado al usuario durante el proceso{Colors.END}")
    else:
        print(f"{Colors.GREEN}✓ Todos los tiempos de respuesta son aceptables (<5s){Colors.END}")

    print(f"\n{Colors.BOLD}{'='*80}{Colors.END}\n")

    return 0 if failed == 0 else 1

if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print(f"\n\n{Colors.YELLOW}Simulación interrumpida{Colors.END}\n")
        sys.exit(130)
