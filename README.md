# Sistema de Llamadas Automáticas para Clientes con Pagos Pendientes

Este sistema Python permite gestionar llamadas automáticas a clientes con facturas pendientes de pago, especialmente enfocadas en los días cercanos a su fecha de corte de servicio.

## Descripción

El script `mysql_overdue_client_call.py` consulta una base de datos MySQL para identificar clientes con facturas pendientes, realiza llamadas automáticas utilizando Asterisk, reproduce un mensaje informativo y registra los resultados en la base de datos.

### Características principales

- Integración con MySQL para obtener datos de clientes con facturas pendientes
- Validación de números de teléfono móviles colombianos
- Lógica de llamadas basada en días de corte del servicio
- Sistema de timeout por llamada para evitar costos excesivos
- Manejo completo del ciclo de vida de la llamada (iniciación, monitoreo, finalización)
- Actualización automática de registros en base de datos
- Sistema robusto de reintentos para llamadas fallidas

## Requisitos

### Dependencias Python

```bash
pip install mysql-connector-python aiohttp websockets asyncio
```

### Variables de Entorno

El script requiere las siguientes variables de entorno:

1. Para conexión a Asterisk:
   - `ASTERISK_USERNAME`
   - `ASTERISK_PASSWORD`

2. Para conexión a MySQL:
   - `MYSQL_DATABASE`
   - `MYSQL_PASSWORD`
   - `MYSQL_SERVER`
   - `MYSQL_USER`

## Configuración del Entorno Asterisk

### 1. Configuración del Dialplan

El archivo `/etc/asterisk/extensions.conf` debe tener configurados los contextos y extensions necesarios. A continuación se muestra la configuración actualizada:

#### Editar el archivo extensions.conf

```bash
sudo nano /etc/asterisk/extensions.conf
```

#### Configuración actual del dialplan

```ini
[from-voip]
; Regla específica para llamadas entrantes al número específico
exten => 3241000752,1,Answer()
    same => n,Set(CHANNEL(audioreadformat)=ulaw)
    same => n,Set(CHANNEL(audiowriteformat)=ulaw)
    same => n,Stasis(openai-app)
    same => n,Hangup()
    
; Regla general para llamadas salientes (cualquier otro número)
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

#### Explicación de los contextos:

1. **from-voip**: Este contexto maneja tanto las llamadas entrantes al número específico (3241000752) como las llamadas salientes a través del trunk SIP.

2. **stasis-openai**: Este contexto maneja las llamadas procesadas por la aplicación openai-app.

3. **stasis-overdue**: Este contexto maneja las llamadas procesadas por la aplicación overdue-app.

#### Aplicar los cambios al dialplan

Después de realizar cambios, debes recargar el dialplan para que Asterisk los aplique:

```bash
sudo asterisk -rx 'dialplan reload'
```

#### Verificar que el dialplan esté cargado correctamente

```bash
sudo asterisk -rx 'dialplan show stasis-overdue'
```

Este comando debería mostrar el contexto que acabas de crear.

### 2. Archivos de Audio

- Formato: `.gsm`
- Ubicación: `/usr/share/asterisk/sounds/es_MX/`
- Nombre del archivo: `morosos_natalia.gsm` (según configuración actual en el script)
- Permisos: `644` (-rw-r--r--)
- Propietario: `asterisk:asterisk`

```bash
sudo chown asterisk:asterisk /usr/share/asterisk/sounds/es_MX/morosos_natalia.gsm
sudo chmod 644 /usr/share/asterisk/sounds/es_MX/morosos_natalia.gsm
```

### 3. Conectividad

- El servicio Asterisk debe estar en ejecución
- La API ARI debe estar habilitada: `http://localhost:8088/ari`
- El WebSocket debe estar disponible: `ws://localhost:8088/ari/events`

### 4. Configuración SIP

- El trunk SIP `voip_issabel` debe estar configurado y funcional

### 5. Aplicación ARI

La API de Asterisk REST Interface (ARI) debe estar correctamente configurada para permitir que nuestro script interactúe con Asterisk.

#### Configurar ari.conf

Editar el archivo de configuración ARI:

```bash
sudo nano /etc/asterisk/ari.conf
```

Añadir la siguiente configuración:

