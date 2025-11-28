#!/usr/bin/env python3
"""
Script de pruebas para la integración de MikroTik API con OpenAI Realtime

Este script permite probar:
1. Conectividad con la API de MikroTik
2. Diferentes tipos de consultas
3. Manejo de timeouts
4. Manejo de errores
"""

import sys
import os
import time
import json

# Agregar el path de utils al sys.path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from mikrotik_api_client import MikroTikAPIClient


def print_separator(title=""):
    """Imprime un separador visual"""
    print("\n" + "=" * 80)
    if title:
        print(f"  {title}")
        print("=" * 80)
    print()


def test_health_check(client):
    """Test 1: Health Check"""
    print_separator("TEST 1: Health Check de la API")

    print("Verificando que la API esté disponible...")
    is_healthy = client.check_health()

    if is_healthy:
        print("✓ API MikroTik está funcionando correctamente")
        return True
    else:
        print("✗ API MikroTik NO está disponible")
        print("  Verifica que el servidor esté corriendo en", client.api_url)
        return False


def test_basic_queries(client):
    """Test 2: Consultas básicas"""
    print_separator("TEST 2: Consultas Básicas")

    queries = [
        "¿Qué routers están configurados?",
        "¿Cuántos clientes activos hay?",
        "¿Cuál es el estado de la red?"
    ]

    results = []

    for i, query in enumerate(queries, 1):
        print(f"\n{i}. Consulta: '{query}'")
        print("-" * 80)

        start_time = time.time()
        result = client.query(query, timeout=15)
        elapsed_time = time.time() - start_time

        print(f"   Success: {result['success']}")
        print(f"   Time: {elapsed_time:.2f}s")
        print(f"   Response: {result['response'][:200]}...")  # Primeros 200 chars

        if 'metadata' in result and result['metadata']:
            print(f"   Metadata: {json.dumps(result['metadata'], indent=6, ensure_ascii=False)}")

        results.append({
            'query': query,
            'success': result['success'],
            'time': elapsed_time
        })

        # Pausa entre consultas
        time.sleep(1)

    # Resumen
    print("\n" + "-" * 80)
    successful = sum(1 for r in results if r['success'])
    print(f"Resumen: {successful}/{len(results)} consultas exitosas")

    return results


def test_specific_router_query(client):
    """Test 3: Consulta específica de router"""
    print_separator("TEST 3: Consulta Específica de Router")

    query = "¿Cuántos clientes activos hay en router-146?"
    print(f"Consulta: '{query}'")
    print("-" * 80)

    result = client.query(query, timeout=15)

    print(f"Success: {result['success']}")
    print(f"Response:\n{result['response']}")

    if 'metadata' in result:
        print(f"\nMetadata:")
        print(json.dumps(result['metadata'], indent=2, ensure_ascii=False))

    return result['success']


def test_traffic_query(client):
    """Test 4: Consulta de tráfico"""
    print_separator("TEST 4: Consulta de Tráfico de Red")

    query = "¿Cuál es el tráfico de la interfaz WAN?"
    print(f"Consulta: '{query}'")
    print("-" * 80)

    result = client.query(query, timeout=15)

    print(f"Success: {result['success']}")
    print(f"Response:\n{result['response']}")

    return result['success']


def test_timeout_handling(client):
    """Test 5: Manejo de timeouts"""
    print_separator("TEST 5: Manejo de Timeouts")

    print("Probando con timeout muy corto (5 segundos)...")
    query = "¿Cuál es el estado completo de todos los routers?"

    result = client.query(query, timeout=5)

    print(f"Success: {result['success']}")
    print(f"Response: {result['response']}")

    if not result['success'] and 'timeout' in result['response'].lower():
        print("✓ Timeout manejado correctamente")
        return True
    elif result['success']:
        print("✓ Consulta completada dentro del timeout")
        return True
    else:
        print("✗ Error inesperado en timeout")
        return False


