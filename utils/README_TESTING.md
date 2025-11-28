# Scripts de Prueba y Depuración

## Resumen Rápido

Este directorio contiene scripts para probar y depurar el sistema de llamadas con OpenAI y MikroTik.

## Scripts Disponibles

### 🧪 `test_complex_queries.py`
Prueba directa de la API de MikroTik con consultas de diferentes complejidades.

**Uso:**
```bash
python3 test_complex_queries.py
```

**Prueba:** Consultas a la API sin hacer llamada telefónica.

---

### 📞 `simulate_phone_questions.py`
Simula preguntas que harías por teléfono.

**Uso:**
```bash
python3 simulate_phone_questions.py
```

**Prueba:** 4 preguntas típicas de usuario (simple → muy compleja)

---

### 📊 `monitor_live_call.sh`
Monitor en tiempo real durante llamadas.

**Uso:**
```bash
./monitor_live_call.sh
```

**Luego:** Realiza tu llamada y observa los eventos.

---

## Flujo de Prueba Recomendado

1. **Primero ejecutar** `test_complex_queries.py` (sin llamada)
   - Verifica que la API de MikroTik funciona
   - Mide tiempos base

2. **Luego ejecutar** `simulate_phone_questions.py` (sin llamada)
   - Simula las preguntas que harás por teléfono
   - Valida tiempos esperados

3. **Finalmente**, iniciar `monitor_live_call.sh` y **hacer llamada real**
   - Observa comportamiento en vivo
   - Detecta problemas de audio/timeout

## Preguntas de Prueba para la Llamada

Cuando llames, prueba estas preguntas en orden:

| # | Pregunta | Tiempo Esperado |
|---|----------|-----------------|
| 1 | "Dame la lista de dispositivos activos del router 152 punto 1" | ~1.5s |
| 2 | "Dame el tráfico de las interfaces SFP del router 152 punto 1" | ~2s |
| 3 | "Dame el tráfico de las interfaces SFP de todos los routers" | ~5s ⚠️ |
| 4 | "Dame un resumen completo del estado de la red" | ~8s ⚠️ |

⚠️ = Observar si el asistente se mantiene "vivo" durante la espera

## Ver Guía Completa

Para más detalles: [/usr/local/asterisk/docs/TESTING_GUIDE.md](../docs/TESTING_GUIDE.md)
