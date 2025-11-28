# Sistema Integrado de Telefonía con Asterisk y OpenAI

Sistema completo de gestión telefónica que combina:
1. **Llamadas entrantes** con asistente de IA (OpenAI Realtime API)
2. **Llamadas salientes** automatizadas para cobranza

## 🚀 Características Principales

### Sistema de Llamadas Entrantes (OpenAI)
- Asistente virtual con voz en tiempo real
- Integración con API de MikroTik para consultas de red
- Function calling para consultas técnicas
- Manejo de audio bidireccional en tiempo real
- Soporte para codec ulaw/alaw

### Sistema de Llamadas Salientes (Cobranza)
- Llamadas automáticas a clientes con pagos pendientes
- Integración con MySQL para gestión de clientes
- Reproducción de mensajes de voz personalizados
- Sistema de reintentos inteligente
- Registro de resultados en base de datos

## 📋 Requisitos

### Dependencias del Sistema
```bash
# Asterisk con módulos
- chan_sip
- res_ari
- app_stasis

# Python 3.10+
sudo apt install python3 python3-pip

# FFmpeg para conversión de audio
sudo apt install ffmpeg
```

### Dependencias Python
```bash
pip install aiohttp websockets asyncio mysql-connector-python requests websocket-client
```

## ⚙️ Configuración

### 1. Variables de Entorno

Crea el archivo `/usr/local/asterisk/.env`:

```bash
# Asterisk ARI
ASTERISK_USERNAME=Asterisk
ASTERISK_PASSWORD=tu_password_ari
ASTERISK_HOST=localhost
ASTERISK_PORT=8088

# OpenAI Realtime API
OPENAI_API_KEY=sk-proj-XXXXXXXXXXXX
OPENAI_REALTIME_MODEL=gpt-4o-realtime-preview-2024-12-17

# MikroTik API (opcional)
MIKROTIK_API_URL=http://10.0.0.9:5050
ENABLE_MIKROTIK_TOOLS=true

# MySQL (para sistema de cobranza)
MYSQL_SERVER=localhost
MYSQL_USER=tu_usuario
MYSQL_PASSWORD=tu_password
MYSQL_DATABASE=isp_database

# Red
LOCAL_IP_ADDRESS=45.61.59.204

# Logs
LOG_FILE_PATH=/var/log/asterisk/inbound_openai.log
```

### 2. Configuración de Asterisk

#### `/etc/asterisk/extensions.conf`
```ini
[from-voip]
; Llamadas entrantes con OpenAI
exten => 3241000752,1,Answer()
    same => n,Set(CHANNEL(audioreadformat)=ulaw)
    same => n,Set(CHANNEL(audiowriteformat)=ulaw)
    same => n,Stasis(openai-app)
    same => n,Hangup()

; Llamadas salientes
exten => _X.,1,NoOp(Llamada saliente a ${EXTEN})
    same => n,Set(CHANNEL(audioreadformat)=ulaw)
    same => n,Set(CHANNEL(audiowriteformat)=ulaw)
    same => n,Dial(SIP/voip_issabel/${EXTEN})
    same => n,Stasis(overdue-app)
    same => n,Hangup()

[stasis-openai]
exten => external_start,1,NoOp(External Media iniciado para OpenAI)
    same => n,Return()

[stasis-overdue]
exten => _X.,1,NoOp(Llamada en Stasis para clientes morosos: ${EXTEN})
    same => n,Answer()
    same => n,Wait(1)
    same => n,Return()
```

#### `/etc/asterisk/ari.conf`
```ini
[general]
enabled = yes
pretty = yes
allowed_origins = *

[Asterisk]
type = user
read_only = no
password = tu_password_ari
password_format = plain
```

#### `/etc/asterisk/sip.conf`
```ini
[general]
context=from-voip
allowguest=yes
udpbindaddr=0.0.0.0:5060
tcpenable=no
transport=udp
qualify=yes
nat=force_rport,comedia
externip=TU_IP_PUBLICA
localnet=192.168.0.0/255.255.255.0

register => usuario:password@voip.proveedor.com/numero

[voip_issabel]
type=friend
host=voip.proveedor.com
port=5060
username=usuario
secret=password
fromuser=usuario
fromdomain=voip.proveedor.com
nat=force_rport,comedia
insecure=port,invite
disallow=all
allow=ulaw
allow=alaw
dtmfmode=rfc2833
context=from-voip
qualify=yes
```

