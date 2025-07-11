#!/bin/bash

# Cargar las variables de entorno del usuario
source $HOME/.bash_profile

# Registrar inicio de ejecución
echo "<<< Iniciando script de llamadas salientes: $(date)" >> $HOME/cron_jobs.log

# Navegar al directorio correcto del script
cd /usr/local/bin/outbound_calls

# Ejecutar el script Python
#python3 /usr/local/bin/outbound_calls/mysql_overdue_client_call.py >> $HOME/outbound_calls.log 2>&1
python3 /usr/local/bin/outbound_calls/enhanced_call_system.py >> $HOME/outbound_calls.log 2>&1

# Registrar finalización
echo "Script de llamadas salientes finalizado: $(date) >>>" >> $HOME/cron_jobs.log

echo  ""

# Este script se ejecuta a través de cron para realizar llamadas salientes a clientes con saldo negativo.

#Nuestro cron realiza la llamada a las 16:47 todos los días del script mysql_overdue_client_call.py
#omar@vpsasterisk:~$ crontab -l
#47 16 * * * /usr/local/bin/run_outbound_calls.sh