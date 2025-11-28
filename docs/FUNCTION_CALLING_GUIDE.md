# 🔧 Guía de Function Calling con OpenAI Realtime API + MikroTik

Esta guía explica cómo integrar llamadas a funciones externas (function calling) en el sistema de llamadas entrantes, permitiendo que el asistente de voz consulte información en tiempo real de la API de MikroTik.

---

## 📋 Tabla de Contenidos

- [¿Qué es Function Calling?](#qué-es-function-calling)
- [Arquitectura de la Integración](#arquitectura-de-la-integración)
- [Instalación y Configuración](#instalación-y-configuración)
- [Uso en Producción](#uso-en-producción)
- [Testing](#testing)
- [Ejemplos de Conversaciones](#ejemplos-de-conversaciones)
- [Solución de Problemas](#solución-de-problemas)

---

## 🎯 ¿Qué es Function Calling?

**Function Calling** permite que el asistente de OpenAI llame a funciones externas durante una conversación telefónica para obtener información en tiempo real.

### Flujo de una conversación con function calling:

```
1. Usuario: "¿Cuántos clientes activos hay en router-146?"

2. OpenAI detecta que necesita información externa
   ↓
3. OpenAI llama a la función: consultar_mikrotik("¿Cuántos clientes activos hay en router-146?")
   ↓
4. Tu código ejecuta la consulta a la API de MikroTik
   ↓
5. API MikroTik responde: "En el router FIBRA OPTICA hay 221 clientes activos"
   ↓
6. Tu código envía el resultado de vuelta a OpenAI
   ↓
7. OpenAI genera una respuesta natural: "En el router Fibra Óptica hay 221 clientes activos en este momento"
   ↓
8. El usuario escucha la respuesta por teléfono
```

---

## 🏗️ Arquitectura de la Integración

```
┌─────────────────────────────────────────────────────────────────┐
│  Usuario llama por teléfono                                     │
└────────────────────┬────────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────────┐
│  Asterisk PBX                                                   │
│  - Recibe llamada al 3241000752                                 │
│  - Audio codec: G.711 ulaw                                      │
└────────────────────┬────────────────────────────────────────────┘
                     │ WebSocket ARI
                     ▼
┌─────────────────────────────────────────────────────────────────┐
│  handle_incoming_call.py (Python)                               │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  OpenAIClient                                            │  │
│  │  - Maneja conversación bidireccional                     │  │
│  │  - Detecta cuando OpenAI llama a una función             │  │
│  │  - Ejecuta la función                                    │  │
│  │  - Devuelve resultado a OpenAI                           │  │
│  └──────────────────────┬───────────────────────────────────┘  │
│                         │                                       │
│                         │ (cuando detecta function call)        │
│                         ▼                                       │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  MikroTikAPIClient                                       │  │
│  │  - Hace POST a http://192.168.1.100:5050/query          │  │
│  │  - Timeout: 15 segundos                                  │  │
│  │  - Retorna respuesta en texto                            │  │
│  └──────────────────────┬───────────────────────────────────┘  │
└─────────────────────────┼───────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│  API MikroTik (http://192.168.1.100:5050)                      │
│  - Endpoint: POST /query                                        │
│  - Procesa preguntas en lenguaje natural                        │
│  - Consulta routers MikroTik                                    │
│  - Retorna información en texto legible                         │
└─────────────────────────────────────────────────────────────────┘
```

---

## ⚙️ Instalación y Configuración

### Paso 1: Instalar Dependencias

```bash
cd /usr/local/asterisk

# Instalar requests si no está instalado
pip install requests
```

### Paso 2: Configurar Variables de Entorno

Edita tu archivo `.env`:

```bash
nano .env
```

Agrega estas variables:

```bash
# API de MikroTik
MIKROTIK_API_URL=http://192.168.1.100:5050
ENABLE_MIKROTIK_TOOLS=true

# Variables existentes (ya configuradas)
ASTERISK_USERNAME=Asterisk
ASTERISK_PASSWORD=tu_password
OPENAI_API_KEY=sk-proj-...
# ... resto de variables
```

### Paso 3: Verificar que la API de MikroTik esté funcionando

```bash
# Test simple
curl http://192.168.1.100:5050/health

# Debería responder:
# {"status":"ok","service":"MikroTik API","version":"1.0"}
```

### Paso 4: Probar la Integración

```bash
# Ejecutar suite de tests
cd /usr/local/asterisk
python3 utils/test_mikrotik_integration.py
```

**Salida esperada:**

```
╔══════════════════════════════════════════════════════════════════════════════╗
║                    TEST SUITE: MikroTik API Integration                      ║
╚══════════════════════════════════════════════════════════════════════════════╝

API URL: http://192.168.1.100:5050
Iniciando tests...

================================================================================
  TEST 1: Health Check de la API
================================================================================

Verificando que la API esté disponible...
✓ API MikroTik está funcionando correctamente

[... más tests ...]

RESUMEN FINAL
Tests pasados: 8/8

  ✓ PASS   - Consultas Básicas
  ✓ PASS   - Consulta de Router Específico
  ✓ PASS   - Consulta de Tráfico
  ✓ PASS   - Manejo de Timeouts
  ✓ PASS   - Manejo de Errores
  ✓ PASS   - Definición del Tool
  ✓ PASS   - Consultas Consecutivas

🎉 ¡Todos los tests pasaron! La integración está funcionando correctamente.
```

---

## 🚀 Uso en Producción

### Opción 1: Actualizar el Archivo Existente (Recomendado)

Copia los métodos de function calling al archivo original:

```bash
cd /usr/local/asterisk/inbound_calls

# Hacer backup del archivo original
cp handle_incoming_call.py handle_incoming_call.py.backup

# Copiar la versión con tools
cp handle_incoming_call_with_tools.py handle_incoming_call.py
```

**IMPORTANTE:** Luego debes copiar las clases `RTPAudioHandler`, `OpenAIHandler` y `AsteriskApp` del backup al nuevo archivo, ya que `handle_incoming_call_with_tools.py` solo contiene la clase `OpenAIClient` modificada.

### Opción 2: Agregar Function Calling Manualmente

Si prefieres agregar el código manualmente, sigue estos pasos:

#### 2.1. Importar el cliente de MikroTik

Al inicio de `handle_incoming_call.py`, después de los imports:

```python
# Agregar después de los imports existentes
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.mikrotik_api_client import MikroTikAPIClient
```

#### 2.2. Modificar `__init__` de `OpenAIClient`

Agregar al final del método `__init__`:

```python
def __init__(self):
    # ... código existente ...

    # NUEVO: Soporte para function calling
    self.current_function_call = None
    self.function_call_id = None
    self.function_arguments_buffer = ""

    # Cliente de MikroTik API
    mikrotik_api_url = os.getenv('MIKROTIK_API_URL', 'http://192.168.1.100:5050')
    enable_tools = os.getenv('ENABLE_MIKROTIK_TOOLS', 'true').lower() == 'true'

    if enable_tools:
        self.mikrotik_client = MikroTikAPIClient(api_url=mikrotik_api_url)
        logging.info("Cliente MikroTik API inicializado")
    else:
        self.mikrotik_client = None
        logging.info("Herramientas MikroTik deshabilitadas")
```

#### 2.3. Modificar `on_open` para agregar tools

Reemplazar el método `on_open`:

```python
def on_open(self, ws):
    """Maneja apertura de conexión - AHORA CON TOOLS"""
    try:
        session_config = {
            "type": "session.update",
            "session": {
                "modalities": ["audio", "text"],
                "voice": "verse",
                "instructions": """
                Eres un asistente virtual amable y profesional para soporte técnico de redes.

                Puedes ayudar con consultas sobre routers MikroTik, estado de clientes,
                información de tráfico, interfaces y gateways.

                Cuando te pregunten sobre información técnica, usa la herramienta
                'consultar_mikrotik' para obtener datos en tiempo real.

                Responde de manera clara y concisa, adaptada para conversación telefónica.
                """,
                "input_audio_format": "g711_ulaw",
                "output_audio_format": "g711_ulaw",
                "turn_detection": {
                    "type": "server_vad",
                    "threshold": 0.2,
                    "prefix_padding_ms": 300,
                    "silence_duration_ms": 100,
                }
            }
        }

        # Agregar tools si están habilitados
        if self.mikrotik_client:
            session_config["session"]["tools"] = [
                self.mikrotik_client.get_tool_definition()
            ]
            session_config["session"]["tool_choice"] = "auto"
            logging.info("✓ Herramientas MikroTik agregadas")

        ws.send(json.dumps(session_config))

    except Exception as e:
        logging.error(f"Error enviando configuración: {e}")
```

#### 2.4. Modificar `on_message` para manejar function calls

Agregar estos casos al método `on_message`, después de los casos existentes:

```python
def on_message(self, ws, message):
    """Procesa mensajes de OpenAI"""
    try:
        data = json.loads(message)
        msg_type = data.get('type', '')

        # ... casos existentes ...

        # NUEVO: Eventos de function calling
        elif msg_type == 'response.function_call_arguments.delta':
            self.handle_function_call_delta(data)

        elif msg_type == 'response.function_call_arguments.done':
            self.handle_function_call_done(ws, data)

        elif msg_type == 'response.output_item.done':
            self.handle_output_item_done(ws, data)

        # ... resto del código ...
```

#### 2.5. Agregar los nuevos métodos

Copiar estos métodos completos al final de la clase `OpenAIClient`:

```python
def handle_function_call_delta(self, data):
    """Maneja chunks de argumentos de función"""
    # [Copiar desde handle_incoming_call_with_tools.py]

def handle_function_call_done(self, ws, data):
    """Maneja finalización de function call"""
    # [Copiar desde handle_incoming_call_with_tools.py]

def handle_output_item_done(self, ws, data):
    """Maneja finalización de items de output"""
    # [Copiar desde handle_incoming_call_with_tools.py]

def execute_function(self, name, arguments):
    """Ejecuta la función solicitada"""
    # [Copiar desde handle_incoming_call_with_tools.py]

def send_function_result(self, ws, call_id, result):
    """Envía resultado a OpenAI"""
    # [Copiar desde handle_incoming_call_with_tools.py]

def send_function_error(self, ws, call_id, error_message):
    """Envía error a OpenAI"""
    # [Copiar desde handle_incoming_call_with_tools.py]
```

### Paso 5: Reiniciar el Servicio

```bash
sudo systemctl restart openai-inbound-calls
sudo journalctl -u openai-inbound-calls -f
```

**Logs esperados:**

```
Cliente MikroTik API inicializado
Iniciando conexión WebSocket con OpenAI
✓ Herramientas MikroTik agregadas a la sesión
Conexión ARI establecida
```

---

## 📱 Ejemplos de Conversaciones

### Ejemplo 1: Consulta de Clientes Activos

```
Usuario: "Hola, ¿cuántos clientes activos tenemos en router-146?"

[OpenAI detecta que necesita información]
[Llama a consultar_mikrotik("¿Cuántos clientes activos hay en router-146?")]
[API responde en ~2-3 segundos]

Asistente: "En el router Fibra Óptica hay 221 clientes activos en este momento."
```

### Ejemplo 2: Estado de Routers

```
Usuario: "¿Qué routers están configurados?"

[Function call a MikroTik API]

Asistente: "Tenemos 3 routers configurados: FIBRA OPTICA en 192.168.26.1,
           ROUTER 2 en 192.168.146.1, y ROUTER 3 en 192.168.150.1."
```

### Ejemplo 3: Información de Tráfico

```
Usuario: "¿Cuál es el tráfico de la interfaz WAN?"

[Function call a MikroTik API]

Asistente: "El tráfico actual de la interfaz WAN es de 45.3 Mbps de bajada
           y 12.7 Mbps de subida."
```

### Ejemplo 4: Conversación Natural con Múltiples Consultas

```
Usuario: "Buenos días"
Asistente: "¡Buenos días! ¿En qué puedo ayudarte hoy?"

Usuario: "Necesito saber cuántos clientes tenemos conectados"
[Function call]
Asistente: "Actualmente tenemos 450 clientes conectados en total."

Usuario: "¿Y en el router principal?"
[Function call - OpenAI entiende contexto: router-146]
Asistente: "En el router principal, FIBRA OPTICA, hay 221 clientes conectados."

Usuario: "Perfecto, gracias"
Asistente: "De nada, que tengas un buen día."
```

---

## 🔍 Monitoring y Debugging

### Ver Logs en Tiempo Real

```bash
# Logs del servicio
sudo journalctl -u openai-inbound-calls -f

# Filtrar solo function calls
sudo journalctl -u openai-inbound-calls -f | grep "Function call"

# Ver logs de la API de MikroTik
tail -f /var/log/mikrotik-api.log  # (si tienes logs configurados)
```

### Logs Importantes a Buscar

```
✓ "Cliente MikroTik API inicializado"
✓ "✓ Herramientas MikroTik agregadas"
✓ "🔧 Function call iniciada: consultar_mikrotik"
✓ "⚙️ Ejecutando función: consultar_mikrotik"
✓ "   ✓ Resultado obtenido (success: True)"
✓ "📤 Function result enviado"
✓ "📊 Total de function calls: X"
```

### Métricas de Rendimiento

Al final de cada llamada, verás métricas:

```
📊 Total de function calls: 3
📊 Tiempo total de llamada: 125.3s
📊 Audio chunks enviados: 1234
📊 Audio chunks recibidos: 1567
```

---

## ⚠️ Solución de Problemas

### Problema 1: "MikroTik client not initialized"

**Síntoma:** El asistente dice "el sistema de consultas no está disponible"

**Solución:**
```bash
# Verificar variable de entorno
grep MIKROTIK /usr/local/asterisk/.env

# Debe tener:
ENABLE_MIKROTIK_TOOLS=true
MIKROTIK_API_URL=http://192.168.1.100:5050

# Reiniciar servicio
sudo systemctl restart openai-inbound-calls
```

### Problema 2: Timeouts en las consultas

**Síntoma:** El asistente dice "la consulta tardó demasiado"

**Causas posibles:**
1. API de MikroTik está lenta
2. Timeout configurado muy corto
3. Problema de red

**Solución:**
```bash
# Test manual de la API
time curl -X POST http://192.168.1.100:5050/query \
  -H "Content-Type: application/json" \
  -d '{"question": "¿Qué routers están configurados?", "timeout": 15}'

# Debería responder en < 5 segundos

# Si es lento, revisar la API de MikroTik
# Puedes aumentar el timeout en mikrotik_api_client.py
```

### Problema 3: Function calls no se ejecutan

**Síntoma:** El asistente responde sin consultar la API

**Debugging:**

```bash
# Ver si los tools están configurados
sudo journalctl -u openai-inbound-calls -n 50 | grep -i "tool"

# Debería mostrar:
# "✓ Herramientas MikroTik agregadas"

# Si no aparece, verificar:
# 1. ENABLE_MIKROTIK_TOOLS=true en .env
# 2. Imports correctos en handle_incoming_call.py
# 3. mikrotik_client se inicializa correctamente
```

### Problema 4: Error "No se pudo conectar a la API"

**Solución:**
```bash
# Verificar que la API esté corriendo
curl http://192.168.1.100:5050/health

# Verificar conectividad de red
ping 192.168.1.100

# Verificar firewall
sudo iptables -L | grep 5050

# Revisar logs de la API
# (depende de cómo esté configurada tu API)
```

### Problema 5: Respuestas incompletas o cortadas

**Síntoma:** El asistente empieza a responder pero se corta

**Causa:** Latencia excesiva por function calling

**Solución:**
- Optimizar la API de MikroTik para responder más rápido
- Usar preguntas más específicas
- Considerar caché en la API para consultas frecuentes

---

## 📊 Optimizaciones de Rendimiento

### 1. Caché de Consultas Frecuentes

Modificar `MikroTikAPIClient` para cachear respuestas:

```python
from functools import lru_cache
import time

@lru_cache(maxsize=128)
def cached_query(self, question, timeout, cache_time):
    # cache_time se usa solo para invalidar el cache
    return self._execute_query(question, timeout)

def query(self, question, timeout=15):
    # Cachear por 30 segundos
    cache_time = int(time.time() / 30)
    return self.cached_query(question, timeout, cache_time)
```

### 2. Conexión Persistente a la API

Usar `requests.Session()` para reutilizar conexiones HTTP:

```python
class MikroTikAPIClient:
    def __init__(self, api_url):
        self.session = requests.Session()  # Reutilizar conexión

    def query(self, question, timeout):
        response = self.session.post(...)  # Más rápido
```

### 3. Timeout Adaptativo

Ajustar timeout según tipo de consulta:

```python
def get_smart_timeout(question):
    if "todos" in question or "completo" in question:
        return 25  # Consultas complejas
    else:
        return 10  # Consultas simples
```

---

## 🎓 Mejores Prácticas

### 1. Instrucciones Claras al Asistente

Las instructions en `on_open` deben ser específicas:

```python
"instructions": """
Eres asistente de soporte técnico de redes.

IMPORTANTE: Cuando te pregunten sobre:
- Clientes conectados
- Estado de routers
- Tráfico de red
- Interfaces o gateways

SIEMPRE usa la herramienta 'consultar_mikrotik' primero.
NO inventes información.

Responde de forma breve y natural para conversación telefónica.
"""
```

### 2. Manejo de Errores Descriptivo

```python
def execute_function(self, name, arguments):
    try:
        result = self.mikrotik_client.query(...)

        if not result['success']:
            # Dar contexto del error al usuario
            return {
                "response": f"Lo siento, hubo un problema: {result['response']}"
            }

    except Exception as e:
        logging.error(f"Error: {e}")
        # Mensaje amigable, no técnico
        return {
            "response": "Ocurrió un error. ¿Puedes repetir tu pregunta?"
        }
```

### 3. Logging Estructurado

```python
logging.info(f"🔧 Function call: {name}")
logging.info(f"   Args: {json.dumps(arguments, ensure_ascii=False)}")
logging.info(f"   Success: {result['success']}")
logging.info(f"   Time: {elapsed_time:.2f}s")
```

---

## 🚀 Próximos Pasos

Una vez que la integración funcione:

1. **Agregar más herramientas:**
   - Consulta de base de datos de clientes
   - Verificación de pagos
   - Creación de tickets de soporte

2. **Optimizaciones:**
   - Implementar caché
   - Conexiones persistentes
   - Timeouts adaptativos

3. **Monitoreo:**
   - Dashboard de function calls
   - Métricas de latencia
   - Alertas por errores

---

## 📚 Referencias

- [OpenAI Realtime API Docs](https://platform.openai.com/docs/guides/realtime)
- [Function Calling Guide](https://platform.openai.com/docs/guides/function-calling)
- [Archivo: handle_incoming_call_with_tools.py](/usr/local/asterisk/inbound_calls/handle_incoming_call_with_tools.py)
- [Archivo: mikrotik_api_client.py](/usr/local/asterisk/utils/mikrotik_api_client.py)
- [Tests: test_mikrotik_integration.py](/usr/local/asterisk/utils/test_mikrotik_integration.py)

---

**Última actualización:** Noviembre 2025
**Versión:** 1.0
