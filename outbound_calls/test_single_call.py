#!/usr/bin/env python3

import logging
import asyncio
import aiohttp
import websockets
import json
import os
import time
from datetime import datetime

# Configuration
ARI_URL = "http://localhost:8088/ari"
WEBSOCKET_URL = "ws://localhost:8088/ari/events"
USERNAME = os.getenv('ASTERISK_USERNAME')
PASSWORD = os.getenv('ASTERISK_PASSWORD')
AUDIO_FILE = "morosos_natalia"  # Audio file name to play

# Test Configuration
TEST_PHONE_NUMBER = "573162950915"  # Número de prueba 
TRUNK_NAME = "voip_issabel"  # SIP trunk name

# Retry configuration
MAX_RETRIES = 3  # Maximum number of attempts for a failed call
RETRY_DELAY = 30  # Time in seconds between retries (reduced for testing)
CALL_TIMEOUT = 90  # Maximum time in seconds to wait for a call to be answered
AUDIO_START_TIMEOUT = 15  # Maximum time in seconds to wait for audio to start playing
MAX_SILENT_CALL_DURATION = 20  # Maximum time in seconds to keep a call without audio

if not USERNAME or not PASSWORD:
    logging.error("Environment variables ASTERISK_USERNAME and ASTERISK_PASSWORD must be set Tip: sudo -E python3 test_single_call.py")
    exit(1)

# Enhanced logging for test purposes
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s.%(msecs)03d - %(levelname)s - %(funcName)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[
        logging.StreamHandler(),  # Console output
        logging.FileHandler('/tmp/test_single_call.log')  # File output
    ]
)

class CallStatus:
    INITIATED = "INITIATED"
    RINGING = "RINGING"
    ANSWERED = "ANSWERED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    TIMEOUT = "TIMEOUT"
    AUDIO_FAILED = "AUDIO_FAILED"

