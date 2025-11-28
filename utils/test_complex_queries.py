#!/usr/bin/env python3
"""
Script de Prueba: Consultas Complejas a MikroTik API
=====================================================

Simula consultas que involucran múltiples routers y toman más tiempo.
Útil para probar el comportamiento del asistente OpenAI durante operaciones largas.

Autor: Omar
Fecha: Nov 2025
"""

import os
import sys
import json
import time
import requests
from datetime import datetime

# Configuración
MIKROTIK_API_URL = os.getenv("MIKROTIK_API_URL", "http://10.0.0.9:5050")

# Colores para output
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
    """Log con timestamp y color"""
    timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    print(f"{color}[{timestamp}] {message}{Colors.END}")

def test_query(description, endpoint, params=None, expected_duration=None):
    """
    Ejecuta una consulta y mide el tiempo de respuesta

    Args:
        description: Descripción de la consulta
        endpoint: Endpoint de la API
        params: Parámetros de la consulta (opcional)
        expected_duration: Duración esperada en segundos (opcional)
    """
    print(f"\n{Colors.BOLD}{'='*70}{Colors.END}")
    log(f"INICIANDO: {description}", Colors.HEADER)
    log(f"Endpoint: {endpoint}", Colors.BLUE)
    if params:
        log(f"Parámetros: {json.dumps(params, indent=2)}", Colors.BLUE)

    url = f"{MIKROTIK_API_URL}{endpoint}"

    try:
        start_time = time.time()
        log("Enviando request...", Colors.YELLOW)

        if params:
            response = requests.post(url, json=params, timeout=60)
        else:
            response = requests.get(url, timeout=60)

        duration = time.time() - start_time

        if response.status_code == 200:
            data = response.json()
            log(f"✓ ÉXITO en {duration:.2f}s", Colors.GREEN)

            # Mostrar resumen de la respuesta
            if isinstance(data, dict):
                if 'data' in data:
                    items = len(data['data']) if isinstance(data['data'], list) else 1
                    log(f"Datos recibidos: {items} items", Colors.GREEN)
                if 'routers_processed' in data:
                    log(f"Routers procesados: {data['routers_processed']}", Colors.GREEN)
                if 'total_time' in data:
                    log(f"Tiempo del servidor: {data['total_time']:.2f}s", Colors.GREEN)

            # Verificar duración esperada
            if expected_duration:
                if duration > expected_duration * 1.5:
                    log(f"⚠ ADVERTENCIA: Duración mayor a la esperada ({expected_duration}s)", Colors.YELLOW)
                elif duration < expected_duration * 0.5:
                    log(f"⚡ Más rápido de lo esperado!", Colors.CYAN)

            # Mostrar preview de datos
            log("Preview de respuesta:", Colors.CYAN)
            print(json.dumps(data, indent=2)[:500] + "..." if len(json.dumps(data)) > 500 else json.dumps(data, indent=2))

            return True, duration, data
        else:
            log(f"✗ ERROR: HTTP {response.status_code}", Colors.RED)
            log(f"Respuesta: {response.text}", Colors.RED)
            return False, duration, None

    except requests.Timeout:
        duration = time.time() - start_time
        log(f"✗ TIMEOUT después de {duration:.2f}s", Colors.RED)
        return False, duration, None
    except Exception as e:
        duration = time.time() - start_time
        log(f"✗ EXCEPCIÓN: {str(e)}", Colors.RED)
        return False, duration, None

