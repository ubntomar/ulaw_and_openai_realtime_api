# Guía de Pruebas y Depuración del Sistema

## Introducción

Esta guía describe cómo probar el sistema de llamadas con OpenAI y consultas a MikroTik, especialmente para validar el comportamiento durante consultas largas que involucran múltiples routers.

## Objetivos de las Pruebas

1. **Validar tiempos de respuesta** en consultas simples vs. complejas
2. **Verificar que el asistente se mantiene activo** durante consultas largas (>5 segundos)
3. **Detectar problemas de timeout** o desconexión
4. **Analizar el comportamiento del audio** durante esperas prolongadas
5. **Identificar oportunidades de mejora** en la experiencia de usuario

## Scripts de Prueba Disponibles

### 1. `test_complex_queries.py` - Pruebas de Consultas Complejas

**Propósito:** Probar directamente la API de MikroTik con consultas de diferentes niveles de complejidad.

**Ubicación:** `/usr/local/asterisk/utils/test_complex_queries.py`

**Uso:**
```bash
cd /usr/local/asterisk/utils
python3 test_complex_queries.py
```

**Casos de Prueba:**
1. ✅ Tráfico SFP de todos los routers (~5s)
2. ✅ Estado de todos los routers (~4s)
3. ✅ Dispositivos activos de múltiples routers (~6s)
4. ✅ Tráfico SFP de un solo router (~1.5s)
5. ✅ Dispositivos activos de un router (~1s)
6. ✅ Análisis completo de red (~10s)

**Salida Esperada:**
```
[HH:MM:SS] INICIANDO: Tráfico de interfaces SFP de TODOS los routers
[HH:MM:SS] Endpoint: /routers/all/sfp/traffic
[HH:MM:SS] Enviando request...
[HH:MM:SS] ✓ ÉXITO en 4.87s
[HH:MM:SS] Datos recibidos: 25 items
[HH:MM:SS] Routers procesados: 5
```

### 2. `simulate_phone_questions.py` - Simulador de Preguntas Telefónicas

**Propósito:** Simular preguntas que un usuario haría por teléfono, midiendo tiempos y analizando experiencia de usuario.

**Ubicación:** `/usr/local/asterisk/utils/simulate_phone_questions.py`

**Uso:**
```bash
cd /usr/local/asterisk/utils
python3 simulate_phone_questions.py
```

**Preguntas Simuladas:**

| # | Pregunta | Función | Tiempo Esperado |
|---|----------|---------|-----------------|
| 1 | "Dame la lista de dispositivos activos del router 152.1" | `query_router_active_devices` | 1.5s |
| 2 | "Dame el tráfico de las interfaces SFP del router 152.1" | `query_router_sfp_traffic` | 2.0s |
| 3 | "Dame el tráfico de las interfaces SFP de todos los routers" | `query_all_routers_sfp` | 5.0s |
| 4 | "Dame un resumen completo del estado de la red" | `query_network_summary` | 8.0s |

**Interpretación de Resultados:**
- ⚡ `< 70% tiempo esperado` - Más rápido de lo esperado
- ✓ `70-150% tiempo esperado` - Tiempo aceptable
- ⚠️ `> 150% tiempo esperado` - Más lento de lo esperado (investigar)

### 3. `monitor_live_call.sh` - Monitor de Llamadas en Tiempo Real

**Propósito:** Monitorear logs en tiempo real durante una llamada telefónica real para observar el comportamiento del sistema.

**Ubicación:** `/usr/local/asterisk/utils/monitor_live_call.sh`

**Uso:**
```bash
cd /usr/local/asterisk/utils
chmod +x monitor_live_call.sh
./monitor_live_call.sh
```

**Qué Monitorea:**
- 📞 Eventos de llamada (inicio/fin/respuesta)
- 🔧 Consultas a routers MikroTik (function calling)
- 🔊 Tráfico de audio RTP (paquetes/segundo)
- ❌ Errores y warnings en logs
- 📊 Estadísticas periódicas cada 30s

**Salida Típica Durante Consulta Compleja:**
```
[17:15:23] 📞 LLAMADA INICIADA
[17:15:23]    Canal: SIP/voip_issabel-00000001
[17:15:24] ✓ LLAMADA CONTESTADA
[17:15:26] 💬 Asistente respondiendo...
[17:15:28] 🔧 FUNCIÓN LLAMADA: query_all_routers_sfp
[17:15:28]    → Consultando router: 152.1
[17:15:29]    → Consultando router: 152.2
[17:15:30]    → Consultando router: 152.3
[17:15:31] 🔊 RTP: ~50 paquetes/s
[17:15:33]    ✓ Función completada exitosamente
[17:15:34] 🎤 Audio recibido de OpenAI
[17:15:40] 📵 LLAMADA FINALIZADA
```

## Procedimiento de Prueba Completo

### Paso 1: Preparación

1. Verificar que el servicio esté corriendo:
```bash
systemctl status openai-inbound-calls.service
```

2. Verificar conectividad con MikroTik API:
```bash
curl http://10.0.0.9:5050/health
```

### Paso 2: Pruebas Automatizadas (sin llamada)

Ejecutar scripts de prueba para validar API:

```bash
# Prueba 1: Consultas complejas
cd /usr/local/asterisk/utils
python3 test_complex_queries.py

# Prueba 2: Simulación de preguntas
python3 simulate_phone_questions.py
```

**Esperado:** Todas las pruebas pasan sin errores mayores.

### Paso 3: Pruebas con Llamada Real

#### 3.1 Iniciar Monitor

En una terminal, iniciar el monitor:
```bash
cd /usr/local/asterisk/utils
./monitor_live_call.sh
```

