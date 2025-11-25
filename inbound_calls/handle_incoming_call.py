#!/usr/bin/env python3
import subprocess
import sys
import socket
import os
import json
import logging
import asyncio
import threading
import websockets
import numpy as np
import webrtcvad
import random
from scipy import signal
from datetime import datetime
import aiohttp
import wave
from collections import deque
import time
from audioop import ulaw2lin
import websocket
import base64

# IMPORTANTE: Este script debe usar el siguiente Dialplan en Asterisk para funcionar correctamente.
# Configuración de dialplan  para handle_call.py ......

# sudo cat /etc/asterisk/extensions.conf

# [from-voip]
# exten => 3241000752,1,Answer()
#     same => n,Set(CHANNEL(audioreadformat)=ulaw)
#     same => n,Set(CHANNEL(audiowriteformat)=ulaw)
#     same => n,Stasis(openai-app)
#     same => n,Hangup()

# [stasis-openai]
# exten => external_start,1,NoOp(External Media iniciado)
#     same => n,Return()

#Reiniciar el dialplan de asterisk para que los cambios surtan efecto
# xxx#sudo  asterisk -rx "dialplan reload"

def check_environment():
    required_vars = {
        'ASTERISK_USERNAME': None,
        'ASTERISK_PASSWORD': None,
        'ASTERISK_HOST': None,
        'ASTERISK_PORT': None,
        'LOG_FILE_PATH': None,
        'LOCAL_IP_ADDRESS': None
    }
    
    missing_vars = []
    
    for var, default in required_vars.items():
        value = os.getenv(var, default)
        if value is None:
            missing_vars.append(var)
        logging.info(f"Variable {var}: {'[CONFIGURADA]' if value else '[NO CONFIGURADA]'}")
    
    if missing_vars:
        logging.error(f"Variables de ambiente requeridas no encontradas: {', '.join(missing_vars)}")
        logging.error("Por favor configure las variables antes de ejecutar el script, Usar la opción -E de sudo para preservar el entorno")
        sys.exit(1)
    
    return {
        'ASTERISK_USERNAME': os.getenv('ASTERISK_USERNAME'),
        'ASTERISK_PASSWORD': os.getenv('ASTERISK_PASSWORD'),
        'ASTERISK_HOST': os.getenv('ASTERISK_HOST'),
        'ASTERISK_PORT': os.getenv('ASTERISK_PORT'),
        'LOG_FILE_PATH': os.getenv('LOG_FILE_PATH'),
        'LOCAL_IP_ADDRESS': os.getenv('LOCAL_IP_ADDRESS')
    }



# Verificar variables de ambiente
env_vars = check_environment()

# Usar las variables verificadas
ASTERISK_HOST = env_vars['ASTERISK_HOST']
ASTERISK_PORT = env_vars['ASTERISK_PORT']
ASTERISK_USERNAME = env_vars['ASTERISK_USERNAME']
ASTERISK_PASSWORD = env_vars['ASTERISK_PASSWORD']
LOG_FILE_PATH = env_vars['LOG_FILE_PATH']
LOCAL_IP_ADDRESS = env_vars['LOCAL_IP_ADDRESS']

# Verificar que el directorio existe
log_dir = os.path.dirname(LOG_FILE_PATH)
if not os.path.exists(log_dir):
    os.makedirs(log_dir)

# Configuración más detallada del logging
logging.basicConfig(
    filename=LOG_FILE_PATH,
    level=logging.DEBUG,
    format='%(asctime)s.%(msecs)03d - %(levelname)s - %(funcName)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    force=True  # Forzar la configuración
)

# # Añadir también un handler para la consola
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
console_handler.setFormatter(formatter)
logging.getLogger('').addHandler(console_handler)


print("Intentando escribir en log...")
logging.info("=== TEST LOG ENTRY ===")
logging.error("=== TEST ERROR ENTRY ===")
print(f"Log file path: {LOG_FILE_PATH}")