**IMPORTANTE:** Después de modificar configuraciones:
```bash
# Recargar dialplan
asterisk -rx "dialplan reload"

# Recargar SIP
asterisk -rx "sip reload"

# O reiniciar Asterisk completamente
systemctl restart asterisk
```

### 3. Servicio systemd

Archivo: `/etc/systemd/system/openai-inbound-calls.service`

```ini
[Unit]
Description=OpenAI Realtime API - Inbound Calls Handler
Documentation=file:///usr/local/asterisk/README.md
After=network.target asterisk.service
Requires=asterisk.service

[Service]
Type=simple
User=asterisk
Group=asterisk
WorkingDirectory=/usr/local/asterisk/inbound_calls
EnvironmentFile=/usr/local/asterisk/.env
ExecStart=/usr/bin/python3 /usr/local/asterisk/inbound_calls/handle_incoming_call.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=openai-inbound

# Límites de recursos
MemoryLimit=512M
CPUQuota=50%

[Install]
WantedBy=multi-user.target
```

Activar el servicio:
```bash
systemctl daemon-reload
systemctl enable openai-inbound-calls.service
systemctl start openai-inbound-calls.service
systemctl status openai-inbound-calls.service
```

## 🗂️ Estructura del Proyecto

```
/usr/local/asterisk/
├── docs/                              # Documentación
│   ├── TROUBLESHOOTING.md            # Guía de solución de problemas
│   ├── FUNCTION_CALLING_GUIDE.md     # Guía de function calling con OpenAI
│   ├── INTEGRATION_SUMMARY.md        # Integración con MikroTik
│   └── otros documentos técnicos
├── inbound_calls/                     # Sistema de llamadas entrantes
│   └── handle_incoming_call.py       # Script principal OpenAI
├── outbound_calls/                    # Sistema de llamadas salientes
│   └── llamada_clientes_moroso.py    # Script de cobranza
├── utils/                             # Utilidades y pruebas
│   ├── mikrotik_api_client.py        # Cliente API MikroTik
│   ├── demo_overdue_call.py          # Demo de llamadas salientes
│   ├── test_*.py                      # Scripts de prueba
│   └── monitor_*.sh                   # Scripts de monitoreo
├── .env                               # Variables de entorno (NO subir a git)
├── .gitignore                         # Archivos ignorados por git
└── README.md                          # Este archivo
```

## 🔧 Uso

### Llamadas Entrantes (OpenAI)

El servicio se ejecuta automáticamente y escucha llamadas entrantes:

```bash
# Ver estado
systemctl status openai-inbound-calls.service

# Ver logs en tiempo real
journalctl -u openai-inbound-calls.service -f

# Reiniciar servicio
systemctl restart openai-inbound-calls.service
```

### Llamadas Salientes (Cobranza)

Ejecutar manualmente o vía cron:

```bash
cd /usr/local/asterisk/outbound_calls
python3 llamada_clientes_moroso.py
```

### Pruebas y Monitoreo

```bash
# Probar integración MikroTik
cd /usr/local/asterisk/utils
python3 test_mikrotik_integration.py

# Monitorear llamadas
./monitor_calls.sh

# Monitorear function calls
./monitor_function_calls.sh
```

## 📊 Monitoreo y Logs

### Logs del Sistema
- **Asterisk general:** `/var/log/asterisk/full`
- **Aplicación OpenAI:** `/var/log/asterisk/inbound_openai.log`
- **Servicio systemd:** `journalctl -u openai-inbound-calls.service`

### Comandos de Diagnóstico

```bash
# Ver canales activos
asterisk -rx "core show channels"

# Ver estado SIP
asterisk -rx "sip show peers"
asterisk -rx "sip show registry"

# Ver aplicaciones Stasis
asterisk -rx "ari show apps"

# Ver módulos
asterisk -rx "module show like chan_sip"

# Monitoreo en tiempo real
tail -f /var/log/asterisk/full | grep -E "(StasisStart|Answer|Hangup)"
```

## 🐛 Solución de Problemas

### Problema: Asistente se queda mudo durante consultas largas

**Síntoma:** El asistente dice "un momento por favor" y nunca vuelve a responder