```ini
[general]
enabled = yes
pretty = yes
allowed_origins = *

[Asterisk]
type = user
read_only = no
password = your_password
password_format = plain
```

Reemplaza `Asterisk` y `your_password` con los valores de `ASTERISK_USERNAME` y `ASTERISK_PASSWORD` que utilizará el script. Estos valores deben coincidir con las variables de entorno.

#### Aplicar cambios

Después de realizar cambios en ari.conf, es necesario reiniciar Asterisk:

```bash
sudo systemctl restart asterisk
```

#### Verificar configuración ARI

Para verificar que la API ARI esté funcionando correctamente:

```bash
curl -u Asterisk:your_password http://localhost:8088/ari/applications
```

Debería recibir una respuesta JSON con las aplicaciones registradas.

### 6. Permisos y Directorios

- El usuario que ejecuta el script debe tener permisos para la API
- Directorios de sonido deben tener permisos `755` (drwxr-xr-x)

## Conversión de Formatos de Audio a GSM

### Instalación de ffmpeg

```bash
sudo apt-get install ffmpeg
```

### Comandos de Conversión

#### De WAV a GSM
```bash
ffmpeg -i input.wav -ar 8000 -ac 1 -acodec gsm output.gsm
```

#### De MP3 a GSM
```bash
ffmpeg -i input.mp3 -ar 8000 -ac 1 -acodec gsm output.gsm
```

#### Convertir y colocar directamente en Asterisk
```bash
ffmpeg -i input.mp3 -ar 8000 -ac 1 -acodec gsm /usr/share/asterisk/sounds/es_MX/morosos_natalia.gsm
```

#### Audio optimizado para telefonía
```bash
ffmpeg -i input.mp3 -af "highpass=f=300, lowpass=f=3400, volume=2" -ar 8000 -ac 1 -acodec gsm output.gsm
```

#### Después de convertir
```bash
sudo chown asterisk:asterisk /usr/share/asterisk/sounds/es_MX/morosos_natalia.gsm
sudo chmod 644 /usr/share/asterisk/sounds/es_MX/morosos_natalia.gsm
```

## Lógica del Sistema de Llamadas

### Selección de Usuarios

El script selecciona usuarios para llamar basado en las siguientes condiciones:

1. El campo `outbound_call` debe ser `1` (marcado para llamada)
2. El campo `outbound_call_is_sent` debe ser `0` (no ha sido contactado aún)
3. Deben tener facturas pendientes (`cerrado = 0` con `saldo > 0`)
4. El día actual debe cumplir con relación al día de corte:
   - Debe ser exactamente un día antes del corte, o
   - Debe ser el día del corte, o
   - Debe ser posterior al día del corte

### Ejemplo de lógica de días de corte:

```
Usuario con corte el día 15:
- Si hoy es día 14: SÍ se realiza llamada (un día antes)
- Si hoy es día 13: NO se realiza llamada (dos días antes)
- Si hoy es día 5: NO se realiza llamada (varios días antes)
- Si hoy es día 15: SÍ se realiza llamada (día del corte)
- Si hoy es día 20: SÍ se realiza llamada (después del corte)
```

### Sistema de Timeout

Para evitar gastos excesivos en llamadas, cada llamada tiene un timeout individual de 90 segundos. Si este tiempo se excede, el script terminará automáticamente la llamada.

Además, hay un timeout global del script de 300 segundos (5 minutos) más 300 segundos adicionales por usuario, para evitar que el script se ejecute indefinidamente.

## Ejecución del Script

### Consultar Llamadas Programadas para Hoy

Antes de ejecutar las llamadas, puedes consultar qué clientes serían llamados hoy usando el script de consulta:

```bash
# Opción 1: Script simple
./ver_llamadas.sh

# Opción 2: Script Python directamente
python3 ver_llamadas_hoy.py
```

Este script muestra:
- ✅ Lista de clientes que serán llamados hoy
- ❌ Lista de clientes excluidos y las razones
- 💰 Deuda total de clientes a llamar
- 📊 Estadísticas detalladas por cliente

**Características del script de consulta:**
- NO realiza llamadas reales, solo consulta la base de datos
- Aplica las mismas reglas de filtrado que el script de llamadas
- Muestra información detallada: ID, nombre, teléfono, deuda, día de corte, intentos previos
- Útil para verificar antes de ejecutar las llamadas automáticas