class RTPAudioHandler:
    def __init__(self):
        self.socket = None
        self.running = False
        self.sequence_number = 0
        self.timestamp = 0
        self.ssrc = random.randint(0, 2**32 - 1)
        self.audio_buffer = []
        self.silence_counter = 0
        self.is_speaking = False
        self.local_address = None
        self.local_port = None
        self.codec = None
        self.vad = webrtcvad.Vad(2)
        self.tasks = set()
        self.rtp_start_port = 10000
        self.rtp_end_port = 20000
        self.remote_address = None
        self.remote_port = None
        self.remote_configured = False  # Nuevo flag para tracking de endpoint remoto
        self.openai_handler = None

    async def find_available_port(self, local_address):
        """
        Encuentra un puerto disponible dentro del rango RTP configurado
        
        Args:
            local_address (str): Dirección IP local para hacer el binding
        """
        try:
            for port in range(self.rtp_start_port, self.rtp_end_port):
                try:
                    test_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                    test_socket.bind((local_address, port))
                    test_socket.close()
                    return port
                except OSError:
                    continue
            raise Exception("No se encontró puerto RTP disponible")
        except Exception as e:
            logging.error(f"Error buscando puerto disponible: {e}")
            raise

    async def start(self, local_address, local_port, remote_address=None, remote_port=None, codec='ulaw'):
        """
        Inicia el RTP handler con la configuración especificada.
        
        Args:
            local_address (str): Dirección IP local
            local_port (int): Puerto local
            remote_address (str, optional): Dirección IP remota
            remote_port (int, optional): Puerto remoto
            codec (str): Codec a usar ('ulaw' o 'alaw')
        """
        try:
            # Configuración básica
            self.local_address = local_address
            self.local_port = local_port
            self.codec = codec
            
            # Crear socket con opción de reutilización
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)  # Permitir envío externo
            try:
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            except AttributeError:
                pass
            
            # Vincular al puerto
            try:
                self.socket.bind((self.local_address, self.local_port))
                logging.info(
                    f"Socket RTP vinculado a {self.local_address}:{self.local_port} "
                    f"usando codec {codec}"
                )
            except OSError as e:
                logging.error(f"No se pudo vincular al puerto RTP {self.local_port}: {e}")
                return False
                
            self.socket.setblocking(False)
            
            # Configurar endpoint remoto
            self.remote_address = remote_address
            self.remote_port = remote_port
            self.remote_configured = bool(remote_address and remote_port)
            
            if self.remote_configured:
                logging.info(
                    f"Endpoint remoto configurado - IP: {remote_address}, "
                    f"Puerto: {remote_port}"
                )
            else:
                logging.warning("Endpoint remoto no configurado")
            
            # Activar el handler
            self.running = True
            
            # Log de configuración completa
            endpoint_info = (
                f"Local: {self.local_address}:{self.local_port}, "
                f"Remoto: {self.remote_address}:{self.remote_port if self.remote_configured else 'No configurado'}"
            )
            logging.info(f"RTP Handler iniciado - {endpoint_info}")
            
            return True
            
        except Exception as e:
            logging.error(f"Error iniciando RTP Handler: {e}")
            if self.socket:
                self.socket.close()
                self.socket = None
            return False   

    async def process_audio_stream(self, local_address  , codec='ulaw', openai_handler=None):
        """Maneja el flujo principal de audio RTP"""
        try:
            logging.info(f"Iniciando stream de audio - {local_address} ({codec})")
            logging.info(
            f"Iniciando stream RTP - Local: {local_address}, "
            f"Codec: {codec}"
            )
            # if not await self.start(local_address, local_port, codec):
            #     logging.error("Fallo al iniciar el RTP Handler")
            #     return False

            self.openai_handler = openai_handler # Guardar referencia a OpenAIHandler

            logging.info("Stream RTP iniciado exitosamente")
            socket_info = self.socket.getsockname()
            logging.info(
                f"Socket RTP listo en {socket_info[0]}:{socket_info[1]}"
                )
            audio_task = asyncio.create_task(self.process_audio())
            self.tasks.add(audio_task)
            
            # Esperar a que termine el procesamiento
            logging.info("Iniciando procesamiento de audio...")
            await audio_task
            
        except Exception as e:
            logging.error(f"Error en stream de audio: {e}")
            return False
        finally:
            logging.info("Finalizando stream de audio")
            await self.cleanup()

    async def process_audio(self):
        """Procesa el audio RTP entrante"""
        loop = asyncio.get_event_loop()
        frames_processed = 0
        last_log_time = time.time()
        frame_size = None
        
        logging.info(f"*******************************Iniciando bucle de procesamiento de audio en socket {self.socket.getsockname()}**********")
        
        openai_client = OpenAIClient()
        try:
           openai_client.start_in_thread()
        except Exception as e:
            logging.error(f"Error en openai_client: {e}")
            return False

        except Exception as e:
            logging.error(f"Error en openai_client: {e}")
            return False
        try:
            receive_task = asyncio.create_task(self.openai_handler.receive_response(openai_client))
        

            while True:
                try:
                    current_time = time.time()
                    if current_time - last_log_time >= 5:
                        
                        last_log_time = current_time
                    
                    try:
                        data = await asyncio.wait_for(
                            loop.sock_recv(self.socket, 1024),
                            timeout=0.2
                        )
                        frames_processed += 1
                    except asyncio.TimeoutError:
                        continue
                        


                    if not data:
                        logging.debug("Frame RTP vacío")
                        continue

                    # Procesar cabecera RTP y obtener payload
                    payload, sequence_number = self.parse_rtp_header(data)
                    if payload is None or sequence_number is None:
                        logging.warning("Frame RTP inválido")
                        continue

                    # Validar consistencia del tamaño de frame
                    if frame_size is None:
                        frame_size = len(payload)
                    elif len(payload) != frame_size:
                        logging.warning(f"Tamaño de frame inconsistente: {len(payload)} vs {frame_size}")
                        continue
                    # Acumular bytes en un buffer
                    if not hasattr(self, 'byte_buffer'):
                        self.byte_buffer = b''
                    
                    
                    

                    self.byte_buffer += payload
                    chunk = 600  #             160 es Tamaño de chunk en bytes (20 ms a 8 kHz)
                    # Llamar al método cuando se acumulen chunk bytes
                    if len(self.byte_buffer) >= chunk:
                        openai_client.pyload_to_openai(self.byte_buffer[:chunk])
                        self.byte_buffer = self.byte_buffer[chunk:]

                except Exception as e:
                    logging.error(f"Error en process_audio: {e}")
                    continue
        
        
        except asyncio.CancelledError:
            logging.info("Procesamiento de audio cancelado")
            receive_task.cancel()  # Cancelar recepción            

    def parse_rtp_header(self, packet):
        """Parsea la cabecera RTP y retorna el payload y número de secuencia"""
        if len(packet) < 12:
            return None, None

        # Extraer el primer byte para análisis
        first_byte = packet[0]
        version = (first_byte >> 6) & 0x03
        padding = (first_byte >> 5) & 0x01
        extension = (first_byte >> 4) & 0x01
        csrc_count = first_byte & 0x0F

        # Validar versión RTP
        if version != 2:
            logging.warning(f"Versión RTP inválida: {version}")
            return None, None

        # Obtener número de secuencia (bytes 2 y 3)
        sequence_number = (packet[2] << 8) | packet[3]

        # Calcular el offset del payload
        offset = 12 + (csrc_count * 4)
        if extension:
            if len(packet) < offset + 4:
                return None, None
            extension_length = (packet[offset + 2] << 8) | packet[offset + 3]
            offset += 4 + (extension_length * 4)

        # Extraer payload considerando padding
        if padding:
            padding_length = packet[-1]
            payload = packet[offset:-padding_length]
        else:
            payload = packet[offset:]

        return payload, sequence_number

    async def cleanup(self):
        try:
            self.running = False
            
            # Cancelar todas las tareas pendientes
            for task in self.tasks:
                if not task.done():
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
            
            # Limpiar buffer
            self.audio_buffer.clear()
            
            # Cerrar socket de manera segura
            if self.socket:
                try:
                    self.socket.shutdown(socket.SHUT_RDWR)
                except (OSError, socket.error):
                    pass  # Ignorar errores al cerrar socket
                finally:
                    self.socket.close()
                    self.socket = None
                    
            logging.info(f"Recursos liberados para RTP Handler {self.local_address}:{self.local_port}")
            
        except Exception as e:
            logging.error(f"Error durante la limpieza de RTP Handler: {e}")

    async def send_rtp_packet(self, packet):
        """Envía un paquete RTP al socket"""
        try:
            if self.socket:
                self.socket.sendto(packet, (self.remote_address, self.remote_port))
                # logging.debug(
                #     f"Paquete RTP enviado a {self.remote_address}:{self.remote_port} "
                #     f"- {len(packet)} bytes"
                # )
            else:
                logging.error("Error enviando paquete RTP: Socket no disponible")
        except Exception as e:
            logging.error(f"Error enviando paquete RTP: {e}")




