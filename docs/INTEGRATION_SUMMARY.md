# 📞 Resumen de Integración: OpenAI Realtime API + MikroTik API

## 🎯 ¿Qué se implementó?

Se ha creado una integración completa que permite que el asistente telefónico de OpenAI consulte información en tiempo real de routers MikroTik durante una conversación telefónica.

---

## 📦 Archivos Creados

### 1. **`utils/mikrotik_api_client.py`**
Cliente Python para consumir la API REST de MikroTik.

**Características:**
- Método `query()` para hacer consultas en lenguaje natural
- Método `check_health()` para verificar disponibilidad
- Método `get_tool_definition()` que retorna la definición del tool para OpenAI
- Manejo robusto de errores y timeouts
- Validación de parámetros
- Logging detallado

**Uso:**
```python
from utils.mikrotik_api_client import MikroTikAPIClient

client = MikroTikAPIClient(api_url="http://10.0.0.9:5050")
result = client.query("¿Cuántos clientes activos hay?", timeout=15)
print(result['response'])  # Texto para reproducir por voz
```

---

### 2. **`inbound_calls/handle_incoming_call_with_tools.py`**
Versión mejorada del sistema de llamadas entrantes con soporte para Function Calling.

**Características nuevas:**
- Clase `OpenAIClient` con métodos para function calling:
  - `handle_function_call_delta()` - Procesa chunks de argumentos
  - `handle_function_call_done()` - Ejecuta la función cuando está completa
  - `execute_function()` - Ejecuta la consulta a MikroTik
  - `send_function_result()` - Envía resultado a OpenAI
  - `send_function_error()` - Maneja errores gracefully

- Configuración de sesión con tools:
  ```python
  "tools": [
      {
          "type": "function",
          "name": "consultar_mikrotik",
          "description": "Consulta información sobre routers...",
          "parameters": {...}
      }
  ]
  ```

- Instrucciones mejoradas para el asistente
- Contador de métricas de function calls
- Logging detallado de cada llamada a función

---

### 3. **`utils/test_mikrotik_integration.py`**
Suite completa de tests para validar la integración.

**Tests incluidos:**
1. ✅ Health Check de la API
2. ✅ Consultas Básicas
3. ✅ Consulta de Router Específico
4. ✅ Consulta de Tráfico
5. ✅ Manejo de Timeouts
6. ✅ Manejo de Errores
7. ✅ Definición del Tool
8. ✅ Consultas Consecutivas (simulando conversación)

**Ejecutar tests:**
```bash
cd /usr/local/asterisk
python3 utils/test_mikrotik_integration.py
```

---

### 4. **`inbound_calls/FUNCTION_CALLING_GUIDE.md`**
Documentación completa con:
- Explicación de qué es function calling
- Arquitectura de la integración
- Guía paso a paso de instalación
- Ejemplos de conversaciones
- Solución de problemas
- Mejores prácticas
- Optimizaciones de rendimiento

---

## 🔄 Flujo de una Conversación

```
1. Usuario por teléfono: "¿Cuántos clientes hay en router-146?"
   ↓
2. Audio → Asterisk → handle_incoming_call.py → OpenAI (WebSocket)
   ↓
3. OpenAI detecta que necesita información externa
   ↓
4. OpenAI envía evento: response.function_call_arguments.done
   {
     "name": "consultar_mikrotik",
     "arguments": {"pregunta": "¿Cuántos clientes hay en router-146?"}
   }
   ↓
5. handle_function_call_done() ejecuta:
   - MikroTikAPIClient.query("¿Cuántos clientes hay en router-146?")
   ↓
6. HTTP POST → http://10.0.0.9:5050/query
   ↓
7. API MikroTik responde en ~2-5 segundos:
   {
     "success": true,
     "response": "En el router FIBRA OPTICA hay 221 clientes activos..."
   }
   ↓
8. send_function_result() envía resultado a OpenAI
   ↓
9. OpenAI genera respuesta natural en audio
   ↓
10. Audio → Asterisk → Usuario escucha la respuesta
```

**Latencia total:** ~3-6 segundos (depende de la API de MikroTik)

---

## ⚙️ Configuración Necesaria

### Variables de Entorno (`.env`):

