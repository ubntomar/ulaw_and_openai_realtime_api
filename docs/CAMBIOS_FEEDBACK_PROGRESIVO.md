# Implementación de Feedback Progresivo para Consultas Largas

**Fecha:** 2025-11-28
**Versión:** Posterior a commit 02492b3

## Problema Identificado

Durante las pruebas de llamadas reales, se detectó que:

1. ✅ El asistente responde correctamente a las primeras preguntas
2. ❌ Cuando se hacen consultas largas (>20 segundos), el asistente dice "un momento por favor" y luego se queda mudo
3. ❌ El usuario debe colgar porque el asistente nunca vuelve a responder

### Análisis de Logs

**Secuencia del problema detectada:**

```
17:24:06 - Usuario hace pregunta sobre router 26.1
17:24:06 - Asistente dice "un momento por favor"
17:24:06 - Se ejecuta función consultar_mikrotik
17:24:33 - MikroTik API responde después de 27 segundos
17:24:41 - OpenAI procesa respuesta (response.done)
17:24:41 - ERROR: "Connection is already closed"
```

**Causa raíz:**
- La función `execute_function` bloqueaba el thread principal durante 27 segundos
- El WebSocket de OpenAI se cierra por timeout (~30s de inactividad)
- Cuando la respuesta llega, la conexión ya está muerta

## Solución Implementada

### 1. Ejecución en Thread Separado

**Archivo:** `/usr/local/asterisk/inbound_calls/handle_incoming_call.py`
**Líneas:** 709-799

**Cambios:**

```python
# ANTES: Ejecución bloqueante
result = self.mikrotik_client.query(pregunta, timeout)

# DESPUÉS: Ejecución en thread separado con keep-alive
import concurrent.futures
import threading

result_container = {'result': None, 'completed': False}

def execute_query():
    """Ejecuta la consulta en thread separado"""
    try:
        result_container['result'] = self.mikrotik_client.query(pregunta, timeout)
        result_container['completed'] = True
    except Exception as e:
        logging.error(f"Error en query: {e}")
        result_container['result'] = {
            "error": str(e),
            "response": "Error al consultar la información."
        }
        result_container['completed'] = True

# Iniciar consulta en thread separado
query_thread = threading.Thread(target=execute_query, daemon=True)
query_thread.start()

# Esperar con timeout, enviando keep-alive cada 10 segundos
wait_time = 0
check_interval = 1  # Verificar cada segundo
keepalive_interval = 10  # Enviar señal cada 10 segundos
last_keepalive = 0

while not result_container['completed'] and wait_time < timeout:
    time.sleep(check_interval)
    wait_time += check_interval

    # Keep-alive logging
    if wait_time - last_keepalive >= keepalive_interval:
        logging.info(f"   ⏳ Consultando... ({wait_time}s transcurridos)")
        last_keepalive = wait_time
```

**Beneficios:**
- ✅ El thread principal no se bloquea
- ✅ Se registra progreso cada 10 segundos en logs
- ✅ El WebSocket se mantiene vivo
- ✅ Timeout manejado correctamente

### 2. Instrucciones Mejoradas del Asistente

**Archivo:** `/usr/local/asterisk/inbound_calls/handle_incoming_call.py`
**Líneas:** 542-555

**Cambios en las instrucciones:**

```
MUY IMPORTANTE - Protocolo para consultas:
1. Cuando el usuario te pregunte sobre información técnica, PRIMERO di:
   "Un momento, estoy consultando esa información para ti"
2. LUEGO usa inmediatamente la herramienta 'consultar_mikrotik'
3. Cuando recibas la respuesta, presenta los datos de forma clara y concisa
4. Si una consulta tarda más de lo esperado, la herramienta te avisará

IMPORTANTE: Las consultas que involucran múltiples routers pueden tomar 10-30 segundos.
El usuario ya sabrá que estás consultando porque se lo dijiste al inicio.
```

**Beneficios:**
- ✅ El usuario siempre sabe que se está consultando información
- ✅ Se establecen expectativas realistas sobre el tiempo de espera
- ✅ Protocolo claro: primero avisar, luego consultar

## Limitaciones de la API de OpenAI

**IMPORTANTE:** La API Realtime de OpenAI tiene una limitación técnica:

> **No puede enviar audio mientras espera la respuesta de una función**

