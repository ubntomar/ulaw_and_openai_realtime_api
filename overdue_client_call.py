#!/usr/bin/env python3

import logging
import asyncio
import aiohttp
import websockets
import json
import os
import time
import mysql.connector
from mysql.connector import Error
from datetime import datetime, timedelta

# Configuración
DESTINATION_NUMBER = "573147654655"  # Número con prefijo del país 57xxxxxxxxx
ARI_URL = "http://localhost:8088/ari"
WEBSOCKET_URL = "ws://localhost:8088/ari/events"
USERNAME = os.getenv('ASTERISK_USERNAME')
PASSWORD = os.getenv('ASTERISK_PASSWORD')
AUDIO_FILE = "morosos"  # Nombre del archivo de audio a reproducir

# Configuración de reintentos
MAX_RETRIES = 5  # Número máximo de intentos para una llamada fallida
RETRY_DELAY = 120  # Tiempo en segundos entre reintentos (2 minutos)
CALL_TIMEOUT = 60  # Tiempo máximo en segundos para esperar a que la llamada sea contestada
AUDIO_START_TIMEOUT = 15  # Tiempo máximo en segundos para esperar a que el audio comience a reproducirse
MAX_SILENT_CALL_DURATION = 20  # Tiempo máximo en segundos para mantener una llamada sin audio

# Configuración de MySQL (comentada por defecto, descomentar cuando se necesite)
# MYSQL_CONFIG = {
#     'host': 'localhost',
#     'user': os.getenv('MYSQL_USER'),
#     'password': os.getenv('MYSQL_PASSWORD'),
#     'database': 'overdue_calls'
# }

if not USERNAME or not PASSWORD:
    logging.error("Environment variables ASTERISK_USERNAME and ASTERISK_PASSWORD must be set")
    exit(1)

TRUNK_NAME = "voip_issabel"  # Nombre del trunk SIP

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s.%(msecs)03d - %(levelname)s - %(funcName)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[
        logging.StreamHandler(),  # Salida a consola
        logging.FileHandler('/tmp/overdue_client_calls.log')  # Salida a archivo
    ]
)

class CallStatus:
    INITIATED = "INITIATED"
    RINGING = "RINGING"
    ANSWERED = "ANSWERED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    TIMEOUT = "TIMEOUT"
    AUDIO_FAILED = "AUDIO_FAILED"  # Nuevo estado para cuando el audio no se reproduce

