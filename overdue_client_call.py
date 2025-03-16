#!/usr/bin/env python3
import logging
import asyncio
import aiohttp
import websockets
import json
import os

# CONDICIONES PARA EJECUTAR CORRECTAMENTE EL SCRIPT overdue_client_call.py
#
# 1. CONFIGURACIÓN DEL DIALPLAN
#    - El archivo /etc/asterisk/extensions.conf debe tener configurados los contextos [from-voip] y [stasis-openai]
#    - El dialplan debe estar activo (usar "sudo asterisk -rx 'dialplan reload'" si se hacen cambios)
#
# 2. VARIABLES DE ENTORNO
#    - Las variables ASTERISK_USERNAME y ASTERISK_PASSWORD deben estar configuradas
#    - Estas credenciales deben tener permisos para acceder a la API de Asterisk
#
# 3. ARCHIVOS DE AUDIO
#    - Los archivos de audio deben estar en formato .gsm
#    - Deben estar ubicados en /var/lib/asterisk/sounds/es_MX/
#    - El archivo debe llamarse "morosos.gsm" (o tener el nombre usado en "media": "sound:morosos")
#    - Los archivos deben tener permisos de lectura para el usuario asterisk (generalmente 644 o -rw-r--r--)
#    - El propietario debe ser asterisk:asterisk (chown asterisk:asterisk /var/lib/asterisk/sounds/es_MX/morosos.gsm)
#
# 4. CONECTIVIDAD
#    - El servicio Asterisk debe estar ejecutándose
#    - La API ARI debe estar habilitada en la URL http://localhost:8088/ari
#    - El WebSocket debe estar disponible en ws://localhost:8088/ari/events
#
# 5. CONFIGURACIÓN SIP
#    - El trunk SIP "voip_issabel" debe estar configurado y funcional
#    - El destino (DESTINATION_NUMBER = "573162950915") debe ser alcanzable desde el trunk
#
# 6. PERMISOS
#    - El usuario que ejecuta el script debe tener permisos para conectarse a la API y WebSocket
#    - El usuario debe estar en el grupo de asterisk o tener permisos sudo
#    - El archivo del script debe tener permisos de ejecución (chmod +x overdue_client_call.py)
#    - Si se usa para programar tareas, el crontab debe ejecutarse con el usuario correcto
#
# 7. DEPENDENCIAS
#    - Las bibliotecas aiohttp, websockets, asyncio deben estar instaladas
#    - Python 3.7+ para soporte de asyncio
#
# 8. APLICACIÓN ARI
#    - La aplicación "openai-app" debe estar definida en Asterisk
#    - La aplicación debe tener permisos para controlar canales y reproducir audio
#    - Verificar configuración en ari.conf (/etc/asterisk/ari.conf)
#
# 9. CONFIGURACIÓN DE CANAL
#    - El canal debe tener idioma configurado a "es" para encontrar los archivos de audio en español
#    - Los formatos de audio deben ser compatibles (aunque el script usa ulaw, Asterisk está usando gsm)
#
# 10. REINICIO DE SERVICIOS
#     - Para recargar el dialplan sin reiniciar: sudo asterisk -rx "dialplan reload"
#     - Para reiniciar completamente Asterisk: sudo systemctl restart asterisk
#     - Si hay cambios en ari.conf: sudo systemctl restart asterisk
#     - Si hay problemas con la API: sudo systemctl restart asterisk
#     - Para verificar el estado del servicio: sudo systemctl status asterisk
#     - Si el servicio no arranca: sudo journalctl -u asterisk para ver los errores
#
# 11. PERMISOS DE DIRECTORIOS
#     - El directorio /var/lib/asterisk/sounds/ debe tener permisos 755 (drwxr-xr-x)
#     - El directorio /var/lib/asterisk/sounds/es_MX/ debe tener permisos 755 (drwxr-xr-x)
#     - Si se crean directorios personalizados, usar: sudo chown -R asterisk:asterisk /ruta/al/directorio
#
# 12. CONVERSIÓN DE FORMATOS DE AUDIO A GSM USANDO FFMPEG
#     - Instalar ffmpeg si no está instalado: sudo apt-get install ffmpeg
#
#     # Convertir de WAV a GSM (ideal que el WAV sea 8kHz, mono, 16-bit)
#     - Para archivos WAV: ffmpeg -i input.wav -ar 8000 -ac 1 -acodec gsm output.gsm
#     
#     # Convertir de MP3 a GSM (con remuestreo a 8kHz)
#     - Para archivos MP3: ffmpeg -i input.mp3 -ar 8000 -ac 1 -acodec gsm output.gsm
#     
#     # Para convertir un archivo y colocarlo directamente en la carpeta de sonidos de Asterisk
#     - ffmpeg -i input.mp3 -ar 8000 -ac 1 -acodec gsm /var/lib/asterisk/sounds/es_MX/morosos.gsm
#     
#     # Convertir múltiples archivos a la vez
#     - for file in *.mp3; do ffmpeg -i "$file" -ar 8000 -ac 1 -acodec gsm "${file%.mp3}.gsm"; done
#     
#     # Verificar si el archivo GSM es válido (decodificarlo)
#     - ffmpeg -i output.gsm -f wav - | aplay
#     
#     # Optimizar la calidad del audio antes de la conversión a GSM
#     - ffmpeg -i input.mp3 -af "highpass=f=300, lowpass=f=3400, volume=2" -ar 8000 -ac 1 -acodec gsm output.gsm
#
#     # Después de convertir, asegurarse de cambiar el propietario:
#     - sudo chown asterisk:asterisk /var/lib/asterisk/sounds/es_MX/output.gsm
#     - sudo chmod 644 /var/lib/asterisk/sounds/es_MX/output.gsm



