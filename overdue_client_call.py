
#!/usr/bin/env python3
import logging
import asyncio
import aiohttp
import websockets
import json

# Configuración
NUMERO_DESTINO = "3147654655"  # Número a llamar
AUDIO_PATH = "file:///tmp/morosos.wav"
ARI_URL = "http://localhost:8088/ari"
WEBSOCKET_URL = "ws://localhost:8088/ari/events"
USUARIO = "asterisk"
CONTRASENA = "asterisk"

logging.basicConfig(
    filename="/tmp/shared_openai/ari_app.log",
    level=logging.INFO,
    format='%(asctime)s.%(msecs)03d - %(levelname)s - %(funcName)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

class LlamadorAutomatico:
    def __init__(self):
        self.playback_map = {}
        self.canal_activo = None
        self.id_llamada = None

    async def iniciar_llamada(self):
        """Inicia la llamada saliente"""
        try:
            url = f"{ARI_URL}/channels"
            data = {
                "endpoint": f"SIP/{NUMERO_DESTINO}",
                "app": "llamador-morosos",
                "appArgs": "dial"
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url,
                    json=data,
                    auth=aiohttp.BasicAuth(USUARIO, CONTRASENA)
                ) as response:
                    if response.status == 200:
                        respuesta = await response.json()
                        self.id_llamada = respuesta['id']
                        logging.info(f"Llamada iniciada: {self.id_llamada}")
                    else:
                        error = await response.text()
                        logging.error(f"Error iniciando llamada: {error}")

        except Exception as e:
            logging.error(f"Error en iniciar_llamada: {e}")

    async def reproducir_audio(self):
        """Reproduce el archivo de audio en el canal activo"""
        try:
            url = f"{ARI_URL}/channels/{self.canal_activo}/play"
            data = {"media": AUDIO_PATH}

            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url,
                    json=data,
                    auth=aiohttp.BasicAuth(USUARIO, CONTRASENA)
                ) as response:
                    if response.status == 200:
                        playback = await response.json()
                        self.playback_map[playback['id']] = self.canal_activo
                        logging.info("Reproduciendo audio...")
                    else:
                        error = await response.text()
                        logging.error(f"Error reproduciendo audio: {error}")
                        await self.finalizar_llamada()

        except Exception as e:
            logging.error(f"Error en reproducir_audio: {e}")
            await self.finalizar_llamada()

    async def manejar_eventos(self, websocket):
        """Procesa eventos de WebSocket"""
        async for mensaje in websocket:
            evento = json.loads(mensaje)
            tipo = evento.get('type')

            if tipo == 'StasisStart':
                if 'args' in evento and evento['args'][0] == 'dial':
                    self.canal_activo = evento['channel']['id']
                    logging.info(f"Canal activo: {self.canal_activo}")
                    await self.reproducir_audio()

            elif tipo == 'PlaybackFinished':
                playback_id = evento['playback']['id']
                if playback_id in self.playback_map:
                    await self.finalizar_llamada()

            elif tipo == 'StasisEnd':
                if 'channel' in evento and evento['channel']['id'] == self.canal_activo:
                    logging.info("Llamada finalizada por el destino")
                    self.canal_activo = None

    async def finalizar_llamada(self):
        """Finaliza la llamada correctamente"""
        try:
            if self.canal_activo:
                url = f"{ARI_URL}/channels/{self.canal_activo}"
                async with aiohttp.ClientSession() as session:
                    await session.delete(
                        url,
                        auth=aiohttp.BasicAuth(USUARIO, CONTRASENA)
                    )
                logging.info("Llamada finalizada exitosamente")

        except Exception as e:
            logging.error(f"Error finalizando llamada: {e}")
        finally:
            self.canal_activo = None
            self.id_llamada = None

    async def ejecutar(self):
        """Flujo principal de ejecución"""
        try:
            async with websockets.connect(
                f"{WEBSOCKET_URL}?api_key={USUARIO}:{CONTRASENA}&app=llamador-morosos"
            ) as websocket:

                # Iniciar la llamada
                await self.iniciar_llamada()

                # Manejar eventos
                await self.manejar_eventos(websocket)

        except Exception as e:
            logging.error(f"Error en ejecución principal: {e}")
            await self.finalizar_llamada()
        finally:
            await websocket.close()

if __name__ == "__main__":
    llamador = LlamadorAutomatico()
    asyncio.run(llamador.ejecutar())
