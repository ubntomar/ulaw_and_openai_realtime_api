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

# Configuration
ARI_URL = "http://localhost:8088/ari"
WEBSOCKET_URL = "ws://localhost:8088/ari/events"
USERNAME = os.getenv('ASTERISK_USERNAME')
PASSWORD = os.getenv('ASTERISK_PASSWORD')
AUDIO_FILE = "morosos_natalia"  # Audio file name to play

# MySQL Configuration from environment variables
MYSQL_DATABASE = os.getenv('MYSQL_DATABASE')
MYSQL_PASSWORD = os.getenv('MYSQL_PASSWORD')
MYSQL_SERVER = os.getenv('MYSQL_SERVER')
MYSQL_USER = os.getenv('MYSQL_USER')

# Retry configuration
MAX_RETRIES = 3  # Maximum number of attempts for a failed call
RETRY_DELAY = 120  # Time in seconds between retries (2 minutes)
CALL_TIMEOUT = 90  # Maximum time in seconds to wait for a call to be answered
AUDIO_START_TIMEOUT = 15  # Maximum time in seconds to wait for audio to start playing
MAX_SILENT_CALL_DURATION = 20  # Maximum time in seconds to keep a call without audio
BASE_SCRIPT_TIMEOUT = 300  # Base timeout in seconds (5 minutes)
ADDITIONAL_TIME_PER_USER = 300  # Additional time per user in seconds (5 minutes)

if not USERNAME or not PASSWORD:
    logging.error("Environment variables ASTERISK_USERNAME and ASTERISK_PASSWORD must be set")
    exit(1)

if not MYSQL_DATABASE or not MYSQL_PASSWORD or not MYSQL_SERVER or not MYSQL_USER:
    logging.error("MySQL environment variables must be set (MYSQL_DATABASE, MYSQL_PASSWORD, MYSQL_SERVER, MYSQL_USER)")
    exit(1)

TRUNK_NAME = "voip_issabel"  # SIP trunk name

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s.%(msecs)03d - %(levelname)s - %(funcName)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[
        logging.StreamHandler(),  # Console output
        logging.FileHandler('/tmp/overdue_client_calls.log')  # File output
    ]
)

class CallStatus:
    INITIATED = "INITIATED"
    RINGING = "RINGING"
    ANSWERED = "ANSWERED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    TIMEOUT = "TIMEOUT"
    AUDIO_FAILED = "AUDIO_FAILED"  # New status for when audio doesn't play

