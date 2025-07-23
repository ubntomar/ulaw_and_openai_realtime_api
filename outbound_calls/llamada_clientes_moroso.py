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

# ============================================================================
# CONFIGURACIÓN DE DEBUG
# ============================================================================
# Cambiar a True para activar logs de debug detallados
# Cambiar a False para mostrar solo logs de progreso limpios
DEBUG_MODE = True  # <-- CAMBIAR AQUÍ PARA ACTIVAR/DESACTIVAR DEBUG

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
BASE_SCRIPT_TIMEOUT = 3000  # Base timeout in seconds (50 minutes)
ADDITIONAL_TIME_PER_USER = 300  # Additional time per user in seconds (5 minutes)

# NUEVA CONFIGURACIÓN BÁSICA - SOLO LO ESENCIAL
EVENT_TIMEOUT = 15  # Timeout básico para eventos de WebSocket
INTER_CLIENT_DELAY = 10  # Pausa entre clientes (aumentada de 5 a 10 segundos)

if not USERNAME or not PASSWORD:
    logging.error("Environment variables ASTERISK_USERNAME and ASTERISK_PASSWORD must be set")
    exit(1)

if not MYSQL_DATABASE or not MYSQL_PASSWORD or not MYSQL_SERVER or not MYSQL_USER:
    logging.error("MySQL environment variables must be set (MYSQL_DATABASE, MYSQL_PASSWORD, MYSQL_SERVER, MYSQL_USER)")
    exit(1)

TRUNK_NAME = "voip_issabel"  # SIP trunk name

# ============================================================================
# CONFIGURACIÓN DE LOGGING MEJORADA
# ============================================================================
def setup_logging():
    """Configura el sistema de logging según DEBUG_MODE"""
    log_level = logging.DEBUG if DEBUG_MODE else logging.INFO
    
    # Configuración base del logging
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s.%(msecs)03d - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        handlers=[
            logging.StreamHandler(),  # Console output
            logging.FileHandler('/tmp/overdue_client_calls.log')  # File output
        ],
        force=True
    )
    
    if DEBUG_MODE:
        logging.info("🔧 DEBUG MODE ACTIVADO - Logs detallados habilitados")
    else:
        logging.info("🚀 MODO PRODUCCIÓN - Logs limpios activados")

def debug_log(message, *args, **kwargs):
    """Helper function para logs de debug organizados"""
    if DEBUG_MODE:
        logging.debug(f"[DEBUG] {message}", *args, **kwargs)

def progress_log(message, *args, **kwargs):
    """Helper function para logs de progreso principales"""
    logging.info(message, *args, **kwargs)

# Inicializar logging
setup_logging()

class CallStatus:
    INITIATED = "INITIATED"
    RINGING = "RINGING"
    ANSWERED = "ANSWERED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    TIMEOUT = "TIMEOUT"
    AUDIO_FAILED = "AUDIO_FAILED"  # New status for when audio doesn't play

