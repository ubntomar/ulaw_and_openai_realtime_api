# Sistema de Llamadas Entrantes con OpenAI Realtime API

Este sistema maneja llamadas telefónicas entrantes utilizando Asterisk ARI y OpenAI Realtime API para conversaciones bidireccionales con inteligencia artificial.

## 📋 Tabla de Contenidos

- [Descripción](#descripción)
- [Arquitectura](#arquitectura)
- [Requisitos](#requisitos)
- [Instalación Rápida](#instalación-rápida)
- [Configuración](#configuración)
- [Uso](#uso)
- [Solución de Problemas](#solución-de-problemas)
- [Monitoreo y Logs](#monitoreo-y-logs)

---

## 🎯 Descripción

El sistema `handle_incoming_call.py` proporciona:

- **Conversaciones de IA en tiempo real** usando OpenAI Realtime API
- **Audio bidireccional** con codec G.711 ulaw (estándar telefónico)
- **Detección de voz automática** (VAD - Voice Activity Detection)
- **Manejo de múltiples llamadas simultáneas**
- **Reconexión automática** en caso de errores
- **Integración completa con Asterisk** vía ARI

---

## 🏗️ Arquitectura

```
┌─────────────────┐
│  Cliente llama  │
│  al 3241000752  │
└────────┬────────┘
         │
         ▼
┌─────────────────────────────────────┐
│  Asterisk PBX                       │
│  - Responde llamada                 │
│  - Configura codec ulaw             │
│  - Envía a Stasis(openai-app)       │
└────────┬───────────────────────────┘
         │ WebSocket ARI
         ▼
┌─────────────────────────────────────┐
│  handle_incoming_call.py            │
│  - AsteriskApp (eventos)            │
│  - RTPAudioHandler (audio UDP)      │
│  - OpenAIClient (IA conversacional) │
└────────┬───────────────────────────┘
         │
         ├──► RTP Stream (UDP)
         │    Puerto: 10000-20000
         │    Formato: G.711 ulaw 8kHz
         │
         └──► OpenAI WebSocket
              Modelo: gpt-4o-realtime-preview
```

---

## 📦 Requisitos

### Software

- **Python 3.8+**
- **Asterisk 16+** con ARI habilitado
- **Cuenta de OpenAI** con acceso a Realtime API

### Dependencias Python

```bash
pip install websockets aiohttp numpy scipy webrtcvad websocket-client
```

### Variables de Entorno Requeridas

```bash
ASTERISK_USERNAME      # Usuario ARI de Asterisk
ASTERISK_PASSWORD      # Contraseña ARI
ASTERISK_HOST          # Host de Asterisk (localhost o IP)
ASTERISK_PORT          # Puerto ARI (8088)
OPENAI_API_KEY         # API Key de OpenAI
LOCAL_IP_ADDRESS       # IP local para RTP
LOG_FILE_PATH          # Ruta del archivo de log
```

---

## 🚀 Instalación Rápida

### Método 1: Instalación Automática (Recomendado)

```bash
cd /usr/local/asterisk
sudo ./install_service.sh
```

Este script:
1. ✅ Crea el archivo `.env` desde `.env.example`
2. ✅ Te permite editar las credenciales
3. ✅ Crea el directorio de logs
4. ✅ Instala el servicio systemd
5. ✅ Habilita inicio automático

### Método 2: Instalación Manual

#### Paso 1: Crear archivo de configuración

```bash
cd /usr/local/asterisk
cp .env.example .env
nano .env
```

Edita las siguientes variables:

```bash
ASTERISK_USERNAME=Asterisk
ASTERISK_PASSWORD=tu_password_aqui
ASTERISK_HOST=localhost
ASTERISK_PORT=8088
OPENAI_API_KEY=sk-proj-tu-key-aqui
LOCAL_IP_ADDRESS=192.168.1.100
LOG_FILE_PATH=/var/log/asterisk/inbound_openai.log
```

#### Paso 2: Obtener IP local automáticamente

```bash
LOCAL_IP=$(hostname -I | awk '{print $1}')
echo "Tu IP local es: $LOCAL_IP"
```

#### Paso 3: Crear directorio de logs

```bash
sudo mkdir -p /var/log/asterisk
sudo chown asterisk:asterisk /var/log/asterisk
```

#### Paso 4: Instalar servicio systemd

```bash
sudo cp openai-inbound-calls.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable openai-inbound-calls
```

---

## ⚙️ Configuración

### Configuración de Asterisk

El dialplan en `/etc/asterisk/extensions.conf` debe tener:

```ini
[from-voip]
exten => 3241000752,1,Answer()
    same => n,Set(CHANNEL(audioreadformat)=ulaw)
    same => n,Set(CHANNEL(audiowriteformat)=ulaw)
    same => n,Stasis(openai-app)
    same => n,Hangup()

[stasis-openai]
exten => external_start,1,NoOp(External Media iniciado)
    same => n,Return()
```

Recargar dialplan:

```bash
sudo asterisk -rx "dialplan reload"
```

### Configuración de OpenAI

El sistema usa el modelo `gpt-4o-realtime-preview-2024-12-17` por defecto.

Para cambiar el modelo, agrega en `.env`:

```bash
OPENAI_REALTIME_MODEL=gpt-4o-realtime-preview-2024-12-17
```

Modelos disponibles:
- `gpt-4o-realtime-preview-2024-12-17` (estable, recomendado)
- `gpt-4o-realtime-preview-2024-10-01` (versión anterior)

### Personalizar Instrucciones del Asistente

Edita el archivo `handle_incoming_call.py` en la línea ~504:

```python
"instructions": """
    Eres un asistente virtual amable.
    Ayudas a los clientes con consultas sobre su servicio.
    Mantén las respuestas breves y claras.
"""
```

---

## 🎮 Uso

### Iniciar el Servicio

```bash
sudo systemctl start openai-inbound-calls
```

### Verificar Estado

```bash
sudo systemctl status openai-inbound-calls
```

Salida esperada:
```
● openai-inbound-calls.service - OpenAI Realtime API - Inbound Calls Handler
     Loaded: loaded (/etc/systemd/system/openai-inbound-calls.service; enabled)
     Active: active (running) since ...
```

### Ver Logs en Tiempo Real

```bash
sudo journalctl -u openai-inbound-calls -f
```

O desde el archivo de log:

```bash
tail -f /var/log/asterisk/inbound_openai.log
```

### Detener el Servicio

```bash
sudo systemctl stop openai-inbound-calls
```

### Reiniciar el Servicio

```bash
sudo systemctl restart openai-inbound-calls
```

### Ejecución Manual (para pruebas)

```bash
cd /usr/local/asterisk
./start_inbound_calls.sh
```

---

## 🔧 Solución de Problemas

### Problema 1: Servicio no inicia

**Síntoma**: `systemctl status` muestra "failed"

**Solución**:

```bash
# Ver logs detallados
sudo journalctl -u openai-inbound-calls -n 50

# Verificar variables de entorno
cat /usr/local/asterisk/.env

# Verificar que Asterisk está corriendo
sudo systemctl status asterisk
```

### Problema 2: Variables de entorno no configuradas

**Síntoma**: Error "Variables de ambiente requeridas no encontradas"

**Solución**:

```bash
# Editar .env
sudo nano /usr/local/asterisk/.env

# Verificar que todas las variables están configuradas
grep -v "^#" /usr/local/asterisk/.env | grep "="
```

### Problema 3: No se escucha audio

**Síntoma**: La llamada se conecta pero no hay audio

**Verificaciones**:

1. **RTP Ports**: Verificar que los puertos UDP 10000-20000 están abiertos

```bash
sudo netstat -nlpu | grep python
```

2. **IP Local**: Verificar que `LOCAL_IP_ADDRESS` es correcta

```bash
hostname -I
ip addr show
```

3. **Codec**: Verificar en logs que el codec es `ulaw`

```bash
grep "Codec detectado" /var/log/asterisk/inbound_openai.log
```

### Problema 4: OpenAI API Key inválida

**Síntoma**: Error de autenticación con OpenAI

**Solución**:

```bash
# Verificar que la key está configurada
echo $OPENAI_API_KEY | head -c 20

# Probar la key con curl
curl https://api.openai.com/v1/models \
  -H "Authorization: Bearer $OPENAI_API_KEY" \
  | jq '.data[0]'
```

### Problema 5: Conexión ARI falla

**Síntoma**: Error "Conexión cerrada, reintentando..."

**Verificaciones**:

1. **ARI habilitado**:

```bash
grep "enabled = yes" /etc/asterisk/ari.conf
```

2. **Credenciales correctas**:

```bash
curl -u Asterisk:password http://localhost:8088/ari/asterisk/info
```

3. **Websocket disponible**:

```bash
telnet localhost 8088
```

### Problema 6: Modelo de OpenAI no disponible

**Síntoma**: Error sobre modelo no encontrado

**Solución**:

Verificar modelos disponibles en tu cuenta:

```bash
curl https://api.openai.com/v1/models \
  -H "Authorization: Bearer $OPENAI_API_KEY" \
  | jq '.data[] | select(.id | contains("realtime"))'
```

---

## 📊 Monitoreo y Logs

### Logs del Sistema

**Journalctl** (logs de systemd):

```bash
# Últimas 100 líneas
sudo journalctl -u openai-inbound-calls -n 100

# Logs desde hoy
sudo journalctl -u openai-inbound-calls --since today

# Logs con nivel ERROR solamente
sudo journalctl -u openai-inbound-calls -p err
```

**Archivo de log**:

```bash
# Ver últimas líneas
tail -f /var/log/asterisk/inbound_openai.log

# Buscar errores
grep ERROR /var/log/asterisk/inbound_openai.log

# Buscar llamadas recibidas
grep "Nueva llamada recibida" /var/log/asterisk/inbound_openai.log
```

### Métricas Importantes

**Logs a monitorear**:

1. **Conexión establecida**:
```
Conexión ARI establecida
```

2. **Llamada recibida**:
```
Nueva llamada recibida - Canal: PJSIP/...
```

3. **RTP iniciado**:
```
Socket RTP vinculado a 192.168.1.100:15234
```

4. **OpenAI conectado**:
```
Conexión WebSocket con OpenAI
```

5. **Sesión configurada**:
```
msg_type updated recibido, ahora enviaré audio chunks
```

### Comandos de Diagnóstico

```bash
# Ver canales activos en Asterisk
sudo asterisk -rx "core show channels"

# Ver aplicaciones ARI
sudo asterisk -rx "ari show apps"

# Ver sockets Python escuchando
sudo netstat -nlpu | grep python

# Ver procesos del script
ps aux | grep handle_incoming_call

# Uso de memoria del proceso
ps aux --sort=-%mem | grep python | head -5
```

---

## 📝 Notas Importantes

### Diferencias con Llamadas Salientes

| Aspecto | Entrantes (este sistema) | Salientes |
|---------|--------------------------|-----------|
| Audio | Bidireccional (IA conversacional) | Unidireccional (pregrabado) |
| Complejidad | Alta (3 WebSockets) | Baja (REST API) |
| Base de datos | No registra (por ahora) | Sí registra |
| Inicio | Automático (servicio) | Crontab |

### Limitaciones Conocidas

1. **No registra en base de datos**: Las llamadas entrantes no se guardan en MySQL (mejora futura)
2. **Sin timeout global**: Las conversaciones pueden durar indefinidamente
3. **Latencia de audio**: Chunk de 600 bytes causa ~75ms de latency (optimizar a 160 bytes)

### Mejoras Futuras

- [ ] Registro de llamadas en MySQL
- [ ] Timeout global para conversaciones
- [ ] Optimizar chunk size (600 → 160 bytes)
- [ ] Dashboard web para monitoreo
- [ ] Transcripciones de llamadas
- [ ] Métricas de uso de OpenAI

---

## 🆘 Soporte

Para problemas técnicos:

1. **Revisar logs**: `sudo journalctl -u openai-inbound-calls -f`
2. **Ver estado**: `sudo systemctl status openai-inbound-calls`
3. **Reiniciar servicio**: `sudo systemctl restart openai-inbound-calls`
4. **Revisar README principal**: `/usr/local/asterisk/README.md`

---

## 📄 Licencia

Este sistema es parte del proyecto de llamadas automáticas para clientes.

---

**Última actualización**: Noviembre 2025
