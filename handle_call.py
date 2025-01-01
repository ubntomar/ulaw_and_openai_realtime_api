#!/usr/bin/env python3
import subprocess
import sys
sys.path.append('/usr/local/bin')
from openai_ws import OpenAIClient
import socket
import os
import json
import logging
import asyncio
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


#Configuración de logging principal para handle_call.py ..
logging.basicConfig(
    filename="/tmp/shared_openai/ari_app.log",
    level=logging.DEBUG,
    format='%(asctime)s.%(msecs)03d - %(levelname)s - %(funcName)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

# Logger específico para procesamiento de audio en handle_call.py
audio_logger = logging.getLogger('handle_call_audio_processing')
audio_handler = logging.FileHandler('/tmp/shared_openai/audio_processing.log')
audio_handler.setFormatter(logging.Formatter(
    '%(asctime)s.%(msecs)03d - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
))
audio_logger.addHandler(audio_handler)
audio_logger.setLevel(logging.DEBUG)





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


    async def process_audio_stream(self, local_address  , codec='ulaw'):
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
        ordered_frames = {}
        
        logging.info(f"******************************************************************Iniciando bucle de procesamiento de audio en socket {self.socket.getsockname()}**********")
        
        while self.running:
            try:
                current_time = time.time()
                if current_time - last_log_time >= 5:
                    logging.info(
                        f"Estado del procesamiento - Frames: {frames_processed}, "
                        f"Buffer: {len(ordered_frames)}"
                    )
                    last_log_time = current_time
                
                try:
                    data = await asyncio.wait_for(
                        loop.sock_recv(self.socket, 1024),
                        timeout=0.5
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

                # Detectar y limpiar silencio en el frame (threshold 0xFC = 252)
                silence_count = sum(1 for byte in payload if byte >= 0xFC)
                if silence_count / len(payload) > 0.9:  # Si 90% del frame es silencio
                    payload = bytes([0xFF] * len(payload))  # Reemplazar con silencio puro
                else:
                    # Limpiar ruido cercano al silencio
                    payload = bytes(0xFF if byte >= 0xFC else byte for byte in payload)

                # Almacenar frame ordenado
                ordered_frames[sequence_number] = payload
                
                # Procesar cuando tengamos suficientes frames
                if len(ordered_frames) >= 300:
                    # Ordenar frames por número de secuencia
                    ordered_numbers = sorted(ordered_frames.keys())
                    self.audio_buffer = [ordered_frames[seq] for seq in ordered_numbers[:100]]
                    logging.info(f"************************300 frames recolectados y ordenados correctamente********************************************************")
                    await self.handle_speech_segment()
                    self.running = False

            except Exception as e:
                logging.error(f"Error en process_audio: {e}")
                continue





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




    async def process_rtp_packet(self, packet):
        """Procesa un paquete RTP y extrae el payload de audio"""
        try:
            payload = packet[12:]
            return payload
            
        except IndexError as e:
            logging.error(f"Error accediendo al payload RTP (paquete muy corto?): {e}")
            return None
        except Exception as e:
            logging.error(f"Error procesando paquete RTP: {e}")
            return None

    async def detect_speech(self, audio_data):
        """Detecta presencia de voz en el audio"""
        try:
            # Calcular energía del audio
            energy = np.sqrt(np.mean(audio_data.astype(np.float32) ** 2)) / 32768.0
            # Detección VAD
            is_speech = self.vad.is_speech(
                audio_data.tobytes(),
                AudioConfig.ASTERISK_SAMPLE_RATE
            )
            # logging.debug(f"VAD: {is_speech}, Energía: {energy:.4f}")
            
            # Log detallado cada 20 frames (aproximadamente cada 400ms)
            if hasattr(self, 'frame_counter'):
                self.frame_counter += 1
            else:
                self.frame_counter = 0
                
            # if self.frame_counter % 20 == 0:
            #     logging.debug(
            #         f"Análisis de voz - Energía: {energy:.4f}, "
            #         f"Umbral: {AudioConfig.ENERGY_THRESHOLD:.4f}, "
            #         f"VAD: {is_speech}"
            #     )
                
            return is_speech and energy > AudioConfig.ENERGY_THRESHOLD
            
        except Exception as e:
            logging.error(f"Error en detección de voz: {e}")
            return False

    async def handle_speech_segment(self):
        """
        Procesa un segmento completo de voz con manejo robusto de errores y métricas.
        """
        start_time = time.time()
        segment_id = f"segment_{int(start_time * 1000)}"
        
        try:
            # 1. Validación inicial del buffer
            if not self.audio_buffer:
                logging.debug(f"[{segment_id}] Buffer de audio vacío - ignorando segmento")
                return

            # # 2. Unión y análisis inicial del audio
            # try:
            complete_audio = self.audio_buffer
            

            # 4. Procesamiento con OpenAI
            try:

                logging.info(f"[{segment_id}] Enviando <<<<<<<<<<<***********************>>>>>>>>>>>> {len(complete_audio)} muestras a OpenAI")
                response = await self.process_with_openai(complete_audio)
                
                if response is None:
                    logging.error(f"[{segment_id}] No se recibió respuesta de OpenAI")
                    return
                    
                if len(response) == 0:
                    logging.warning(f"[{segment_id}] Respuesta de OpenAI vacía")
                    return

                logging.info(
                    f"[{segment_id}] Respuesta recibida: "
                    f"{len(response)} bytes, "
                    f"duración estimada: {len(response)/32000:.1f}s"
                )


            except Exception as e:
                logging.error(f"[{segment_id}] Error en comunicación con OpenAI: {e}")
                return

        except Exception as e:
            logging.error(f"[{segment_id}] Error general en procesamiento: {e}")
            logging.exception("Detalles completos del error:")
        
        finally:
            # Asegurar limpieza del buffer incluso en caso de error
            self.audio_buffer = []
            self.is_speaking = False






    def create_rtp_packet(self, payload, payload_type=0, timestamp=None):
        """
        Crea un paquete RTP con el payload y tipo especificados.
        
        Args:
            payload: Audio codificado (numpy array o bytes)
            payload_type: Tipo de payload RTP (0 para ulaw, 8 para alaw)
            
        Returns:
            bytes: Paquete RTP completo
        """
        try:
            # Primer byte: V=2, P=0, X=0, CC=0 -> 0x80
            # Segundo byte: M=0, PT=payload_type
            header = bytearray([
                0x80,
                payload_type & 0x7F,  # Aseguramos que el bit M está en 0
                (self.sequence_number >> 8) & 0xFF,
                self.sequence_number & 0xFF,
                (self.timestamp >> 24) & 0xFF,
                (self.timestamp >> 16) & 0xFF,
                (self.timestamp >> 8) & 0xFF,
                self.timestamp & 0xFF,
                (self.ssrc >> 24) & 0xFF,
                (self.ssrc >> 16) & 0xFF,
                (self.ssrc >> 8) & 0xFF,
                self.ssrc & 0xFF
            ])
            
            # Convertir payload a bytes si es numpy array
            if isinstance(payload, np.ndarray):
                payload_bytes = payload.tobytes()
            else:
                payload_bytes = bytes(payload)
                
            # Crear paquete final
            packet = bytes(header) + payload_bytes
            
            # logging.debug(
            #     f"Paquete RTP creado - Header: {len(header)} bytes, "
            #     f"Payload: {len(payload_bytes)} bytes, "
            #     f"Type: {payload_type}"
            # )
            
            return packet
            
        except Exception as e:
            logging.error(f"Error creando paquete RTP: {e}")
            logging.exception("Detalles del error:")
            return None


    

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





    # REEMPLAZAR POR ESTE NUEVO MÉTODO:
    async def process_with_openai(self, audio_data):
        """
        Procesa el audio aplicando reducción de ruido y lo envía a OpenAI.
        Args:
            audio_data: Lista de payloads de audio en formato uLaw
        Returns:
            bytes: Respuesta de OpenAI
        """
        try:
            # Constantes para reducción de ruido
            NOISE_FLOOR = 50
            VOICE_MULTIPLIER = 1.2
            
            # Procesar cada frame individualmente
            processed_frames = []
            for i, frame in enumerate(audio_data):
                frame_array = np.frombuffer(frame, dtype=np.int8)
                frame_rms = np.sqrt(np.mean(frame_array.astype(float)**2))
                
                # Logging cada 10 frames para debug
                if i % 10 == 0:
                    logging.info(f"Frame {i} - RMS: {frame_rms:.2f}, Umbral: {NOISE_FLOOR * VOICE_MULTIPLIER}")
                
                # Umbral para reducción de ruido
                if frame_rms < NOISE_FLOOR:
                    processed_frames.append(bytes([0xFE] * len(frame)))
                else:
                    processed_frames.append(frame)

            # Combinar frames procesados
            combined_audio = b''.join(processed_frames)
            
            # # Log de información del audio procesado
            # total_samples = len(combined_audio)
            # duration_ms = (total_samples * 1000) / AudioConfig.ASTERISK_SAMPLE_RATE
            # logging.info(f"Audio procesado - Duración: {duration_ms:.2f} ms, Tamaño: {total_samples} bytes")

            # # Guardar audio procesado
            # wav_path = "/tmp/shared_openai/audio_8k_ulaw.wav"
            # with wave.open(wav_path, 'wb') as wav_file:
            #     wav_file.setnchannels(1)
            #     wav_file.setsampwidth(1)
            #     wav_file.setframerate(AudioConfig.ASTERISK_SAMPLE_RATE)
            #     wav_file.writeframes(combined_audio)

            # Enviar audio procesado a OpenAI
            logging.info("|||||||||||||||||||||||||||Enviando audio procesado a OpenAI...")
            process = await asyncio.create_subprocess_exec(
                '/usr/local/bin/openai_ws.py',
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(combined_audio),
                    timeout=20.0
                )
                
                if stderr:
                    logging.error(f"Error de OpenAI: {stderr.decode()}")
                
                if stdout:
                    logging.info("Respuesta recibida de OpenAI")
                    return stdout
                
            except asyncio.TimeoutError:
                logging.error("Timeout al enviar audio a OpenAI")
                if process.returncode is None:
                    process.kill()
                return None
                
            return None
            
        except Exception as e:
            logging.error(f"Error procesando audio uLaw: {e}")
            logging.exception("Detalles del error:")
            return None






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
        self.base_url = 'http://localhost:8088/ari'
        self.username = 'asterisk'
        self.password = 'asterisk'
        
        
        self.openai_client = OpenAIClient()
        
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
            local_address = "45.61.59.204"
            rtp_handler = RTPAudioHandler()
            
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
                                codec=codec
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
            # Construimos la URL del WebSocket con las credenciales
            ws_url = f"ws://localhost:8088/ari/events?api_key={self.username}:{self.password}&app=openai-app"
            logging.info("Iniciando conexión ARI")
            
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
    try:
        app = AsteriskApp()
        logging.info("Aplicación iniciada") 
        await app.start()
        logging.info("Aplicación finalizada")
    except Exception as e:
        logging.error(f"Error en main: {e}")

if __name__ == "__main__":
    asyncio.run(main())