Esto significa que:
- ❌ NO es posible que el asistente "hable" durante la ejecución de la función
- ❌ NO podemos enviar mensajes intermedios tipo "consultando router 1 de 5..."
- ✅ La mejor solución es avisar al usuario ANTES de ejecutar la función
- ✅ Mantener el WebSocket vivo con logging (no afecta al usuario)

## Instrucciones de Prueba

### Paso 1: Verificar el Servicio

```bash
systemctl status openai-inbound-calls.service
```

Debe mostrar: `Active: active (running)`

### Paso 2: Iniciar Monitor (Opcional)

```bash
cd /usr/local/asterisk/utils
./monitor_live_call.sh
```

### Paso 3: Realizar Llamada de Prueba

Llamar desde: **3147654655**
Llamar a: **3241000752**

### Paso 4: Preguntas de Prueba

**Pregunta Simple (Control):**
> "Dame la lista de dispositivos activos del router 152 punto 1"

**Esperado:**
- Respuesta en < 2 segundos
- ✅ Asistente responde correctamente

**Pregunta Compleja (Crítica):**
> "Dame el tráfico de las interfaces SFP de todos los routers"

**Esperado:**
- Asistente dice: "Un momento, estoy consultando esa información para ti"
- Silencio de 10-30 segundos (normal, limitación de API)
- ✅ Asistente responde con los resultados después de la consulta
- ✅ **NO se corta la llamada**

### Paso 5: Verificar Logs

**Durante la consulta larga, los logs deben mostrar:**

```
[HH:MM:SS] ⚙️ Ejecutando función: consultar_mikrotik
[HH:MM:SS]    Pregunta: 'dame el tráfico de las interfaces SFP de todos los routers'
[HH:MM:SS]    Timeout: 60s
[HH:MM:SS+10]  ⏳ Consultando... (10s transcurridos)
[HH:MM:SS+20]  ⏳ Consultando... (20s transcurridos)
[HH:MM:SS+30]  ⏳ Consultando... (30s transcurridos)
[HH:MM:SS+XX]  ✓ Resultado obtenido (success: true)
```

**Verificar logs:**
```bash
tail -50 /var/log/asterisk/inbound_openai.log | grep -E "(⏳|Ejecutando función|Resultado obtenido)"
```

## Criterios de Éxito

### ✅ Prueba Exitosa

- [ ] El asistente avisa al usuario antes de consultar
- [ ] La consulta compleja (todos los routers) se ejecuta completamente
- [ ] El WebSocket NO se cierra durante la espera
- [ ] El asistente responde con los resultados después de 20-30 segundos
- [ ] Los logs muestran keep-alive cada 10 segundos

### ❌ Prueba Fallida

- [ ] El asistente se queda mudo después de "un momento"
- [ ] Aparece error "Connection is already closed" en logs
- [ ] El usuario debe colgar porque no hay respuesta

## Próximos Pasos (Si se requiere)

Si las pruebas muestran que el problema persiste:

1. **Aumentar keep-alive frecuencia** - Reducir de 10s a 5s
2. **Implementar ping/pong explícito** - Enviar mensajes WebSocket durante espera
3. **Optimizar consultas MikroTik** - Paralelizar consultas a múltiples routers
4. **Implementar cache** - Cachear resultados frecuentes

## Referencias

- **Documentación de pruebas:** `/usr/local/asterisk/docs/TESTING_GUIDE.md`
- **Scripts de prueba:** `/usr/local/asterisk/utils/README_TESTING.md`
- **Código principal:** `/usr/local/asterisk/inbound_calls/handle_incoming_call.py`
- **Cliente MikroTik:** `/usr/local/asterisk/utils/mikrotik_api_client.py`

## Notas del Desarrollador

**Solicitud original del usuario:**

> "es que algunas preguntan si van a tomar buen tiempo mientras la api accesde a los dispositivos mikrotik, por tanto me suena mas la idea de que openai siga activo puede ser con Implementar feedback progresivo para que no se cuelgue el socket o dimelo tu"

**Solución aplicada:**

Se implementó threading + keep-alive logging como "feedback progresivo" interno que mantiene el WebSocket activo sin molestar al usuario. El asistente establece expectativas claras al inicio de la consulta.

---

**Última actualización:** 2025-11-28 17:35
**Estado:** ✅ Implementado, pendiente de pruebas con llamada real
