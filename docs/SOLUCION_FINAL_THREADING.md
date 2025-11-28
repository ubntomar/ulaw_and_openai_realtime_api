# Solución Final: Threading para Consultas Largas

**Fecha:** 2025-11-28 18:05
**Problema:** Asistente se queda mudo durante consultas largas (>20 segundos)

## Problema Raíz Identificado

Después de múltiples intentos, se identificó el verdadero problema:

### Error Original:
```
Conexión cerrada: 1011 - keepalive ping timeout
```

### Causa Real:
1. El callback `on_message` del WebSocket se ejecuta en el **mismo thread** que maneja el WebSocket
2. Cuando `handle_function_call_done()` llamaba a `execute_function()` de forma SÍNCRONA, bloqueaba el thread
3. Durante 20-30 segundos de ejecución de la función, **el WebSocket no podía procesar pings entrantes de OpenAI**
4. OpenAI esperaba ~30 segundos sin recibir PONG y cerraba la conexión con código 1011

## Soluciones Intentadas (FALLIDAS)

### Intento 1: Threading dentro de execute_function ❌
- **Líneas modificadas:** 743-795
- **Problema:** Usar `time.sleep()` en el callback seguía bloqueando el thread del WebSocket
- **Resultado:** Mismo error 1011

### Intento 2: Dispatcher `rel` ❌
- **Cambio:** Agregar `dispatcher=rel` a `ws.run_forever()`
- **Problema:** `rel` requiere el main thread, pero el WebSocket corre en un worker thread
- **Error:** `signal only works in main thread of the main interpreter`
- **Resultado:** OpenAI no se conectaba en absoluto

### Intento 3: Aumentar ping_timeout ❌
- **Cambio:** `ping_timeout=90`
- **Problema:** Confusión sobre qué parámetro hace qué
- **Error:** `Ensure ping_interval > ping_timeout`
- **Resultado:** Error de configuración

## Solución Final: Threading en handle_function_call_done ✅

### Ubicación del Cambio
**Archivo:** `/usr/local/asterisk/inbound_calls/handle_incoming_call.py`
**Líneas:** 666-721

### Código Implementado

```python
def handle_function_call_done(self, ws, data):
    """Maneja finalización de function call - EJECUTA LA FUNCIÓN EN THREAD SEPARADO"""
    try:
        call_id = data.get('call_id', '')
        name = data.get('name', '')
        arguments_str = data.get('arguments', '{}')

        logging.info(f"🔧 Function call completada: {name}")
        logging.info(f"   Arguments: {arguments_str}")

        # Parsear argumentos
        try:
            arguments = json.loads(arguments_str)
        except json.JSONDecodeError:
            logging.error(f"Error parseando argumentos: {arguments_str}")
            arguments = {}

        # EJECUTAR LA FUNCIÓN EN UN THREAD SEPARADO
        # Esto evita bloquear el thread del WebSocket que maneja ping/pong
        import threading

        def execute_and_send():
            """Ejecuta la función y envía el resultado - en thread separado"""
            try:
                # Ejecutar la función (esto puede tomar 20-30 segundos)
                result = self.execute_function(name, arguments)

                logging.info(f"   Resultado: {result}")

                # Enviar resultado de vuelta a OpenAI
                self.send_function_result(ws, call_id, result)

                # Incrementar métrica
                self.metrics['function_calls'] += 1

                # Resetear estado
                self.current_function_call = None

            except Exception as e:
                logging.error(f"Error ejecutando función en thread: {e}")
                # Enviar error a OpenAI
                error_result = {
                    "error": str(e),
                    "response": "Lo siento, ocurrió un error al procesar tu solicitud."
                }
                self.send_function_result(ws, call_id, error_result)

        # Iniciar thread y retornar inmediatamente
        # Esto permite que el WebSocket continúe procesando pings
        thread = threading.Thread(target=execute_and_send, daemon=True)
        thread.start()
        logging.info(f"   ⚡ Función iniciada en thread separado (thread no bloqueará ping/pong)")
```

### Configuración de Ping/Pong

**Líneas:** 512-519

```python
ws.run_forever(
    ping_interval=90,  # Enviar ping cada 90 segundos
    ping_timeout=30    # Esperar 30s por pong antes de timeout
)
```

**Importante:**
- `ping_interval` > `ping_timeout` (requerimiento de websocket-client)
- Intervalo de 90s es suficientemente largo para no interferir con consultas de 60s
- Timeout de 30s permite detectar conexiones muertas rápidamente

## Cómo Funciona la Solución

