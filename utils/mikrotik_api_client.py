#!/usr/bin/env python3
"""
Cliente para consultar la API de MikroTik
Diseñado para ser usado por OpenAI Realtime API Function Calling
"""

import requests
import logging
from typing import Dict, Any, Optional

class MikroTikAPIClient:
    """Cliente para interactuar con la API REST de MikroTik"""

    def __init__(self, api_url: str = "http://10.0.0.9:5050"):
        """
        Inicializa el cliente de API MikroTik

        Args:
            api_url: URL base de la API (default: http://10.0.0.9:5050)
        """
        self.api_url = api_url
        self.query_endpoint = f"{api_url}/query"
        self.health_endpoint = f"{api_url}/health"

        # Timeout configurado para telefonía (60 segundos para la API + 10 de margen)
        self.default_timeout = 60
        self.request_timeout = 70  # timeout del request HTTP (debe ser mayor que default_timeout)

    def check_health(self) -> bool:
        """
        Verifica que la API esté funcionando

        Returns:
            bool: True si la API responde correctamente
        """
        try:
            response = requests.get(
                self.health_endpoint,
                timeout=5
            )

            if response.status_code == 200:
                data = response.json()
                logging.info(f"API MikroTik: {data.get('status', 'unknown')}")
                return True
            else:
                logging.error(f"API MikroTik health check failed: {response.status_code}")
                return False

        except requests.Timeout:
            logging.error("API MikroTik health check timeout")
            return False
        except Exception as e:
            logging.error(f"Error en health check de API MikroTik: {e}")
            return False

    def query(self, question: str, timeout: Optional[int] = None) -> Dict[str, Any]:
        """
        Hace una consulta a la API de MikroTik

        Args:
            question: Pregunta en lenguaje natural
            timeout: Timeout en segundos (default: 60)

        Returns:
            Dict con la respuesta:
            {
                "success": bool,
                "response": str,  # Texto para reproducir por voz
                "metadata": dict  # Información adicional (opcional)
            }
        """
        if timeout is None:
            timeout = self.default_timeout

        try:
            # Validar longitud de la pregunta
            if len(question) > 500:
                return {
                    "success": False,
                    "response": "La pregunta es demasiado larga. Por favor, hazla más corta."
                }

            if len(question) < 3:
                return {
                    "success": False,
                    "response": "La pregunta es demasiado corta. Por favor, sé más específico."
                }

            logging.info(f"Consultando API MikroTik: '{question}' (timeout: {timeout}s)")

            # Hacer la petición POST
            response = requests.post(
                self.query_endpoint,
                json={
                    "question": question,
                    "timeout": timeout
                },
                timeout=self.request_timeout  # timeout del HTTP request
            )

            # Procesar respuesta
            if response.status_code == 200:
                data = response.json()

                # La API siempre devuelve el campo "response" con el texto a reproducir
                return {
                    "success": data.get("success", False),
                    "response": data.get("response", "No recibí respuesta del servidor."),
                    "metadata": data.get("metadata", {})
                }
            else:
                logging.error(f"API MikroTik error HTTP {response.status_code}")
                return {
                    "success": False,
                    "response": "Hubo un error al consultar el servidor. Por favor, intenta nuevamente."
                }

        except requests.Timeout:
            logging.error(f"Timeout al consultar API MikroTik después de {timeout}s: {question}")
            return {
                "success": False,
                "response": "La consulta tardó demasiado tiempo en responder. Por favor, intenta con una pregunta más simple o inténtalo nuevamente."
            }

        except requests.ConnectionError:
            logging.error("No se pudo conectar a la API MikroTik")
            return {
                "success": False,
                "response": "No pude conectarme al servidor de información. Por favor, intenta más tarde."
            }

        except Exception as e:
            logging.error(f"Error consultando API MikroTik: {e}")
            return {
                "success": False,
                "response": "Ocurrió un error al procesar tu consulta. Por favor, intenta nuevamente."
            }

    def get_tool_definition(self) -> Dict[str, Any]:
        """
        Devuelve la definición de la herramienta (tool) para OpenAI Realtime API

        Returns:
            Dict con la definición del tool en formato OpenAI
        """
        return {
            "type": "function",
            "name": "consultar_mikrotik",
            "description": (
                "Consulta información sobre routers MikroTik, clientes activos, "
                "tráfico de red, interfaces, gateways y estado de la red. "
                "Usa esta función cuando el usuario pregunte sobre: "
                "clientes conectados, estado de routers, tráfico de red, "
                "interfaces libres, gateways activos, o cualquier información "
                "técnica de la infraestructura de red."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "pregunta": {
                        "type": "string",
                        "description": (
                            "La pregunta del usuario en lenguaje natural sobre la red MikroTik. "
                            "Ejemplos: '¿Cuántos clientes activos hay en router-146?', "
                            "'¿Qué routers están configurados?', "
                            "'¿Cuál es el tráfico de la interfaz WAN?'"
                        )
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "Tiempo máximo de espera en segundos (default: 60, rango: 15-90)",
                        "default": 60,
                        "minimum": 15,
                        "maximum": 90
                    }
                },
                "required": ["pregunta"]
            }
        }


# Función helper para ser llamada desde el handler de función de OpenAI
def execute_mikrotik_query(pregunta: str, timeout: int = 15) -> Dict[str, Any]:
    """
    Ejecuta una consulta a la API de MikroTik
    Función helper diseñada para ser llamada desde OpenAI function calling

    Args:
        pregunta: Pregunta en lenguaje natural
        timeout: Timeout en segundos (default: 15)

    Returns:
        Dict con la respuesta de la API
    """
    client = MikroTikAPIClient()
    return client.query(pregunta, timeout)


# Testing cuando se ejecuta directamente
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )

    print("=== Testing MikroTik API Client ===\n")

    client = MikroTikAPIClient()

    # Test 1: Health check
    print("1. Health Check:")
    is_healthy = client.check_health()
    print(f"   API Status: {'✓ OK' if is_healthy else '✗ Error'}\n")

    # Test 2: Query de ejemplo
    print("2. Query de ejemplo:")
    result = client.query("¿Qué routers están configurados?", timeout=15)
    print(f"   Success: {result['success']}")
    print(f"   Response: {result['response']}")
    if 'metadata' in result:
        print(f"   Metadata: {result['metadata']}\n")

    # Test 3: Mostrar definición del tool
    print("3. Definición del tool para OpenAI:")
    tool_def = client.get_tool_definition()
    import json
    print(json.dumps(tool_def, indent=2, ensure_ascii=False))