#### 3.2 Realizar Llamada

Llamar al número configurado (3241000752) desde tu teléfono (3147654655).

#### 3.3 Preguntas de Prueba

Realizar las siguientes preguntas en orden:

**Pregunta 1 (Simple):**
> "Dame la lista de dispositivos activos del router 152 punto 1"

**Qué observar:**
- Respuesta en < 2 segundos
- Asistente responde con lista de dispositivos
- No hay silencios prolongados

**Pregunta 2 (Media):**
> "Dame el tráfico de las interfaces SFP del router 152 punto 1"

**Qué observar:**
- Respuesta en 2-3 segundos
- Asistente lee datos de tráfico
- Audio continuo durante toda la respuesta

**Pregunta 3 (Compleja - CRÍTICA):**
> "Dame el tráfico de las interfaces SFP de todos los routers"

**Qué observar:**
- ⚠️ **CRÍTICO**: El asistente debe mantenerse "vivo" durante 5-8 segundos
- Idealmente, el asistente debería decir algo como:
  - "Un momento, estoy consultando todos los routers..."
  - "Esto puede tomar unos segundos..."
- NO debe haber silencio total > 3 segundos
- Debe responder con resumen de todos los routers

**Pregunta 4 (Muy Compleja):**
> "Dame un resumen completo del estado de la red"

**Qué observar:**
- Puede tomar 10-15 segundos
- El asistente debe mantener al usuario informado
- No debe cortarse la llamada por timeout

#### 3.4 Analizar Logs del Monitor

Durante y después de la llamada, observar en el monitor:

**✅ Comportamiento Correcto:**
- Function calls se ejecutan y completan
- Audio RTP fluye continuamente (~50 paquetes/s)
- Respuestas de OpenAI llegan
- No hay errores de timeout

**❌ Problemas a Detectar:**
- Silencios prolongados (>5s) durante consultas
- Función completa pero asistente no responde
- Audio RTP se detiene
- Timeouts o desconexiones

### Paso 4: Análisis de Resultados

Revisar logs completos:
```bash
# Ver últimos 100 eventos de function calling
grep "Ejecutando función" /var/log/asterisk/inbound_openai.log | tail -100

# Ver tiempos de respuesta
grep "función exitosa" /var/log/asterisk/inbound_openai.log | tail -50

# Ver errores recientes
grep -i error /var/log/asterisk/inbound_openai.log | tail -20
```

## Problemas Conocidos y Soluciones

### Problema 1: Asistente Mudo Durante Consulta Larga

**Síntoma:** Durante consultas >5s, el asistente no dice nada mientras espera respuesta de API.

**Causa:** OpenAI espera la respuesta completa de la función antes de generar audio.

**Soluciones Posibles:**
1. **Implementar streaming de respuestas parciales**
   - Enviar updates parciales mientras consulta múltiples routers
   - Ejemplo: "He consultado 3 de 5 routers..."

2. **Mensaje inicial inmediato**
   - Modificar instrucciones del asistente para que diga inmediatamente:
     "Consultando la información, un momento por favor..."

3. **Implementar timeout de respuesta amigable**
   - Después de 3s sin respuesta, enviar mensaje intermedio

### Problema 2: Timeout de Llamada

**Síntoma:** Llamada se corta durante consulta larga.

**Causa:** Timeout de RTP o WebSocket.

**Solución:**
```python
# En handle_incoming_call.py, ajustar timeouts:
QUERY_TIMEOUT = 30  # segundos
RTP_KEEPALIVE_INTERVAL = 2  # segundos
```

### Problema 3: Respuesta Incompleta

**Síntoma:** Asistente da respuesta parcial de consulta multi-router.

**Causa:** Timeout de función individual.

**Solución:**
```python
# En mikrotik_api_client.py:
def query_all_routers_sfp_traffic(self):
    # Implementar timeout por router
    TIMEOUT_PER_ROUTER = 3  # segundos
```

## Métricas de Éxito

| Métrica | Objetivo | Crítico |
|---------|----------|---------|
| Tiempo consulta simple | < 2s | < 5s |
| Tiempo consulta media | < 3s | < 8s |
| Tiempo consulta compleja | < 8s | < 15s |
| Tasa de éxito | > 95% | > 80% |
| Silencios durante consulta | < 3s | < 5s |
| Tasa de desconexión | < 1% | < 5% |

## Registro de Pruebas

Mantener un log de pruebas:

```
Fecha: 2025-11-28
Hora: 17:30
Tester: Omar
Versión: 7322808

Pregunta 1 (simple): ✓ 1.2s - OK
Pregunta 2 (media): ✓ 2.8s - OK
Pregunta 3 (compleja): ⚠️ 6.5s - Silencio de 4s durante consulta
Pregunta 4 (muy compleja): ✗ Timeout después de 12s

Notas:
- Implementar mensajes intermedios durante consultas largas
- Revisar timeout de function calling
```

## Próximos Pasos

1. **Implementar feedback progresivo** durante consultas largas
2. **Agregar caching** para consultas frecuentes
3. **Optimizar consultas** a múltiples routers (paralelización)
4. **Implementar circuit breaker** para routers lentos
5. **Mejorar instrucciones** del asistente para manejar esperas

## Referencias

- [handle_incoming_call.py:1-200](/usr/local/asterisk/inbound_calls/handle_incoming_call.py:1-200) - Configuración de OpenAI
- [mikrotik_api_client.py](/usr/local/asterisk/utils/mikrotik_api_client.py) - Cliente API MikroTik
- [FUNCTION_CALLING_GUIDE.md](FUNCTION_CALLING_GUIDE.md) - Guía de function calling
