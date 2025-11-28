# Guía de Solución de Problemas

## Problemas Comunes y Soluciones

### 1. Error: "Ensure ping_interval > ping_timeout"

**Síntoma:**
```
ERROR - Error en inicio: Ensure ping_interval > ping_timeout
```

**Causa:** Los parámetros del WebSocket están configurados incorrectamente.

**Solución:** En `handle_incoming_call.py`, asegúrate de que:
```python
ws.run_forever(
    ping_interval=60,  # Debe ser MAYOR que ping_timeout
    ping_timeout=20
)
```

### 2. Módulo chan_sip no carga

**Síntoma:**
```
ERROR[7528] loader.c: chan_sip declined to load.
NOTICE[7528] chan_sip.c: Unable to load config sip.conf
```

**Causa:** Permisos incorrectos en `/etc/asterisk/sip.conf`

**Solución:**
```bash
chown asterisk:asterisk /etc/asterisk/sip.conf
systemctl restart asterisk
asterisk -rx "module show like chan_sip"
```

### 3. Llamadas se cuelgan inmediatamente

**Diagnóstico:**
```bash
# Verificar que SIP trunk esté registrado
asterisk -rx "sip show registry"

# Verificar módulo SIP
asterisk -rx "module show like chan_sip"

# Ver llamadas activas
asterisk -rx "core show channels"
```

**Posibles causas:**
- Módulo chan_sip no está corriendo
- SIP trunk no está registrado con el proveedor
- Configuración de `allowguest` incorrecta en sip.conf

### 4. GPT asistente está mudo (sin audio)

**Causa común:** Error en la conexión WebSocket con OpenAI

**Verificación:**
```bash
tail -f /var/log/asterisk/inbound_openai.log | grep -E "(OpenAI|Error|session)"
```

**Buscar:**
- "Iniciando conexión WebSocket con OpenAI"
- "session.update" - indica que la sesión se configuró
- Cualquier mensaje de error

### 5. Permisos de git para usuario omar

**Problema:** Usuario root realizó cambios y omar no puede hacer commit/push

**Solución:**
```bash
# Ajustar permisos de todo el proyecto
chown -R omar:omar /usr/local/asterisk

# Configurar git para omar
su - omar
cd /usr/local/asterisk
git config user.name "Omar"
git config user.email "omar@ejemplo.com"
```

## Comandos Útiles de Diagnóstico

### Verificar servicio OpenAI
```bash
systemctl status openai-inbound-calls.service
journalctl -u openai-inbound-calls.service -f
```

### Monitoreo de logs en tiempo real
```bash
# Logs de Asterisk
tail -f /var/log/asterisk/full

# Logs de aplicación OpenAI
tail -f /var/log/asterisk/inbound_openai.log

# Filtrar solo llamadas
tail -f /var/log/asterisk/full | grep -E "(StasisStart|Answer|Hangup)"
```

### Verificar conectividad OpenAI API
```bash
# Probar API key (requiere curl y jq)
OPENAI_KEY=$(grep "^OPENAI_API_KEY=" /usr/local/asterisk/.env | cut -d= -f2)
curl -s https://api.openai.com/v1/models \
  -H "Authorization: Bearer $OPENAI_KEY" | jq '.data[0].id'
```

### Verificar configuración de Asterisk
```bash
# Ver dialplan
asterisk -rx "dialplan show from-voip"

# Ver peers SIP
asterisk -rx "sip show peers"

# Ver canales externos
asterisk -rx "core show channels"
```

## Logs Importantes

1. **Asterisk general:** `/var/log/asterisk/full`
2. **Aplicación OpenAI:** `/var/log/asterisk/inbound_openai.log`
3. **Servicio systemd:** `journalctl -u openai-inbound-calls.service`

## Estructura de Archivos del Proyecto

```
/usr/local/asterisk/
├── docs/                              # Documentación
│   ├── TROUBLESHOOTING.md            # Esta guía
│   ├── FUNCTION_CALLING_GUIDE.md     # Guía de function calling
│   ├── INTEGRATION_SUMMARY.md        # Resumen de integración MikroTik
│   └── ...
├── inbound_calls/                     # Sistema de llamadas entrantes
│   └── handle_incoming_call.py       # Script principal OpenAI
├── outbound_calls/                    # Sistema de llamadas salientes
│   └── llamada_clientes_moroso.py    # Script de clientes morosos
├── utils/                             # Utilidades
│   ├── mikrotik_api_client.py        # Cliente API MikroTik
│   ├── test_*.py                      # Scripts de prueba
│   └── *.sh                           # Scripts de monitoreo
├── .env                               # Variables de entorno
└── README.md                          # Documentación principal
```