**Ejemplo de salida:**

```
================================================================================
📅 CONSULTA DE LLAMADAS PROGRAMADAS PARA HOY: 2025-11-25
📆 Día del mes actual: 25
================================================================================

✅ Clientes que SERÁN llamados hoy: 5

+-----+------+-----------------------+--------------+---------+---------+------------+
|   # |   ID | Nombre                |     Teléfono | Deuda   |   Corte |   Intentos |
+=====+======+=======================+==============+=========+=========+============+
|   1 | 1616 | Luis Hugo Garcia      | 573218260348 | $60,000 |      24 |          0 |
|   2 | 1618 | Maria Rodriguez       | 573145678901 | $45,000 |      25 |          1 |
...
+-----+------+-----------------------+--------------+---------+---------+------------+

💰 Deuda total de clientes a llamar: $305,000
```

### Ejecución Manual de Llamadas

```bash
python3 outbound_calls/mysql_overdue_client_call.py
```

### Configuración como Tarea Programada (Cron)

Para ejecutar el script automáticamente a una hora específica cada día, puedes configurarlo como una tarea cron:

1. Abre el editor de crontab:
   ```bash
   crontab -e
   ```

2. Añade una línea para ejecutar el script a las 8:00 AM todos los días:
   ```bash
   0 8 * * * cd /usr/local/asterisk && export ASTERISK_USERNAME=Asterisk && export ASTERISK_PASSWORD=your_password && export MYSQL_DATABASE=database && export MYSQL_PASSWORD=password && export MYSQL_SERVER=server && export MYSQL_USER=user && python3 outbound_calls/mysql_overdue_client_call.py >> /tmp/llamadas_automaticas.log 2>&1
   ```

   Asegúrate de reemplazar:
   - Las variables de entorno con tus valores reales
   - La ruta del log si deseas cambiarlo

3. Guarda y cierra el editor.

### Configuración en un Archivo de Servicio Systemd

Para gestionar el script como un servicio, puedes crear un archivo de servicio systemd:

1. Crea un archivo de servicio:
   ```bash
   sudo nano /etc/systemd/system/llamadas-automaticas.service
   ```

2. Añade el siguiente contenido:
   ```ini
   [Unit]
   Description=Servicio de Llamadas Automáticas para Clientes Morosos
   After=network.target asterisk.service mysql.service

   [Service]
   Type=simple
   User=asterisk
   WorkingDirectory=/usr/local/asterisk
   Environment="ASTERISK_USERNAME=Asterisk"
   Environment="ASTERISK_PASSWORD=your_password"
   Environment="MYSQL_DATABASE=database"
   Environment="MYSQL_PASSWORD=password"
   Environment="MYSQL_SERVER=server"
   Environment="MYSQL_USER=user"
   ExecStart=/usr/bin/python3 outbound_calls/mysql_overdue_client_call.py
   Restart=on-failure
   RestartSec=60

   [Install]
   WantedBy=multi-user.target
   ```

