#!/usr/bin/env python3
import os
import json
import base64
import logging
import websocket
import sys
import time
import numpy as np
import wave
from datetime import datetime
from audioop import ulaw2lin


# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("/tmp/shared_openai/openai_ws.log"),
        logging.StreamHandler()
    ]
)




class AudioConfig:
    """Configuración de audio para OpenAI"""
    CHUNK_SIZE = 8192           # Tamaño del chunk para envío
    MAX_AUDIO_SIZE = 10 * 1024 * 1024  # 10MB límite de OpenAI
    FRAME_DURATION_MS = 20      # Duración de frame en ms

class OpenAIClient:
    def __init__(self):
        
        self.api_key = os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            logging.error("API Key de OpenAI no configurada")
        else:
            logging.info("API Key de OpenAI configurada")


        self.url = "wss://api.openai.com/v1/realtime?model=gpt-4o-realtime-preview-2024-12-17"
        self.headers = [
            "Authorization: Bearer " + self.api_key,
            "OpenAI-Beta: realtime=v1"
        ]
        self.audio_chunks = []
        self.session_configured = False
        self.input_audio = None
        self.metrics = {
            'start_time': None,
            'chunks_sent': 0,
            'chunks_received': 0,
            'total_bytes_sent': 0,
            'total_bytes_received': 0,
            'processing_time': 0
        }

    def start(self, input_audio):
        """Inicia el procesamiento con OpenAI"""
        try:
            self.metrics['start_time'] = time.time()

            self.input_audio = input_audio
            
            logging.info(f"Audio recibido: {len(input_audio)} bytes")
            
            # Validar tamaño del audio
            if len(input_audio) > AudioConfig.MAX_AUDIO_SIZE:
                logging.error(f"Audio demasiado grande: {len(input_audio)} bytes")
                return None
            
            # Configurar y ejecutar WebSocket
            ws = websocket.WebSocketApp(
                self.url,
                header=self.headers,
                on_open=self.on_open,
                on_message=self.on_message,
                on_error=self.on_error,
                on_close=self.on_close
            )
            
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
                    "voice": "echo",
                    "instructions": "Contesta mis preguntas",
                    "input_audio_format": "pcm16",
                    "output_audio_format": "pcm16",         
                    "turn_detection": None
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
                logging.debug(message)
                self.handle_session_updated(ws)
            elif msg_type == 'response.audio.delta':
                self.handle_audio_delta(data)
            elif msg_type == 'response.done':
                logging.info("Respuesta final recibida response.done")
                logging.debug(message)
                self.handle_response_done(ws)
            elif msg_type == 'response.audio_transcript.done':
                logging.info(f"Transcripción: {data.get('transcript', '')}")    
            elif msg_type == 'response.input_audio_buffer.speech_started':
                logging.info("Inicio de habla detectado speech_started")
                logging.debug(data)
            elif msg_type == 'error':
                self.handle_error(data)
            
            logging.debug(f"Mensaje procesado: {msg_type}")
            
        except Exception as e:
            logging.error(f"Error procesando mensaje: {e}")

    def handle_session_updated(self, ws):
        """Maneja confirmación de configuración"""
        try:
            self.session_configured = True
            logging.info("<<<<<<<<< Iniciando envío de audio to_openai .empieza el for que contiene chunks")
            
            # Enviar audio en chunks
            for i in range(0, len(self.input_audio), AudioConfig.CHUNK_SIZE):
                chunk = self.input_audio[i:i + AudioConfig.CHUNK_SIZE]
                self.send_audio_chunk_to_openai(ws, chunk)
            
            logging.info(f"Audios total enviado to_openai : {self.metrics['total_bytes_sent']} bytes >>>>>>>>>>>>")

            input_audio_buffer_commit={
                "type": "input_audio_buffer.commit"
            }
            ws.send(json.dumps(input_audio_buffer_commit))
            create_response = {
                "type": "response.create"
            }
            ws.send(json.dumps(create_response))

        except Exception as e:
            logging.error(f"Error después de configuración: {e}")

    def send_audio_chunk_to_openai(self, ws, chunk):
        """Envía chunk de audio a OpenAI"""
        try:
            audio_event = {
                "event_id": f"audio_{int(time.time())}",
                "type": "input_audio_buffer.append",
                "audio": base64.b64encode(chunk).decode('utf-8')
            }
            
            ws.send(json.dumps(audio_event))
            
            self.metrics['chunks_sent'] += 1
            self.metrics['total_bytes_sent'] += len(chunk)
            
            logging.debug(
                f"Chunk enviado to_openai: {len(chunk)} bytes "
                f"(Total: {self.metrics['total_bytes_sent']})"
            )
            
        except Exception as e:
            logging.error(f"Error enviando chunk: {e}")

    # def ulaw_to_pcm(self, ulaw_data):
    #     """Convierte datos de audio uLaw a PCM"""
    #     # Decodifica desde u-law (bytes) a lineal de 16 bits (bytes)
    #     linear_bytes = ulaw2lin(ulaw_data, 2)
    #     # Convierte esos bytes en un array NumPy de int16
    #     return np.frombuffer(linear_bytes, dtype=np.int16)
    
    
    def handle_audio_delta(self, data):
        """Procesa chunks de audio recibidos"""
        try:
            audio_buffer = base64.b64decode(data['delta'])
            
            # Agregar el chunk de audio a la lista
            self.audio_chunks.append(audio_buffer)

            
            # self.metrics['chunks_received'] += 1
            # self.metrics['total_bytes_received'] += len(audio_data)
            
            # logging.debug(
            #     f"Audio recibido: {len(audio_data)} bytes "
            #     f"(Total: {self.metrics['total_bytes_received']})"
            # )
            
        except Exception as e:
            logging.error(f"Error procesando audio delta: {e}")

    def handle_response_done(self, ws):
        """Maneja la finalización de la respuesta de OpenAI"""
        try:
            # Concatenar todos los chunks de audio en uno solo
            combined_audio = np.concatenate(self.audio_chunks)
            # Configurar los parámetros del archivo WAV
            num_channels = 1    # Número de canales (mono)
            sampwidth = 2        # Ancho de muestra en bytes (16 bits)
            num_frames = combined_audio.shape[0]  # Número de frames
            with wave.open("/tmp/shared_openai/audio.wav", 'w') as wf:
                wf.setnchannels(num_channels)
                wf.setsampwidth(sampwidth)
                wf.setframerate(8000)
                wf.writeframes(combined_audio.tobytes())
            logging.info(f"Audio guardado en: /tmp/shared_openai/audio.wav")

            # # 3. Enviamos el audio completo como respuesta
            # sys.stdout.buffer.write(final_audio)
            
            # # 4. Cerramos la conexión WebSocket
            # ws.close()

            


        except Exception as e:
            logging.error(f"Error procesando respuesta final: {e}")

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

def main():
    """Función principal"""
    logging.info("Iniciando openai_ws.py  recordatorio:python3 openai_ws.py ,  export OPENAI_API_KEY='' , luego ejecutar el comando source ~/.bashrc ")
    
    
    # api_key = os.getenv("OPENAI_API_KEY")
    # if not api_key:
    #     logging.error("API Key de OpenAI no configurada")
    # else:
    #     logging.info("API Key de OpenAI configurada")
    
    
    try:
        input_audio = sys.stdin.buffer.read()
        logging.info(f"Audio leído: {len(input_audio)} bytes")
        if input_audio == b'':
            logging.error("No se recibió audio")
            sys.exit(1)
        else:
            logging.info("Audio recibido con éxito")    
            client = OpenAIClient()
            logging.info("Iniciando WebSocket dentro de openai_ws.py")  
            result = client.start(input_audio)
            if result is None:
                logging.error("Error al procesar audio")
                sys.exit(1)
        
        sys.exit(0)

    except Exception as e:
        logging.error(f"Error en main: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()