class LlamadorAutomatico:
    def __init__(self, destination, user_id=None, client_info=None):
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
        
        # NUEVO: Información del cliente y resultado final
        self.client_info = client_info or {}
        self.cliente = client_info.get('cliente', 'Desconocido') if client_info else 'Desconocido'
        self.final_result = {
            'user_id': user_id,
            'phone': destination,
            'status': 'PENDING',
            'attempts': 0,
            'failure_reason': None,
            'duration': None,
            'audio_played': False
        }

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
            
        # CORRECCIÓN BÁSICA: CANCELAR TODOS LOS TIMEOUTS PENDIENTES
        timeout_tasks = [self.timeout_task, self.audio_timeout_task, self.silent_call_timeout_task]
        for task in timeout_tasks:
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        
        self.timeout_task = None
        self.audio_timeout_task = None
        self.silent_call_timeout_task = None
        
        debug_log("Todos los timeouts individuales cancelados en cleanup_session")

    def _get_client_progress_info(self):
        """Helper para obtener información de progreso del cliente"""
        current_num = self.client_info.get('current_number', '?')
        total_num = self.client_info.get('total_clients', '?')
        return current_num, total_num

    def _determine_failure_reason(self, status):
        """Determina la razón específica del fallo"""
        if status == CallStatus.TIMEOUT:
            return "TIMEOUT_NO_ANSWER"
        elif status == CallStatus.AUDIO_FAILED:
            return "CALL_ANSWERED_BUT_AUDIO_FAILED"
        elif status == CallStatus.FAILED:
            return "CALL_FAILED_TO_CONNECT"
        elif not self.audio_started:
            return "NO_AUDIO_PLAYBACK"
        else:
            return "UNKNOWN_FAILURE"

    def log_call_attempt(self, status, duration=None):
        """Enhanced logging with client progress info and debug details"""
        current_num, total_num = self._get_client_progress_info()
        
        # ================================
        # LOGS PRINCIPALES (SIEMPRE VISIBLES)
        # ================================
        progress_message = (
            f"📞 CLIENTE {current_num}/{total_num} - "
            f"ID: {self.user_id} | "
            f"Tel: {self.destination} | "
            f"Nombre: {self.cliente} | "
            f"Intento: {self.attempt_count}/{MAX_RETRIES} | "
            f"Estado: {status}"
        )
        
        if duration is not None:
            progress_message += f" | Duración: {duration}s"
        
        # Determinar ícono según estado
        if status == CallStatus.COMPLETED and self.audio_started:
            icon = "✅"
            progress_message += " | Audio: REPRODUCIDO"
        elif status in [CallStatus.FAILED, CallStatus.TIMEOUT, CallStatus.AUDIO_FAILED]:
            icon = "❌"
            progress_message += " | Audio: FALLO"
        else:
            icon = "⏳"
            audio_status = "REPRODUCIDO" if self.audio_started else "PENDIENTE"
            progress_message += f" | Audio: {audio_status}"
        
        progress_log(f"{icon} {progress_message}")
        
        # ================================
        # LOGS DE DEBUG (SOLO SI DEBUG_MODE = True)
        # ================================
        if DEBUG_MODE:
            debug_log("=" * 60)
            debug_log(f"DETALLES DE LLAMADA - Cliente {current_num}/{total_num}")
            debug_log(f"Call ID: {self.call_id}")
            debug_log(f"Canal Activo: {self.active_channel}")
            debug_log(f"Audio iniciado: {self.audio_started}")
            
            if self.audio_requested_time:
                request_time = time.time() - self.audio_requested_time
                debug_log(f"Tiempo desde solicitud de audio: {request_time:.2f}s")
            
            if self.audio_started_time:
                audio_duration = time.time() - self.audio_started_time
                debug_log(f"Duración de audio: {audio_duration:.2f}s")
            
            debug_log(f"Playback map: {self.playback_map}")
            debug_log(f"BD actualizada en playback: {self.db_updated_on_playback}")
            debug_log("=" * 60)
        
        # ================================
        # ACTUALIZACIÓN DE RESULTADO FINAL
        # ================================
        if status == CallStatus.COMPLETED and self.audio_started:
            self.final_result.update({
                'status': 'SUCCESS',
                'attempts': self.attempt_count,
                'duration': duration,
                'audio_played': True
            })
        elif self.attempt_count >= MAX_RETRIES:
            failure_reason = self._determine_failure_reason(status)
            self.final_result.update({
                'status': 'FAILED',
                'attempts': self.attempt_count,
                'failure_reason': failure_reason,
                'duration': duration
            })
        
        # ================================
        # ACTUALIZACIÓN BASE DE DATOS (Sin cambios - solo mejores logs)
        # ================================
        should_update_db = (
            self.user_id and 
            (
                (self.attempt_count >= MAX_RETRIES and not self.db_updated_on_playback) or
                (status == CallStatus.COMPLETED and not self.db_updated_on_playback)
            )
        )
        
        if should_update_db:
            try:
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
                        debug_log("Actualizando BD para llamada exitosa desde log_call_attempt (caso raro)")
                        update_query = """
                        UPDATE afiliados 
                        SET outbound_call_attempts = %s, 
                            outbound_call_is_sent = 1, 
                            outbound_call_completed_at = %s 
                        WHERE id = %s
                        """
                        cursor.execute(update_query, (self.attempt_count, current_date, self.user_id))
                        
                    else:
                        progress_log(f"💾 Registrando {self.attempt_count} intentos fallidos para cliente {self.user_id}")
                        update_query = """
                        UPDATE afiliados 
                        SET outbound_call_attempts = %s
                        WHERE id = %s
                        """
                        cursor.execute(update_query, (self.attempt_count, self.user_id))
                    
                    conn.commit()
                    debug_log(f"BD actualizada exitosamente para usuario {self.user_id}")
                    
                    cursor.close()
                    conn.close()
            except Error as e:
                logging.error(f"❌ Error actualizando BD: {e}")

    async def iniciar_llamada(self):
        """Initiates an outgoing call using the SIP trunk"""
        self.attempt_count += 1
        self.call_status = CallStatus.INITIATED
        self.call_start_time = time.time()
        current_num, total_num = self._get_client_progress_info()

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

            progress_log(f"📱 Iniciando llamada - Cliente {current_num}/{total_num} - Intento {self.attempt_count}")
            debug_log(f"URL: {url}")
            debug_log(f"Datos de llamada: {json.dumps(data, indent=2)}")

            async with self.session.post(url, json=data) as response:
                response_text = await response.text()
                if response.status == 200:
                    response_data = json.loads(response_text)
                    self.call_id = response_data['id']
                    debug_log(f"Call ID generado: {self.call_id}")

                    # Set a timeout for the call
                    self.timeout_task = asyncio.create_task(self.call_timeout())

                    self.log_call_attempt(CallStatus.INITIATED)
                    return True
                else:
                    # DIAGNÓSTICO MEJORADO PARA ALLOCATION FAILED
                    progress_log(f"❌ Error iniciando llamada - Status: {response.status}")
                    progress_log(f"❌ Respuesta completa: {response_text}")
                    progress_log(f"❌ Headers de respuesta: {dict(response.headers)}")
                    
                    # Verificar canales activos en Asterisk
                    try:
                        channels_url = f"{ARI_URL}/channels"
                        async with self.session.get(channels_url) as channels_response:
                            if channels_response.status == 200:
                                channels_data = await channels_response.json()
                                progress_log(f"🔍 Canales activos en Asterisk: {len(channels_data)}")
                                if len(channels_data) > 0:
                                    debug_log("Primeros 3 canales activos:")
                                    for i, channel in enumerate(channels_data[:3]):
                                        debug_log(f"  Canal {i+1}: {channel.get('id')} - Estado: {channel.get('state')}")
                            else:
                                progress_log(f"⚠️ No se pudo consultar canales: {channels_response.status}")
                    except Exception as e:
                        debug_log(f"Error consultando canales: {e}")
                    
                    self.call_status = CallStatus.FAILED
                    self.log_call_attempt(CallStatus.FAILED)
                    
                    # NUEVA PAUSA PARA EVITAR ALLOCATION FAILED
                    if "Allocation failed" in response_text:
                        progress_log("⏳ Esperando 30s por error de allocation...")
                        await asyncio.sleep(30)
                    
                    return False

        except Exception as e:
            logging.error(f"❌ Excepción en iniciar_llamada: {e}")
            self.call_status = CallStatus.FAILED
            self.log_call_attempt(CallStatus.FAILED)
            return False

    async def call_timeout(self):
        """Handles call timeout if there's no response"""
        await asyncio.sleep(CALL_TIMEOUT)
        try:
            if self.call_status not in [CallStatus.ANSWERED, CallStatus.COMPLETED]:
                current_num, total_num = self._get_client_progress_info()
                progress_log(f"⏰ TIMEOUT - Cliente {current_num}/{total_num} - Sin respuesta en {CALL_TIMEOUT}s")
                self.call_status = CallStatus.TIMEOUT
                self.log_call_attempt(CallStatus.TIMEOUT)
                await self.finalizar_llamada()
        except Exception as e:
            logging.error(f"❌ Error en call_timeout: {e}")
            debug_log(f"Traceback completo: {e}", exc_info=True)

    async def audio_start_timeout(self):
        """Handles timeout if audio doesn't start playing"""
        await asyncio.sleep(AUDIO_START_TIMEOUT)
        if self.active_channel and not self.audio_started and self.call_status == CallStatus.ANSWERED:
            current_num, total_num = self._get_client_progress_info()
            progress_log(f"⏰ Cliente {current_num}/{total_num} - Timeout esperando audio ({AUDIO_START_TIMEOUT}s)")
            
            if DEBUG_MODE:
                debug_log(f"Playbacks registrados: {len(self.playback_map)}")
                for playback_id, channel in self.playback_map.items():
                    debug_log(f"  - Playback ID: {playback_id}, Channel: {channel}")

            self.call_status = CallStatus.AUDIO_FAILED
            self.log_call_attempt(CallStatus.AUDIO_FAILED)
            await self.finalizar_llamada()

    async def silent_call_timeout(self):
        """Ends the call if it remains too long without audio activity"""
        await asyncio.sleep(MAX_SILENT_CALL_DURATION)
        if self.active_channel and self.audio_requested_time and not self.audio_started and self.call_status == CallStatus.ANSWERED:
            elapsed = time.time() - self.audio_requested_time
            current_num, total_num = self._get_client_progress_info()
            progress_log(f"🔇 Cliente {current_num}/{total_num} - Llamada silenciosa por {elapsed:.1f}s")

            if self.playback_map:
                debug_log(f"Playbacks registrados pero audio_started=False: {len(self.playback_map)}")
                debug_log("Forzando audio_started=True como medida preventiva")
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
                self.silent_call_timeout_task = asyncio.create_task(self.silent_call_timeout())

                debug_log(f"Solicitando reproducción de audio: {AUDIO_FILE}")
                debug_log(f"URL: {url}")
                debug_log(f"Datos: {json.dumps(data, indent=2)}")

                async with self.session.post(url, json=data) as response:
                    response_text = await response.text()
                    debug_log(f"Respuesta de reproducción de audio: {response_text}")
                    
                    if response.status == 201:
                        playback = json.loads(response_text)
                        playback_id = playback['id']
                        progress_log(f"🎵 Audio solicitado - ID: {playback_id}")
                        self.playback_map[playback_id] = self.active_channel
                        debug_log(f"Playback map actualizado: {self.playback_map}")

                        # Schedule a check for call completion
                        asyncio.create_task(self.check_call_completion(playback_id))
                    else:
                        logging.error(f"❌ Error reproduciendo audio: {response_text}")
                        self.call_status = CallStatus.AUDIO_FAILED
                        await self.finalizar_llamada()
            except Exception as e:
                logging.error(f"❌ Excepción en reproducir_audio: {e}")
                self.call_status = CallStatus.AUDIO_FAILED
                await self.finalizar_llamada()

    async def check_call_completion(self, playback_id):
        """Checks if a playback has finished to end the call"""
        try:
            await asyncio.sleep(30)  # Wait 30 seconds

            if self.active_channel and playback_id in self.playback_map and self.call_status not in [CallStatus.COMPLETED, CallStatus.FAILED]:
                debug_log(f"Verificando completado de audio sin evento PlaybackFinished: {playback_id}")

                url = f"{ARI_URL}/playbacks/{playback_id}"
                try:
                    async with self.session.get(url) as response:
                        if response.status == 404:
                            debug_log(f"Playback {playback_id} ya no existe, asumiendo terminado")
                            self.call_status = CallStatus.COMPLETED
                            await self.finalizar_llamada(status=CallStatus.COMPLETED)
                        else:
                            playback_data = await response.json()
                            playback_state = playback_data.get('state')
                            debug_log(f"Estado actual del playback {playback_id}: {playback_state}")

                            if playback_state in ['done', 'cancelled']:
                                self.call_status = CallStatus.COMPLETED
                                await self.finalizar_llamada(status=CallStatus.COMPLETED)
                except Exception as e:
                    debug_log(f"Error verificando estado del playback: {e}")
                    self.call_status = CallStatus.COMPLETED
                    await self.finalizar_llamada(status=CallStatus.COMPLETED)
        except Exception as e:
            debug_log(f"Error en check_call_completion: {e}")

    async def manejar_eventos(self, websocket):
        """Processes WebSocket events - CORRECCIÓN BÁSICA APLICADA"""
        try:
            debug_log(f"Llamada iniciada, entrando en bucle de eventos para cliente {self._get_client_progress_info()[0]}")
            
            while True:
                try:
                    # CORRECCIÓN BÁSICA 1: Agregar timeout simple a la espera de eventos
                    try:
                        mensaje = await asyncio.wait_for(websocket.recv(), timeout=EVENT_TIMEOUT)
                    except asyncio.TimeoutError:
                        # Si hay timeout pero la llamada está completada, salir
                        if self.call_status == CallStatus.COMPLETED:
                            debug_log("Timeout en eventos - llamada ya completada, saliendo")
                            break
                        # Para otros casos, continuar esperando
                        continue
                    
                    evento = json.loads(mensaje)
                    tipo = evento.get('type')
                    debug_log(f"Evento recibido: {tipo}")

                    if tipo == 'Dial':
                        dial_state = evento.get('dialstatus')
                        if dial_state == 'RINGING':
                            self.call_status = CallStatus.RINGING
                            debug_log("Llamada está sonando")

                    elif tipo == 'StasisStart':
                        self.active_channel = evento['channel']['id']
                        self.call_status = CallStatus.ANSWERED
                        current_num, total_num = self._get_client_progress_info()
                        progress_log(f"📞 CONTESTADA - Cliente {current_num}/{total_num} - Canal: {self.active_channel}")

                        # Cancel the timeout if it exists
                        if self.timeout_task:
                            self.timeout_task.cancel()
                            self.timeout_task = None

                        # NUEVA LÓGICA: LLAMADA EXITOSA EN StasisStart
                        if self.user_id and not self.db_updated_on_playback:
                            try:
                                conn = mysql.connector.connect(
                                    host=MYSQL_SERVER,
                                    database=MYSQL_DATABASE,
                                    user=MYSQL_USER,
                                    password=MYSQL_PASSWORD
                                )
                                
                                if conn.is_connected():
                                    cursor = conn.cursor()
                                    current_date = datetime.now().strftime('%Y-%m-%d')
                                    
                                    update_query = """
                                    UPDATE afiliados 
                                    SET outbound_call_is_sent = 1,
                                        outbound_call_attempts = %s, 
                                        outbound_call_completed_at = %s 
                                    WHERE id = %s
                                    """
                                    
                                    cursor.execute(update_query, (self.attempt_count, current_date, self.user_id))
                                    conn.commit()
                                    
                                    progress_log(f"✅ LLAMADA EXITOSA - Cliente {current_num}/{total_num} registrada en BD")
                                    debug_log(f"BD actualizada: intento {self.attempt_count}, fecha {current_date}")
                                    
                                    self.db_updated_on_playback = True
                                    
                                    cursor.close()
                                    conn.close()
                                    
                            except Error as e:
                                logging.error(f"❌ Error actualizando BD en StasisStart: {e}")

                        # Reproducir audio (opcional, no afecta el éxito)
                        await asyncio.sleep(1)
                        await self.reproducir_audio()

                        # Programar finalización de llamada después de un tiempo
                        asyncio.create_task(self.finalizar_llamada_exitosa())
                    
                    elif tipo == 'PlaybackStarted':
                        playback_id = evento['playback']['id']
                        if playback_id in self.playback_map:
                            current_num, total_num = self._get_client_progress_info()
                            progress_log(f"🎵 AUDIO INICIADO - Cliente {current_num}/{total_num} - ID: {playback_id}")
                            self.audio_started = True
                            self.audio_started_time = time.time()
                            
                            # Ya no es necesario actualizar BD aquí (se hace en StasisStart)
                            debug_log("Audio iniciado - BD ya actualizada en StasisStart")

                    elif tipo == 'PlaybackFinished':
                        playback_id = evento['playback']['id']
                        if playback_id in self.playback_map:
                            current_num, total_num = self._get_client_progress_info()
                            
                            if self.audio_started_time:
                                audio_duration = time.time() - self.audio_started_time
                                progress_log(f"🎵 AUDIO COMPLETADO - Cliente {current_num}/{total_num} - Duración: {audio_duration:.2f}s")

                            await asyncio.sleep(2)
                            await self.finalizar_llamada(status=CallStatus.COMPLETED)
                            
                            # CORRECCIÓN BÁSICA 2: Salir del bucle inmediatamente después de audio completado
                            debug_log(f"Audio completado - saliendo del bucle de eventos para cliente {current_num}")
                            return  # Salir completamente del método

                    elif tipo == 'StasisEnd':
                        if evento.get('channel', {}).get('id') == self.active_channel:
                            debug_log("Llamada terminada por el destino")
                            self.active_channel = None
                            if self.call_status == CallStatus.ANSWERED:
                                self.call_status = CallStatus.COMPLETED

                    elif tipo == 'ChannelStateChange':
                        state = evento.get('channel', {}).get('state')
                        debug_log(f"Estado del canal cambió a: {state}")
                        if state == 'Up' and self.call_status != CallStatus.ANSWERED:
                            self.call_status = CallStatus.ANSWERED

                    elif tipo == 'ChannelDestroyed':
                        channel_id = evento.get('channel', {}).get('id')
                        if channel_id == self.call_id:
                            debug_log(f"Canal destruido: {channel_id}")

                            call_duration = None
                            if self.call_start_time:
                                call_duration = round(time.time() - self.call_start_time)

                            if self.call_status not in [CallStatus.COMPLETED]:
                                # Si hubo StasisStart pero no se marcó como completado, es un fallo técnico
                                if self.call_status == CallStatus.ANSWERED and self.db_updated_on_playback:
                                    # La llamada fue exitosa (StasisStart + BD actualizada)
                                    current_num, total_num = self._get_client_progress_info()
                                    progress_log(f"✅ Cliente {current_num}/{total_num} - LLAMADA COMPLETADA EXITOSAMENTE")
                                    self.log_call_attempt(CallStatus.COMPLETED, call_duration)
                                    
                                    if current_num < total_num:
                                        progress_log(f"🔄 CONTINUANDO CON SIGUIENTE CLIENTE ({current_num + 1}/{total_num})")
                                    
                                    debug_log(f"Terminando bucle de eventos para cliente exitoso {current_num}/{total_num}")
                                    break
                                elif self.call_status == CallStatus.ANSWERED and not self.db_updated_on_playback:
                                    self.call_status = CallStatus.AUDIO_FAILED
                                elif self.call_status not in [CallStatus.AUDIO_FAILED]:
                                    self.call_status = CallStatus.FAILED

                                self.log_call_attempt(self.call_status, call_duration)

                                # Lógica de reintentos
                                if self.attempt_count < MAX_RETRIES:
                                    current_num, total_num = self._get_client_progress_info()
                                    retry_reason = "fallo de audio" if self.call_status == CallStatus.AUDIO_FAILED else "llamada fallida"
                                    
                                    progress_log(f"🔄 Cliente {current_num}/{total_num} - Reintento #{self.attempt_count + 1} en {RETRY_DELAY}s por {retry_reason}")
                                    debug_log(f"Esperando {RETRY_DELAY} segundos antes del siguiente intento")
                                    
                                    await asyncio.sleep(RETRY_DELAY)
                                    
                                    # Reset states for the new attempt
                                    self.active_channel = None
                                    self.call_id = None
                                    self.audio_started = False
                                    self.audio_requested_time = None
                                    self.audio_started_time = None
                                    
                                    if await self.iniciar_llamada():
                                        continue
                                    else:
                                        break
                                else:
                                    current_num, total_num = self._get_client_progress_info()
                                    progress_log(f"❌ Cliente {current_num}/{total_num} - MÁXIMO DE INTENTOS ALCANZADO ({MAX_RETRIES})")
                                    
                                    if current_num < total_num:
                                        progress_log(f"🔄 CONTINUANDO CON SIGUIENTE CLIENTE ({current_num + 1}/{total_num})")
                                    
                                    break
                            else:
                                # LLAMADA EXITOSA - REGISTRAR Y TERMINAR CORRECTAMENTE
                                current_num, total_num = self._get_client_progress_info()
                                if self.call_status == CallStatus.ANSWERED and call_duration:
                                    self.log_call_attempt(CallStatus.COMPLETED, call_duration)
                                
                                progress_log(f"✅ Cliente {current_num}/{total_num} - LLAMADA COMPLETADA EXITOSAMENTE")
                                
                                if current_num < total_num:
                                    progress_log(f"🔄 CONTINUANDO CON SIGUIENTE CLIENTE ({current_num + 1}/{total_num})")
                                
                                debug_log(f"Terminando bucle de eventos para cliente exitoso {current_num}/{total_num}")
                                break

                except websockets.ConnectionClosed:
                    debug_log("Conexión WebSocket cerrada durante el manejo de eventos")
                    break
                except Exception as e:
                    logging.error(f"❌ Error procesando evento individual: {e}")
                    continue

        except Exception as e:
            logging.error(f"❌ Error en manejar_eventos: {e}")
            await self.finalizar_llamada()
        finally:
            debug_log(f"Bucle de eventos terminado para cliente {self._get_client_progress_info()[0]}")

    async def finalizar_llamada(self, status=None):
        """Ends the active call"""
        try:
            # CORRECCIÓN BÁSICA 3: CANCELACIÓN SIMPLE DE TODOS LOS TIMEOUTS
            timeout_tasks = [self.timeout_task, self.audio_timeout_task, self.silent_call_timeout_task]
            for task in timeout_tasks:
                if task and not task.done():
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass

            self.timeout_task = None
            self.audio_timeout_task = None
            self.silent_call_timeout_task = None
            
            debug_log("Todos los timeouts cancelados en finalizar_llamada")

            if status:
                self.call_status = status

            call_duration = None
            if self.call_start_time:
                call_duration = round(time.time() - self.call_start_time)
            
            debug_log(f"Finalizando llamada con estado: {self.call_status}")
            debug_log(f"Canal activo: {self.active_channel}")
            
            if self.active_channel:
                url = f"{ARI_URL}/channels/{self.active_channel}"
                async with self.session.delete(url) as response:
                    if response.ok:
                        debug_log(f"Llamada terminada exitosamente (duración: {call_duration}s)")
                        if self.call_status == CallStatus.ANSWERED and not status:
                            self.log_call_attempt(CallStatus.COMPLETED, call_duration)
                    else:
                        response_text = await response.text()
                        if "Channel not found" in response_text:
                            debug_log("Canal ya no existe, probablemente ya terminó")
                        else:
                            debug_log(f"Error terminando llamada: {response_text}")

                        if not status:
                            self.log_call_attempt(self.call_status or CallStatus.FAILED, call_duration)
            
            debug_log("Llamada terminada")
        except Exception as e:
            logging.error(f"❌ Error terminando llamada: {e}")
        finally:
            self.active_channel = None
            self.call_id = None
            self.audio_started = False
            self.audio_requested_time = None
            self.audio_started_time = None

    async def finalizar_llamada_exitosa(self):
        """Finaliza una llamada exitosa después de un tiempo razonable"""
        await asyncio.sleep(45)  # Esperar 45 segundos para que se reproduzca el audio
        
        if self.active_channel and self.call_status == CallStatus.ANSWERED:
            current_num, total_num = self._get_client_progress_info()
            progress_log(f"✅ Cliente {current_num}/{total_num} - FINALIZANDO LLAMADA EXITOSA")
            await self.finalizar_llamada(status=CallStatus.COMPLETED)

    async def ejecutar(self):
        """Main execution flow"""
        current_num, total_num = self._get_client_progress_info()
        debug_log(f"=== INICIANDO EJECUCIÓN PARA CLIENTE {current_num}/{total_num} ===")
        
        try:
            await self.setup_session()
            debug_log(f"Sesión HTTP configurada para cliente {current_num}")
            
            async with websockets.connect(
                f"{WEBSOCKET_URL}?api_key={USERNAME}:{PASSWORD}&app=overdue-app",
                ping_interval=30,
                ping_timeout=10
            ) as websocket:
                debug_log(f"WebSocket conectado para cliente {current_num}")
                await asyncio.sleep(5)
                
                if await self.iniciar_llamada():
                    debug_log(f"Llamada iniciada, entrando en bucle de eventos para cliente {current_num}")
                    await self.manejar_eventos(websocket)
                    debug_log(f"Bucle de eventos terminado para cliente {current_num}")
                else:
                    debug_log(f"Fallo al iniciar llamada para cliente {current_num}")

        except websockets.exceptions.ConnectionClosed as e:
            logging.error(f"❌ Conexión WebSocket cerrada para cliente {current_num}: {e}")
            self.final_result.update({
                'status': 'FAILED',
                'failure_reason': 'WEBSOCKET_CONNECTION_CLOSED',
                'attempts': self.attempt_count
            })
        except Exception as e:
            logging.error(f"❌ Error en ejecución principal del cliente {current_num}: {e}")
            debug_log(f"Error detallado para cliente {current_num}: {e}", exc_info=True)
            await self.finalizar_llamada()
            self.final_result.update({
                'status': 'FAILED',
                'failure_reason': 'EXECUTION_ERROR',
                'attempts': self.attempt_count
            })
        finally:
            await self.cleanup_session()
            debug_log(f"Sesión limpiada para cliente {current_num}")
            
        debug_log(f"=== RETORNANDO RESULTADO PARA CLIENTE {current_num}: {self.final_result} ===")
        
        # Retornar resultado final
        return self.final_result