3. Habilita y inicia el servicio:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable llamadas-automaticas.service
   sudo systemctl start llamadas-automaticas.service
   ```

4. Comprueba el estado del servicio:
   ```bash
   sudo systemctl status llamadas-automaticas.service
   ```

## Solución de Problemas

### Reinicio de Servicios
- Recargar dialplan: `sudo asterisk -rx "dialplan reload"`
- Reiniciar Asterisk: `sudo systemctl restart asterisk`
- Verificar estado: `sudo systemctl status asterisk`
- Ver logs de errores: `sudo journalctl -u asterisk`

### Problemas Comunes y Soluciones

1. **Error "Allocation failed" al iniciar llamadas**
   - **Síntoma**: El script muestra `Error initiating call: {"error":"Allocation failed"}`
   - **Causa**: Normalmente se debe a falta de recursos en Asterisk o problemas de conexión
   - **Solución**: Reiniciar el servicio Asterisk para liberar recursos
   ```bash
   sudo systemctl restart asterisk
   ```

2. **Error de conexión a la base de datos**
   - **Verificación**: Comprobar credenciales MySQL y conectividad
   ```bash
   mysql -h $MYSQL_SERVER -u $MYSQL_USER -p$MYSQL_PASSWORD -e "SELECT 1"
   ```

3. **Error en la API de Asterisk**
   - **Verificación**: Comprobar que Asterisk esté en ejecución y que la API esté habilitada
   ```bash
   sudo systemctl status asterisk
   curl -u $ASTERISK_USERNAME:$ASTERISK_PASSWORD http://localhost:8088/ari/applications
   ```

4. **Audio no se reproduce**
   - **Verificación**: Comprobar permisos y formato del archivo de audio
   ```bash
   ls -la /usr/share/asterisk/sounds/es_MX/morosos_natalia.gsm
   ```
   - **Solución**: Convertir el audio nuevamente al formato correcto y establecer permisos adecuados

5. **Llamadas no se realizan**
   - **Verificación**: Comprobar configuración del trunk SIP
   ```bash
   sudo asterisk -rx "sip show peers" | grep voip_issabel
   ```

6. **Error en la consulta SQL**
   - **Verificación**: Comprobar estructura de tablas y ejecutar consultas de prueba
   ```bash
   mysql -h $MYSQL_SERVER -u $MYSQL_USER -p$MYSQL_PASSWORD $MYSQL_DATABASE -e "DESCRIBE afiliados"
   mysql -h $MYSQL_SERVER -u $MYSQL_USER -p$MYSQL_PASSWORD $MYSQL_DATABASE -e "DESCRIBE factura"
   ```

7. **El script termina abruptamente**
   - **Verificación**: Comprobar logs para identificar timeouts o errores
   ```bash
   tail -n 100 /tmp/overdue_client_calls.log
   ```

## Registros y Depuración

### Logs del sistema
Los logs del script se almacenan en:
```
/tmp/overdue_client_calls.log
```

### Depuración Avanzada
Para una depuración más detallada, puedes habilitar más logging en el script cambiando el nivel a DEBUG:

```python
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s.%(msecs)03d - %(levelname)s - %(funcName)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('/tmp/overdue_client_calls.log')
    ]
)
```

## Estructura de la Base de Datos

### Tabla `afiliados`
Contiene información de los clientes y su estado de pago.

Campos relevantes:
- `id`: Identificador único del cliente
- `telefono`: Número de teléfono móvil
- `corte`: Día del mes en que se realiza el corte del servicio
- `outbound_call`: Marcador para realizar llamada (1=sí, 0=no)
- `outbound_call_is_sent`: Si ya se realizó la llamada (1=sí, 0=no)
- `outbound_call_attempts`: Número de intentos realizados
- `outbound_call_completed_at`: Fecha de completado

### Tabla `factura`
Contiene información de las facturas de los clientes.

Campos relevantes:
- `id-afiliado`: ID del cliente (referencia a afiliados.id)
- `saldo`: Monto pendiente de pago
- `cerrado`: Estado de la factura (1=pagado, 0=pendiente)

## Mantenimiento

Se recomienda verificar periódicamente:

1. Logs del sistema para detectar problemas de timeouts o errores
2. Base de datos para confirmar que los registros se actualizan correctamente
3. Calidad del audio para asegurar la comprensión del mensaje
4. Estado del servicio Asterisk para prevenir problemas de recursos

### Comprobaciones regulares recomendadas:

```bash
# Verificar estado del servicio Asterisk
sudo systemctl status asterisk

# Verificar conexiones SIP activas
sudo asterisk -rx "sip show peers"

# Verificar canales activos
sudo asterisk -rx "core show channels"

# Verificar aplicaciones ARI
sudo asterisk -rx "ari show apps"

# Verificar uso de recursos del sistema
top -b -n 1 | head -n 20
df -h
free -m
```

**Problema Identificado y Solucionado:**

- **Diagnóstico correcto:** El error "Allocation failed" NO era por tu código.
- **Causa real:** Trunk SIP en estado UNKNOWN.
- **Solución:** Reinicio de Asterisk restauró la conectividad:
  ```bash
  sudo systemctl restart asterisk
  ```

Actualmente puedes revisar los logs del sistema en `/tmp/overdue_client_calls.log` , `~/outbound_calls.log`


## Contacto y Soporte

Para problemas técnicos o consultas sobre este sistema, contactar al equipo de desarrollo responsable del mantenimiento.