def main():
    """Ejecuta suite de pruebas de consultas complejas"""

    print(f"\n{Colors.BOLD}{Colors.HEADER}")
    print("="*70)
    print("  SCRIPT DE PRUEBA: CONSULTAS COMPLEJAS A MIKROTIK API")
    print("="*70)
    print(f"{Colors.END}\n")

    log(f"API URL: {MIKROTIK_API_URL}", Colors.CYAN)
    log("Iniciando batería de pruebas...\n", Colors.CYAN)

    results = []

    # ==================================================================
    # PRUEBA 1: Consulta compleja - SFP de todos los routers
    # ==================================================================
    success, duration, data = test_query(
        description="Tráfico de interfaces SFP de TODOS los routers",
        endpoint="/routers/all/sfp/traffic",
        expected_duration=5.0  # Esperamos ~5 segundos
    )
    results.append(("SFP All Routers", success, duration))

    time.sleep(2)  # Pausa entre pruebas

    # ==================================================================
    # PRUEBA 2: Consulta compleja - Estado de todos los routers
    # ==================================================================
    success, duration, data = test_query(
        description="Estado general de TODOS los routers",
        endpoint="/routers/all/status",
        expected_duration=4.0
    )
    results.append(("Status All Routers", success, duration))

    time.sleep(2)

    # ==================================================================
    # PRUEBA 3: Consulta compleja - Dispositivos activos de múltiples routers
    # ==================================================================
    success, duration, data = test_query(
        description="Dispositivos activos de múltiples routers específicos",
        endpoint="/routers/multiple/active-devices",
        params={
            "router_ids": ["152.1", "152.2", "152.3", "152.4", "152.5"]
        },
        expected_duration=6.0
    )
    results.append(("Active Devices Multiple", success, duration))

    time.sleep(2)

    # ==================================================================
    # PRUEBA 4: Consulta media - SFP de un solo router
    # ==================================================================
    success, duration, data = test_query(
        description="Tráfico SFP de router específico (152.1)",
        endpoint="/router/152.1/sfp/traffic",
        expected_duration=1.5
    )
    results.append(("SFP Single Router", success, duration))

    time.sleep(2)

    # ==================================================================
    # PRUEBA 5: Consulta simple - Dispositivos activos de un router
    # ==================================================================
    success, duration, data = test_query(
        description="Dispositivos activos del router 152.1",
        endpoint="/router/152.1/active-devices",
        expected_duration=1.0
    )
    results.append(("Active Devices Single", success, duration))

    time.sleep(2)

    # ==================================================================
    # PRUEBA 6: Consulta muy compleja - Análisis completo de red
    # ==================================================================
    success, duration, data = test_query(
        description="Análisis completo de red (todos los routers + métricas)",
        endpoint="/network/full-analysis",
        expected_duration=10.0
    )
    results.append(("Full Network Analysis", success, duration))

    # ==================================================================
    # RESUMEN DE RESULTADOS
    # ==================================================================
    print(f"\n\n{Colors.BOLD}{Colors.HEADER}")
    print("="*70)
    print("  RESUMEN DE PRUEBAS")
    print("="*70)
    print(f"{Colors.END}\n")

    total_tests = len(results)
    passed = sum(1 for _, success, _ in results if success)
    failed = total_tests - passed

    print(f"{Colors.BOLD}Pruebas ejecutadas: {total_tests}{Colors.END}")
    print(f"{Colors.GREEN}Exitosas: {passed}{Colors.END}")
    print(f"{Colors.RED}Fallidas: {failed}{Colors.END}\n")

    print(f"{Colors.BOLD}Detalle por prueba:{Colors.END}\n")
    for name, success, duration in results:
        status = f"{Colors.GREEN}✓ PASS" if success else f"{Colors.RED}✗ FAIL"
        print(f"  {status}{Colors.END} | {name:30s} | {duration:6.2f}s")

    # Estadísticas de tiempos
    durations = [d for _, s, d in results if s]
    if durations:
        avg_duration = sum(durations) / len(durations)
        max_duration = max(durations)
        min_duration = min(durations)

        print(f"\n{Colors.BOLD}Estadísticas de tiempo:{Colors.END}")
        print(f"  Promedio: {avg_duration:.2f}s")
        print(f"  Mínimo:   {min_duration:.2f}s")
        print(f"  Máximo:   {max_duration:.2f}s")

    print(f"\n{Colors.BOLD}{'='*70}{Colors.END}\n")

    # Retornar código de salida
    sys.exit(0 if failed == 0 else 1)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n\n{Colors.YELLOW}Pruebas interrumpidas por el usuario{Colors.END}\n")
        sys.exit(130)