```bash
# MikroTik API
MIKROTIK_API_URL=http://10.0.0.9:5050
ENABLE_MIKROTIK_TOOLS=true

# Existentes (ya configuradas)
ASTERISK_USERNAME=Asterisk
ASTERISK_PASSWORD=...
OPENAI_API_KEY=sk-proj-...
ASTERISK_HOST=localhost
ASTERISK_PORT=8088
LOCAL_IP_ADDRESS=192.168.1.100
LOG_FILE_PATH=/var/log/asterisk/inbound_openai.log
```

---

## 📊 Características Técnicas

### Timeouts y Latencia:
- **Timeout por defecto:** 15 segundos (configurable)
- **Timeout de HTTP request:** 20 segundos
- **Latencia esperada de function call:** 2-6 segundos
- **Latencia total (pregunta → respuesta):** 4-8 segundos

### Manejo de Errores:
- ✅ Timeout de API → mensaje amigable al usuario
- ✅ API no disponible → mensaje alternativo
- ✅ Error de parsing → fallback graceful
- ✅ Pregunta inválida → validación con feedback

### Logging:
```
🔧 Function call iniciada: consultar_mikrotik (call_id: abc123)
⚙️ Ejecutando función: consultar_mikrotik
   Pregunta: '¿Cuántos clientes activos hay?'
   Timeout: 15s
   ✓ Resultado obtenido (success: True)
📤 Function result enviado para call_id: abc123
📊 Total de function calls: 3
```

---

## 🧪 Testing

### Test Rápido de la API:

```bash
# 1. Verificar health
curl http://10.0.0.9:5050/health

# 2. Hacer una consulta
curl -X POST http://10.0.0.9:5050/query \
  -H "Content-Type: application/json" \
  -d '{"question": "¿Qué routers están configurados?", "timeout": 15}'
```

### Test Completo de Integración:

```bash
cd /usr/local/asterisk

# Configurar la URL correcta
export MIKROTIK_API_URL=http://10.0.0.9:5050

# Ejecutar tests
python3 utils/test_mikrotik_integration.py
```

### Test en Producción (Llamada Real):

```
1. Llamar al número: 3241000752
2. Esperar el saludo del asistente
3. Preguntar: "¿Cuántos clientes activos tenemos?"
4. Escuchar la respuesta
```

**Logs esperados:**
```bash
sudo journalctl -u openai-inbound-calls -f | grep "Function call"
```

---

## 🎯 Ejemplos de Preguntas Soportadas

### Información de Clientes:
- "¿Cuántos clientes activos hay?"
- "¿Cuántos clientes hay en router-146?"
- "¿Hay clientes con problemas?"

### Estado de Routers:
- "¿Qué routers están configurados?"
- "¿Cuál es el estado de los routers?"
- "¿Qué routers tenemos?"

### Tráfico de Red:
- "¿Cuál es el tráfico de la interfaz WAN?"
- "¿Qué interfaz tiene más tráfico?"
- "¿Cuánto tráfico hay en total?"

### Interfaces y Gateways:
- "¿Qué interfaces están libres?"
- "¿Qué gateways están activos?"
- "¿Cuál es el estado de las interfaces?"

---

## 🚀 Próximos Pasos para Activar en Producción

### Paso 1: Configurar Variables de Entorno

```bash
cd /usr/local/asterisk
nano .env
```

Agregar estas líneas:
```bash
MIKROTIK_API_URL=http://10.0.0.9:5050
ENABLE_MIKROTIK_TOOLS=true
```

### Paso 2: Verificar Conectividad con la API

```bash
# Desde el servidor de Asterisk
curl http://10.0.0.9:5050/health

# Debe responder:
# {"status":"ok","service":"MikroTik API","version":"1.0"}
```

### Paso 3: Ejecutar Tests

```bash
cd /usr/local/asterisk
export MIKROTIK_API_URL=http://10.0.0.9:5050
python3 utils/test_mikrotik_integration.py
```

Deberías ver:
```
🎉 ¡Todos los tests pasaron! La integración está funcionando correctamente.
```

### Paso 4: Integrar Function Calling al Código Principal

Ver guía detallada en:
`/usr/local/asterisk/inbound_calls/FUNCTION_CALLING_GUIDE.md`

### Paso 5: Reiniciar Servicio

```bash
sudo systemctl restart openai-inbound-calls
sudo journalctl -u openai-inbound-calls -f
```

Buscar en los logs:
```
✓ Herramientas MikroTik agregadas a la sesión
```

