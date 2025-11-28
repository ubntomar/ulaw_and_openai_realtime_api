#!/usr/bin/env python3

import logging
import asyncio
import aiohttp
import websockets
import json
import os
import time
from datetime import datetime, timedelta

# Configuration
DESTINATION_NUMBER = "573001234567"  # Phone number with country prefix 57xxxxxxxxx (example)
ARI_URL = "http://localhost:8088/ari"
WEBSOCKET_URL = "ws://localhost:8088/ari/events"
USERNAME = os.getenv('ASTERISK_USERNAME')
PASSWORD = os.getenv('ASTERISK_PASSWORD')
AUDIO_FILE = "morosos"  # Audio file name to play

# Retry configuration
MAX_RETRIES = 3  # Maximum number of attempts for a failed call
RETRY_DELAY = 120  # Time in seconds between retries (2 minutes)
CALL_TIMEOUT = 90  # Maximum time in seconds to wait for a call to be answered
AUDIO_START_TIMEOUT = 15  # Maximum time in seconds to wait for audio to start playing
MAX_SILENT_CALL_DURATION = 20  # Maximum time in seconds to keep a call without audio

if not USERNAME or not PASSWORD:
    logging.error("Environment variables ASTERISK_USERNAME and ASTERISK_PASSWORD must be set")
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

    def load_pending_calls(self):
        """Loads pending calls"""
        # For testing without MySQL, use a predefined phone number
        self.pending_calls = [{"phone_number": DESTINATION_NUMBER, "attempts": 0}]
        return True

    async def process_pending_calls(self):
        """Processes all pending calls"""
        if not self.load_pending_calls():
            logging.warning("No pending calls to process")
            return

        for call_data in self.pending_calls:
            phone_number = call_data.get("phone_number")
            logging.info(f"Processing call to {phone_number}")

            llamador = LlamadorAutomatico(destination=phone_number)
            await llamador.ejecutar()

            # Wait a short time between calls to avoid system saturation
            await asyncio.sleep(5)


async def terminar_por_timeout():
    await asyncio.sleep(300)  # Esperar 55 
    logging.warning("¡TIEMPO MÁXIMO DE XX SEGUNDOS ALCANZADO! Terminando script...")
    # Forzar la terminación del programa
    os._exit(0)  # Esto termina el programa de forma abrupta


async def main():
    # Crear la tarea de terminación por timeout
    asyncio.create_task(terminar_por_timeout())
    
    # Resto del código normal
    llamador = LlamadorAutomatico()
    await llamador.ejecutar()

if __name__ == "__main__":
    asyncio.run(main())