# Configuración
DESTINATION_NUMBER = "573162950915"  # Número con prefijo del país 57xxxxxxxxx
AUDIO_PATH = "file:///var/lib/asterisk/sounds/morosos_ulaw.wav"  # Ruta del archivo de audio
ARI_URL = "http://localhost:8088/ari"
WEBSOCKET_URL = "ws://localhost:8088/ari/events"
USERNAME = os.getenv('ASTERISK_USERNAME')
PASSWORD = os.getenv('ASTERISK_PASSWORD')

if not USERNAME or not PASSWORD:
    logging.error("Environment variables ASTERISK_USERNAME and ASTERISK_PASSWORD must be set")
    exit(1)


TRUNK_NAME = "voip_issabel"  # Nombre del trunk SIP

logging.basicConfig(
    # filename="/tmp/shared_openai/ari_app.log",
    level=logging.DEBUG,
    format='%(asctime)s.%(msecs)03d - %(levelname)s - %(funcName)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

class LlamadorAutomatico:
    def __init__(self):
        self.playback_map = {}
        self.active_channel = None
        self.call_id = None
        self.session = None
        self.audio_started = False

    async def setup_session(self):
        if self.session is None:
            timeout = aiohttp.ClientTimeout(total=30)
            self.session = aiohttp.ClientSession(
                auth=aiohttp.BasicAuth(USERNAME, PASSWORD),
                timeout=timeout
            )

    async def cleanup_session(self):
        if self.session:
            await self.session.close()
            self.session = None

    async def iniciar_llamada(self):
        """Inicia una llamada saliente usando el trunk SIP"""
        try:
            url = f"{ARI_URL}/channels"
            data = {
                "endpoint": f"SIP/{TRUNK_NAME}/{DESTINATION_NUMBER}",
                "app": "openai-app",
                "callerId": "\"Llamada Automatica\" <3241000752>",
                "variables": {
                    "CHANNEL(language)": "es",
                    # "CHANNEL(audioreadformat)": "ulaw",
                    # "CHANNEL(audiowriteformat)": "ulaw"
                }
            }

            logging.info(f"Iniciando llamada a {DESTINATION_NUMBER} via trunk {TRUNK_NAME}")
            logging.debug(f"Datos de la llamada: {json.dumps(data, indent=2)}")

            async with self.session.post(url, json=data) as response:
                response_text = await response.text()
                if response.status == 200:
                    response_data = json.loads(response_text)
                    self.call_id = response_data['id']
                    logging.info(f"Llamada iniciada: {self.call_id}")
                    return True
                else:
                    logging.error(f"Error iniciando llamada: {response_text}")
                    return False

        except Exception as e:
            logging.error(f"Error en iniciar_llamada: {e}")
            return False

    async def reproducir_audio(self):
        """Reproduce el archivo de audio"""
        if not self.audio_started and self.active_channel:
            try:
                url = f"{ARI_URL}/channels/{self.active_channel}/play"
                data = {
                    "media": "sound:morosos2" 
                }
                #"media": "sound:morosos2"  #reproduce los audios .gsm almacenados en la carpeta /var/lib/asterisk/sounds/es_MX 
                async with self.session.post(url, json=data) as response:
                    response_text = await response.text()
                    logging.debug(f"Respuesta de reproducción de audio: {response_text}")
                    if response.status == 201:
                        playback = json.loads(response_text)
                        self.playback_map[playback['id']] = self.active_channel
                        self.audio_started = True
                        logging.info(f"Reproduciendo audio en canal {self.active_channel}")
                   
                    else:
                        logging.error(f"Error reproduciendo audio: {response_text}")
                        logging.error(f"Data: {json.dumps(data, indent=2)}")
                        await self.finalizar_llamada()


            except Exception as e:
                logging.error(f"Error en reproducir_audio: {e}")
                await self.finalizar_llamada()

    async def manejar_eventos(self, websocket):
        """Procesa eventos de WebSocket"""
        try:
            async for mensaje in websocket:
                evento = json.loads(mensaje)
                tipo = evento.get('type')
                logging.debug(f"Evento recibido: {tipo}")

                if tipo == 'StasisStart':
                    self.active_channel = evento['channel']['id']
                    logging.info(f"Canal activo: {self.active_channel}")
                    await asyncio.sleep(1)
                    await self.reproducir_audio()

                elif tipo == 'PlaybackFinished':
                    playback_id = evento['playback']['id']
                    if playback_id in self.playback_map:
                        logging.info("Audio reproducido completamente")
                        await asyncio.sleep(2)
                        await self.finalizar_llamada()

                elif tipo == 'StasisEnd':
                    if evento.get('channel', {}).get('id') == self.active_channel:
                        logging.info("Llamada terminada por el destino")
                        self.active_channel = None

                elif tipo == 'ChannelStateChange':
                    state = evento.get('channel', {}).get('state')
                    logging.info(f"Estado del canal cambiado a: {state}")

        except Exception as e:
            logging.error(f"Error en manejar_eventos: {e}")
            await self.finalizar_llamada()

    async def finalizar_llamada(self):
        """Finaliza la llamada activa"""
        try:
            if self.active_channel:
                url = f"{ARI_URL}/channels/{self.active_channel}"
                async with self.session.delete(url) as response:
                    if response.ok:
                        logging.info("Llamada finalizada exitosamente")
                    else:
                        logging.error(f"Error finalizando llamada: {await response.text()}")

        except Exception as e:
            logging.error(f"Error finalizando llamada: {e}")
        finally:
            self.active_channel = None
            self.call_id = None
            self.audio_started = False

    async def ejecutar(self):
        """Flujo principal de ejecución"""
        try:
            await self.setup_session()
            async with websockets.connect(
                f"{WEBSOCKET_URL}?api_key={USERNAME}:{PASSWORD}&app=openai-app",
                ping_interval=30,
                ping_timeout=10
            ) as websocket:
                if await self.iniciar_llamada():
                    await self.manejar_eventos(websocket)

        except Exception as e:
            logging.error(f"Error en ejecución principal: {e}")
            await self.finalizar_llamada()
        finally:
            await self.cleanup_session()

if __name__ == "__main__":
    llamador = LlamadorAutomatico()
    asyncio.run(llamador.ejecutar())