class OpenAIClient:
    def __init__(self):
        self.api_key = os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            logging.error("API Key de OpenAI no configurada")
        else:
            logging.info("API Key de OpenAI configurada")

        # Modelo de OpenAI Realtime API
        # IMPORTANTE: Verifica en https://platform.openai.com/docs/models que el modelo esté disponible
        #
        # Versiones disponibles (verificadas Nov 2025):
        # - gpt-4o-realtime-preview-2024-12-17 (estable, probada, RECOMENDADA)
        # - gpt-4o-realtime-preview-2024-10-01 (versión anterior)
        #
        # Versiones más recientes (verificar disponibilidad en tu región):
        # - gpt-4o-realtime-preview-2025-01-21 (si está disponible)
        #
        # Para cambiar de modelo, modifica el parámetro 'model=' en la URL:
        model_name = os.getenv("OPENAI_REALTIME_MODEL", "gpt-4o-realtime-preview-2024-12-17")
        self.url = f"wss://api.openai.com/v1/realtime?model={model_name}"
        logging.info(f"Usando modelo OpenAI Realtime: {model_name}")
        self.headers = [
            "Authorization: Bearer " + self.api_key,
            "OpenAI-Beta: realtime=v1"
        ]
        self.input_audio = None
        self.metrics = {
            'start_time': None,
            'chunks_sent': 0,
            'chunks_received': 0,
            'total_bytes_sent': 0,
            'total_bytes_received': 0,
            'processing_time': 0
        }
        self.incoming_audio_queue = asyncio.Queue()  # Para cuando WS reciba audio
        self.outgoing_audio_queue = asyncio.Queue()  # Para enviar audio al WS
        self.loop = asyncio.get_event_loop()  # Obtener el loop de eventos de asyncio
        # Agregando lógica para interrumpir audio en caso de que el cliente hable mientras el asistente está hablando
        self.current_ws = None
        self.assistant_speaking = False


    def pyload_to_openai(self, audio_data):
        self.outgoing_audio_queue.put_nowait(audio_data)

    def start_in_thread(self):
        thread = threading.Thread(target=self.run, daemon=True)
        thread.start()

    def run(self):
        """Inicia el procesamiento con OpenAI"""
        try:
            self.metrics['start_time'] = time.time()

            # Configurar y ejecutar WebSocket
            ws = websocket.WebSocketApp(
                self.url,
                header=self.headers,
                on_open=self.on_open,
                on_message=self.on_message,
                on_error=self.on_error,
                on_close=self.on_close
            )

            # Agregando lógica para interrumpir audio en caso de que el cliente hable mientras el asistente está hablando
            self.current_ws = ws  


            logging.info("Iniciando conexión WebSocket con OpenAI")
            ws.run_forever()
            logging.info("Conexión WebSocket cerrada")
            return True

        except Exception as e:
            logging.error(f"Error en inicio: {e}")
            return None


    def on_open(self, ws):
        """Maneja apertura de conexión"""
        try:
            config = {
                "type": "session.update",
                "session": {
                    "modalities": ["audio", "text"],
                    "voice": "verse",
                    "instructions": """
                    Contesa de una manera amable y muy detallada.
                    """,
                    "input_audio_format": "g711_ulaw",
                    "output_audio_format": "g711_ulaw",
                    "turn_detection": {
                        "type": "server_vad",
                        "threshold": 0.2,
                        "prefix_padding_ms": 300,
                        "silence_duration_ms": 100,
                    }
                }
            }


            ws.send(json.dumps(config))

        except Exception as e:
            logging.error(f"Error enviando configuración: {e}")

    def on_message(self, ws, message):
        """Procesa mensajes de OpenAI"""
        try:
            data = json.loads(message)
            msg_type = data.get('type', '')

            if msg_type == 'response.created':
                logging.info("Sesión create creada!")

            elif msg_type == 'session.updated':
                logging.info("msg_type updated recibido, ahora enviaré audio chunks")
                asyncio.run_coroutine_threadsafe(self.handle_session_updated(ws), self.loop)
            
            elif msg_type == 'response.audio.delta':
                logging.info("++++++++++++response.audio.delta recibido++++++++++++")
                self.handle_audio_delta(data)
            
            elif msg_type == 'input_audio_buffer.speech_started':
                logging.info("*****************************speech_<START> Recibido***********************************************")
                
                # Limpiar la cola de audio pendiente
                while not self.incoming_audio_queue.empty():
                    try:
                        self.incoming_audio_queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break
                logging.info("Cola de audio limpiada por detección de voz del usuario")
                
            
            elif msg_type == 'input_audio_buffer.speech_stopped':
                logging.info("*****************************speech_<END> recibido***********************************************")
                # self.asistente_callate = False

            elif msg_type == 'response.done':
                logging.info("Respuesta final recibida response.done")
            
            elif msg_type == 'response.audio_transcript.done':
                logging.info(f"Transcripción: {data.get('transcript', '')}")
            
            elif msg_type == 'error':
                self.handle_error(data)

            logging.debug(f"Mensaje procesado: {data}")

        except Exception as e:
            logging.error(f"Error procesando mensaje: {e}")

   

    async def handle_session_updated(self, ws):
        """Maneja confirmación de configuración"""
        try:
            while True:
                # Obtener audio del buffer de salida
                audio_data = await self.outgoing_audio_queue.get()
                self.send_audio_chunk_to_openai(ws, audio_data)
                # logging.info(f"Audios total enviado to_openai : {self.metrics['total_bytes_sent']} bytes >>>>>>>>>>>>")

        except asyncio.CancelledError:
            logging.info("Tarea de envío de audio a OpenAI cancelada.")
        except Exception as e:
            logging.error(f"Error después de configuración: {e}")

    def send_audio_chunk_to_openai(self, ws, chunk):
        """Envía chunk de audio a OpenAI"""
        try:
            if ws.sock and ws.sock.connected:
                audio_event = {
                    "event_id": f"audio_{int(time.time())}",
                    "type": "input_audio_buffer.append",
                    "audio": base64.b64encode(chunk).decode('utf-8')
                }

                ws.send(json.dumps(audio_event))

                self.metrics['chunks_sent'] += 1
                self.metrics['total_bytes_sent'] += len(chunk)

                # logging.debug(
                #     f"Chunk enviado to_openai: {len(chunk)} bytes "
                #     f"(Total: {self.metrics['total_bytes_sent']})"
                # )
            else:
                logging.error("Error enviando chunk: Connection is already closed.")
        except Exception as e:
            logging.error(f"Error enviando chunk: {e}")

    def handle_audio_delta(self, data):
        """Procesa chunks de audio recibidos"""
        try:
            audio_buffer = base64.b64decode(data['delta'])
            self.incoming_audio_queue.put_nowait(audio_buffer)
            # logging.debug(
            #     f"Chunks audio recibido desde openai: {len(audio_buffer)} bytes "
            # )
        except Exception as e:
            logging.error(f"Error procesando audio delta: {e}")

    def handle_error(self, data):
        """Procesa errores de OpenAI"""
        error_msg = data.get('error', {}).get('message', 'Error desconocido')
        logging.error(f"Error de OpenAI: {error_msg}")

    def on_error(self, ws, error):
        """Maneja errores de WebSocket"""
        logging.error(f"Error de WebSocket: {error}")

    def on_close(self, ws, close_status_code, close_msg):
        """Maneja cierre de conexión"""
        logging.info(
            f"Conexión cerrada: {close_status_code} - {close_msg}"
        )




