# Mejoras para Evitar Silencios en Function Calling

## Problema
Cuando el asistente hace function calling a la API de MikroTik, se genera un silencio incómodo mientras espera la respuesta.

## Soluciones Implementadas

### 1. **Instrucciones Mejoradas** ✅ APLICADO
He modificado las instrucciones del sistema para que el asistente:
- **Avise antes** de hacer la consulta ("Déjame consultar esa información")
- **Mantenga conversación fluida** durante las consultas
- **Evite silencios largos**

Archivos modificados:
- `handle_incoming_call.py` (líneas 539-556)
- `handle_incoming_call_with_tools.py` (líneas 211-228)

### 2. **Mejoras Adicionales Opcionales**

#### A. Ajustar detección de voz para respuestas más rápidas
En la configuración de `turn_detection`, puedes ajustar:

```python
"turn_detection": {
    "type": "server_vad",
    "threshold": 0.2,           # Más bajo = más sensible
    "prefix_padding_ms": 300,   # Contexto antes del habla
    "silence_duration_ms": 100, # Reducir para respuestas más rápidas (actual: 100ms)
}
```

**Recomendación**: Puedes bajar `silence_duration_ms` a `80` para que el asistente responda más rápido.

#### B. Usar frases de relleno más naturales
Puedes enriquecer las instrucciones con variedad de frases:

```python
"instructions": """
...
Frases para usar mientras consultas información:
- "Dame un segundo mientras reviso eso"
- "Permíteme verificar en el sistema"
- "Voy a consultar esos datos ahora mismo"
- "Un momento, te busco esa información"
- "Déjame ver qué tenemos aquí"

Usa diferentes frases para que la conversación sea más natural.
"""
```

#### C. Reducir el timeout de la API (AVANZADO)
En `handle_incoming_call.py:786`, el timeout por defecto es 35 segundos:

```python
timeout = arguments.get('timeout', 35)  # Default 35s
```

Si tu API de MikroTik responde más rápido, puedes reducirlo a 15-20 segundos.

#### D. Implementar respuestas parciales (MUY AVANZADO)
OpenAI permite respuestas "streaming" donde el asistente puede hablar mientras procesa.
Esto requiere modificar la lógica de function calling para:
1. Decir algo ANTES de llamar a la función
2. Procesar la función
3. Responder con el resultado

## Cómo Probar las Mejoras

### 1. Reinicia el servicio
```bash
sudo systemctl restart asterisk-openai
```

### 2. Llama al sistema y pregunta:
- "¿Cuántos clientes tenemos conectados?"
- "¿Cuál es el estado de la red?"
- "Consulta el tráfico del router"

### 3. Observa el comportamiento
Ahora el asistente debería:
✅ Decir algo ANTES de hacer la consulta
✅ Mantener la conversación más fluida
✅ Evitar silencios largos

## Ejemplos de Conversación Mejorada

### ❌ ANTES (silencio sepulcral):
```
Usuario: "¿Cuántos clientes están conectados?"
Asistente: [SILENCIO 5-10 segundos mientras consulta API]
Asistente: "Hay 45 clientes conectados"
```

### ✅ AHORA (conversacional):
```
Usuario: "¿Cuántos clientes están conectados?"
Asistente: "Déjame consultar esa información"
[1 segundo]
Asistente: [Hace function call]
[2-3 segundos]
Asistente: "Tenemos 45 clientes conectados en este momento"
```

## Ajustes Finos según tu API

### Si tu API MikroTik es RÁPIDA (< 2 segundos):
```python
timeout = arguments.get('timeout', 10)  # Reducir timeout
```

### Si tu API MikroTik es LENTA (> 5 segundos):
Agrega frases de "sigue esperando":
```python
"instructions": """
...
Si la consulta tarda más de lo normal, puedes decir:
- "Esto está tardando un poco más de lo usual, dame otro segundo"
- "Estoy obteniendo los datos, gracias por tu paciencia"
"""
```

## Monitoreo

Revisa los logs para ver cuánto tardan las consultas:
```bash
tail -f /var/log/asterisk/openai_inbound.log | grep "Function call"
```

Busca líneas como:
```
🔧 Function call iniciada: consultar_mikrotik
⚙️ Ejecutando función: consultar_mikrotik
✓ Resultado obtenido (success: True)
```

## Notas Técnicas

La API Realtime de OpenAI tiene limitaciones:
- **NO** puede hablar Y ejecutar funciones simultáneamente
- **SÍ** puede decir algo ANTES de ejecutar la función
- **SÍ** puede usar frases de relleno naturales

Por eso las instrucciones son críticas para guiar al asistente a ser más conversacional.

## Próximos Pasos Recomendados

1. ✅ Probar las instrucciones mejoradas
2. ⏳ Ajustar `silence_duration_ms` si es necesario
3. ⏳ Medir tiempos reales de respuesta de tu API
4. ⏳ Agregar más variedad de frases si es necesario

## Recursos

- [OpenAI Realtime API Docs](https://platform.openai.com/docs/guides/realtime)
- [Function Calling Best Practices](https://platform.openai.com/docs/guides/function-calling)
- Logs del sistema: `/var/log/asterisk/openai_inbound.log`
