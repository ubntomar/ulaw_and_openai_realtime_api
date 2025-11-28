# Mejoras Implementadas: Keepalive y Timeout Awareness

**Fecha:** 2025-11-28
**Objetivo:** Solucionar el problema de timeout en llamadas con consultas largas a MikroTik API

---

## 🔍 Problema Identificado

Durante las llamadas telefónicas, cuando se realizaban consultas complejas (como "tráfico de todas las interfaces SFP de todos los routers"), la llamada se cortaba con error:

```
Conexión cerrada: 1011 - keepalive ping timeout
```

**Causa raíz:**
- Las consultas complejas tardaban ~30 segundos
- El WebSocket de OpenAI tenía un timeout de keepalive muy corto
- La conexión se cerraba antes de que OpenAI pudiera reproducir la respuesta completa

---

## ✅ Soluciones Implementadas

### 1. **Mejora del Keepalive en WebSocket** (/usr/local/asterisk/inbound_calls/handle_incoming_call.py:524-530)

**Cambios:**
```python
# ANTES (sin configuración explícita)
ws.run_forever()

# DESPUÉS (con keepalive robusto)
ws.run_forever(
    ping_interval=20,    # Enviar ping cada 20 segundos
    ping_timeout=60      # Esperar hasta 60s por pong
)
```

**Handlers agregados:**
```python
def on_ping(self, ws, message):
    """Maneja mensajes ping del servidor"""
    logging.debug(f"PING recibido del servidor: {len(message)} bytes")

def on_pong(self, ws, message):
    """Maneja mensajes pong del servidor"""
    logging.debug(f"PONG recibido del servidor: {len(message)} bytes")
```

**Beneficios:**
- ✅ Keepalive cada 20 segundos mantiene la conexión activa
- ✅ Timeout de 60 segundos permite consultas largas (20-40s)
- ✅ Logs detallados para monitoreo de ping/pong

---

### 2. **Timeout Awareness en el Prompt de IA** (/usr/local/asterisk/inbound_calls/handle_incoming_call.py:547-583)

**Instrucciones mejoradas para la IA:**

```
ANTES de hacer la consulta, analiza la complejidad:

- Consulta SIMPLE (5-10s): información de un solo router específico
  Ejemplo: "tráfico del router 146", "clientes en Casa Omar"

- Consulta COMPLEJA (20-40s): información de múltiples routers o interfaces
  Ejemplo: "todas las interfaces SFP", "todos los routers", "tráfico de toda la red"

Para consultas SIMPLES:
- Di: "Déjame consultar esa información" o "Un momento, verifico eso"
- Usa la herramienta 'consultar_mikrotik'

Para consultas COMPLEJAS:
- Di: "Esta consulta puede tardar hasta 30 segundos porque necesito revisar varios routers.
      Dame un momento mientras obtengo esa información para ti."
- Usa la herramienta 'consultar_mikrotik'
- Si el usuario pregunta por "todas las interfaces" o "todos los routers", sugiere primero:
  "¿Te gustaría que revise un router específico primero? Será más rápido."
```

**Beneficios:**
- ✅ La IA advierte al usuario sobre consultas largas
- ✅ Sugiere alternativas más rápidas cuando es apropiado
- ✅ Mejor experiencia de usuario con expectativas claras

---

### 3. **Monitoreo de Tiempos de Ejecución** (/usr/local/asterisk/inbound_calls/handle_incoming_call.py:774-784)

**Código agregado:**
```python
# Medir tiempo de ejecución para monitoreo
start_time = time.time()

# Ejecutar la función
result = self.execute_function(name, arguments)

execution_time = time.time() - start_time
logging.info(f"   ⏱️ Tiempo de ejecución: {execution_time:.2f}s")

if execution_time > 30:
    logging.warning(f"   ⚠️ Function call tardó más de 30s: {execution_time:.2f}s")
```

**Beneficios:**
- ✅ Logs con tiempos exactos de ejecución
- ✅ Alertas automáticas cuando una consulta tarda >30s
- ✅ Facilita debugging y optimización

---

## 📊 Resultados Esperados