class OpenAIHandler:
    def __init__(self, rtp_handler):
        self.process = None
        self.rtp_handler = rtp_handler
        self.sequence_number = 0
        self.timestamp = 0
        self.ssrc = random.randint(0, 2**32 - 1)
        self.audio_buffer = bytearray()
        self.last_packet_time = 0
        self.packet_interval = 0.0179  # 20ms entre paquetes
        self.rtp_packet_size = 160    # 20ms de audio a 8kHz
        self.target_buffer_size = 3200  # 200ms de buffer inicial (10 paquetes RTP)

    async def receive_response(self, openai_client):
        """Recibe la respuesta de OpenAI y la envía como paquetes RTP temporizados."""
        try:
            await self.wait_for_buffer(openai_client)
            last_log = time.time()
            packets_sent = 0

            while True:
                current_time = time.time()

                # Procesar el buffer si hay suficientes datos
                while len(self.audio_buffer) >= self.rtp_packet_size:
                    time_since_last = current_time - self.last_packet_time
                    
                    if time_since_last >= self.packet_interval:
                        # Extraer y enviar un paquete RTP
                        packet_data = self.audio_buffer[:self.rtp_packet_size]
                        self.audio_buffer = self.audio_buffer[self.rtp_packet_size:]
                        
                        # Crear y enviar el paquete RTP
                        await self.send_rtp_packet(packet_data)
                        
                        self.last_packet_time = current_time
                        packets_sent += 1
                        
                        # Log cada segundo
                        if current_time - last_log >= 1.0:
                            logging.debug(f"Paquetes RTP enviados en el último segundo: {packets_sent}")
                            packets_sent = 0
                            last_log = current_time
                    else:
                        # Esperar hasta el próximo intervalo
                        await asyncio.sleep(self.packet_interval - time_since_last)
                        break

                # Si el buffer está bajo, esperar más datos
                if len(self.audio_buffer) < self.rtp_packet_size:
                    try:
                        new_data = await asyncio.wait_for(
                            openai_client.incoming_audio_queue.get(),
                            timeout=0.5
                        )
                        self.audio_buffer.extend(new_data)
                    except asyncio.TimeoutError:
                        # Si no hay datos nuevos, insertar un frame de silencio
                        if len(self.audio_buffer) < self.rtp_packet_size:
                            await asyncio.sleep(self.packet_interval)
                    except Exception as e:
                        logging.error(f"Error recibiendo audio: {e}")
                        continue

                await asyncio.sleep(0.001)  # Pequeña pausa para evitar CPU alta

        except asyncio.CancelledError:
            logging.info("Tarea de recepción de respuesta de OpenAI cancelada.")
        except Exception as e:
            logging.error(f"Error recibiendo respuesta de OpenAI: {e}")
            logging.exception("Detalles del error:")

    async def wait_for_buffer(self, openai_client):
        """Espera hasta tener suficiente audio en el buffer antes de comenzar."""
        logging.info("Esperando buffer inicial...")
        while len(self.audio_buffer) < self.target_buffer_size:
            try:
                data = await openai_client.incoming_audio_queue.get()
                self.audio_buffer.extend(data)
            except Exception as e:
                logging.error(f"Error llenando buffer inicial: {e}")
                await asyncio.sleep(0.1)
        logging.info(f"Buffer inicial listo: {len(self.audio_buffer)} bytes")

    async def send_rtp_packet(self, payload):
        """Envía un paquete RTP con el payload proporcionado."""
        try:
            rtp_header = bytearray(12)
            rtp_header[0] = 0x80  # Versión 2
            rtp_header[1] = 0x00  # Tipo de payload (0 para PCMU/ulaw)
            rtp_header[2] = (self.sequence_number >> 8) & 0xFF
            rtp_header[3] = self.sequence_number & 0xFF
            rtp_header[4] = (self.timestamp >> 24) & 0xFF
            rtp_header[5] = (self.timestamp >> 16) & 0xFF
            rtp_header[6] = (self.timestamp >> 8) & 0xFF
            rtp_header[7] = self.timestamp & 0xFF
            rtp_header[8] = (self.ssrc >> 24) & 0xFF
            rtp_header[9] = (self.ssrc >> 16) & 0xFF
            rtp_header[10] = (self.ssrc >> 8) & 0xFF
            rtp_header[11] = self.ssrc & 0xFF

            rtp_packet = bytes(rtp_header) + payload
            
            await self.rtp_handler.send_rtp_packet(rtp_packet)
            
            # Incrementar secuencia y timestamp
            self.sequence_number = (self.sequence_number + 1) & 0xFFFF
            self.timestamp = (self.timestamp + len(payload)) & 0xFFFFFFFF
            
        except Exception as e:
            logging.error(f"Error enviando paquete RTP: {e}")