class LlamadorAutomatico:
    def __init__(self, destination, user_id=None):
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
        self.user_id = user_id  # Store user ID for updates
        self.attempt_count = 0
        self.timeout_task = None
        self.audio_timeout_task = None
        self.silent_call_timeout_task = None
        self.db_updated_on_playback = False  # Flag to track if DB was updated on playback

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

    def log_call_attempt(self, status, duration=None):
        """Logs a call attempt"""
        
        # ================================
        # PARTE 1: LOGGING (Sin cambios - siempre útil)
        # ================================
        log_message = f"CALL LOG: Number={self.destination}, ID={self.call_id}, Status={status}, Attempt={self.attempt_count}"
        if duration is not None:
            log_message += f", Duration={duration}s"

        # Log current audio status for diagnostics
        audio_status = "AUDIO_STARTED" if self.audio_started else "NO_AUDIO"
        log_message += f", Audio={audio_status}"

        # If there's an audio request time, log the elapsed time
        if self.audio_requested_time:
            request_time = time.time() - self.audio_requested_time
            log_message += f", Time since audio request={request_time:.2f}s"

        logging.info(log_message)
        
        # ================================
        # PARTE 2: ACTUALIZACIÓN BASE DE DATOS (Modificada)
        # ================================
        
        # Solo actualizar BD en casos específicos donde no se hizo en PlaybackStarted
        should_update_db = (
            self.user_id and 
            (
                # CASO 1: Llamada fallida después de máximos intentos (sin audio exitoso)
                (self.attempt_count >= MAX_RETRIES and not self.db_updated_on_playback) or
                
                # CASO 2: Llamada exitosa SOLO si no se actualizó ya en PlaybackStarted
                (status == CallStatus.COMPLETED and not self.db_updated_on_playback)
            )
        )
        
        if should_update_db:
            try:
                # Connect to the database
                conn = mysql.connector.connect(
                    host=MYSQL_SERVER,
                    database=MYSQL_DATABASE,
                    user=MYSQL_USER,
                    password=MYSQL_PASSWORD
                )
                
                if conn.is_connected():
                    cursor = conn.cursor()
                    current_date = datetime.now().strftime('%Y-%m-%d')
                    
                    if status == CallStatus.COMPLETED:
                        # CASO RARO: Llamada completada sin PlaybackStarted (no debería pasar normalmente)
                        logging.warning("Actualizando BD desde log_call_attempt para COMPLETED - caso inusual")
                        update_query = """
                        UPDATE afiliados 
                        SET outbound_call_attempts = %s, 
                            outbound_call_is_sent = 1, 
                            outbound_call_completed_at = %s 
                        WHERE id = %s
                        """
                        cursor.execute(update_query, (self.attempt_count, current_date, self.user_id))
                        
                    else:
                        # CASO NORMAL: Llamada fallida después de intentos máximos
                        logging.info(f"Actualizando BD para llamada fallida - {self.attempt_count} intentos realizados")
                        update_query = """
                        UPDATE afiliados 
                        SET outbound_call_attempts = %s
                        WHERE id = %s
                        """
                        cursor.execute(update_query, (self.attempt_count, self.user_id))
                    
                    conn.commit()
                    logging.info(f"Updated call status in DB for user ID {self.user_id} - Status: {status}")
                    
                    cursor.close()
                    conn.close()
            except Error as e:
                logging.error(f"Error updating database: {e}")
        else:
            # Log por qué no se actualiza la BD
            if self.db_updated_on_playback:
                logging.info(f"BD ya actualizada en PlaybackStarted para usuario {self.user_id} - Saltando actualización")
            else:
                logging.debug(f"No se requiere actualización BD para status={status}, attempts={self.attempt_count}")


    async def iniciar_llamada(self):
        """Initiates an outgoing call using the SIP trunk"""
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

            logging.info(f"Initiating call to {self.destination} via trunk {TRUNK_NAME} (Attempt {self.attempt_count})")
            logging.debug(f"Call data: {json.dumps(data, indent=2)}")

            async with self.session.post(url, json=data) as response:
                response_text = await response.text()
                if response.status == 200:
                    response_data = json.loads(response_text)
                    self.call_id = response_data['id']
                    logging.info(f"Call initiated: {self.call_id}")

                    # Set a timeout for the call
                    self.timeout_task = asyncio.create_task(self.call_timeout())

                    self.log_call_attempt(CallStatus.INITIATED)
                    return True
                else:
                    logging.error(f"Error initiating call: {response_text}")
                    self.call_status = CallStatus.FAILED
                    self.log_call_attempt(CallStatus.FAILED)
                    return False

        except Exception as e:
            logging.error(f"Error in iniciar_llamada: {e}")
            self.call_status = CallStatus.FAILED
            self.log_call_attempt(CallStatus.FAILED)
            return False

    async def call_timeout(self):
        """Handles call timeout if there's no response"""
        await asyncio.sleep(CALL_TIMEOUT)
        try:
            if self.call_status not in [CallStatus.ANSWERED, CallStatus.COMPLETED]:
                logging.warning(f"Call timeout after {CALL_TIMEOUT} seconds")
                self.call_status = CallStatus.TIMEOUT
                self.log_call_attempt(CallStatus.TIMEOUT)
                await self.finalizar_llamada()
        except Exception as e:
            logging.error(f"Error in call_timeout: {e}")
            logging.exception("Complete traceback:")

    async def audio_start_timeout(self):
        """Handles timeout if audio doesn't start playing"""
        await asyncio.sleep(AUDIO_START_TIMEOUT)
        if self.active_channel and not self.audio_started and self.call_status == CallStatus.ANSWERED:
            logging.warning(f"Timeout waiting for audio playback to start after {AUDIO_START_TIMEOUT} seconds")
            # Check if playback_map has entries
            if self.playback_map:
                logging.warning(f"We have {len(self.playback_map)} playbacks in the map, but audio_started=False")
                for playback_id, channel in self.playback_map.items():
                    logging.warning(f"Playback ID: {playback_id}, Channel: {channel}")
            else:
                logging.warning("No playbacks registered in the map")

            self.call_status = CallStatus.AUDIO_FAILED
            self.log_call_attempt(CallStatus.AUDIO_FAILED)
            logging.info("Ending call due to audio start failure")
            await self.finalizar_llamada()

    async def silent_call_timeout(self):
        """Ends the call if it remains too long without audio activity"""
        await asyncio.sleep(MAX_SILENT_CALL_DURATION)
        if self.active_channel and self.audio_requested_time and not self.audio_started and self.call_status == CallStatus.ANSWERED:
            elapsed = time.time() - self.audio_requested_time
            logging.warning(f"Call without active audio for {elapsed:.1f} seconds, ending")

            # Check if we have registered playbacks
            if self.playback_map:
                logging.warning(f"There are {len(self.playback_map)} registered playbacks but audio_started=False")
                for playback_id, channel in self.playback_map.items():
                    logging.warning(f"Registered playback: ID={playback_id}, Channel={channel}")

                # As an extreme measure, force audio_started to True if there are registered playbacks
                # This will prevent us from hanging up a call that possibly has audio playing
                logging.warning("Forcing audio_started=True as a preventive measure")
                self.audio_started = True
                self.audio_started_time = time.time()
                return

            self.call_status = CallStatus.AUDIO_FAILED
            self.log_call_attempt(CallStatus.AUDIO_FAILED)
            await self.finalizar_llamada()

    async def reproducir_audio(self):
        """Plays the audio file"""
        if not self.audio_started and self.active_channel:
            try:
                self.audio_requested_time = time.time()
                url = f"{ARI_URL}/channels/{self.active_channel}/play"
                data = {
                    "media": f"sound:{AUDIO_FILE}"
                }

                # Cancel existing timeouts before creating new ones
                if self.audio_timeout_task:
                    self.audio_timeout_task.cancel()
                if self.silent_call_timeout_task:
                    self.silent_call_timeout_task.cancel()

                # Set timeout for audio start
                self.audio_timeout_task = asyncio.create_task(self.audio_start_timeout())

                # Set timeout for silent call
                self.silent_call_timeout_task = asyncio.create_task(self.silent_call_timeout())

                async with self.session.post(url, json=data) as response:
                    response_text = await response.text()
                    logging.debug(f"Audio playback response: {response_text}")
                    if response.status == 201:
                        playback = json.loads(response_text)
                        playback_id = playback['id']
                        logging.info(f"Generated Playback ID: {playback_id}")
                        self.playback_map[playback_id] = self.active_channel
                        logging.info(f"Audio playback requested for channel {self.active_channel}")

                        # Log current state
                        logging.debug(f"State after requesting audio - playback_map: {self.playback_map}, audio_started: {self.audio_started}")

                        # Schedule a check for call completion
                        # This is a backup in case PlaybackFinished events are not processed correctly
                        asyncio.create_task(self.check_call_completion(playback_id))
                    else:
                        logging.error(f"Error playing audio: {response_text}")
                        logging.error(f"Data: {json.dumps(data, indent=2)}")
                        self.call_status = CallStatus.AUDIO_FAILED
                        await self.finalizar_llamada()
            except Exception as e:
                logging.error(f"Error in reproducir_audio: {e}")
                self.call_status = CallStatus.AUDIO_FAILED
                await self.finalizar_llamada()

    async def check_call_completion(self, playback_id):
        """Checks if a playback has finished to end the call"""
        try:
            # Estimated time for audio playback + margin
            await asyncio.sleep(30)  # Wait 30 seconds, enough time for any audio to finish

            if self.active_channel and playback_id in self.playback_map and self.call_status not in [CallStatus.COMPLETED, CallStatus.FAILED]:
                # If after 30 seconds the call is still active and has not been marked as completed
                # we assume that PlaybackFinished was not processed correctly
                logging.warning(f"Detected possible audio completion without PlaybackFinished event for {playback_id}")
                logging.warning("Ending call by safety mechanism")

                # Check current status
                url = f"{ARI_URL}/playbacks/{playback_id}"
                try:
                    async with self.session.get(url) as response:
                        if response.status == 404:
                            # If the playback no longer exists, we assume it's already finished
                            logging.info(f"Playback {playback_id} no longer exists, assuming it's finished")
                            self.call_status = CallStatus.COMPLETED
                            await self.finalizar_llamada(status=CallStatus.COMPLETED)
                        else:
                            # If we get another response, let's check the status
                            playback_data = await response.json()
                            playback_state = playback_data.get('state')
                            logging.info(f"Current state of playback {playback_id}: {playback_state}")

                            if playback_state in ['done', 'cancelled']:
                                # If it's already finished but we didn't receive the event
                                self.call_status = CallStatus.COMPLETED
                                await self.finalizar_llamada(status=CallStatus.COMPLETED)
                except Exception as e:
                    logging.error(f"Error checking playback status: {e}")
                    # If there's an error, end the call for safety
                    self.call_status = CallStatus.COMPLETED
                    await self.finalizar_llamada(status=CallStatus.COMPLETED)
        except Exception as e:
            logging.error(f"Error in check_call_completion: {e}")
            logging.exception("Complete traceback:")

    async def manejar_eventos(self, websocket):
        """Processes WebSocket events"""
        try:
            async for mensaje in websocket:
                evento = json.loads(mensaje)
                tipo = evento.get('type')
                logging.debug(f"Event received: {tipo}")

                if tipo == 'Dial':
                    # Check if the call is ringing
                    dial_state = evento.get('dialstatus')
                    if dial_state == 'RINGING':
                        self.call_status = CallStatus.RINGING
                        logging.info("Call is ringing")

                elif tipo == 'StasisStart':
                    # The call was answered and entered the Stasis application
                    self.active_channel = evento['channel']['id']
                    self.call_status = CallStatus.ANSWERED
                    logging.info(f"Active channel: {self.active_channel} - Call answered")

                    # Cancel the timeout if it exists
                    if self.timeout_task:
                        self.timeout_task.cancel()
                        self.timeout_task = None

                    # To see if there's any playback in progress, request its status
                    try:
                        url = f"{ARI_URL}/playbacks"
                        async with self.session.get(url) as response:
                            if response.status == 200:
                                playbacks = await response.json()
                                logging.info(f"Active playbacks: {len(playbacks)}")
                                for pb in playbacks:
                                    logging.info(f"  - ID: {pb.get('id')}, Channel: {pb.get('target_uri')}, State: {pb.get('state')}")
                            else:
                                logging.warning("Could not get information about active playbacks")
                    except Exception as e:
                        logging.error(f"Error querying playbacks: {e}")

                    # Small pause to ensure the channel is ready
                    await asyncio.sleep(1)

                    # Try to play the audio
                    await self.reproducir_audio()

                    # If the audio hasn't been played, check why
                    if not self.audio_started and not self.audio_requested_time:
                        logging.error("Could not request audio playback")
                        self.call_status = CallStatus.AUDIO_FAILED
                        await self.finalizar_llamada()
                    else:
                        logging.info("Waiting for audio playback...")
                
                elif tipo == 'PlaybackStarted':
                    playback_id = evento['playback']['id']
                    if playback_id in self.playback_map:
                        logging.info(f"Audio playback started: {playback_id}")
                        self.audio_started = True
                        self.audio_started_time = time.time()
                        
                        # ACTUALIZACIÓN COMPLETA EN EL MOMENTO DEL ÉXITO
                        # Desde que comienza el audio, la llamada es exitosa para efectos del negocio
                        if self.user_id and not self.db_updated_on_playback:
                            try:
                                # Conectar a la base de datos
                                conn = mysql.connector.connect(
                                    host=MYSQL_SERVER,
                                    database=MYSQL_DATABASE,
                                    user=MYSQL_USER,
                                    password=MYSQL_PASSWORD
                                )
                                
                                if conn.is_connected():
                                    cursor = conn.cursor()
                                    
                                    # Obtener la fecha actual
                                    current_date = datetime.now().strftime('%Y-%m-%d')
                                    
                                    # ACTUALIZACIÓN COMPLETA: llamada exitosa desde que comienza el audio
                                    update_query = """
                                    UPDATE afiliados 
                                    SET outbound_call_is_sent = 1,
                                        outbound_call_attempts = %s, 
                                        outbound_call_completed_at = %s 
                                    WHERE id = %s
                                    """
                                    
                                    cursor.execute(update_query, (self.attempt_count, current_date, self.user_id))
                                    conn.commit()
                                    
                                    logging.info(f"LLAMADA EXITOSA - Usuario ID {self.user_id}: "
                                            f"Intento {self.attempt_count}, Audio iniciado, "
                                            f"Fecha registrada: {current_date}")
                                    
                                    # Marcar como actualizado para evitar actualizaciones duplicadas
                                    self.db_updated_on_playback = True
                                    
                                    cursor.close()
                                    conn.close()
                                    
                            except Error as e:
                                logging.error(f"Error actualizando la base de datos en PlaybackStarted: {e}")
                                logging.exception("Detalles del error:")
                            except Exception as e:
                                logging.error(f"Error inesperado actualizando base de datos: {e}")
                                logging.exception("Detalles del error:")

                elif tipo == 'PlaybackFinished':
                    playback_id = evento['playback']['id']
                    if playback_id in self.playback_map:
                        logging.info("Audio played completely")
                        # Calculate playback duration
                        if self.audio_started_time:
                            audio_duration = time.time() - self.audio_started_time
                            logging.info(f"Playback duration: {audio_duration:.2f} seconds")

                        # Small pause before hanging up to ensure the last audio is heard completely
                        await asyncio.sleep(2)
                        logging.info("Ending call after audio playback")
                        await self.finalizar_llamada(status=CallStatus.COMPLETED)

                elif tipo == 'StasisEnd':
                    if evento.get('channel', {}).get('id') == self.active_channel:
                        logging.info("Call terminated by destination")
                        self.active_channel = None
                        if self.call_status == CallStatus.ANSWERED:
                            self.call_status = CallStatus.COMPLETED

                elif tipo == 'ChannelStateChange':
                    state = evento.get('channel', {}).get('state')
                    logging.info(f"Channel state changed to: {state}")
                    if state == 'Up' and self.call_status != CallStatus.ANSWERED:
                        self.call_status = CallStatus.ANSWERED

                elif tipo == 'ChannelDestroyed':
                    channel_id = evento.get('channel', {}).get('id')
                    if channel_id == self.call_id:
                        logging.info(f"Channel destroyed: {channel_id}")

                        # Calculate call duration
                        call_duration = None
                        if self.call_start_time:
                            call_duration = round(time.time() - self.call_start_time)

                        # If the call was not answered or did not have audio and the channel was destroyed, mark it as failed
                        if self.call_status not in [CallStatus.COMPLETED]:
                            # If it was answered but there was no audio, use AUDIO_FAILED
                            if self.call_status == CallStatus.ANSWERED and not self.audio_started:
                                self.call_status = CallStatus.AUDIO_FAILED
                                logging.warning("Call answered but without audio playback")
                            # If it was not answered, mark as FAILED
                            elif self.call_status not in [CallStatus.AUDIO_FAILED]:
                                self.call_status = CallStatus.FAILED

                            self.log_call_attempt(self.call_status, call_duration)

                            # If we can retry, schedule the next attempt
                            if self.attempt_count < MAX_RETRIES:
                                retry_reason = "audio failure" if self.call_status == CallStatus.AUDIO_FAILED else "failed call"
                                logging.info(f"Scheduling retry #{self.attempt_count + 1} in {RETRY_DELAY} seconds due to {retry_reason}")
                                await asyncio.sleep(RETRY_DELAY)
                                # Reset states for the new attempt
                                self.active_channel = None
                                self.call_id = None
                                self.audio_started = False
                                self.audio_requested_time = None
                                self.audio_started_time = None
                                # Start new attempt
                                if await self.iniciar_llamada():
                                    continue  # Continue listening for events
                                else:
                                    # If the retry fails, end
                                    break
                            else:
                                logging.warning(f"Maximum number of attempts ({MAX_RETRIES}) reached for {self.destination}")
                                break
                        else:
                            # If the call was successful, log it
                            if self.call_status == CallStatus.ANSWERED and call_duration:
                                self.log_call_attempt(CallStatus.COMPLETED, call_duration)
                            break

        except Exception as e:
            logging.error(f"Error in manejar_eventos: {e}")
            await self.finalizar_llamada()

    async def finalizar_llamada(self, status=None):
        """Ends the active call"""
        try:
            # Cancel all timeouts
            for task in [self.timeout_task, self.audio_timeout_task, self.silent_call_timeout_task]:
                if task:
                    task.cancel()

            self.timeout_task = None
            self.audio_timeout_task = None
            self.silent_call_timeout_task = None

            if status:
                self.call_status = status

            # Calculate call duration if there's a start time
            call_duration = None
            if self.call_start_time:
                call_duration = round(time.time() - self.call_start_time)
            logging.info(f"Ending call with status: {self.call_status}")
            logging.info(f"Active channel: {self.active_channel}")
            if self.active_channel:
                url = f"{ARI_URL}/channels/{self.active_channel}"
                async with self.session.delete(url) as response:
                    if response.ok:
                        logging.info(f"Call ended successfully (duration: {call_duration}s)")
                        # If the call was successful, log COMPLETED
                        if self.call_status == CallStatus.ANSWERED and not status:
                            self.log_call_attempt(CallStatus.COMPLETED, call_duration)
                    else:
                        response_text = await response.text()
                        # Don't throw an error if the channel no longer exists (probably already hung up)
                        if "Channel not found" in response_text:
                            logging.warning("Channel no longer exists, call probably already ended")
                        else:
                            logging.error(f"Error ending call: {response_text}")

                        # If there was an error ending the call, log the current status
                        if not status:  # Don't overwrite the status if one has already been passed
                            self.log_call_attempt(self.call_status or CallStatus.FAILED, call_duration)
            logging.info("Call ended")
        except Exception as e:
            logging.error(f"Error ending call: {e}")
        finally:
            self.active_channel = None
            self.call_id = None
            self.audio_started = False
            self.audio_requested_time = None
            self.audio_started_time = None

    async def ejecutar(self):
        """Main execution flow"""
        try:
            await self.setup_session()
            async with websockets.connect(
                f"{WEBSOCKET_URL}?api_key={USERNAME}:{PASSWORD}&app=overdue-app",
                ping_interval=30,
                ping_timeout=10
            ) as websocket:
                await asyncio.sleep(5)  # Esperar 5 segundos para registro
                if await self.iniciar_llamada():
                    await self.manejar_eventos(websocket)

        except websockets.exceptions.ConnectionClosed as e:
            logging.error(f"WebSocket connection closed: {e}")
        except Exception as e:
            logging.error(f"Error in main execution: {e}")
            await self.finalizar_llamada()
        finally:
            await self.cleanup_session()

