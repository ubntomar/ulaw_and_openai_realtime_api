import os
import sys
from mistralai import Mistral

# Obtener la API key desde la variable de entorno
api_key = os.environ.get("MISTRAL_API_KEY")

if not api_key:
    raise ValueError("No se encontró la API key. Asegúrate de configurar la variable de entorno MISTRAL_API_KEY.")

# Configuración del modelo
model = "mistral-large-latest"

# Inicializar el cliente de Mistral
client = Mistral(api_key=api_key)

# Verificar si se proporcionó un mensaje como argumento
if len(sys.argv) != 2:
    print("Uso: python script.py \"Tu mensaje aquí\"")
    sys.exit(1)

# Obtener el mensaje de la línea de comandos
user_message = sys.argv[1]

# Enviar el mensaje a la API de Mistral
chat_response = client.chat.complete(
    model=model,
    messages=[
        {
            "role": "user",
            "content": user_message,
        },
    ]
)

# Imprimir la respuesta
print(chat_response.choices[0].message.content)