def test_error_handling(client):
    """Test 6: Manejo de errores"""
    print_separator("TEST 6: Manejo de Errores")

    test_cases = [
        ("Pregunta muy corta", "Hi", "La pregunta es demasiado corta"),
        ("Pregunta muy larga", "a" * 600, "La pregunta es demasiado larga"),
        ("Pregunta vacía", "", "La pregunta es demasiado corta"),
    ]

    passed = 0

    for name, query, expected_msg in test_cases:
        print(f"\nTest: {name}")
        print(f"Query: '{query[:50]}...' (len={len(query)})")

        result = client.query(query, timeout=10)

        print(f"Success: {result['success']}")
        print(f"Response: {result['response']}")

        if not result['success']:
            print("✓ Error manejado correctamente")
            passed += 1
        else:
            print("✗ Debería haber fallado")

    print(f"\nResumen: {passed}/{len(test_cases)} tests de error pasados")
    return passed == len(test_cases)


def test_tool_definition(client):
    """Test 7: Definición del tool para OpenAI"""
    print_separator("TEST 7: Definición del Tool para OpenAI")

    print("Obteniendo definición del tool...")
    tool_def = client.get_tool_definition()

    print("\nDefinición del tool:")
    print(json.dumps(tool_def, indent=2, ensure_ascii=False))

    # Validar campos requeridos
    required_fields = ['type', 'name', 'description', 'parameters']
    missing_fields = [field for field in required_fields if field not in tool_def]

    if not missing_fields:
        print("\n✓ Definición del tool es válida")
        return True
    else:
        print(f"\n✗ Faltan campos: {missing_fields}")
        return False


def test_concurrent_queries(client):
    """Test 8: Consultas concurrentes simuladas"""
    print_separator("TEST 8: Consultas Consecutivas (Simulando Conversación)")

    conversation = [
        "¿Qué routers tenemos?",
        "¿Cuántos clientes hay en total?",
        "¿Hay algún problema en la red?",
    ]

    print("Simulando conversación telefónica con 3 preguntas consecutivas...")
    print()

    results = []

    for i, query in enumerate(conversation, 1):
        print(f"Usuario: {query}")

        start_time = time.time()
        result = client.query(query, timeout=15)
        elapsed_time = time.time() - start_time

        print(f"Asistente ({elapsed_time:.1f}s): {result['response'][:150]}...")
        print()

        results.append(result['success'])

        # Pausa natural entre preguntas
        time.sleep(0.5)

    successful = sum(results)
    print(f"Resumen: {successful}/{len(conversation)} respuestas exitosas")

    return successful == len(conversation)


def run_all_tests():
    """Ejecuta todos los tests"""
    print("\n" + "╔" + "=" * 78 + "╗")
    print("║" + " " * 20 + "TEST SUITE: MikroTik API Integration" + " " * 22 + "║")
    print("╚" + "=" * 78 + "╝")

    # Configuración
    api_url = os.getenv('MIKROTIK_API_URL', 'http://10.0.0.9:5050')
    print(f"\nAPI URL: {api_url}")
    print("Iniciando tests...\n")

    # Crear cliente
    client = MikroTikAPIClient(api_url=api_url)

    # Ejecutar tests
    tests = [
        ("Health Check", test_health_check),
        ("Consultas Básicas", test_basic_queries),
        ("Consulta de Router Específico", test_specific_router_query),
        ("Consulta de Tráfico", test_traffic_query),
        ("Manejo de Timeouts", test_timeout_handling),
        ("Manejo de Errores", test_error_handling),
        ("Definición del Tool", test_tool_definition),
        ("Consultas Consecutivas", test_concurrent_queries),
    ]

    results = []

    # Test 1 es crítico
    if not test_health_check(client):
        print("\n" + "!" * 80)
        print("ERROR CRÍTICO: La API no está disponible.")
        print("Verifica que el servidor esté corriendo y la URL sea correcta.")
        print("!" * 80)
        return

    # Ejecutar resto de tests
    for name, test_func in tests[1:]:
        try:
            result = test_func(client)
            results.append((name, result))
        except Exception as e:
            print(f"\n✗ Error en test '{name}': {e}")
            results.append((name, False))

    # Resumen final
    print_separator("RESUMEN FINAL")

    passed = sum(1 for _, result in results if result)
    total = len(results)

    print(f"Tests pasados: {passed}/{total}\n")

    for name, result in results:
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"  {status:8} - {name}")

    print("\n" + "=" * 80)

    if passed == total:
        print("\n🎉 ¡Todos los tests pasaron! La integración está funcionando correctamente.")
    else:
        print(f"\n⚠️  {total - passed} test(s) fallaron. Revisa los logs arriba.")

    print("\n" + "=" * 80 + "\n")


if __name__ == "__main__":
    run_all_tests()