---

## 📈 Métricas y Monitoreo

### Ver Logs en Tiempo Real:

```bash
# Logs generales
sudo journalctl -u openai-inbound-calls -f

# Solo function calls
sudo journalctl -u openai-inbound-calls -f | grep -E "Function|🔧|⚙️|📤"

# Errores
sudo journalctl -u openai-inbound-calls -p err
```

### Métricas al Final de Llamada:

```
📊 Total de function calls: 3
📊 Tiempo total de llamada: 125.3s
📊 Audio chunks enviados: 1234
📊 Audio chunks recibidos: 1567
```

---

## ⚠️ Consideraciones Importantes

### 1. Conectividad de Red:
- La API está en **10.0.0.9:5050**
- Verificar que el servidor de Asterisk pueda alcanzar esa IP
- Verificar firewall y routing
- Prueba: `ping 10.0.0.9` y `telnet 10.0.0.9 5050`

### 2. Latencia Telefónica:
- Function calls añaden 2-6 segundos de latencia
- Informar al usuario: "Déjame consultar esa información..."
- La API de MikroTik debe responder en < 5 segundos

### 3. Manejo de Timeouts:
- Timeout de 15s es apropiado para telefonía
- Mensajes claros cuando hay timeout
- No usar timeouts muy largos (> 30s)

### 4. Testing Antes de Producción:
```bash
# SIEMPRE ejecutar tests primero
export MIKROTIK_API_URL=http://10.0.0.9:5050
python3 utils/test_mikrotik_integration.py

# Verificar que todos pasen
# Expected: 8/8 tests PASS
```

---

## 🐛 Troubleshooting Rápido

| Problema | Causa Probable | Solución |
|----------|---------------|----------|
| "Sistema no disponible" | API apagada | `curl http://10.0.0.9:5050/health` |
| Connection refused | Firewall/routing | `ping 10.0.0.9` y `telnet 10.0.0.9 5050` |
| Timeout frecuentes | API lenta o red lenta | Revisar latencia: `ping 10.0.0.9` |
| No usa la herramienta | Instructions incorrectas | Revisar `on_open()` |
| Error de imports | Path incorrecto | Verificar `sys.path.append()` |
| Servicio no inicia | Variables faltantes | Revisar `.env` |

---

## 📚 Archivos de Referencia

```
/usr/local/asterisk/
├── utils/
│   ├── mikrotik_api_client.py         ← Cliente de API
│   └── test_mikrotik_integration.py   ← Tests completos
├── inbound_calls/
│   ├── handle_incoming_call.py        ← Original (sin tools)
│   ├── handle_incoming_call_with_tools.py  ← Con function calling
│   └── FUNCTION_CALLING_GUIDE.md      ← Guía completa
├── .env                                ← Variables de entorno
└── INTEGRATION_SUMMARY.md             ← Este archivo
```

---

## ✅ Checklist de Implementación

- [ ] API de MikroTik está corriendo en http://10.0.0.9:5050
- [ ] Verificar conectividad: `curl http://10.0.0.9:5050/health` responde OK
- [ ] Verificar red: `ping 10.0.0.9` funciona
- [ ] Variables agregadas a `.env`:
  - [ ] `MIKROTIK_API_URL=http://10.0.0.9:5050`
  - [ ] `ENABLE_MIKROTIK_TOOLS=true`
- [ ] Tests ejecutados: `python3 utils/test_mikrotik_integration.py`
- [ ] Todos los tests pasan (8/8)
- [ ] Código de function calling agregado a `handle_incoming_call.py`
- [ ] Servicio reiniciado: `sudo systemctl restart openai-inbound-calls`
- [ ] Logs muestran: "✓ Herramientas MikroTik agregadas"
- [ ] Llamada de prueba realizada
- [ ] Function calling funciona correctamente

---

## 🎉 ¡Listo para Producción!

Una vez completado el checklist, el sistema estará listo para:

✅ Recibir llamadas telefónicas
✅ Conversar naturalmente con usuarios
✅ Consultar información en tiempo real de MikroTik
✅ Responder preguntas sobre routers, clientes y tráfico
✅ Manejar errores gracefully
✅ Registrar todas las interacciones

---

**Fecha de Creación:** Noviembre 2025
**Versión:** 1.0
**Estado:** ✅ Implementación Completa
**API URL:** http://10.0.0.9:5050