class TestCallManager:
    def __init__(self):
        self.playback_map = {}
        self.active_channel = None
        self.call_id = None
        self.session = None
        self.audio_started = False
        self.audio_requested_time = None
        self.audio_started_time = None
        self.call_status = None
        self.call_start_time = None
        self.destination = TEST_PHONE_NUMBER
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
        """Logs a call attempt for testing purposes"""
        log_message = f"TEST CALL LOG: Number={self.destination}, ID={self.call_id}, Status={status}, Attempt={self.attempt_count}"
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
        """Initiates a test call using the SIP trunk"""
        self.attempt_count += 1
        self.call_status = CallStatus.INITIATED
        self.call_start_time = time.time()

        try:
            url = f"{ARI_URL}/channels"
            data = {
                "endpoint": f"SIP/{TRUNK_NAME}/{self.destination}",
                "app": "overdue-app",
                "callerId": "\"Test Call\" <3241000752>",
                "variables": {
                    "CHANNEL(language)": "es",
                    "TEST_CALL": "true"
                }
            }

            logging.info(f"🔥 INITIATING TEST CALL to {self.destination} via trunk {TRUNK_NAME} (Attempt {self.attempt_count})")
            logging.debug(f"Call data: {json.dumps(data, indent=2)}")

            async with self.session.post(url, json=data) as response:
                response_text = await response.text()
                if response.status == 200:
                    response_data = json.loads(response_text)
                    self.call_id = response_data['id']
                    logging.info(f"✅ TEST CALL INITIATED: {self.call_id}")

                    # Set a timeout for the call
                    self.timeout_task = asyncio.create_task(self.call_timeout())

                    self.log_call_attempt(CallStatus.INITIATED)
                    return True
                else:
                    logging.error(f"❌ ERROR INITIATING TEST CALL: {response_text}")
                    self.call_status = CallStatus.FAILED
                    self.log_call_attempt(CallStatus.FAILED)
                    return False

        except Exception as e:
            logging.error(f"❌ EXCEPTION IN TEST CALL INITIATION: {e}")
            self.call_status = CallStatus.FAILED
            self.log_call_attempt(CallStatus.FAILED)
            return False

    async def call_timeout(self):
        """Handles call timeout if there's no response"""
        await asyncio.sleep(CALL_TIMEOUT)
        try:
            if self.call_status not in [CallStatus.ANSWERED, CallStatus.COMPLETED]:
                logging.warning(f"⏰ TEST CALL TIMEOUT after {CALL_TIMEOUT} seconds")
                self.call_status = CallStatus.TIMEOUT
                self.log_call_attempt(CallStatus.TIMEOUT)
                await self.finalizar_llamada()
        except Exception as e:
            logging.error(f"❌ ERROR in call_timeout: {e}")
            logging.exception("Complete traceback:")

    async def audio_start_timeout(self):
        """Handles timeout if audio doesn't start playing"""
        await asyncio.sleep(AUDIO_START_TIMEOUT)
        if self.active_channel and not self.audio_started and self.call_status == CallStatus.ANSWERED:
            logging.warning(f"⏰ TIMEOUT waiting for audio playback to start after {AUDIO_START_TIMEOUT} seconds")
            
            if self.playback_map:
                logging.warning(f"📋 We have {len(self.playback_map)} playbacks in the map, but audio_started=False")
                for playback_id, channel in self.playback_map.items():
                    logging.warning(f"   Playback ID: {playback_id}, Channel: {channel}")
            else:
                logging.warning("📋 No playbacks registered in the map")

            self.call_status = CallStatus.AUDIO_FAILED
            self.log_call_attempt(CallStatus.AUDIO_FAILED)
            logging.info("🔚 Ending test call due to audio start failure")
            await self.finalizar_llamada()

    async def silent_call_timeout(self):
        """Ends the call if it remains too long without audio activity"""
        await asyncio.sleep(MAX_SILENT_CALL_DURATION)
        if self.active_channel and self.audio_requested_time and not self.audio_started and self.call_status == CallStatus.ANSWERED:
            elapsed = time.time() - self.audio_requested_time
            logging.warning(f"🔇 Test call without active audio for {elapsed:.1f} seconds, ending")

            if self.playback_map:
                logging.warning(f"📋 There are {len(self.playback_map)} registered playbacks but audio_started=False")
                for playback_id, channel in self.playback_map.items():
                    logging.warning(f"   Registered playback: ID={playback_id}, Channel={channel}")

                logging.warning("🔧 Forcing audio_started=True as a preventive measure")
                self.audio_started = True
                self.audio_started_time = time.time()
                return

            self.call_status = CallStatus.AUDIO_FAILED
            self.log_call_attempt(CallStatus.AUDIO_FAILED)
            await self.finalizar_llamada()

    async def reproducir_audio(self):
        """Plays the test audio file"""
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

                logging.info(f"🎵 Requesting audio playback for test call: {AUDIO_FILE}")
                async with self.session.post(url, json=data) as response:
                    response_text = await response.text()
                    logging.debug(f"Audio playback response: {response_text}")
                    if response.status == 201:
                        playback = json.loads(response_text)
                        playback_id = playback['id']
                        logging.info(f"✅ Generated Playback ID for test: {playback_id}")
                        self.playback_map[playback_id] = self.active_channel
                        logging.info(f"🎵 Audio playback requested for test channel {self.active_channel}")

                        logging.debug(f"State after requesting test audio - playback_map: {self.playback_map}, audio_started: {self.audio_started}")

                        # Schedule a check for call completion
                        asyncio.create_task(self.check_call_completion(playback_id))
                    else:
                        logging.error(f"❌ ERROR playing test audio: {response_text}")
                        logging.error(f"Data sent: {json.dumps(data, indent=2)}")
                        self.call_status = CallStatus.AUDIO_FAILED
                        await self.finalizar_llamada()
            except Exception as e:
                logging.error(f"❌ ERROR in reproducir_audio for test: {e}")
                self.call_status = CallStatus.AUDIO_FAILED
                await self.finalizar_llamada()

    async def check_call_completion(self, playback_id):
        """Checks if a playback has finished to end the test call"""
        try:
            await asyncio.sleep(30)  # Wait 30 seconds for audio completion

            if self.active_channel and playback_id in self.playback_map and self.call_status not in [CallStatus.COMPLETED, CallStatus.FAILED]:
                logging.warning(f"🔍 Detected possible audio completion without PlaybackFinished event for test playback {playback_id}")
                logging.warning("🔚 Ending test call by safety mechanism")

                url = f"{ARI_URL}/playbacks/{playback_id}"
                try:
                    async with self.session.get(url) as response:
                        if response.status == 404:
                            logging.info(f"✅ Test playback {playback_id} no longer exists, assuming it's finished")
                            self.call_status = CallStatus.COMPLETED
                            await self.finalizar_llamada(status=CallStatus.COMPLETED)
                        else:
                            playback_data = await response.json()
                            playback_state = playback_data.get('state')
                            logging.info(f"📊 Current state of test playback {playback_id}: {playback_state}")

                            if playback_state in ['done', 'cancelled']:
                                self.call_status = CallStatus.COMPLETED
                                await self.finalizar_llamada(status=CallStatus.COMPLETED)
                except Exception as e:
                    logging.error(f"❌ ERROR checking test playback status: {e}")
                    self.call_status = CallStatus.COMPLETED
                    await self.finalizar_llamada(status=CallStatus.COMPLETED)
        except Exception as e:
            logging.error(f"❌ ERROR in check_call_completion for test: {e}")
            logging.exception("Complete traceback:")

    async def manejar_eventos(self, websocket):
        """Processes WebSocket events for test call"""
        try:
            async for mensaje in websocket:
                evento = json.loads(mensaje)
                tipo = evento.get('type')
                logging.debug(f"📨 Test event received: {tipo}")

                if tipo == 'Dial':
                    dial_state = evento.get('dialstatus')
                    if dial_state == 'RINGING':
                        self.call_status = CallStatus.RINGING
                        logging.info("📞 Test call is ringing")

                elif tipo == 'StasisStart':
                    self.active_channel = evento['channel']['id']
                    self.call_status = CallStatus.ANSWERED
                    logging.info(f"✅ TEST CALL ANSWERED - Active channel: {self.active_channel}")

                    # Cancel the timeout if it exists
                    if self.timeout_task:
                        self.timeout_task.cancel()
                        self.timeout_task = None

                    # Small pause to ensure the channel is ready
                    await asyncio.sleep(1)

                    # Try to play the test audio
                    await self.reproducir_audio()

                    if not self.audio_started and not self.audio_requested_time:
                        logging.error("❌ Could not request test audio playback")
                        self.call_status = CallStatus.AUDIO_FAILED
                        await self.finalizar_llamada()
                    else:
                        logging.info("⏳ Waiting for test audio playback...")
                
                elif tipo == 'PlaybackStarted':
                    playback_id = evento['playback']['id']
                    if playback_id in self.playback_map:
                        logging.info(f"🎵 TEST AUDIO PLAYBACK STARTED: {playback_id}")
                        self.audio_started = True
                        self.audio_started_time = time.time()
                        logging.info(f"✅ TEST CALL SUCCESS - Audio started successfully!")

                elif tipo == 'PlaybackFinished':
                    playback_id = evento['playback']['id']
                    if playback_id in self.playback_map:
                        logging.info("🎵 TEST AUDIO PLAYED COMPLETELY")
                        if self.audio_started_time:
                            audio_duration = time.time() - self.audio_started_time
                            logging.info(f"📊 Test playback duration: {audio_duration:.2f} seconds")

                        await asyncio.sleep(2)  # Small pause before hanging up
                        logging.info("🔚 Ending test call after audio playback")
                        await self.finalizar_llamada(status=CallStatus.COMPLETED)

                elif tipo == 'StasisEnd':
                    if evento.get('channel', {}).get('id') == self.active_channel:
                        logging.info("📞 Test call terminated by destination")
                        self.active_channel = None
                        if self.call_status == CallStatus.ANSWERED:
                            self.call_status = CallStatus.COMPLETED

                elif tipo == 'ChannelStateChange':
                    state = evento.get('channel', {}).get('state')
                    logging.info(f"📊 Test channel state changed to: {state}")
                    if state == 'Up' and self.call_status != CallStatus.ANSWERED:
                        self.call_status = CallStatus.ANSWERED

                elif tipo == 'ChannelDestroyed':
                    channel_id = evento.get('channel', {}).get('id')
                    if channel_id == self.call_id:
                        logging.info(f"🗑️ Test channel destroyed: {channel_id}")

                        call_duration = None
                        if self.call_start_time:
                            call_duration = round(time.time() - self.call_start_time)

                        if self.call_status not in [CallStatus.COMPLETED]:
                            if self.call_status == CallStatus.ANSWERED and not self.audio_started:
                                self.call_status = CallStatus.AUDIO_FAILED
                                logging.warning("⚠️ Test call answered but without audio playback")
                            elif self.call_status not in [CallStatus.AUDIO_FAILED]:
                                self.call_status = CallStatus.FAILED

                            self.log_call_attempt(self.call_status, call_duration)

                            # Retry logic for test call
                            if self.attempt_count < MAX_RETRIES:
                                retry_reason = "audio failure" if self.call_status == CallStatus.AUDIO_FAILED else "failed call"
                                logging.info(f"🔄 Scheduling test retry #{self.attempt_count + 1} in {RETRY_DELAY} seconds due to {retry_reason}")
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
                                logging.warning(f"❌ Maximum number of test attempts ({MAX_RETRIES}) reached for {self.destination}")
                                break
                        else:
                            if self.call_status == CallStatus.ANSWERED and call_duration:
                                self.log_call_attempt(CallStatus.COMPLETED, call_duration)
                            break

        except Exception as e:
            logging.error(f"❌ ERROR in manejar_eventos for test: {e}")
            await self.finalizar_llamada()

    async def finalizar_llamada(self, status=None):
        """Ends the test call"""
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

            call_duration = None
            if self.call_start_time:
                call_duration = round(time.time() - self.call_start_time)
            
            logging.info(f"🔚 Ending test call with status: {self.call_status}")
            logging.info(f"📊 Active channel: {self.active_channel}")
            
            if self.active_channel:
                url = f"{ARI_URL}/channels/{self.active_channel}"
                async with self.session.delete(url) as response:
                    if response.ok:
                        logging.info(f"✅ Test call ended successfully (duration: {call_duration}s)")
                        if self.call_status == CallStatus.ANSWERED and not status:
                            self.log_call_attempt(CallStatus.COMPLETED, call_duration)
                    else:
                        response_text = await response.text()
                        if "Channel not found" in response_text:
                            logging.warning("⚠️ Test channel no longer exists, call probably already ended")
                        else:
                            logging.error(f"❌ ERROR ending test call: {response_text}")

                        if not status:
                            self.log_call_attempt(self.call_status or CallStatus.FAILED, call_duration)
            
            logging.info("✅ Test call ended")
        except Exception as e:
            logging.error(f"❌ ERROR ending test call: {e}")
        finally:
            self.active_channel = None
            self.call_id = None
            self.audio_started = False
            self.audio_requested_time = None
            self.audio_started_time = None

    async def ejecutar_test(self):
        """Main execution flow for test call"""
        try:
            await self.setup_session()
            logging.info(f"🚀 STARTING TEST CALL to {self.destination}")
            logging.info(f"🔧 Using trunk: {TRUNK_NAME}")
            logging.info(f"🎵 Audio file: {AUDIO_FILE}")
            
            # Add small delay to ensure ARI app is registered
            await asyncio.sleep(2)
            
            async with websockets.connect(
                f"{WEBSOCKET_URL}?api_key={USERNAME}:{PASSWORD}&app=overdue-app",
                ping_interval=30,
                ping_timeout=10
            ) as websocket:
                logging.info("🌐 WebSocket connected for test call")
                if await self.iniciar_llamada():
                    await self.manejar_eventos(websocket)
                else:
                    logging.error("❌ Failed to initiate test call")

        except websockets.exceptions.ConnectionClosed as e:
            logging.error(f"❌ WebSocket connection closed during test: {e}")
        except Exception as e:
            logging.error(f"❌ ERROR in test execution: {e}")
            logging.exception("Complete traceback:")
            await self.finalizar_llamada()
        finally:
            await self.cleanup_session()
            logging.info("🧹 Test call cleanup completed")

async def main():
    """Main function for test call"""
    try:
        logging.info("=" * 60)
        logging.info("🧪 STARTING SINGLE TEST CALL")
        logging.info(f"📞 Target number: {TEST_PHONE_NUMBER}")
        logging.info(f"🌐 Trunk: {TRUNK_NAME}")
        logging.info(f"⏰ Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        logging.info("=" * 60)
        
        test_manager = TestCallManager()
        await test_manager.ejecutar_test()
        
        logging.info("=" * 60)
        logging.info("✅ TEST CALL EXECUTION COMPLETED")
        logging.info("=" * 60)
        
    except Exception as e:
        logging.error(f"❌ ERROR in main test function: {e}")
        logging.exception("Complete traceback:")

if __name__ == "__main__":
    asyncio.run(main())