#!/usr/bin/env python3
import logging
import asyncio
import aiohttp
import websockets
import json
import os

# Configuración
DESTINATION_NUMBER = "573147654655"  # Número con prefijo del país
AUDIO_PATH = "file:///tmp/morosos_telefono.wav"
ARI_URL = "http://localhost:8088/ari"
WEBSOCKET_URL = "ws://localhost:8088/ari/events"
USERNAME = "asterisk"
PASSWORD = "-Agwist2017Ubnt1234"
TRUNK_NAME = "voip_issabel"  # Nombre del trunk SIP

logging.basicConfig(
    filename="/tmp/shared_openai/ari_app.log",
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
                    "CHANNEL(audioreadformat)": "ulaw",
                    "CHANNEL(audiowriteformat)": "ulaw"
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
                    "media": "sound:morosos"
                }
 
                async with self.session.post(url, json=data) as response:
                    response_text = await response.text()
                    logging.debug(f"Respuesta de reproducción de audio: {response_text}")
                    if True:
                        playback = json.loads(response_text)
                        self.playback_map[playback['id']] = self.active_channel
                        self.audio_started = True
                        logging.info(f"Reproduciendo audio en canal {self.active_channel}")
                   
                    # else:
                    #     logging.error(f"Error reproduciendo audio: {response_text}")
                    #     logging.error(f"Data: {json.dumps(data, indent=2)}")
                    #     # await self.finalizar_llamada()


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