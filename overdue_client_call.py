#!/usr/bin/env python3
import logging
import asyncio
import aiohttp
import websockets
import json
import os

# Configuración
DESTINATION_NUMBER = "3147654655"
AUDIO_PATH = "/tmp/morosos_telefono.wav"
ARI_URL = "http://localhost:8088/ari"
WEBSOCKET_URL = "ws://localhost:8088/ari/events"
USERNAME = "asterisk"
PASSWORD = "asterisk"

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
        """Inicializa la sesión HTTP"""
        if self.session is None:
            self.session = aiohttp.ClientSession(auth=aiohttp.BasicAuth(USERNAME, PASSWORD))

    async def cleanup_session(self):
        """Limpia la sesión HTTP"""
        if self.session:
            await self.session.close()
            self.session = None

    async def verificar_audio(self):
        """Verifica que el archivo de audio existe"""
        if not os.path.exists(AUDIO_PATH):
            logging.error(f"Archivo de audio no encontrado: {AUDIO_PATH}")
            return False
        return True

    async def iniciar_llamada(self):
        """Inicia la llamada saliente"""
        try:
            if not await self.verificar_audio():
                return False

            url = f"{ARI_URL}/channels"
            data = {
                "endpoint": f"Local/{DESTINATION_NUMBER}@from-voip",
                "app": "openai-app",
                "appArgs": ["dial"]  # Aseguramos que sea una lista
            }

            async with self.session.post(url, json=data) as response:
                if response.status == 200:
                    response_data = await response.json()
                    self.call_id = response_data['id']
                    logging.info(f"Llamada iniciada: {self.call_id}")
                    return True
                else:
                    error = await response.text()
                    logging.error(f"Error iniciando llamada: {error}")
                    return False

        except Exception as e:
            logging.error(f"Error en iniciar_llamada: {e}")
            return False

    async def reproducir_audio(self):
        """Reproduce el archivo de audio en el canal activo"""
        try:
            if not self.audio_started:
                url = f"{ARI_URL}/channels/{self.active_channel}/play"
                # Usar solo el nombre del archivo sin la ruta
                audio_name = os.path.basename(AUDIO_PATH)
                data = {
                    "media": f"sound:{audio_name}",
                    "lang": "es"
                }

                async with self.session.post(url, json=data) as response:
                    response_text = await response.text()
                    if response.status == 200:
                        playback = json.loads(response_text)
                        self.playback_map[playback['id']] = self.active_channel
                        self.audio_started = True
                        logging.info(f"Reproduciendo audio... ID: {playback['id']}")
                    else:
                        logging.error(f"Error reproduciendo audio: {response_text}")
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
                    # Verificar que args existe y tiene elementos
                    args = evento.get('args', [])
                    if args and args[0] == 'dial':
                        self.active_channel = evento['channel']['id']
                        logging.info(f"Canal activo: {self.active_channel}")
                        await self.establecer_formato_canal()
                        await asyncio.sleep(1)
                        await self.reproducir_audio()

                elif tipo == 'PlaybackFinished':
                    playback_id = evento['playback']['id']
                    if playback_id in self.playback_map:
                        logging.info(f"Reproducción finalizada: {playback_id}")
                        await self.finalizar_llamada()

                elif tipo == 'StasisEnd':
                    if evento.get('channel', {}).get('id') == self.active_channel:
                        logging.info("Llamada terminada por el destino")
                        self.active_channel = None

        except Exception as e:
            logging.error(f"Error en manejar_eventos: {e}")
            await self.finalizar_llamada()

    async def establecer_formato_canal(self):
        """Establece el formato de audio del canal a ulaw"""
        try:
            if self.active_channel:
                url = f"{ARI_URL}/channels/{self.active_channel}/variable"
                
                # Establecer formato de lectura
                params = {
                    "variable": "CHANNEL(audioreadformat)",
                    "value": "ulaw"
                }
                async with self.session.post(url, params=params) as response:
                    if not response.ok:
                        logging.error(f"Error estableciendo audioreadformat: {await response.text()}")

                # Establecer formato de escritura
                params["variable"] = "CHANNEL(audiowriteformat)"
                async with self.session.post(url, params=params) as response:
                    if not response.ok:
                        logging.error(f"Error estableciendo audiowriteformat: {await response.text()}")

                logging.info("Formato de audio del canal establecido a ulaw")

        except Exception as e:
            logging.error(f"Error estableciendo formato del canal: {e}")

    async def finalizar_llamada(self):
        """Finaliza la llamada correctamente"""
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
                f"{WEBSOCKET_URL}?api_key={USERNAME}:{PASSWORD}&app=openai-app"
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