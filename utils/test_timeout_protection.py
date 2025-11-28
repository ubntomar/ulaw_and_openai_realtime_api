#!/usr/bin/env python3
"""
Script de prueba para verificar protección contra timeouts
Simula diferentes escenarios de error para validar que el sistema maneja correctamente
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.mikrotik_api_client import MikroTikAPIClient
import logging
import time

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

def print_separator(title):
    """Imprime un separador visual"""
    print("\n" + "="*70)
    print(f"  {title}")
    print("="*70 + "\n")

def test_normal_query():
    """Test 1: Consulta normal (debería funcionar si la API está disponible)"""
    print_separator("TEST 1: Consulta Normal")

    client = MikroTikAPIClient()

    print("Pregunta: ¿Qué routers están configurados?")
    print("Timeout: 15 segundos")
    print("\nEnviando consulta...")

    start = time.time()
    result = client.query("¿Qué routers están configurados?", timeout=15)
    elapsed = time.time() - start

    print(f"\n⏱️  Tiempo de respuesta: {elapsed:.2f}s")
    print(f"✅ Success: {result['success']}")
    print(f"📝 Response: {result['response']}")

    if result['success']:
        print("\n✅ TEST PASADO - La API respondió correctamente")
    else:
        print(f"\n⚠️  TEST INFORMATIVO - La API devolvió error: {result.get('response')}")

    return result

def test_timeout_scenario():
    """Test 2: Consulta con timeout muy corto (debería fallar por timeout)"""
    print_separator("TEST 2: Simulación de Timeout")

    client = MikroTikAPIClient()

    # Configurar un timeout muy corto para forzar timeout
    print("Pregunta: ¿Cuántos clientes activos hay en todos los routers?")
    print("Timeout: 1 segundo (INTENCIONALMENTE CORTO)")
    print("\nEnviando consulta...")

    start = time.time()
    result = client.query(
        "¿Dame información detallada de todos los clientes activos en todos los routers con estadísticas completas?",
        timeout=1  # Timeout muy corto para forzar error
    )
    elapsed = time.time() - start

    print(f"\n⏱️  Tiempo de respuesta: {elapsed:.2f}s")
    print(f"❌ Success: {result['success']}")
    print(f"📝 Response: {result['response']}")

    # Verificar que el mensaje contiene palabras clave de timeout
    timeout_keywords = ['tardó', 'tiempo', 'timeout', 'simple']
    has_timeout_message = any(keyword in result['response'].lower() for keyword in timeout_keywords)

    if not result['success'] and has_timeout_message:
        print("\n✅ TEST PASADO - El sistema manejó correctamente el timeout")
        print("   El usuario recibiría un mensaje amigable en lugar de silencio")
    else:
        print("\n⚠️  TEST ADVERTENCIA - La respuesta no parece ser de timeout")
        print("   Esto podría significar que la API respondió muy rápido")

    return result

def test_connection_error():
    """Test 3: Error de conexión (API no disponible)"""
    print_separator("TEST 3: Simulación de Error de Conexión")

    # Crear cliente con URL inválida
    client = MikroTikAPIClient(api_url="http://192.168.255.255:9999")

    print("API URL: http://192.168.255.255:9999 (INTENCIONALMENTE INVÁLIDA)")
    print("Pregunta: ¿Cuántos clientes están conectados?")
    print("\nEnviando consulta...")

    start = time.time()
    result = client.query("¿Cuántos clientes están conectados?", timeout=5)
    elapsed = time.time() - start

    print(f"\n⏱️  Tiempo de respuesta: {elapsed:.2f}s")
    print(f"❌ Success: {result['success']}")
    print(f"📝 Response: {result['response']}")

    # Verificar que el mensaje contiene palabras clave de conexión
    connection_keywords = ['conectar', 'servidor', 'disponible', 'conexión']
    has_connection_message = any(keyword in result['response'].lower() for keyword in connection_keywords)

    if not result['success'] and has_connection_message:
        print("\n✅ TEST PASADO - El sistema manejó correctamente el error de conexión")
        print("   El usuario recibiría un mensaje amigable en lugar de freeze")
    else:
        print("\n❌ TEST FALLIDO - La respuesta no parece ser de error de conexión")

    return result

def test_invalid_question():
    """Test 4: Pregunta inválida (muy corta)"""
    print_separator("TEST 4: Validación de Pregunta Inválida")

    client = MikroTikAPIClient()

    print("Pregunta: 'ho' (DEMASIADO CORTA)")
    print("\nEnviando consulta...")

    start = time.time()
    result = client.query("ho", timeout=15)
    elapsed = time.time() - start

    print(f"\n⏱️  Tiempo de respuesta: {elapsed:.2f}s")
    print(f"❌ Success: {result['success']}")
    print(f"📝 Response: {result['response']}")

    if not result['success'] and 'corta' in result['response'].lower():
        print("\n✅ TEST PASADO - El sistema validó correctamente la pregunta")
    else:
        print("\n❌ TEST FALLIDO - La validación no funcionó como esperado")

    return result

def test_health_check():
    """Test 5: Health check de la API"""
    print_separator("TEST 5: Health Check")

    client = MikroTikAPIClient()

    print("Verificando estado de la API...")

    start = time.time()
    is_healthy = client.check_health()
    elapsed = time.time() - start

    print(f"\n⏱️  Tiempo de respuesta: {elapsed:.2f}s")
    print(f"{'✅' if is_healthy else '❌'} API Status: {'DISPONIBLE' if is_healthy else 'NO DISPONIBLE'}")

    if is_healthy:
        print("\n✅ TEST PASADO - La API está disponible")
    else:
        print("\n⚠️  TEST INFORMATIVO - La API no está disponible")
        print("   (Esto es normal si la API MikroTik no está corriendo)")

    return is_healthy

def main():
    """Ejecuta todos los tests"""
    print("\n")
    print("╔════════════════════════════════════════════════════════════════════╗")
    print("║                                                                    ║")
    print("║    TEST DE PROTECCIÓN CONTRA TIMEOUTS Y ERRORES                   ║")
    print("║    Sistema de Telefonía con OpenAI Realtime API                   ║")
    print("║                                                                    ║")
    print("╚════════════════════════════════════════════════════════════════════╝")

    results = {
        'passed': 0,
        'failed': 0,
        'warnings': 0
    }

    # Test 5 primero para verificar disponibilidad
    is_healthy = test_health_check()

    # Test 1: Consulta normal
    try:
        result1 = test_normal_query()
        if result1['success']:
            results['passed'] += 1
        else:
            results['warnings'] += 1
    except Exception as e:
        print(f"\n❌ ERROR EN TEST 1: {e}")
        results['failed'] += 1

    # Test 2: Timeout
    try:
        result2 = test_timeout_scenario()
        if not result2['success']:
            results['passed'] += 1
        else:
            results['warnings'] += 1
    except Exception as e:
        print(f"\n❌ ERROR EN TEST 2: {e}")
        results['failed'] += 1

    # Test 3: Error de conexión
    try:
        result3 = test_connection_error()
        if not result3['success']:
            results['passed'] += 1
        else:
            results['failed'] += 1
    except Exception as e:
        print(f"\n❌ ERROR EN TEST 3: {e}")
        results['failed'] += 1

    # Test 4: Pregunta inválida
    try:
        result4 = test_invalid_question()
        if not result4['success']:
            results['passed'] += 1
        else:
            results['failed'] += 1
    except Exception as e:
        print(f"\n❌ ERROR EN TEST 4: {e}")
        results['failed'] += 1

    # Resumen final
    print_separator("RESUMEN DE TESTS")

    total_tests = results['passed'] + results['failed'] + results['warnings']

    print(f"Tests ejecutados: {total_tests}")
    print(f"✅ Pasados: {results['passed']}")
    print(f"❌ Fallidos: {results['failed']}")
    print(f"⚠️  Advertencias: {results['warnings']}")

    print("\n" + "─"*70)

    if results['failed'] == 0:
        print("\n🎉 ¡EXCELENTE! Todos los tests críticos pasaron")
        print("   Tu sistema está protegido contra freezes y timeouts")
    else:
        print("\n⚠️  ATENCIÓN: Algunos tests fallaron")
        print("   Revisa los resultados arriba para más detalles")

    print("\n" + "─"*70)
    print("\n💡 IMPORTANTE:")
    print("   - Estos tests verifican el manejo de errores en el cliente")
    print("   - Si la API MikroTik no está disponible, algunos tests mostrarán warnings")
    print("   - Lo crítico es que NINGÚN test deje el sistema en freeze")
    print("   - Todos los errores deben devolver mensajes amigables al usuario")

    print("\n📋 Para probar en llamada real:")
    print("   1. Reinicia el servicio: sudo systemctl restart asterisk-openai")
    print("   2. Llama al sistema")
    print("   3. Pregunta: '¿Cuántos clientes están conectados?'")
    print("   4. Observa que SIEMPRE hay una respuesta (éxito o error amigable)")

    print("\n")

if __name__ == "__main__":
    main()
