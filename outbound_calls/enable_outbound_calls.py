#!/usr/bin/env python3

"""
Script de Activacion Mensual de Llamadas Salientes
===================================================
Este script activa el flag outbound_call para clientes activos que lo tengan
en 0 o NULL, permitiendo que sean evaluados por el sistema de llamadas a morosos.

Se ejecuta automaticamente via cron: 0 1 1 * * (1:00 AM el dia 1 de cada mes)

Nota: El script de llamadas (llamada_clientes_moroso.py) ya filtra por deuda
pendiente y dia de corte, por lo que activar outbound_call solo habilita la
evaluacion, no garantiza que se realice la llamada.
"""

import logging
import mysql.connector
from mysql.connector import Error
from datetime import datetime
import os
import sys

# MySQL Configuration from environment variables
MYSQL_DATABASE = os.getenv('MYSQL_DATABASE')
MYSQL_PASSWORD = os.getenv('MYSQL_PASSWORD')
MYSQL_SERVER = os.getenv('MYSQL_SERVER')
MYSQL_USER = os.getenv('MYSQL_USER')

# Configuracion de logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('/tmp/enable_outbound_calls.log')
    ]
)


def validate_environment():
    """Valida que las variables de entorno esten configuradas"""
    if not all([MYSQL_DATABASE, MYSQL_PASSWORD, MYSQL_SERVER, MYSQL_USER]):
        logging.error("ERROR: Variables de entorno MySQL no configuradas")
        logging.error("   Requeridas: MYSQL_DATABASE, MYSQL_PASSWORD, MYSQL_SERVER, MYSQL_USER")
        return False
    return True


def connect_to_mysql():
    """Conecta a MySQL y retorna el objeto de conexion"""
    try:
        connection = mysql.connector.connect(
            host=MYSQL_SERVER,
            database=MYSQL_DATABASE,
            user=MYSQL_USER,
            password=MYSQL_PASSWORD
        )
        if connection.is_connected():
            db_info = connection.get_server_info()
            logging.info(f"Conectado a MySQL Server version {db_info}")
            return connection
        else:
            logging.error("Fallo al conectar a MySQL")
            return None
    except Error as e:
        logging.error(f"Error conectando a MySQL: {e}")
        return None


def get_statistics(cursor):
    """Obtiene estadisticas de outbound_call"""
    try:
        query_disabled = """
        SELECT COUNT(*) as total
        FROM afiliados
        WHERE (outbound_call = 0 OR outbound_call IS NULL)
        AND activo = 1
        AND eliminar = 0
        """
        cursor.execute(query_disabled)
        result = cursor.fetchone()
        total_disabled = result[0] if result else 0

        query_enabled = """
        SELECT COUNT(*) as total
        FROM afiliados
        WHERE outbound_call = 1
        AND activo = 1
        AND eliminar = 0
        """
        cursor.execute(query_enabled)
        result = cursor.fetchone()
        total_enabled = result[0] if result else 0

        return {
            'total_disabled': total_disabled,
            'total_enabled': total_enabled
        }
    except Error as e:
        logging.error(f"Error obteniendo estadisticas: {e}")
        return None


def enable_outbound_calls(connection):
    """Activa outbound_call para clientes que lo tengan en 0 o NULL"""
    try:
        cursor = connection.cursor()
        current_month = datetime.now().strftime('%Y-%m')

        logging.info("=" * 70)
        logging.info(f"ACTIVACION MENSUAL DE OUTBOUND_CALL - {current_month}")
        logging.info("=" * 70)

        # Estadisticas antes
        logging.info("Obteniendo estadisticas antes de la activacion...")
        stats_before = get_statistics(cursor)

        if stats_before:
            logging.info(f"   Clientes con outbound_call activo (1): {stats_before['total_enabled']}")
            logging.info(f"   Clientes con outbound_call inactivo (0/NULL): {stats_before['total_disabled']}")

        if stats_before and stats_before['total_disabled'] == 0:
            logging.info("No hay clientes con outbound_call en 0 o NULL. Nada que actualizar.")
            cursor.close()
            return True

        # Consulta de actualizacion
        update_query = """
        UPDATE afiliados
        SET outbound_call = 1
        WHERE (outbound_call = 0 OR outbound_call IS NULL)
        AND activo = 1
        AND eliminar = 0
        """

        logging.info("Ejecutando activacion de outbound_call...")
        cursor.execute(update_query)
        rows_affected = cursor.rowcount

        connection.commit()

        logging.info("=" * 70)
        logging.info("ACTIVACION COMPLETADA EXITOSAMENTE")
        logging.info(f"Registros actualizados: {rows_affected}")
        logging.info(f"Fecha de activacion: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        logging.info("=" * 70)

        # Verificar
        logging.info("Verificando activacion...")
        stats_after = get_statistics(cursor)

        if stats_after:
            logging.info(f"   Clientes con outbound_call activo (1): {stats_after['total_enabled']}")
            logging.info(f"   Clientes con outbound_call inactivo (0/NULL): {stats_after['total_disabled']}")

            if stats_after['total_disabled'] == 0:
                logging.info("VERIFICACION EXITOSA: Todos los clientes activos tienen outbound_call = 1")
            else:
                logging.warning("ADVERTENCIA: Algunos clientes aun tienen outbound_call en 0/NULL")

        cursor.close()
        return True

    except Error as e:
        logging.error(f"Error activando outbound_call: {e}")
        if connection:
            connection.rollback()
        return False


def main():
    """Funcion principal"""
    try:
        logging.info("Iniciando script de activacion mensual de outbound_call")

        if not validate_environment():
            sys.exit(1)

        connection = connect_to_mysql()
        if not connection:
            sys.exit(1)

        success = enable_outbound_calls(connection)

        if connection.is_connected():
            connection.close()
            logging.info("Conexion MySQL cerrada")

        if success:
            logging.info("Script finalizado exitosamente")
            sys.exit(0)
        else:
            logging.error("Script finalizado con errores")
            sys.exit(1)

    except Exception as e:
        logging.error(f"Error inesperado en funcion principal: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
