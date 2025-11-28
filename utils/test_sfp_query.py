#!/usr/bin/env python3
"""
Script de debug para consultar tráfico de interfaces SFP
Muestra debug detallado del proceso completo
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.mikrotik_api_client import MikroTikAPIClient
import logging
import time
import json

# Configurar logging con más detalle
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s.%(msecs)03d - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

def print_header(title):
    """Imprime header visual"""
    print("\n" + "="*80)
    print(f"  {title}")
    print("="*80 + "\n")

def print_step(step_num, description):
    """Imprime paso del proceso"""
    print(f"\n{'─'*80}")
    print(f"📍 PASO {step_num}: {description}")
    print(f"{'─'*80}\n")

def test_sfp_query():
    """Consulta tráfico de interfaces SFP con debug completo"""

    print_header("DEBUG: Consulta de Tráfico de Interfaces SFP")

    # Paso 1: Inicializar cliente
    print_step(1, "Inicializando cliente MikroTik API")

    api_url = os.getenv('MIKROTIK_API_URL', 'http://10.0.0.9:5050')
    print(f"   API URL: {api_url}")

    client = MikroTikAPIClient(api_url=api_url)
    print(f"   ✓ Cliente inicializado")
    print(f"   - Default timeout: {client.default_timeout}s")
    print(f"   - Request timeout: {client.request_timeout}s")

    # Paso 2: Health check
    print_step(2, "Verificando salud de la API")

    health_start = time.time()
    is_healthy = client.check_health()
    health_elapsed = time.time() - health_start

    if is_healthy:
        print(f"   ✅ API disponible (respondió en {health_elapsed:.2f}s)")
    else:
        print(f"   ❌ API NO disponible")
        print(f"   ⚠️  Los siguientes tests pueden fallar")

    # Paso 3: Preparar consulta
    print_step(3, "Preparando consulta sobre interfaces SFP")

    pregunta = "dime el trafico de las interfaces sfp de todos los router"
    timeout = 60

    print(f"   Pregunta: '{pregunta}'")
    print(f"   Timeout configurado: {timeout} segundos")
    print(f"   HTTP timeout: {client.request_timeout} segundos")

    # Paso 4: Realizar consulta
    print_step(4, "Ejecutando consulta a la API")
    print(f"   ⏳ Esperando respuesta (máx {timeout}s)...\n")

    start_time = time.time()

    try:
        result = client.query(pregunta, timeout=timeout)
        elapsed_time = time.time() - start_time

        # Paso 5: Analizar respuesta
        print_step(5, "Analizando respuesta de la API")

        print(f"   ⏱️  Tiempo total de respuesta: {elapsed_time:.2f} segundos")
        print(f"   📊 Success: {result.get('success', False)}")
        print(f"\n   {'─'*76}")
        print(f"   📝 RESPUESTA COMPLETA:")
        print(f"   {'─'*76}\n")

        # Mostrar respuesta formateada
        response_text = result.get('response', 'Sin respuesta')

        # Dividir en líneas para mejor visualización
        lines = response_text.split('\n')
        for line in lines:
            print(f"   {line}")

        print(f"\n   {'─'*76}")

        # Metadata si existe
        if 'metadata' in result and result['metadata']:
            print(f"\n   📋 METADATA:")
            print(f"   {'─'*76}\n")
            for key, value in result['metadata'].items():
                print(f"   {key}: {value}")
            print(f"\n   {'─'*76}")

        # Paso 6: Validación de resultados
        print_step(6, "Validando calidad de la respuesta")

        # Verificar palabras clave esperadas
        keywords_check = {
            'interfaces': 'interfaces' in response_text.lower() or 'sfp' in response_text.lower(),
            'tráfico': 'tráfico' in response_text.lower() or 'trafico' in response_text.lower() or 'tx' in response_text.lower() or 'rx' in response_text.lower(),
            'routers': 'router' in response_text.lower(),
        }

        print(f"   Verificación de contenido:")
        for check, passed in keywords_check.items():
            status = "✅" if passed else "❌"
            print(f"   {status} Menciona {check}: {'Sí' if passed else 'No'}")

        # Longitud de respuesta
        response_length = len(response_text)
        print(f"\n   📏 Longitud de respuesta: {response_length} caracteres")

        if response_length < 50:
            print(f"   ⚠️  Respuesta muy corta, podría indicar un error")
        elif response_length < 200:
            print(f"   ℹ️  Respuesta normal")
        else:
            print(f"   ✅ Respuesta detallada")

        # Verificar si hay errores en la respuesta
        error_indicators = ['error', 'no pude', 'no se pudo', 'tardó demasiado', 'timeout']
        has_errors = any(indicator in response_text.lower() for indicator in error_indicators)

        if has_errors:
            print(f"\n   ⚠️  La respuesta contiene indicadores de error:")
            for indicator in error_indicators:
                if indicator in response_text.lower():
                    print(f"       - Encontrado: '{indicator}'")

        # Paso 7: Resumen final
        print_step(7, "Resumen de la prueba")

        if result.get('success') and not has_errors and all(keywords_check.values()):
            print(f"   ✅ PRUEBA EXITOSA")
            print(f"   - La API respondió correctamente")
            print(f"   - El tiempo de respuesta fue aceptable ({elapsed_time:.2f}s)")
            print(f"   - La respuesta contiene información relevante")
            print(f"\n   🎯 Esta consulta funcionará correctamente en una llamada telefónica")
            print(f"      El asistente dirá: 'Déjame consultar esa información'")
            print(f"      Luego esperará ~{elapsed_time:.0f} segundos")
            print(f"      Y responderá con la información de tráfico de SFP")

        elif result.get('success') and elapsed_time > 30:
            print(f"   ⚠️  ADVERTENCIA: Respuesta lenta")
            print(f"   - La API respondió en {elapsed_time:.2f}s (>30s)")
            print(f"   - En una llamada, el usuario esperará este tiempo")
            print(f"   - Considera optimizar la consulta en la API si es posible")

        elif not result.get('success'):
            print(f"   ❌ PRUEBA FALLIDA")
            print(f"   - La API reportó un error")
            print(f"   - En una llamada telefónica, el usuario escucharía:")
            print(f"     '{response_text}'")

        else:
            print(f"   ⚠️  RESULTADO PARCIAL")
            print(f"   - La API respondió pero puede haber problemas")
            print(f"   - Revisa la respuesta arriba para más detalles")

        return result

    except Exception as e:
        elapsed_time = time.time() - start_time

        print_step(5, "ERROR CAPTURADO")
        print(f"   ❌ Tipo de error: {type(e).__name__}")
        print(f"   ❌ Mensaje: {str(e)}")
        print(f"   ⏱️  Tiempo hasta el error: {elapsed_time:.2f}s")

        import traceback
        print(f"\n   📋 Traceback completo:")
        print(f"   {'─'*76}")
        traceback.print_exc()
        print(f"   {'─'*76}")

        print_step(6, "Análisis del error")

        if 'timeout' in str(e).lower():
            print(f"   ⚠️  Error de TIMEOUT")
            print(f"   - La API tardó más de {timeout}s en responder")
            print(f"   - En una llamada, el usuario escucharía:")
            print(f"     'La consulta tardó demasiado tiempo en responder...'")
        elif 'connection' in str(e).lower():
            print(f"   ⚠️  Error de CONEXIÓN")
            print(f"   - No se pudo conectar a la API")
            print(f"   - En una llamada, el usuario escucharía:")
            print(f"     'No pude conectarme al servidor de información...'")
        else:
            print(f"   ⚠️  Error INESPERADO")
            print(f"   - Este tipo de error debería estar manejado")
            print(f"   - En una llamada, el usuario escucharía:")
            print(f"     'Ocurrió un error al procesar tu consulta...'")

        return None

def main():
    """Ejecuta el test con debug completo"""

    print("\n")
    print("╔════════════════════════════════════════════════════════════════════════════╗")
    print("║                                                                            ║")
    print("║    DEBUG: CONSULTA DE TRÁFICO DE INTERFACES SFP                           ║")
    print("║    Test detallado de consulta compleja a API MikroTik                     ║")
    print("║                                                                            ║")
    print("╚════════════════════════════════════════════════════════════════════════════╝")

    result = test_sfp_query()

    print("\n" + "="*80)
    print("  FIN DEL DEBUG")
    print("="*80 + "\n")

    if result and result.get('success'):
        print("✅ La consulta funcionó correctamente")
        print("\n💡 TIP: Esta es exactamente la información que el asistente telefónico")
        print("   leerá al usuario cuando haga esta pregunta en una llamada.\n")
        return 0
    else:
        print("⚠️  La consulta tuvo problemas")
        print("\n💡 TIP: Revisa el debug arriba para identificar el problema.")
        print("   El sistema NUNCA se quedará congelado, siempre habrá una respuesta.\n")
        return 1

if __name__ == "__main__":
    sys.exit(main())