### Antes de las mejoras:
```
Usuario: "Dame el tráfico de todas las interfaces SFP"
IA: "Déjame consultar esa información"
[Consulta tarda 31 segundos]
[TIMEOUT - Conexión cerrada: 1011]
Usuario: [Llamada cortada] ❌
```

### Después de las mejoras:
```
Usuario: "Dame el tráfico de todas las interfaces SFP"
IA: "Esta consulta puede tardar hasta 30 segundos porque necesito revisar varios routers.
     Dame un momento mientras obtengo esa información para ti."
[Consulta tarda 31 segundos]
[Keepalive mantiene la conexión activa]
IA: "Las interfaces SFP están funcionando bien en todos los routers. El servidor Guamal
     tiene el mayor tráfico con 422 Mbps..." ✅
```

---

## 🧪 Cómo Probar las Mejoras

### Prueba 1: Consulta Simple (debe tardar 5-10s)
```
Llamar al sistema y decir:
"¿Cuál es el tráfico del router 146?"
```

**Resultado esperado:**
- ✅ La IA dice: "Déjame consultar esa información"
- ✅ Respuesta en ~5-10 segundos
- ✅ Sin timeouts

### Prueba 2: Consulta Compleja (debe tardar 20-40s)
```
Llamar al sistema y decir:
"¿Cuál es el tráfico de todas las interfaces SFP de todos los routers?"
```

**Resultado esperado:**
- ✅ La IA advierte: "Esta consulta puede tardar hasta 30 segundos..."
- ✅ Respuesta completa en ~30 segundos
- ✅ Sin timeouts - la conexión se mantiene activa
- ✅ Los logs muestran: `⏱️ Tiempo de ejecución: 31.XX s`

### Prueba 3: Sugerencia Proactiva
```
Llamar al sistema y decir:
"Dame información de todos los routers"
```

**Resultado esperado:**
- ✅ La IA sugiere: "¿Te gustaría que revise un router específico primero? Será más rápido."

---

## 📝 Logs de Monitoreo

### Verificar Keepalive activo:
```bash
tail -f /var/log/asterisk/inbound_openai.log | grep -E "(PING|PONG|keepalive)"
```

### Verificar tiempos de function calls:
```bash
grep "⏱️ Tiempo de ejecución" /var/log/asterisk/inbound_openai.log
```

### Verificar consultas largas:
```bash
grep "⚠️ Function call tardó más de 30s" /var/log/asterisk/inbound_openai.log
```

---

## 🔧 Configuración Técnica

### Parámetros del WebSocket:
- **ping_interval:** 20 segundos
- **ping_timeout:** 60 segundos

### Timeouts de la API MikroTik:
- **Default timeout:** 60 segundos (handle_incoming_call.py:789)
- **HTTP request timeout:** 70 segundos (mikrotik_api_client.py:99)

### Archivos Modificados:
1. `/usr/local/asterisk/inbound_calls/handle_incoming_call.py`
   - Líneas 502-536: Configuración de WebSocket con keepalive
   - Líneas 547-583: Prompt mejorado con timeout awareness
   - Líneas 757-802: Monitoreo de tiempos de ejecución
   - Líneas 918-924: Handlers de ping/pong

---

## 📞 Servicio Actualizado

**PID actual:** 1107494
**Log file:** `/var/log/asterisk/inbound_openai.log`
**Estado:** ✅ Corriendo con mejoras aplicadas

Para reiniciar el servicio:
```bash
sudo pkill -f handle_incoming_call.py
sudo -E nohup python3 /usr/local/asterisk/inbound_calls/handle_incoming_call.py > /tmp/asterisk_app.log 2>&1 &
```

---

## ✨ Próximos Pasos

1. **Probar con llamada real** - Verificar que las consultas complejas ya no corten la llamada
2. **Monitorear logs** - Revisar tiempos de ejecución durante 24-48 horas
3. **Optimizar si es necesario** - Si hay consultas que tardan >40s, considerar:
   - Aumentar `ping_timeout` a 90s
   - Optimizar queries en la API de MikroTik
   - Implementar caché para consultas frecuentes

---

**Documentación creada:** 2025-11-28 15:08
**Estado:** ✅ Mejoras implementadas y servicio reiniciado