class AudioConfig:
    """Configuración global de parámetros de audio"""
    # Tasas de muestreo
    ASTERISK_SAMPLE_RATE = 8000     # G.711 siempre usa 8kHz
    OPENAI_SAMPLE_RATE = 24000      # OpenAI usa 24kHz
    FRAME_DURATION_MS = 20          # Duración estándar de frame en telefonía
    
    
    # Parámetros de detección de voz
    SILENCE_THRESHOLD = 1000        # ms de silencio para considerar fin de habla
    ENERGY_THRESHOLD = 0.005       # Umbral base de energía
    MIN_AUDIO_LENGTH = 500         # ms mínimos de audio para procesar
    MAX_AUDIO_LENGTH = 15000       # ms máximos de audio para procesar
    





class AsteriskApp:
    def __init__(self):
        """Inicializa la aplicación ARI con todos los componentes necesarios"""
        # Configuración de conexión ARI
        self.base_url = f'http://{ASTERISK_HOST}:{ASTERISK_PORT}/ari'
        self.username = ASTERISK_USERNAME
        self.password = ASTERISK_PASSWORD
        
       
        
        # Gestión de estado
        self.active_channels = set()
        self.rtp_handlers = {}
        self.active_tasks = {}
        self.bridges = {}
        
        # Configuración
        self.config = {
            'bridge_channels': True,
            'default_codec': 'ulaw'
        }

    async def get_channel_info(self, channel_id):
        """
        Obtiene información detallada sobre un canal de Asterisk, incluyendo datos RTP.
        
        Args:
            channel_id (str): El identificador único del canal
            
        Returns:
            dict: Información completa del canal con datos RTP, o None si hay error
        """
        try:
            # 1. Obtener información básica del canal
            url = f"{self.base_url}/channels/{channel_id}"
            channel_data = None
            
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url,
                    auth=aiohttp.BasicAuth(self.username, self.password)
                ) as response:
                    if response.status == 200:
                        channel_data = await response.json()
                        # logging.debug(
                        #     f"Información básica del canal {channel_id}: "
                        #     f"{json.dumps(channel_data, indent=2)}"
                        # )
                    else:
                        error_text = await response.text()
                        logging.error(
                            f"Error obteniendo información del canal {channel_id}: "
                            f"Status {response.status} - {error_text}"
                        )
                        return None

                # 2. Si tenemos datos básicos, obtener información RTP
                # Variables RTP a consultar
                rtp_variables = {
                    'CHANNEL(rtp,remote_address)': 'rtp_remote_address',
                    'CHANNEL(rtp,remote_port)': 'rtp_remote_port',
                    'CHANNEL(peerip)': 'peer_ip',
                    'CHANNEL(rtpaddress)': 'rtp_address',
                    'CHANNEL(rtpdest)': 'rtp_dest',
                    'CHANNEL(rtpsource)': 'rtp_source',
                    'CHANNEL(rtp,destport)': 'rtp_dest_port',
                    'CHANNEL(rtp,port)': 'rtp_local_port',
                    'CHANNEL(rtp,srcport)': 'rtp_src_port'
                }
                # if channel_data and 'channelInfo' in channel_data:
                #     logging.info(f"Información RTP completa para canal {channel_id}:")
                #     logging.info(f"Remote Address: {channel_data['channelInfo'].get('rtp_remote_address')}")
                #     logging.info(f"Remote Port: {channel_data['channelInfo'].get('rtp_remote_port')}")
                #     logging.info(f"Peer IP: {channel_data['channelInfo'].get('peer_ip')}")
                #     logging.info(f"RTP Destination: {channel_data['channelInfo'].get('rtp_dest')}")
                #     logging.info(f"RTP Source: {channel_data['channelInfo'].get('rtp_source')}")
                #     logging.info(f"RTP Dest Port: {channel_data['channelInfo'].get('rtp_dest_port')}")
                #     logging.info(f"RTP Local Port: {channel_data['channelInfo'].get('rtp_local_port')}")
                #     logging.info(f"RTP Source Port: {channel_data['channelInfo'].get('rtp_src_port')}")
                if channel_data:
                    # Obtener cada variable RTP
                    for variable, key in rtp_variables.items():
                        try:
                            var_url = f"{self.base_url}/channels/{channel_id}/variable"
                            async with session.get(
                                var_url,
                                params={'variable': variable},
                                auth=aiohttp.BasicAuth(self.username, self.password)
                            ) as var_response:
                                if var_response.status == 200:
                                    var_data = await var_response.json()
                                    if 'value' in var_data and var_data['value']:
                                        if 'channelInfo' not in channel_data:
                                            channel_data['channelInfo'] = {}
                                        channel_data['channelInfo'][key] = var_data['value']
                                        # logging.debug(
                                        #     f"Variable RTP obtenida - {key}: {var_data['value']}"
                                        # )
                        except Exception as var_error:
                            logging.warning(
                                f"Error obteniendo variable RTP {variable}: {var_error}"
                            )
                            continue

                    # 3. Detectar tipo de canal y obtener información específica
                    if 'name' in channel_data:
                        channel_name = channel_data['name']
                        if channel_name.startswith('UnicastRTP/'):
                            # Es un canal RTP, extraer información adicional
                            try:
                                rtp_info = channel_name.split('/')[1].split('-')[0]
                                address, port = rtp_info.split(':')
                                channel_data['channelInfo']['local_address'] = address
                                channel_data['channelInfo']['local_port'] = int(port)
                            except Exception as e:
                                logging.warning(f"Error parseando información RTP: {e}")

                    # logging.debug(
                    #     f"Información completa del canal {channel_id}: "
                    #     f"{json.dumps(channel_data, indent=2)}"
                    # )
                    return channel_data

        except aiohttp.ClientError as e:
            logging.error(f"Error de conexión al obtener información del canal: {e}")
            return None
        except Exception as e:
            logging.error(f"Error inesperado en get_channel_info: {e}")
            logging.exception("Detalles del error:")
            return None
        
    async def get_channel_codec(self, channel_id):
        """
        Detecta el codec de audio utilizado por un canal.
        
        Esta función obtiene el formato de audio configurado en el canal, verificando
        primero las variables específicas de codec y luego las variables de formato
        de audio generales.
        
        Args:
            channel_id (str): El identificador único del canal
            
        Returns:
            str: El codec detectado ('ulaw' o 'alaw' por defecto), o 'ulaw' si no se puede determinar
        """
        try:
            # Primero intentamos obtener el codec de las variables del canal
            variables_to_check = [
                'CHANNEL(audioreadformat)',
                'CHANNEL(audiowriteformat)',
                'CHANNEL(format)'
            ]
            
            for variable in variables_to_check:
                # Construimos la URL para obtener la variable
                url = f"{self.base_url}/channels/{channel_id}/variable"
                params = {'variable': variable}
                
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        url,
                        params=params,
                        auth=aiohttp.BasicAuth(self.username, self.password)
                    ) as response:
                        if response.status == 200:
                            data = await response.json()
                            codec = data.get('value', '').lower()
                            
                            # Verificamos si es un codec válido
                            if codec in ['ulaw', 'alaw']:
                                logging.info(
                                    f"Codec detectado para canal {channel_id}: {codec} "
                                    f"(de variable {variable})"
                                )
                                return codec
                                
            # Si no pudimos detectar el codec, usamos ulaw por defecto
            logging.warning(
                f"No se pudo detectar el codec para canal {channel_id}, "
                "usando ulaw por defecto"
            )
            return 'ulaw'
            
        except aiohttp.ClientError as e:
            # Error de conexión HTTP
            logging.error(f"Error de conexión al detectar codec: {e}")
            return 'ulaw'
        except Exception as e:
            # Otros errores inesperados
            logging.error(f"Error inesperado en get_channel_codec: {e}")
            logging.exception("Detalles del error:")
            return 'ulaw'

    async def setup_bridge(self, channel_id, external_channel_id):
        """
        Configura un bridge para conectar el canal original con el canal External Media
        """
        try:
            bridge_id = f"bridge_{channel_id}"
            logging.info(f"Iniciando creación de bridge {bridge_id}")
            
            # 1. Crear el bridge
            async with aiohttp.ClientSession() as session:
                create_url = f"{self.base_url}/bridges"
                create_data = {
                    "type": "mixing",
                    "bridgeId": bridge_id,
                    "name": f"OpenAI Bridge {channel_id}"
                }
                
                logging.debug(f"Creando bridge con datos: {json.dumps(create_data)}")
                async with session.post(
                    create_url,
                    json=create_data,
                    auth=aiohttp.BasicAuth(self.username, self.password)
                ) as response:
                    if response.status not in [200, 204]:  # Aceptar 204 como éxito
                        response_text = await response.text()
                        raise Exception(f"Error creando bridge: {response.status} - {response_text}")
                        
                    logging.info(f"Bridge {bridge_id} creado exitosamente")
                    
                # 2. Añadir el canal original
                logging.info(f"Añadiendo canal original {channel_id} al bridge")
                add_url = f"{self.base_url}/bridges/{bridge_id}/addChannel"
                async with session.post(
                    add_url,
                    json={"channel": channel_id},
                    auth=aiohttp.BasicAuth(self.username, self.password)
                ) as response:
                    if response.status not in [200, 204]:  # Aceptar 204 como éxito
                        response_text = await response.text()
                        raise Exception(
                            f"Error añadiendo canal {channel_id} al bridge: "
                            f"{response.status} - {response_text}"
                        )
                    logging.info(f"Canal {channel_id} añadido al bridge exitosamente")
                    
                # 3. Añadir el canal External Media
                logging.info(f"Añadiendo canal External Media {external_channel_id} al bridge")
                async with session.post(
                    add_url,
                    json={"channel": external_channel_id},
                    auth=aiohttp.BasicAuth(self.username, self.password)
                ) as response:
                    if response.status not in [200, 204]:  # Aceptar 204 como éxito
                        response_text = await response.text()
                        raise Exception(
                            f"Error añadiendo canal External Media al bridge: "
                            f"{response.status} - {response_text}"
                        )
                    logging.info(f"Canal External Media añadido al bridge exitosamente")
                    
            # 4. Guardar referencia al bridge y retornar éxito
            self.bridges[channel_id] = bridge_id
            logging.info(f"Bridge {bridge_id} configurado completamente")
            return True
            
        except Exception as e:
            logging.error(f"Error configurando bridge: {e}")
            logging.exception("Detalles del error:")
            
            # Intentar limpiar el bridge en caso de error
            try:
                if bridge_id:
                    await self.cleanup_bridge(bridge_id)
            except Exception as cleanup_error:
                logging.error(f"Error limpiando bridge después de fallo: {cleanup_error}")
                
            return False

    async def cleanup_bridge(self, bridge_id):
        """
        Limpia los recursos del bridge al finalizar
        """
        try:
            logging.info(f"Iniciando limpieza del bridge {bridge_id}")
            
            async with aiohttp.ClientSession() as session:
                url = f"{self.base_url}/bridges/{bridge_id}"
                async with session.delete(
                    url,
                    auth=aiohttp.BasicAuth(self.username, self.password)
                ) as response:
                    if response.status == 200:
                        logging.info(f"Bridge {bridge_id} eliminado correctamente")
                    else:
                        response_text = await response.text()
                        logging.warning(
                            f"Error eliminando bridge {bridge_id}: "
                            f"{response.status} - {response_text}"
                        )
        except Exception as e:
            logging.error(f"Error limpiando bridge {bridge_id}: {e}")
            logging.exception("Detalles del error de limpieza:")

    async def handle_events(self, websocket):
        """Maneja eventos entrantes de Asterisk"""
        while True:
            try:
                message = await websocket.recv()
                #logging.debug(f"Evento recibido: {message}")
                
                event = json.loads(message)
                event_type = event.get('type', 'unknown')
                # logging.info(f"Procesando evento tipo: {event_type}")
                
                if event_type == 'StasisStart':
                    channel_id = event['channel']['id']
                    # 1) Ignorar si es canal External Media
                    if channel_id.startswith("external_"):
                        logging.debug(f"Saltando StasisStart en canal External Media: {channel_id}")
                        continue
                    logging.info(f"Nueva llamada recibida - Canal: {channel_id}")
                    self.active_channels.add(channel_id)
                    
                    # Obtener información detallada del canal
                    channel_info = await self.get_channel_info(channel_id)
                    # logging.debug(f"Información del canal: {json.dumps(channel_info, indent=2)}")
                    
                    # Detectar codec
                    codec = await self.get_channel_codec(channel_id)
                    logging.info(f"Codec detectado para canal {channel_id}: {codec}")
                    
                    # Iniciar External Media
                    asyncio.create_task(self.setup_external_media(event, codec))
                    
                elif event_type == 'StasisEnd':
                    channel_id = event['channel']['id']
                    logging.info(f"Llamada terminada - Canal: {channel_id}")
                    await self.handle_stasis_end(event)
                    
            except websockets.ConnectionClosed:
                logging.warning("Conexión WebSocket cerrada, reconectando...")
                break
            except json.JSONDecodeError as e:
                logging.error(f"Error decodificando JSON: {e}")
            except Exception as e:
                logging.error(f"Error procesando evento: {e}")
                logging.exception("Detalles del error:")

    async def setup_external_media(self, event, codec='ulaw'):
        channel_id = event['channel']['id']
        try:
            # Evitar procesar canales External Media secundarios
            if channel_id.startswith('external_'):
                logging.debug(f"Ignorando canal External Media secundario: {channel_id}")
                return
            
            logging.info(f"Iniciando configuración External Media - Canal: {channel_id}")
            
            # 1) Obtener información RTP del canal original primero
            original_channel_info = await self.get_channel_info(channel_id)
            rtp_remote_address = None
            rtp_remote_port = None
            
            if original_channel_info and 'channelInfo' in original_channel_info:
                rtp_dest = original_channel_info['channelInfo'].get('rtp_dest')
                rtp_source = original_channel_info['channelInfo'].get('rtp_source')
                peer_ip = original_channel_info['channelInfo'].get('peer_ip')
                
                if rtp_dest:
                    try:
                        addr, port = rtp_dest.split(':')
                        rtp_remote_address = addr
                        rtp_remote_port = int(port)
                        # logging.info(
                        #     f"Información RTP del canal original - "
                        #     f"Destino: {rtp_remote_address}:{rtp_remote_port}"
                        # )
                    except Exception as e:
                        logging.error(f"Error parseando RTP dest '{rtp_dest}': {e}")
            
            # 2) Crear RTP handler y obtener puerto local
            local_address = LOCAL_IP_ADDRESS
            rtp_handler = RTPAudioHandler()
            
            #Crear OpenAIHandler con el rtp_handler
            if rtp_handler != None:
                logging.info("RTP Handler creado exitosamente para canal {channel_id}")
                openai_handler = OpenAIHandler(rtp_handler)
            
            
            try:
                available_port = await rtp_handler.find_available_port(local_address)
                # logging.info(f"Puerto RTP local encontrado: {available_port}")
            except Exception as e:
                logging.error(f"No se pudo encontrar puerto RTP: {e}")
                return
            
            # 3) Crear el canal External Media con la información RTP
            external_channel_id = f"external_{channel_id}"
            media_data = {
                "app": "openai-app",
                "channelId": external_channel_id,
                "external_host": f"{local_address}:{available_port}",
                "format": codec,
                "encapsulation": "rtp",
                "transport": "udp",
                "connection_type": "client",
                "variables": {
                    "CHANNEL_PURPOSE": "openai_chat",
                    "ORIGINAL_CHANNEL_ID": channel_id,
                    "RTP_REMOTE_ADDRESS": rtp_remote_address,
                    "RTP_REMOTE_PORT": str(rtp_remote_port) if rtp_remote_port else "",
                    "PEER_IP": peer_ip if peer_ip else ""
                }
            }
            #"direction": "both",

            # 4) Crear canal en Asterisk
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.base_url}/channels/externalMedia",
                    json=media_data,
                    auth=aiohttp.BasicAuth(self.username, self.password)
                ) as response:
                    if response.status == 200:
                        channel_info = await response.json()
                        logging.info(f"Canal External Media creado: {external_channel_id}")
                        
                        # 5) Iniciar RTP handler con la información completa
                        success = await rtp_handler.start(
                            local_address=local_address,
                            local_port=available_port,
                            remote_address=rtp_remote_address,
                            remote_port=rtp_remote_port,
                            codec=codec
                        )
                        
                        if not success:
                            raise Exception("No se pudo iniciar RTP Handler")
                        
                        logging.info(
                            f"RTP Handler iniciado - Local: {local_address}:{available_port}, "
                            f"Remoto: {rtp_remote_address}:{rtp_remote_port}"
                        )

                        # 6) Configurar bridge
                        bridge_success = await self.setup_bridge(channel_id, external_channel_id)
                        if not bridge_success:
                            raise Exception("Error configurando el bridge")

                        # 7) Iniciar procesamiento de audio
                        rtp_task = asyncio.create_task(
                            rtp_handler.process_audio_stream(
                                local_address=local_address,
                                codec=codec,
                                openai_handler=openai_handler
                            )
                        )
                        self.active_tasks[external_channel_id] = rtp_task
                        self.rtp_handlers[external_channel_id] = rtp_handler

                        logging.info("Configuración External Media completada exitosamente")
                    else:
                        response_text = await response.text()
                        raise Exception(
                            f"Error creando canal External Media: {response.status} - {response_text}"
                        )

        except Exception as e:
            logging.error(f"Error en setup de External Media: {e}")
            logging.exception("Detalles del error:")
            await self.cleanup_channel(channel_id)

    async def handle_stasis_end(self, event):
        """Maneja el fin de Stasis para un canal"""
        channel_id = event['channel']['id']
        try:
            # Limpiar recursos del canal original
            await self.cleanup_channel(channel_id)
            
            # Limpiar recursos del canal External Media si existe
            external_channel_id = f"external_{channel_id}"
            if external_channel_id in self.active_channels:
                await self.cleanup_channel(external_channel_id)
            
            # Limpiar bridge si existe
            if channel_id in self.bridges:
                await self.cleanup_bridge(self.bridges[channel_id])
            
            logging.info(f"Recursos liberados para canal {channel_id}")
            
        except Exception as e:
            logging.error(f"Error en handle_stasis_end: {e}")
            logging.exception("Detalles del error:")

    async def cleanup_channel(self, channel_id):
        """Limpia recursos asociados a un canal"""
        try:
            # Remover de canales activos
            if channel_id in self.active_channels:
                self.active_channels.remove(channel_id)
            
            # Limpiar RTP handler
            if channel_id in self.rtp_handlers:
                handler = self.rtp_handlers[channel_id]
                await handler.cleanup()
                del self.rtp_handlers[channel_id]
            
            # Cancelar tareas activas
            if channel_id in self.active_tasks:
                task = self.active_tasks[channel_id]
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                del self.active_tasks[channel_id]
                
            logging.info(f"Recursos liberados para canal {channel_id}")
            
        except Exception as e:
            logging.error(f"Error en cleanup_channel: {e}")
            logging.exception("Detalles del error:")

    async def start(self):
        """
        Inicia la aplicación ARI y mantiene la conexión WebSocket con Asterisk.
        
        Este método:
        1. Establece la conexión inicial con Asterisk
        2. Maneja reconexiones automáticas en caso de desconexión
        3. Procesa eventos de manera continua
        4. Maneja errores y logging
        """
        try:
            # Construimos la URL del WebSocket con las credenciales usando variables de entorno
            ws_url = f"ws://{ASTERISK_HOST}:{ASTERISK_PORT}/ari/events?api_key={self.username}:{self.password}&app=openai-app"
            logging.info(f"Iniciando conexión ARI a {ASTERISK_HOST}:{ASTERISK_PORT}")
            
            # Bucle principal de reconexión
            while True:
                try:
                    # Establecer conexión WebSocket
                    async with websockets.connect(
                        ws_url,
                        ping_interval=30,  # Mantener la conexión activa
                        ping_timeout=10    # Timeout para detectar desconexiones
                    ) as websocket:
                        logging.info("Conexión ARI establecida")
                        
                        # Procesar eventos
                        await self.handle_events(websocket)
                        
                except websockets.ConnectionClosed:
                    # La conexión se cerró, intentamos reconectar
                    logging.warning("Conexión cerrada, reintentando en 5 segundos...")
                    await asyncio.sleep(5)
                    
                except Exception as e:
                    # Otros errores inesperados
                    logging.error(f"Error en la conexión: {e}")
                    logging.info(f"Conectando a Asterisk en {self.base_url}")
                    logging.info(f"Usuario: {ASTERISK_USERNAME}")
                    logging.info(f"Contraseña: {ASTERISK_PASSWORD}")
                    logging.exception("Detalles del error:")
                    await asyncio.sleep(5)
                    
        except Exception as e:
            # Error fatal que requiere atención manual
            logging.error(f"Error fatal en start: {e}")
            logging.exception("Detalles del error fatal:")
            raise




async def main():
    """Función principal"""
    logging.info("Iniciando aplicación Asterisk ARI")
    await asyncio.sleep(1)
    try:
        app = AsteriskApp()
        logging.info("Aplicación iniciada") 
        await app.start()
        logging.info("Aplicación finalizada")
    except Exception as e:
        logging.error(f"Error en main: {e}")

if __name__ == "__main__":
    logging.info("Iniciando script...")
    asyncio.run(main())