class LlamadorAutomatico:
    def __init__(self, destination=DESTINATION_NUMBER):
        self.playback_map = {}
        self.active_channel = None
        self.call_id = None
        self.session = None
        self.audio_started = False
        self.audio_requested_time = None
        self.audio_started_time = None
        self.call_status = None
        self.call_start_time = None
        self.destination = destination
        self.attempt_count = 0
        self.timeout_task = None
        self.audio_timeout_task = None
        self.silent_call_timeout_task = None
        self.db_connection = None

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

    def setup_db_connection(self):
        """Establece conexión con la base de datos MySQL"""
        # Descomentar cuando se implemente MySQL
        # try:
        #     self.db_connection = mysql.connector.connect(**MYSQL_CONFIG)
        #     logging.info("Conexión a MySQL establecida")
        # except Error as e:
        #     logging.error(f"Error conectando a MySQL: {e}")
        pass

    def close_db_connection(self):
        """Cierra la conexión con la base de datos"""
        # Descomentar cuando se implemente MySQL
        # if self.db_connection and self.db_connection.is_connected():
        #     self.db_connection.close()
        #     logging.info("Conexión a MySQL cerrada")
        pass

    def log_call_attempt(self, status, duration=None):
        """Registra un intento de llamada en la base de datos"""
        # Descomentar cuando se implemente MySQL
        # if not self.db_connection or not self.db_connection.is_connected():
        #     self.setup_db_connection()
        #
        # if self.db_connection and self.db_connection.is_connected():
        #     try:
        #         cursor = self.db_connection.cursor()
        #         query = """
        #         INSERT INTO call_attempts (destination_number, call_id, status, attempt_number, duration, timestamp)
        #         VALUES (%s, %s, %s, %s, %s, %s)
        #         """
        #         timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        #         values = (self.destination, self.call_id, status, self.attempt_count, duration, timestamp)
        #         cursor.execute(query, values)
        #         self.db_connection.commit()
        #         cursor.close()
        #         logging.info(f"Registro de llamada guardado en la base de datos: {status}")
        #     except Error as e:
        #         logging.error(f"Error registrando llamada en MySQL: {e}")
        # else:
        #     logging.warning("No se pudo registrar la llamada. Sin conexión a la base de datos.")

        # Por ahora, solo registramos en el log
        log_message = f"CALL LOG: Número={self.destination}, ID={self.call_id}, Estado={status}, Intento={self.attempt_count}"
        if duration is not None:
            log_message += f", Duración={duration}s"

        # Registramos el estado actual de audio para diagnóstico
        audio_status = "AUDIO_STARTED" if self.audio_started else "NO_AUDIO"
        log_message += f", Audio={audio_status}"

        # Si hay tiempo de solicitud de audio, registramos el tiempo transcurrido
        if self.audio_requested_time:
            request_time = time.time() - self.audio_requested_time
            log_message += f", Tiempo desde solicitud de audio={request_time:.2f}s"

        logging.info(log_message)

    async def iniciar_llamada(self):
        """Inicia una llamada saliente usando el trunk SIP"""
        self.attempt_count += 1
        self.call_status = CallStatus.INITIATED
        self.call_start_time = time.time()

        try:
            url = f"{ARI_URL}/channels"
            data = {
                "endpoint": f"SIP/{TRUNK_NAME}/{self.destination}",
                "app": "overdue-app",
                "callerId": "\"Llamada Automatica\" <3241000752>",
                "variables": {
                    "CHANNEL(language)": "es",
                }
            }

            logging.info(f"Iniciando llamada a {self.destination} via trunk {TRUNK_NAME} (Intento {self.attempt_count})")
            logging.debug(f"Datos de la llamada: {json.dumps(data, indent=2)}")

            async with self.session.post(url, json=data) as response:
                response_text = await response.text()
                if response.status == 200:
                    response_data = json.loads(response_text)
                    self.call_id = response_data['id']
                    logging.info(f"Llamada iniciada: {self.call_id}")

                    # Configurar un timeout para la llamada
                    self.timeout_task = asyncio.create_task(self.call_timeout())

                    self.log_call_attempt(CallStatus.INITIATED)
                    return True
                else:
                    logging.error(f"Error iniciando llamada: {response_text}")
                    self.call_status = CallStatus.FAILED
                    self.log_call_attempt(CallStatus.FAILED)
                    return False

        except Exception as e:
            logging.error(f"Error en iniciar_llamada: {e}")
            self.call_status = CallStatus.FAILED
            self.log_call_attempt(CallStatus.FAILED)
            return False

    async def call_timeout(self):
        """Maneja el timeout de la llamada si no hay respuesta"""
        await asyncio.sleep(CALL_TIMEOUT)
        try:
            if self.call_status not in [CallStatus.ANSWERED, CallStatus.COMPLETED]:
                logging.warning(f"Timeout de llamada después de {CALL_TIMEOUT} segundos")
                self.call_status = CallStatus.TIMEOUT
                self.log_call_attempt(CallStatus.TIMEOUT)
                await self.finalizar_llamada()
        except Exception as e:
            logging.error(f"Error en call_timeout: {e}")
            logging.exception("Traceback completo:")

    async def audio_start_timeout(self):
        """Maneja el timeout si el audio no comienza a reproducirse"""
        await asyncio.sleep(AUDIO_START_TIMEOUT)
        if self.active_channel and not self.audio_started and self.call_status == CallStatus.ANSWERED:
            logging.warning(f"Timeout esperando inicio de reproducción de audio después de {AUDIO_START_TIMEOUT} segundos")
            # Verificar si el playback_map tiene entradas
            if self.playback_map:
                logging.warning(f"Tenemos {len(self.playback_map)} playbacks en el mapa, pero audio_started=False")
                for playback_id, channel in self.playback_map.items():
                    logging.warning(f"Playback ID: {playback_id}, Canal: {channel}")
            else:
                logging.warning("No hay playbacks registrados en el mapa")

            self.call_status = CallStatus.AUDIO_FAILED
            self.log_call_attempt(CallStatus.AUDIO_FAILED)
            logging.info("Finalizando llamada debido a fallo en inicio de audio")
            await self.finalizar_llamada()

    async def silent_call_timeout(self):
        """Finaliza la llamada si permanece demasiado tiempo sin actividad de audio"""
        await asyncio.sleep(MAX_SILENT_CALL_DURATION)
        if self.active_channel and self.audio_requested_time and not self.audio_started and self.call_status == CallStatus.ANSWERED:
            elapsed = time.time() - self.audio_requested_time
            logging.warning(f"Llamada sin audio activo durante {elapsed:.1f} segundos, finalizando")

            # Verificar si tenemos playbacks registrados
            if self.playback_map:
                logging.warning(f"Hay {len(self.playback_map)} playbacks registrados pero audio_started=False")
                for playback_id, channel in self.playback_map.items():
                    logging.warning(f"Playback registrado: ID={playback_id}, Canal={channel}")

                # Como medida extrema, forzamos audio_started a True si hay playbacks registrados
                # Esto evitará que colgamos una llamada que posiblemente tiene audio reproduciendo
                logging.warning("Forzando audio_started=True como medida preventiva")
                self.audio_started = True
                self.audio_started_time = time.time()
                return

            self.call_status = CallStatus.AUDIO_FAILED
            self.log_call_attempt(CallStatus.AUDIO_FAILED)
            await self.finalizar_llamada()

    async def reproducir_audio(self):
        """Reproduce el archivo de audio"""
        if not self.audio_started and self.active_channel:
            try:
                self.audio_requested_time = time.time()
                url = f"{ARI_URL}/channels/{self.active_channel}/play"
                data = {
                    "media": f"sound:{AUDIO_FILE}"
                }

                # Cancelar timeouts existentes antes de crear nuevos
                if self.audio_timeout_task:
                    self.audio_timeout_task.cancel()
                if self.silent_call_timeout_task:
                    self.silent_call_timeout_task.cancel()

                # Configurar timeout para inicio de audio
                self.audio_timeout_task = asyncio.create_task(self.audio_start_timeout())

                # Configurar timeout para llamada silenciosa
                self.silent_call_timeout_task = asyncio.create_task(self.silent_call_timeout())

                async with self.session.post(url, json=data) as response:
                    response_text = await response.text()
                    logging.debug(f"Respuesta de reproducción de audio: {response_text}")
                    if response.status == 201:
                        playback = json.loads(response_text)
                        playback_id = playback['id']
                        logging.info(f"Playback ID generado: {playback_id}")
                        self.playback_map[playback_id] = self.active_channel
                        logging.info(f"Reproducción de audio solicitada para canal {self.active_channel}")

            # Registrar estado actual
                        logging.debug(f"Estado después de solicitar audio - playback_map: {self.playback_map}, audio_started: {self.audio_started}")

                        # Programar una verificación de finalización de la llamada
                        # Esto es un respaldo en caso de que los eventos de PlaybackFinished no se procesen correctamente
                        asyncio.create_task(self.check_call_completion(playback_id))
                    else:
                        logging.error(f"Error reproduciendo audio: {response_text}")
                        logging.error(f"Data: {json.dumps(data, indent=2)}")
                        self.call_status = CallStatus.AUDIO_FAILED
                        await self.finalizar_llamada()
            except Exception as e:
                logging.error(f"Error en reproducir_audio: {e}")
                self.call_status = CallStatus.AUDIO_FAILED
                await self.finalizar_llamada()

    async def check_call_completion(self, playback_id):
        """Verifica si un playback ha terminado para finalizar la llamada"""
        try:
            # Tiempo estimado para la reproducción del audio + margen
            await asyncio.sleep(30)  # Esperamos 30 segundos, tiempo suficiente para que termine cualquier audio

            if self.active_channel and playback_id in self.playback_map and self.call_status not in [CallStatus.COMPLETED, CallStatus.FAILED]:
                # Si después de 30 segundos la llamada sigue activa y no se ha marcado como completada
                # asumimos que el PlaybackFinished no se procesó correctamente
                logging.warning(f"Detectado posible audio completado sin evento PlaybackFinished para {playback_id}")
                logging.warning("Finalizando llamada por mecanismo de seguridad")

                # Verificar estado actual
                url = f"{ARI_URL}/playbacks/{playback_id}"
                try:
                    async with self.session.get(url) as response:
                        if response.status == 404:
                            # Si el playback ya no existe, asumimos que ya terminó
                            logging.info(f"Playback {playback_id} ya no existe, asumimos que terminó")
                            self.call_status = CallStatus.COMPLETED
                            await self.finalizar_llamada(status=CallStatus.COMPLETED)
                        else:
                            # Si obtenemos otra respuesta, vamos a verificar el estado
                            playback_data = await response.json()
                            playback_state = playback_data.get('state')
                            logging.info(f"Estado actual del playback {playback_id}: {playback_state}")

                            if playback_state in ['done', 'cancelled']:
                                # Si ya terminó pero no recibimos el evento
                                self.call_status = CallStatus.COMPLETED
                                await self.finalizar_llamada(status=CallStatus.COMPLETED)
                except Exception as e:
                    logging.error(f"Error verificando estado del playback: {e}")
                    # Si hay error, finalizamos la llamada por seguridad
                    self.call_status = CallStatus.COMPLETED
                    await self.finalizar_llamada(status=CallStatus.COMPLETED)
        except Exception as e:
            logging.error(f"Error en check_call_completion: {e}")
            logging.exception("Traceback completo:")

    async def manejar_eventos(self, websocket):
        """Procesa eventos de WebSocket"""
        try:
            async for mensaje in websocket:
                evento = json.loads(mensaje)
                tipo = evento.get('type')
                logging.debug(f"Evento recibido: {tipo}")

                if tipo == 'Dial':
                    # Verificar si la llamada está sonando
                    dial_state = evento.get('dialstatus')
                    if dial_state == 'RINGING':
                        self.call_status = CallStatus.RINGING
                        logging.info("Llamada está timbrando")

                elif tipo == 'StasisStart':
                    # La llamada fue respondida y entró en la aplicación Stasis
                    self.active_channel = evento['channel']['id']
                    self.call_status = CallStatus.ANSWERED
                    logging.info(f"Canal activo: {self.active_channel} - Llamada contestada")

                    # Cancelar el timeout si existe
                    if self.timeout_task:
                        self.timeout_task.cancel()
                        self.timeout_task = None

                    # Para ver si hay algún playback en progreso, solicitamos su estado
                    try:
                        url = f"{ARI_URL}/playbacks"
                        async with self.session.get(url) as response:
                            if response.status == 200:
                                playbacks = await response.json()
                                logging.info(f"Playbacks activos: {len(playbacks)}")
                                for pb in playbacks:
                                    logging.info(f"  - ID: {pb.get('id')}, Canal: {pb.get('target_uri')}, Estado: {pb.get('state')}")
                            else:
                                logging.warning("No se pudo obtener información de playbacks activos")
                    except Exception as e:
                        logging.error(f"Error consultando playbacks: {e}")

                    # Pequeña pausa para asegurarnos que el canal está listo
                    await asyncio.sleep(1)

                    # Intentar reproducir el audio
                    await self.reproducir_audio()

                # Si no se ha reproducido el audio, verificar por qué
                    if not self.audio_started and not self.audio_requested_time:
                        logging.error("No se pudo solicitar la reproducción de audio")
                        self.call_status = CallStatus.AUDIO_FAILED
                        await self.finalizar_llamada()
                    else:
                        logging.info("Esperando reproducción de audio...")

                elif tipo == 'PlaybackFinished':
                    playback_id = evento['playback']['id']
                    if playback_id in self.playback_map:
                        logging.info("Audio reproducido completamente")
                        # Calcular duración de la reproducción
                        if self.audio_started_time:
                            audio_duration = time.time() - self.audio_started_time
                            logging.info(f"Duración de reproducción: {audio_duration:.2f} segundos")

                        # Pequeña pausa antes de colgar para asegurar que el último audio se escuche completamente
                        await asyncio.sleep(2)
                        logging.info("Finalizando llamada después de reproducción de audio")
                        await self.finalizar_llamada(status=CallStatus.COMPLETED)

                elif tipo == 'StasisEnd':
                    if evento.get('channel', {}).get('id') == self.active_channel:
                        logging.info("Llamada terminada por el destino")
                        self.active_channel = None
                        if self.call_status == CallStatus.ANSWERED:
                            self.call_status = CallStatus.COMPLETED

                elif tipo == 'ChannelStateChange':
                    state = evento.get('channel', {}).get('state')
                    logging.info(f"Estado del canal cambiado a: {state}")
                    if state == 'Up' and self.call_status != CallStatus.ANSWERED:
                        self.call_status = CallStatus.ANSWERED

                elif tipo == 'ChannelDestroyed':
                    channel_id = evento.get('channel', {}).get('id')
                    if channel_id == self.call_id:
                        logging.info(f"Canal destruido: {channel_id}")

                        # Calcular duración de la llamada
                        call_duration = None
                        if self.call_start_time:
                            call_duration = round(time.time() - self.call_start_time)

                        # Si la llamada no fue contestada o no tuvo audio y se destruyó el canal, marcarla como fallida
                        if self.call_status not in [CallStatus.COMPLETED]:
                            # Si fue contestada pero no hubo audio, usar AUDIO_FAILED
                            if self.call_status == CallStatus.ANSWERED and not self.audio_started:
                                self.call_status = CallStatus.AUDIO_FAILED
                                logging.warning("Llamada contestada pero sin reproducción de audio")
                            # Si no fue contestada, marcar como FAILED
                            elif self.call_status not in [CallStatus.AUDIO_FAILED]:
                                self.call_status = CallStatus.FAILED

                            self.log_call_attempt(self.call_status, call_duration)

                            # Si podemos reintentar, programamos el próximo intento
                            if self.attempt_count < MAX_RETRIES:
                                retry_reason = "fallo de audio" if self.call_status == CallStatus.AUDIO_FAILED else "llamada fallida"
                                logging.info(f"Programando reintento #{self.attempt_count + 1} en {RETRY_DELAY} segundos debido a {retry_reason}")
                                await asyncio.sleep(RETRY_DELAY)
                                # Reiniciamos estados para el nuevo intento
                                self.active_channel = None
                                self.call_id = None
                                self.audio_started = False
                                self.audio_requested_time = None
                                self.audio_started_time = None
                                # Iniciamos nuevo intento
                                if await self.iniciar_llamada():
                                    continue  # Continuamos escuchando eventos
                                else:
                                    # Si falla el reintento, terminamos
                                    break
                            else:
                                logging.warning(f"Número máximo de intentos ({MAX_RETRIES}) alcanzado para {self.destination}")
                                break
                        else:
                            # Si la llamada fue exitosa, lo registramos
                            if self.call_status == CallStatus.ANSWERED and call_duration:
                                self.log_call_attempt(CallStatus.COMPLETED, call_duration)
                            break

        except Exception as e:
            logging.error(f"Error en manejar_eventos: {e}")
            await self.finalizar_llamada()

    async def finalizar_llamada(self, status=None):
        """Finaliza la llamada activa"""
        try:
            # Cancelar todos los timeouts
            for task in [self.timeout_task, self.audio_timeout_task, self.silent_call_timeout_task]:
                if task:
                    task.cancel()

            self.timeout_task = None
            self.audio_timeout_task = None
            self.silent_call_timeout_task = None

            if status:
                self.call_status = status

            # Calcular duración de la llamada si existe tiempo de inicio
            call_duration = None
            if self.call_start_time:
                call_duration = round(time.time() - self.call_start_time)
            logging.info(f"Finalizando llamada con estado: {self.call_status}")
            logging.info(f"Canal activo: {self.active_channel}")
            if self.active_channel:
                url = f"{ARI_URL}/channels/{self.active_channel}"
                async with self.session.delete(url) as response:
                    if response.ok:
                        logging.info(f"Llamada finalizada exitosamente (duración: {call_duration}s)")
                        # Si la llamada fue exitosa, registramos COMPLETED
                        if self.call_status == CallStatus.ANSWERED and not status:
                            self.log_call_attempt(CallStatus.COMPLETED, call_duration)
                    else:
                        response_text = await response.text()
                        # No lanzar error si el canal ya no existe (probablemente ya está colgado)
                        if "Channel not found" in response_text:
                            logging.warning("Canal ya no existe, probablemente la llamada ya finalizó")
                        else:
                            logging.error(f"Error finalizando llamada: {response_text}")

                        # Si hubo error al finalizar, registramos el estado actual
                        if not status:  # No sobrescribir el estado si ya se ha pasado uno
                            self.log_call_attempt(self.call_status or CallStatus.FAILED, call_duration)
            logging.info("Llamada finalizada")
        except Exception as e:
            logging.error(f"Error finalizando llamada: {e}")
        finally:
            self.active_channel = None
            self.call_id = None
            self.audio_started = False
            self.audio_requested_time = None
            self.audio_started_time = None

    async def ejecutar(self):
        """Flujo principal de ejecución"""
        try:
            # Configurar la conexión a la base de datos (comentado por defecto)
            # self.setup_db_connection()

            await self.setup_session()
            async with websockets.connect(
                f"{WEBSOCKET_URL}?api_key={USERNAME}:{PASSWORD}&app=overdue-app",
                ping_interval=30,
                ping_timeout=10
            ) as websocket:
                if await self.iniciar_llamada():
                    await self.manejar_eventos(websocket)

        except websockets.exceptions.ConnectionClosed as e:
            logging.error(f"Conexión WebSocket cerrada: {e}")
        except Exception as e:
            logging.error(f"Error en ejecución principal: {e}")
            await self.finalizar_llamada()
        finally:
            await self.cleanup_session()
            self.close_db_connection()