### Flujo Anterior (BLOQUEANTE):
```
1. OpenAI envía: "response.function_call_arguments.done"
2. on_message() → handle_function_call_done() → execute_function()
                                                    ↓
3. [BLOQUEA 28 SEGUNDOS esperando MikroTik API]
                                                    ↓
4. OpenAI envía PING → [THREAD BLOQUEADO, NO RESPONDE]
5. OpenAI espera 30s → [TIMEOUT] → Cierra conexión (1011)
6. execute_function() termina → intenta enviar resultado
7. ERROR: "Connection is already closed"
```

### Flujo Nuevo (NO BLOQUEANTE):
```
1. OpenAI envía: "response.function_call_arguments.done"
2. on_message() → handle_function_call_done()
                      ↓
3. Crea Thread → execute_and_send() [EN PARALELO]
4. RETORNA INMEDIATAMENTE ← handle_function_call_done()
                      ↓
5. on_message() termina → Thread del WebSocket LIBRE
                      ↓
6. [THREAD WORKER ejecuta consulta de 28 segundos]
7. OpenAI envía PING → Thread WebSocket RESPONDE PONG ✓
8. [Consulta termina] → execute_and_send() → send_function_result()
9. OpenAI recibe resultado → Genera audio → Usuario escucha respuesta ✓
```

## Ventajas de Esta Solución

1. ✅ **Simplicidad:** Solo requiere cambio en UN lugar (handle_function_call_done)
2. ✅ **No requiere librerías externas:** Usa threading estándar de Python
3. ✅ **No afecta otros callbacks:** Otros eventos (audio, transcripciones) no se modifican
4. ✅ **Thread-safe:** El WebSocket de websocket-client es thread-safe para envío
5. ✅ **Mantiene ping/pong vivo:** El thread principal responde a pings de OpenAI
6. ✅ **Sin cambios en execute_function:** La lógica de negocio queda simple y síncrona

## Pruebas Requeridas

### Paso 1: Verificar Servicio
```bash
systemctl status openai-inbound-calls.service
# Debe mostrar: Active: active (running)
```

### Paso 2: Realizar Llamada
Llamar de **3147654655** a **3241000752**

### Paso 3: Pregunta de Prueba
> "Dame el tráfico de las interfaces SFP de todos los routers"

### Paso 4: Comportamiento Esperado

**Mientras se consulta (20-30 segundos):**
- ✅ Usuario escucha: "Un momento, estoy consultando esa información para ti"
- ✅ Silencio mientras se ejecuta la consulta (normal, limitación de API)
- ✅ NO se corta la llamada
- ✅ Logs muestran: "⚡ Función iniciada en thread separado"

**Después de la consulta:**
- ✅ Asistente responde con los resultados
- ✅ Usuario puede hacer más preguntas
- ✅ Llamada continúa normalmente

### Paso 5: Verificar Logs

```bash
journalctl -u openai-inbound-calls.service -f | grep -E "(⚡ Función iniciada|Resultado obtenido|Connection.*closed)"
```

**Logs esperados:**
```
[HH:MM:SS] 🔧 Function call completada: consultar_mikrotik
[HH:MM:SS]    ⚡ Función iniciada en thread separado (thread no bloqueará ping/pong)
[HH:MM:SS+28]  ✓ Resultado obtenido en 28.3s (success: true)
```

**NO debe aparecer:**
```
Connection is already closed
keepalive ping timeout
```

## Criterios de Éxito

- [ ] Llamada NO se corta durante consulta larga (>20s)
- [ ] Asistente responde con resultados después de la consulta
- [ ] Logs muestran "⚡ Función iniciada en thread separado"
- [ ] NO aparece error "Connection is already closed"
- [ ] Usuario puede hacer múltiples preguntas complejas en la misma llamada

## Próximos Pasos (Si Funciona)

1. ✅ **Commit y push** de esta solución
2. ✅ **Actualizar documentación** con esta implementación final
3. 🔄 **Optimizar consultas MikroTik** (paralelizar consultas a múltiples routers)
4. 🔄 **Implementar cache** para consultas frecuentes
5. 🔄 **Mejorar feedback del asistente** durante esperas largas

## Referencias

- **Código modificado:** `/usr/local/asterisk/inbound_calls/handle_incoming_call.py:666-721`
- **Configuración ping/pong:** `/usr/local/asterisk/inbound_calls/handle_incoming_call.py:512-519`
- **Issue original:** Asistente mudo durante consultas largas (mensaje del usuario del 2025-11-28)

---

**Última actualización:** 2025-11-28 18:05
**Estado:** ✅ Implementado, listo para pruebas
