#!/usr/bin/env python3

"""
Script de Reinicio Mensual de Contadores de Llamadas
====================================================
Este script reinicia los contadores de llamadas salientes el día 1 de cada mes
para permitir que los clientes morosos sean contactados nuevamente.

Se ejecuta automáticamente vía cron: 0 2 1 * * (2:00 AM el día 1 de cada mes)
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

# Configuración de logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('/tmp/monthly_reset.log')
    ]
)

def validate_environment():
    """Valida que las variables de entorno estén configuradas"""
    if not all([MYSQL_DATABASE, MYSQL_PASSWORD, MYSQL_SERVER, MYSQL_USER]):
        logging.error("❌ ERROR: Variables de entorno MySQL no configuradas")
        logging.error("   Requeridas: MYSQL_DATABASE, MYSQL_PASSWORD, MYSQL_SERVER, MYSQL_USER")
        return False
    return True

def connect_to_mysql():
    """Conecta a MySQL y retorna el objeto de conexión"""
    try:
        connection = mysql.connector.connect(
            host=MYSQL_SERVER,
            database=MYSQL_DATABASE,
            user=MYSQL_USER,
            password=MYSQL_PASSWORD
        )
        if connection.is_connected():
            db_info = connection.get_server_info()
            logging.info(f"✅ Conectado a MySQL Server versión {db_info}")
            return connection
        else:
            logging.error("❌ Fallo al conectar a MySQL")
            return None
    except Error as e:
        logging.error(f"❌ Error conectando a MySQL: {e}")
        return None

def get_reset_statistics(cursor):
    """Obtiene estadísticas antes del reinicio"""
    try:
        # Contar clientes que ya fueron llamados
        query_sent = """
        SELECT COUNT(*) as total_sent
        FROM afiliados
        WHERE outbound_call = 1
        AND outbound_call_is_sent = 1
        AND activo = 1
        AND eliminar = 0
        """
        cursor.execute(query_sent)
        result = cursor.fetchone()
        total_sent = result[0] if result else 0

        # Contar clientes con intentos registrados
        query_attempts = """
        SELECT COUNT(*) as total_with_attempts
        FROM afiliados
        WHERE outbound_call = 1
        AND outbound_call_attempts > 0
        AND activo = 1
        AND eliminar = 0
        """
        cursor.execute(query_attempts)
        result = cursor.fetchone()
        total_with_attempts = result[0] if result else 0

        # Contar total de clientes marcados para llamar
        query_total = """
        SELECT COUNT(*) as total_marked
        FROM afiliados
        WHERE outbound_call = 1
        AND activo = 1
        AND eliminar = 0
        """
        cursor.execute(query_total)
        result = cursor.fetchone()
        total_marked = result[0] if result else 0

        return {
            'total_sent': total_sent,
            'total_with_attempts': total_with_attempts,
            'total_marked': total_marked
        }
    except Error as e:
        logging.error(f"❌ Error obteniendo estadísticas: {e}")
        return None

def reset_monthly_counters(connection):
    """Reinicia los contadores de llamadas mensuales"""
    try:
        cursor = connection.cursor()
        current_month = datetime.now().strftime('%Y-%m')

        logging.info("=" * 70)
        logging.info(f"🗓️  REINICIO MENSUAL DE CONTADORES - {current_month}")
        logging.info("=" * 70)

        # Obtener estadísticas antes del reinicio
        logging.info("📊 Obteniendo estadísticas antes del reinicio...")
        stats_before = get_reset_statistics(cursor)

        if stats_before:
            logging.info(f"   • Clientes marcados para llamar: {stats_before['total_marked']}")
            logging.info(f"   • Clientes contactados exitosamente: {stats_before['total_sent']}")
            logging.info(f"   • Clientes con intentos registrados: {stats_before['total_with_attempts']}")

        # Consulta de actualización
        update_query = """
        UPDATE afiliados
        SET outbound_call_is_sent = 0,
            outbound_call_attempts = 0,
            outbound_call_completed_at = NULL
        WHERE outbound_call = 1
        AND activo = 1
        AND eliminar = 0
        """

        logging.info("🔄 Ejecutando reinicio de contadores...")
        cursor.execute(update_query)
        rows_affected = cursor.rowcount

        # F2: resetear el contador mensual de creditos de comunicaciones (usados_mes)
        # para que el gate del dialer vea el cupo fresco al inicio del mes. Fail-safe.
        try:
            cursor.execute("UPDATE tenant_comms_account SET usados_mes = 0")
            logging.info(f"   - tenant_comms_account.usados_mes reseteado ({cursor.rowcount} tenants)")
        except Exception as _e:
            logging.warning(f"   - no se pudo resetear usados_mes: {_e}")

        connection.commit()

        logging.info("=" * 70)
        logging.info(f"✅ REINICIO COMPLETADO EXITOSAMENTE")
        logging.info(f"📈 Registros actualizados: {rows_affected}")
        logging.info(f"📅 Fecha de reinicio: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        logging.info("=" * 70)

        # Verificar el reinicio
        logging.info("🔍 Verificando reinicio...")
        stats_after = get_reset_statistics(cursor)

        if stats_after:
            logging.info(f"   • Clientes con is_sent = 1: {stats_after['total_sent']} (debe ser 0)")
            logging.info(f"   • Clientes con attempts > 0: {stats_after['total_with_attempts']} (debe ser 0)")

            if stats_after['total_sent'] == 0 and stats_after['total_with_attempts'] == 0:
                logging.info("✅ VERIFICACIÓN EXITOSA: Todos los contadores fueron reiniciados")
            else:
                logging.warning("⚠️ ADVERTENCIA: Algunos contadores no se reiniciaron correctamente")

        cursor.close()
        return True

    except Error as e:
        logging.error(f"❌ Error reiniciando contadores: {e}")
        if connection:
            connection.rollback()
        return False

def main():
    """Función principal"""
    try:
        logging.info("🚀 Iniciando script de reinicio mensual de contadores")

        # Validar variables de entorno
        if not validate_environment():
            sys.exit(1)

        # Conectar a MySQL
        connection = connect_to_mysql()
        if not connection:
            sys.exit(1)

        # Reiniciar contadores
        success = reset_monthly_counters(connection)

        # Cerrar conexión
        if connection.is_connected():
            connection.close()
            logging.info("🔌 Conexión MySQL cerrada")

        if success:
            logging.info("✅ Script finalizado exitosamente")
            sys.exit(0)
        else:
            logging.error("❌ Script finalizado con errores")
            sys.exit(1)

    except Exception as e:
        logging.error(f"❌ Error inesperado en función principal: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