class CallManager:
    """Class to manage multiple calls"""

    def __init__(self):
        self.pending_calls = []
        self.timeout_task = None
        self.timeout_seconds = BASE_SCRIPT_TIMEOUT
        self.timeout_event = asyncio.Event()

    def connect_to_mysql(self):
        """Connects to MySQL and returns connection object"""
        try:
            connection = mysql.connector.connect(
                host=MYSQL_SERVER,
                database=MYSQL_DATABASE,
                user=MYSQL_USER,
                password=MYSQL_PASSWORD
            )
            if connection.is_connected():
                return connection
            else:
                logging.error("Failed to connect to MySQL database")
                return None
        except Error as e:
            logging.error(f"Error connecting to MySQL: {e}")
            return None

    def load_pending_calls(self):
        """Loads pending calls from MySQL database"""
        conn = self.connect_to_mysql()
        if not conn:
            return False

        try:
            cursor = conn.cursor(dictionary=True)
            
            # Obtener la fecha actual para la comparación del día de corte
            current_day = datetime.now().day
            logging.info(f"Día actual: {current_day}")
            
            # Query para encontrar clientes con outbound_call=1, que tengan deudas pendientes 
            # y cuyo día de corte sea válido para llamar
            # Nota: Utilizando el nombre correcto del campo id-afiliado con comillas invertidas
            query = """
            SELECT a.id, a.telefono, a.outbound_call_attempts, a.corte,
                   SUM(CASE WHEN f.cerrado = 0 THEN f.saldo ELSE 0 END) AS deuda_total
            FROM afiliados a
            LEFT JOIN factura f ON a.id = f.`id-afiliado`
            WHERE a.outbound_call = 1 
            AND a.outbound_call_is_sent = 0
            GROUP BY a.id, a.telefono, a.outbound_call_attempts, a.corte
            HAVING deuda_total > 0
            ORDER BY a.id
            """
            
            cursor.execute(query)
            results = cursor.fetchall()
            
            logging.info(f"Found {len(results)} pending calls in database with unpaid bills")
            
            self.pending_calls = []
            for row in results:
                user_id = row['id']
                phone = row['telefono'].strip() if row['telefono'] else ""
                attempts = row['outbound_call_attempts'] or 0
                corte = row['corte']
                deuda_total = row['deuda_total']
                
                # Verificar el día de corte
                if corte and corte.isdigit():
                    corte_day = int(corte)
                    
                    # Comprobar si:
                    # 1. Estamos un día antes del corte (ej: hoy 14, corte 15)
                    # 2. Estamos en el día del corte (ej: hoy 15, corte 15)
                    # 3. Ya pasó el día de corte (ej: hoy 20, corte 15)
                    is_valid_call_day = (current_day == corte_day - 1) or (current_day >= corte_day)
                    
                    if not is_valid_call_day:
                        logging.info(f"Usuario {user_id} no será llamado - día actual ({current_day}) está a más de un día del corte ({corte_day})")
                        continue
                
                # Específica validación para números móviles colombianos (10 dígitos)
                if phone and len(phone) == 10 and phone.startswith('3'):
                    # Formato correcto: agregar prefijo país 57
                    formatted_phone = '57' + phone
                    
                    logging.info(f"Usuario {user_id} - Número: {formatted_phone} - Deuda: {deuda_total} - Día de corte: {corte}")
                    
                    self.pending_calls.append({
                        "user_id": user_id,
                        "phone_number": formatted_phone,
                        "attempts": attempts,
                        "deuda_total": deuda_total,
                        "corte": corte
                    })
                else:
                    logging.warning(f"Número de teléfono inválido para usuario {user_id}: '{phone}' - debe ser un móvil de 10 dígitos que comience con 3")
            
            cursor.close()
            conn.close()
            
            return len(self.pending_calls) > 0
        except Error as e:
            logging.error(f"Error fetching pending calls: {e}")
            if conn.is_connected():
                cursor.close()
                conn.close()
            return False

    async def update_timeout(self, additional_seconds):
        """Updates the timeout duration and extends the existing timeout task"""
        self.timeout_seconds += additional_seconds
        
        # Cancel existing timeout task if it exists
        if self.timeout_task and not self.timeout_task.done():
            self.timeout_task.cancel()
            logging.info(f"Cancelling old timeout task and extending timeout to {self.timeout_seconds} seconds")
        
        # Create a new timeout task
        self.timeout_task = asyncio.create_task(self.terminar_por_timeout())
        logging.info(f"Script timeout extended to {self.timeout_seconds} seconds")

    async def terminar_por_timeout(self):
        """Ends the script after a timeout period"""
        try:
            # Wait until timeout or until the event is set
            await asyncio.wait_for(self.timeout_event.wait(), timeout=self.timeout_seconds)
            logging.info("Timeout task completed normally")
        except asyncio.TimeoutError:
            # Timeout occurred - the call took too long
            logging.warning(f"¡TIEMPO MÁXIMO DE {self.timeout_seconds} SEGUNDOS ALCANZADO PARA LA LLAMADA ACTUAL! Terminando script...")
            logging.warning("Terminación forzada para evitar costos excesivos en llamadas")
            # Force the program to end immediately
            os._exit(0)

    async def process_pending_calls(self):
        """Processes all pending calls"""
        if not self.load_pending_calls():
            logging.warning("No pending calls to process")
            # Set the event to allow normal termination
            self.timeout_event.set()
            return

        # Process each call with its own independent timeout
        for call_data in self.pending_calls:
            user_id = call_data.get("user_id")
            phone_number = call_data.get("phone_number")
            logging.info(f"Processing call to user ID {user_id} with phone {phone_number}")
            
            # Reset the timeout event and create a new timeout task for this specific user
            self.timeout_event = asyncio.Event()
            
            # Cancel any existing timeout task
            if self.timeout_task and not self.timeout_task.done():
                self.timeout_task.cancel()
                logging.info("Cancelling previous timeout task")
                
            # Reset timeout to base value for each user
            self.timeout_seconds = BASE_SCRIPT_TIMEOUT
            logging.info(f"Setting fresh timeout of {self.timeout_seconds} seconds for user ID {user_id}")
            
            # Create new timeout task
            self.timeout_task = asyncio.create_task(self.terminar_por_timeout())
            
            # Process this user's call
            llamador = LlamadorAutomatico(destination=phone_number, user_id=user_id)
            await llamador.ejecutar()
            
            # Wait a short time between calls to avoid system saturation
            await asyncio.sleep(5)

        # All calls processed, set the event to allow normal termination
        if self.timeout_task and not self.timeout_task.done():
            self.timeout_event.set()
            logging.info("All calls processed successfully, cancelling timeout task")

async def main():
    try:
        call_manager = CallManager()
        await call_manager.process_pending_calls()
    except Exception as e:
        logging.error(f"Error in main function: {e}")
        logging.exception("Complete traceback:")

if __name__ == "__main__":
    asyncio.run(main())