**Causa:** Las consultas largas (>20s) bloqueaban el thread del WebSocket, impidiendo que responda a pings de OpenAI. Después de ~30s, OpenAI cierra la conexión (error 1011: keepalive ping timeout).

**Solución Implementada:** Threading asíncrono en `handle_function_call_done()` (líneas 666-721)
- Las funciones ahora se ejecutan en un thread separado
- El WebSocket principal queda libre para manejar pings
- Ver documentación completa: `docs/SOLUCION_FINAL_THREADING.md`

### Problema: GPT asistente está mudo desde el inicio

**Causa:** Error en WebSocket de OpenAI con ping_interval/ping_timeout

**Solución:** Verificar en `handle_incoming_call.py`:
```python
ws.run_forever(
    ping_interval=90,  # DEBE SER MAYOR que ping_timeout
    ping_timeout=30
)
```

### Problema: Módulo chan_sip no carga

**Causa:** Permisos incorrectos en `/etc/asterisk/sip.conf`

**Solución:**
```bash
chown asterisk:asterisk /etc/asterisk/sip.conf
systemctl restart asterisk
```

### Problema: Llamadas se cuelgan inmediatamente

**Verificar:**
1. SIP trunk registrado: `asterisk -rx "sip show registry"`
2. Módulo chan_sip activo: `asterisk -rx "module show like chan_sip"`
3. Configuración allowguest en sip.conf

**Ver guía completa:** `docs/TROUBLESHOOTING.md`

## 📚 Documentación Adicional

### Documentación Técnica Principal
- **[SOLUCION_FINAL_THREADING.md](docs/SOLUCION_FINAL_THREADING.md)** - ⭐ Solución de threading para consultas largas
- **[TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md)** - Guía completa de solución de problemas
- **[FUNCTION_CALLING_GUIDE.md](docs/FUNCTION_CALLING_GUIDE.md)** - Cómo usar function calling con OpenAI
- **[INTEGRATION_SUMMARY.md](docs/INTEGRATION_SUMMARY.md)** - Integración con API de MikroTik
- **[TESTING_GUIDE.md](docs/TESTING_GUIDE.md)** - Guía de pruebas y validación

### Documentación de Desarrollo
- **[CAMBIOS_FEEDBACK_PROGRESIVO.md](docs/CAMBIOS_FEEDBACK_PROGRESIVO.md)** - Historia del desarrollo de la solución
- **[MEJORAS_KEEPALIVE_Y_TIMEOUT.md](docs/MEJORAS_KEEPALIVE_Y_TIMEOUT.md)** - Mejoras en configuración de WebSocket
- **[PROTECCION_TIMEOUTS.md](docs/PROTECCION_TIMEOUTS.md)** - Protección contra timeouts

## 🔐 Seguridad

**IMPORTANTE:**
- El archivo `.env` contiene credenciales sensibles y NO debe subirse a git
- Ya está incluido en `.gitignore`
- Cambiar contraseñas por defecto en producción
- Usar HTTPS/WSS en producción para APIs externas
- Revisar `allowguest=yes` en sip.conf (solo para desarrollo)

## 📝 Licencia

Proyecto privado - Todos los derechos reservados

## 👥 Autores

- Omar - Propietario del proyecto
- Desarrollado con asistencia de Claude Code

## 🔄 Historial de Cambios

Ver archivo `CAMBIOS_REALIZADOS.md` para detalles completos.

### Versión Actual (Nov 2025)
- ✅ Sistema de llamadas entrantes con OpenAI funcional
- ✅ Integración con MikroTik API
- ✅ Function calling implementado
- ✅ **Threading asíncrono para consultas largas** (solución definitiva)
- ✅ Corrección de bug ping_interval/ping_timeout
- ✅ Corrección de permisos chan_sip
- ✅ Sistema de llamadas salientes para cobranza
- ✅ Documentación organizada en carpeta docs/
- ✅ Scripts de prueba y monitoreo en utils/

### Cambio Importante (2025-11-28)
**Solución de Threading para Consultas Largas:**
- Problema: Asistente mudo durante consultas >20s
- Solución: Ejecución de funciones en threads separados
- Resultado: Comunicación fluida durante consultas largas
- Ver: `docs/SOLUCION_FINAL_THREADING.md`
