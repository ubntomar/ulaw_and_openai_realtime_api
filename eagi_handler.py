# eagi_handler.py - Maneja la entrada de audio
#!/usr/bin/env python3
import os
import sys
import fcntl

def setup_fd():
    fd = 3  # Audio FD
    flags = fcntl.fcntl(fd, fcntl.F_GETFL)
    fcntl.fcntl(fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)
    return fd

def main():
    fd = setup_fd()
    audio_pipe = "/tmp/shared_openai/audio_pipe"

    # Crear pipe si no existe
    if not os.path.exists(audio_pipe):
        os.mkfifo(audio_pipe)

    # Leer de FD 3 y escribir al pipe
    while True:
        try:
            data = os.read(fd, 320)  # 40ms de audio a 8 kHz
            if not data:
                break
            with open(audio_pipe, 'wb') as f:
                f.write(data)
        except BlockingIOError:
            continue
        except Exception as e:
            sys.stderr.write(f"Error: {e}\n")
            break

if __name__ == "__main__":
    main()