class CallManager:
    """Class to manage multiple calls with enhanced logging and statistics"""

    def __init__(self):
        self.pending_calls = []
        self.timeout_task = None
        self.timeout_seconds = BASE_SCRIPT_TIMEOUT
        self.timeout_event = asyncio.Event()
        
        # NUEVAS VARIABLES PARA ESTADÍSTICAS
        self.call_results = []
        self.total_clients = 0
        self.successful_calls = 0
        self.failed_calls = 0
        self.current_client_number = 0

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
                logging.error("❌ Fallo al conectar a MySQL")
                return None
        except Error as e:
            logging.error(f"❌ Error conectando a MySQL: {e}")
            return None

    async def check_asterisk_status(self):
        """Verifica el estado del sistema Asterisk antes de iniciar llamadas"""
        progress_log("🔍 VERIFICANDO ESTADO DEL SISTEMA ASTERISK...")
        
        try:
            # Crear sesión temporal para verificaciones
            timeout = aiohttp.ClientTimeout(total=10)
            async with aiohttp.ClientSession(
                auth=aiohttp.BasicAuth(USERNAME, PASSWORD),
                timeout=timeout
            ) as session:
                
                # 1. Verificar canales activos
                try:
                    channels_url = f"{ARI_URL}/channels"
                    async with session.get(channels_url) as response:
                        if response.status == 200:
                            channels = await response.json()
                            progress_log(f"📊 Canales activos: {len(channels)}")
                            if len(channels) > 50:  # Threshold de advertencia
                                progress_log(f"⚠️ ADVERTENCIA: Muchos canales activos ({len(channels)})")
                        else:
                            progress_log(f"❌ Error consultando canales: {response.status}")
                except Exception as e:
                    progress_log(f"❌ Error verificando canales: {e}")
                
                # 2. Verificar endpoints (trunks)
                try:
                    endpoints_url = f"{ARI_URL}/endpoints"
                    async with session.get(endpoints_url) as response:
                        if response.status == 200:
                            endpoints = await response.json()
                            progress_log(f"📊 Endpoints disponibles: {len(endpoints)}")
                            
                            # Buscar nuestro trunk específico
                            trunk_found = False
                            for endpoint in endpoints:
                                if TRUNK_NAME in endpoint.get('resource', ''):
                                    trunk_found = True
                                    state = endpoint.get('state', 'unknown')
                                    progress_log(f"🔗 Trunk {TRUNK_NAME}: {state}")
                                    break
                            
                            if not trunk_found:
                                progress_log(f"⚠️ ADVERTENCIA: Trunk {TRUNK_NAME} no encontrado")
                        else:
                            progress_log(f"❌ Error consultando endpoints: {response.status}")
                except Exception as e:
                    progress_log(f"❌ Error verificando endpoints: {e}")
                
                # 3. Verificar aplicación Stasis
                try:
                    apps_url = f"{ARI_URL}/applications"
                    async with session.get(apps_url) as response:
                        if response.status == 200:
                            apps = await response.json()
                            app_found = False
                            for app in apps:
                                if app.get('name') == 'overdue-app':
                                    app_found = True
                                    channels_in_app = len(app.get('channel_ids', []))
                                    progress_log(f"📱 Aplicación 'overdue-app': {channels_in_app} canales")
                                    break
                            
                            if not app_found:
                                progress_log("⚠️ ADVERTENCIA: Aplicación 'overdue-app' no encontrada")
                        else:
                            progress_log(f"❌ Error consultando aplicaciones: {response.status}")
                except Exception as e:
                    progress_log(f"❌ Error verificando aplicaciones: {e}")
        
        except Exception as e:
            progress_log(f"❌ Error general verificando Asterisk: {e}")
        
        progress_log("✅ Verificación del sistema completada")
        progress_log("-" * 60)

    async def cleanup_stale_channels(self):
        """Limpia canales colgados que pueden estar causando el allocation failed"""
        progress_log("🧹 LIMPIANDO CANALES COLGADOS...")
        
        try:
            timeout = aiohttp.ClientTimeout(total=15)
            async with aiohttp.ClientSession(
                auth=aiohttp.BasicAuth(USERNAME, PASSWORD),
                timeout=timeout
            ) as session:
                
                # Obtener todos los canales
                channels_url = f"{ARI_URL}/channels"
                async with session.get(channels_url) as response:
                    if response.status == 200:
                        channels = await response.json()
                        progress_log(f"🔍 Encontrados {len(channels)} canales activos")
                        
                        channels_cleaned = 0
                        for channel in channels:
                            channel_id = channel.get('id')
                            channel_state = channel.get('state')
                            
                            # Limpiar canales en estado problemático
                            if channel_state in ['Down', 'Reserved'] or 'overdue-app' in channel.get('dialplan', {}).get('app_name', ''):
                                try:
                                    delete_url = f"{ARI_URL}/channels/{channel_id}"
                                    async with session.delete(delete_url) as del_response:
                                        if del_response.status in [200, 404]:  # 404 = ya no existe
                                            channels_cleaned += 1
                                            debug_log(f"Canal limpiado: {channel_id} (estado: {channel_state})")
                                        else:
                                            debug_log(f"No se pudo limpiar canal {channel_id}: {del_response.status}")
                                except Exception as e:
                                    debug_log(f"Error limpiando canal {channel_id}: {e}")
                        
                        progress_log(f"✅ Limpieza completada: {channels_cleaned} canales removidos")
                    else:
                        progress_log(f"❌ Error obteniendo lista de canales: {response.status}")
        
        except Exception as e:
            progress_log(f"❌ Error en limpieza de canales: {e}")

    def load_pending_calls(self):
        """Loads pending calls from MySQL database with enhanced logging"""
        progress_log("📋 Consultando clientes pendientes en base de datos...")
        
        conn = self.connect_to_mysql()
        if not conn:
            return False

        try:
            cursor = conn.cursor(dictionary=True)
            
            current_day = datetime.now().day
            debug_log(f"Día actual para verificación de corte: {current_day}")
            
            query = """
            SELECT a.id, a.telefono, a.outbound_call_attempts, a.corte, a.cliente,
                   SUM(CASE WHEN f.cerrado = 0 THEN f.saldo ELSE 0 END) AS deuda_total
            FROM afiliados a
            LEFT JOIN factura f ON a.id = f.`id-afiliado`
            WHERE a.outbound_call = 1 
            AND a.outbound_call_is_sent = 0
            AND a.activo = 1
            AND a.eliminar = 0
            GROUP BY a.id, a.telefono, a.outbound_call_attempts, a.corte
            HAVING deuda_total > 0
            ORDER BY a.id
            """
            
            debug_log("Ejecutando consulta SQL:")
            debug_log(query)
            
            cursor.execute(query)
            results = cursor.fetchall()
            
            progress_log(f"📊 Encontrados {len(results)} clientes con facturas pendientes")
            
            self.pending_calls = []
            excluded_count = 0
            
            for row in results:
                user_id = row['id']
                cliente = row['cliente']
                phone = row['telefono'].strip() if row['telefono'] else ""
                attempts = row['outbound_call_attempts'] or 0
                corte = row['corte']
                deuda_total = row['deuda_total']
                
                debug_log(f"Evaluando cliente {user_id}: teléfono={phone}, corte={corte}, deuda={deuda_total} nombre={cliente}")
                
                # Verificar el día de corte
                if corte and corte.isdigit():
                    corte_day = int(corte)
                    is_valid_call_day = ((current_day == corte_day - 1) or (current_day >= corte_day)) and (corte_day >= current_day-3)
                    
                    if not is_valid_call_day:
                        debug_log(f"------Cliente {user_id} nombre={cliente} corte={corte} EXCLUIDO - día actual: ({current_day}) corte :({corte_day})")
                        excluded_count += 1
                        continue
                
                # Validación de teléfono móvil colombiano
                if phone and len(phone) == 10 and phone.startswith('3'):
                    formatted_phone = '57' + phone
                    
                    debug_log(f"Cliente {user_id} INCLUIDO - teléfono válido: {formatted_phone}")
                    
                    self.pending_calls.append({
                        "user_id": user_id,
                        "cliente": cliente,
                        "phone_number": formatted_phone,
                        "attempts": attempts,
                        "deuda_total": deuda_total,
                        "corte": corte
                    })
                else:
                    debug_log(f"Cliente {user_id} excluido - teléfono inválido: '{phone}'")
                    excluded_count += 1
            
            cursor.close()
            conn.close()
            
            progress_log(f"✅ {len(self.pending_calls)} clientes elegibles para llamada")
            if excluded_count > 0:
                progress_log(f"⚠️ {excluded_count} clientes excluidos por validaciones")
            
            return len(self.pending_calls) > 0
            
        except Error as e:
            logging.error(f"❌ Error consultando llamadas pendientes: {e}")
            if conn.is_connected():
                cursor.close()
                conn.close()
            return False

    def show_final_summary(self):
        """Muestra resumen final de todas las llamadas realizadas"""
        progress_log("\n" + "=" * 80)
        progress_log("🏁 RESUMEN FINAL DE LLAMADAS AUTOMÁTICAS")
        progress_log("=" * 80)
        progress_log(f"📊 TOTAL PROCESADO: {self.total_clients} clientes")
        progress_log(f"✅ LLAMADAS EXITOSAS: {self.successful_calls}")
        progress_log(f"❌ LLAMADAS FALLIDAS: {self.failed_calls}")
        
        if self.total_clients > 0:
            success_rate = (self.successful_calls/self.total_clients*100)
            progress_log(f"📈 TASA DE ÉXITO: {success_rate:.1f}%")
        
        progress_log("-" * 80)
        
        # Detalle por cliente
        for i, result in enumerate(self.call_results, 1):
            status_icon = "✅" if result['status'] == 'SUCCESS' else "❌"
            progress_log(f"{status_icon} Cliente {i}: ID {result['user_id']} - {result['phone']}")
            progress_log(f"   Estado: {result['status']} | Intentos: {result['attempts']}")
            
            if result['status'] == 'SUCCESS':
                duration = result.get('duration', 0)
                progress_log(f"   ✅ Audio reproducido correctamente (Duración: {duration}s)")
            else:
                progress_log(f"   ❌ Razón: {result['failure_reason']}")
        
        progress_log("=" * 80)
        
        # Resumen de razones de fallo
        if self.failed_calls > 0:
            failure_reasons = {}
            for result in self.call_results:
                if result['status'] != 'SUCCESS':
                    reason = result['failure_reason']
                    failure_reasons[reason] = failure_reasons.get(reason, 0) + 1
            
            progress_log("📋 ANÁLISIS DE FALLOS:")
            for reason, count in failure_reasons.items():
                progress_log(f"   • {reason}: {count} cliente(s)")
            progress_log("=" * 80)

    async def update_timeout(self, additional_seconds):
        """Updates the timeout duration and extends the existing timeout task"""
        self.timeout_seconds += additional_seconds
        
        if self.timeout_task and not self.timeout_task.done():
            self.timeout_task.cancel()
            debug_log(f"Timeout extendido a {self.timeout_seconds} segundos")
        
        self.timeout_task = asyncio.create_task(self.terminar_por_timeout())

    async def terminar_por_timeout(self):
        """Ends the script after a timeout period"""
        try:
            await asyncio.wait_for(self.timeout_event.wait(), timeout=self.timeout_seconds)
            debug_log("Timeout task completado normalmente")
        except asyncio.TimeoutError:
            logging.warning(f"⏰ ¡TIEMPO MÁXIMO DE {self.timeout_seconds} SEGUNDOS ALCANZADO!")
            logging.warning("🛑 Terminación forzada para evitar costos excesivos")
            os._exit(0)

    async def process_pending_calls(self):
        """Processes all pending calls with enhanced progress logging"""
        if not self.load_pending_calls():
            progress_log("⚠️ No hay llamadas pendientes para procesar")
            self.timeout_event.set()
            return
        
        # NUEVA VERIFICACIÓN DEL SISTEMA ANTES DE INICIAR
        await self.check_asterisk_status()
        
        # NUEVA LIMPIEZA DE CANALES COLGADOS
        await self.cleanup_stale_channels()
        
        # Establecer totales y mostrar resumen inicial
        self.total_clients = len(self.pending_calls)
        progress_log("\n" + "=" * 80)
        progress_log("🚀 INICIANDO PROCESAMIENTO DE LLAMADAS AUTOMÁTICAS")
        progress_log(f"📊 TOTAL DE CLIENTES A PROCESAR: {self.total_clients}")
        progress_log(f"⏰ Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        progress_log(f"🔥 TIMEOUT GLOBAL DESHABILITADO - Script procesará TODOS los clientes")
        progress_log("=" * 80)
        
        # Procesar cada llamada con contador de progreso
        for call_index, call_data in enumerate(self.pending_calls, 1):
            self.current_client_number = call_index
            user_id = call_data.get("user_id")
            cliente = call_data.get("cliente", "Desconocido")
            phone_number = call_data.get("phone_number")
            deuda_total = call_data.get("deuda_total", 0)
            corte = call_data.get("corte", "N/A")
            
            debug_log(f"=== INICIANDO BUCLE PARA CLIENTE {call_index}/{self.total_clients} (ID: {user_id}) ===")
            
            # Log de progreso detallado
            progress_log("\n" + "=" * 60)
            progress_log(f"📞 PROCESANDO CLIENTE {self.current_client_number} DE {self.total_clients}")
            progress_log(f"👤 ID Cliente: {user_id}")
            progress_log(f"🧑‍🤝‍🧑 Nombre Cliente: {cliente}")
            progress_log(f"📱 Teléfono: {phone_number}")
            progress_log(f"💰 Deuda Total: ${deuda_total:,.2f}")
            progress_log(f"📅 Día de Corte: {corte}")
            progress_log("=" * 60)
            
            # CANCELACIÓN ROBUSTA DE TIMEOUTS ANTERIORES
            if self.timeout_task and not self.timeout_task.done():
                self.timeout_task.cancel()
                try:
                    await self.timeout_task
                except asyncio.CancelledError:
                    pass
                debug_log(f"Timeout anterior cancelado completamente para cliente {self.current_client_number}")
            
            # Reset timeout configurations per user
            self.timeout_event = asyncio.Event()
            self.timeout_seconds = BASE_SCRIPT_TIMEOUT
            debug_log(f"Timeout fresco de {self.timeout_seconds}s para cliente {user_id}")
            
            # Crear nuevo timeout task
            self.timeout_task = asyncio.create_task(self.terminar_por_timeout())
            
            # Procesar llamada con información del cliente
            try:
                llamador = LlamadorAutomatico(
                    destination=phone_number, 
                    user_id=user_id,
                    client_info={
                        'current_number': self.current_client_number,
                        'total_clients': self.total_clients,
                        'cliente': cliente,
                        'deuda_total': deuda_total,
                        'corte': corte
                    }
                )
                
                debug_log(f"Iniciando procesamiento del cliente {self.current_client_number}/{self.total_clients}")
                
                # Obtener resultado de la llamada
                call_result = await llamador.ejecutar()
                
                debug_log(f"Cliente {self.current_client_number} procesado. Resultado: {call_result}")
                
                # CANCELAR TIMEOUT INMEDIATAMENTE DESPUÉS DEL PROCESAMIENTO
                if self.timeout_task and not self.timeout_task.done():
                    self.timeout_task.cancel()
                    try:
                        await self.timeout_task
                    except asyncio.CancelledError:
                        pass
                    debug_log(f"Timeout del cliente {self.current_client_number} cancelado después del procesamiento")
                
                self.call_results.append(call_result)
                
                # Actualizar contadores
                if call_result['status'] == 'SUCCESS':
                    self.successful_calls += 1
                    progress_log(f"✅ Cliente {self.current_client_number}/{self.total_clients} - CONTACTADO EXITOSAMENTE")
                else:
                    self.failed_calls += 1
                    progress_log(f"❌ Cliente {self.current_client_number}/{self.total_clients} - NO CONTACTADO")
                
                # CORRECCIÓN BÁSICA 4: Pausa aumentada entre llamadas
                if self.current_client_number < self.total_clients:
                    progress_log(f"⏳ Esperando {INTER_CLIENT_DELAY} segundos antes del siguiente cliente...")
                    debug_log(f"Pausa de {INTER_CLIENT_DELAY} segundos antes del siguiente cliente")
                    await asyncio.sleep(INTER_CLIENT_DELAY)
                
                debug_log(f"=== CLIENTE {self.current_client_number}/{self.total_clients} COMPLETADO ===")
                    
            except Exception as e:
                logging.error(f"❌ Error procesando cliente {self.current_client_number}: {e}")
                debug_log(f"Error detallado procesando cliente {user_id}: {e}", exc_info=True)
                
                # CANCELAR TIMEOUT EN CASO DE ERROR TAMBIÉN
                if self.timeout_task and not self.timeout_task.done():
                    self.timeout_task.cancel()
                    try:
                        await self.timeout_task
                    except asyncio.CancelledError:
                        pass
                    debug_log(f"Timeout cancelado después de error en cliente {self.current_client_number}")
                
                # Registrar como fallido y continuar
                failed_result = {
                    'user_id': user_id,
                    'phone': phone_number,
                    'status': 'FAILED',
                    'attempts': 0,
                    'failure_reason': 'PROCESSING_ERROR',
                    'duration': None,
                    'audio_played': False
                }
                self.call_results.append(failed_result)
                self.failed_calls += 1
                
                progress_log(f"❌ Cliente {self.current_client_number}/{self.total_clients} - ERROR EN PROCESAMIENTO")
                
                # Continuar con el siguiente cliente después de un error
                if self.current_client_number < self.total_clients:
                    progress_log(f"🔄 CONTINUANDO CON SIGUIENTE CLIENTE ({self.current_client_number + 1}/{self.total_clients})")
                    await asyncio.sleep(INTER_CLIENT_DELAY)
                
                debug_log(f"=== CLIENTE {self.current_client_number}/{self.total_clients} COMPLETADO CON ERROR ===")

        # CANCELACIÓN FINAL DE TIMEOUT
        if self.timeout_task and not self.timeout_task.done():
            self.timeout_event.set()
            self.timeout_task.cancel()
            try:
                await self.timeout_task
            except asyncio.CancelledError:
                pass
            debug_log("Timeout final cancelado completamente")
        
        progress_log(f"\n🏁 PROCESAMIENTO COMPLETADO - {self.total_clients} clientes procesados")
        self.show_final_summary()

async def main():
    try:
        progress_log("🚀 Iniciando sistema de llamadas automáticas")
        progress_log(f"🔧 Modo DEBUG: {'ACTIVADO' if DEBUG_MODE else 'DESACTIVADO'}")
        progress_log("✅ TIMEOUT GLOBAL DESHABILITADO - Script procesará todos los clientes")
        
        call_manager = CallManager()
        await call_manager.process_pending_calls()
        
        progress_log("✅ Sistema de llamadas finalizado correctamente")
        
    except Exception as e:
        logging.error(f"❌ Error en función principal: {e}")
        debug_log("Traceback completo:", exc_info=True)

if __name__ == "__main__":
    asyncio.run(main())