class CallManager:
    """Clase para gestionar varias llamadas, útil para futuras integraciones con MySQL"""

    def __init__(self):
        self.db_connection = None
        self.pending_calls = []
        self.completed_calls = []
        self.failed_calls = []

    def setup_db_connection(self):
        """Establece conexión con la base de datos MySQL"""
        # Descomentar cuando se implemente MySQL
        # try:
        #     self.db_connection = mysql.connector.connect(**MYSQL_CONFIG)
        #     logging.info("Conexión a MySQL establecida")
        #     return True
        # except Error as e:
        #     logging.error(f"Error conectando a MySQL: {e}")
        #     return False
        return False

    def close_db_connection(self):
        """Cierra la conexión con la base de datos"""
        # Descomentar cuando se implemente MySQL
        # if self.db_connection and self.db_connection.is_connected():
        #     self.db_connection.close()
        #     logging.info("Conexión a MySQL cerrada")
        pass

    def load_pending_calls(self):
        """Carga las llamadas pendientes desde la base de datos"""
        # Descomentar cuando se implemente MySQL
        # if not self.db_connection or not self.db_connection.is_connected():
        #     if not self.setup_db_connection():
        #         return False
        #
        # try:
        #     cursor = self.db_connection.cursor(dictionary=True)
        #     query = """
        #     SELECT c.id, c.phone_number, c.client_name, c.last_attempt, c.attempts
        #     FROM overdue_clients c
        #     WHERE c.status = 'PENDING'
        #     AND (c.last_attempt IS NULL OR c.last_attempt < %s)
        #     AND c.attempts < %s
        #     ORDER BY c.priority DESC, c.last_attempt ASC
        #     LIMIT 50
        #     """
        #     # Solo cargar llamadas que no se hayan intentado en las últimas 2 horas
        #     min_time = (datetime.now() - timedelta(hours=2)).strftime('%Y-%m-%d %H:%M:%S')
        #     cursor.execute(query, (min_time, MAX_RETRIES))
        #
        #     self.pending_calls = cursor.fetchall()
        #     cursor.close()
        #
        #     logging.info(f"Cargadas {len(self.pending_calls)} llamadas pendientes")
        #     return len(self.pending_calls) > 0
        # except Error as e:
        #     logging.error(f"Error cargando llamadas pendientes: {e}")
        #     return False

        # Para pruebas sin MySQL, usar un número de teléfono predefinido
        self.pending_calls = [{"phone_number": DESTINATION_NUMBER, "attempts": 0}]
        return True

    def update_call_status(self, call_id, status, attempt=None):
        """Actualiza el estado de una llamada en la base de datos"""
        # Descomentar cuando se implemente MySQL
        # if not self.db_connection or not self.db_connection.is_connected():
        #     if not self.setup_db_connection():
        #         return False
        #
        # try:
        #     cursor = self.db_connection.cursor()
        #
        #     # Actualizar timestamp y número de intentos
        #     query = """
        #     UPDATE overdue_clients
        #     SET status = %s, last_attempt = %s
        #     """
        #
        #     values = [status, datetime.now().strftime('%Y-%m-%d %H:%M:%S')]
        #
        #     if attempt is not None:
        #         query += ", attempts = %s"
        #         values.append(attempt)
        #
        #     query += " WHERE id = %s"
        #     values.append(call_id)
        #
        #     cursor.execute(query, tuple(values))
        #     self.db_connection.commit()
        #     cursor.close()
        #
        #     logging.info(f"Actualizado estado de llamada {call_id} a {status}")
        #     return True
        # except Error as e:
        #     logging.error(f"Error actualizando estado de llamada: {e}")
        #     return False
        pass

    async def process_pending_calls(self):
        """Procesa todas las llamadas pendientes"""
        if not self.load_pending_calls():
            logging.warning("No hay llamadas pendientes para procesar")
            return

        for call_data in self.pending_calls:
            phone_number = call_data.get("phone_number")
            logging.info(f"Procesando llamada a {phone_number}")

            llamador = LlamadorAutomatico(destination=phone_number)
            await llamador.ejecutar()

            # Esperar un tiempo entre llamadas para no saturar el sistema
            await asyncio.sleep(5)

async def main():
    """Función principal para ejecutar el script"""
    # Para una sola llamada
    llamador = LlamadorAutomatico()
    await llamador.ejecutar()

    # Para procesar múltiples llamadas (descomentar cuando se implemente MySQL)
    # call_manager = CallManager()
    # await call_manager.process_pending_calls()

if __name__ == "__main__":
    asyncio.run(main())
