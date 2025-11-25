#!/usr/bin/env python3

"""
Script para consultar qué clientes serán llamados hoy
sin ejecutar ninguna llamada real.
"""

import mysql.connector
from mysql.connector import Error
from datetime import datetime
import os
from tabulate import tabulate

# MySQL Configuration from environment variables
MYSQL_DATABASE = os.getenv('MYSQL_DATABASE')
MYSQL_PASSWORD = os.getenv('MYSQL_PASSWORD')
MYSQL_SERVER = os.getenv('MYSQL_SERVER')
MYSQL_USER = os.getenv('MYSQL_USER')

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
            return connection
        else:
            print("❌ Fallo al conectar a MySQL")
            return None
    except Error as e:
        print(f"❌ Error conectando a MySQL: {e}")
        return None

def get_clients_to_call_today():
    """Obtiene la lista de clientes que serán llamados hoy"""

    if not all([MYSQL_DATABASE, MYSQL_PASSWORD, MYSQL_SERVER, MYSQL_USER]):
        print("❌ Error: Variables de entorno MySQL no configuradas")
        print("   Asegúrate de que estén definidas: MYSQL_DATABASE, MYSQL_PASSWORD, MYSQL_SERVER, MYSQL_USER")
        return []

    conn = connect_to_mysql()
    if not conn:
        return []

    try:
        cursor = conn.cursor(dictionary=True)

        current_day = datetime.now().day
        current_date = datetime.now().strftime('%Y-%m-%d')

        print(f"\n{'='*80}")
        print(f"📅 CONSULTA DE LLAMADAS PROGRAMADAS PARA HOY: {current_date}")
        print(f"📆 Día del mes actual: {current_day}")
        print(f"{'='*80}\n")

        # Query idéntica a la del script de llamadas
        query = """
        SELECT a.id, a.telefono, a.outbound_call_attempts, a.corte, a.cliente, a.apellido,
               SUM(CASE WHEN f.cerrado = 0 THEN f.saldo ELSE 0 END) AS deuda_total
        FROM afiliados a
        LEFT JOIN factura f ON a.id = f.`id-afiliado`
        WHERE a.outbound_call = 1
        AND a.outbound_call_is_sent = 0
        AND a.activo = 1
        AND a.eliminar = 0
        GROUP BY a.id, a.telefono, a.outbound_call_attempts, a.corte, a.cliente, a.apellido
        HAVING deuda_total > 0
        ORDER BY a.id
        """

        print("🔍 Consultando base de datos...")
        cursor.execute(query)
        results = cursor.fetchall()

        print(f"✅ Se encontraron {len(results)} clientes con deudas pendientes en la base de datos\n")

        clients_to_call = []
        excluded_clients = []

        for row in results:
            user_id = row['id']
            cliente = row['cliente'] or 'Sin nombre'
            apellido = row['apellido'] or ''
            phone = row['telefono'].strip() if row['telefono'] else ""
            attempts = row['outbound_call_attempts'] or 0
            corte = row['corte']
            deuda_total = float(row['deuda_total'])

            # Verificar día de corte
            is_valid_cut_day = False
            cut_day_reason = ""

            if corte and corte.isdigit():
                corte_day = int(corte)
                # Lógica: llamar 1 día antes del corte, el día del corte, o hasta 3 días después
                is_valid_cut_day = ((current_day == corte_day - 1) or (current_day >= corte_day)) and (corte_day >= current_day - 3)

                if not is_valid_cut_day:
                    cut_day_reason = f"Día de corte {corte_day} no válido para hoy ({current_day})"
            else:
                cut_day_reason = "Día de corte no válido o vacío"

            # Validar teléfono móvil colombiano
            is_valid_phone = phone and len(phone) == 10 and phone.startswith('3')
            phone_reason = "" if is_valid_phone else f"Teléfono inválido: '{phone}'"

            # Formatear teléfono para llamadas
            formatted_phone = '57' + phone if is_valid_phone else phone

            client_data = {
                'id': user_id,
                'nombre': f"{cliente} {apellido}".strip(),
                'telefono': formatted_phone,
                'telefono_original': phone,
                'deuda': deuda_total,
                'corte': corte,
                'intentos': attempts,
                'valido_corte': is_valid_cut_day,
                'valido_telefono': is_valid_phone,
                'razon_exclusion': cut_day_reason or phone_reason
            }

            if is_valid_cut_day and is_valid_phone:
                clients_to_call.append(client_data)
            else:
                excluded_clients.append(client_data)

        cursor.close()
        conn.close()

        return clients_to_call, excluded_clients

    except Error as e:
        print(f"❌ Error consultando llamadas pendientes: {e}")
        if conn.is_connected():
            cursor.close()
            conn.close()
        return [], []

def display_results(clients_to_call, excluded_clients):
    """Muestra los resultados de manera formateada"""

    print(f"\n{'='*80}")
    print(f"📊 RESUMEN DE CLIENTES")
    print(f"{'='*80}")
    print(f"✅ Clientes que SERÁN llamados hoy: {len(clients_to_call)}")
    print(f"❌ Clientes excluidos: {len(excluded_clients)}")
    print(f"{'='*80}\n")

    if clients_to_call:
        print(f"\n{'='*80}")
        print("✅ CLIENTES QUE SERÁN LLAMADOS HOY")
        print(f"{'='*80}\n")

        # Preparar datos para tabla
        table_data = []
        total_deuda = 0

        for i, client in enumerate(clients_to_call, 1):
            table_data.append([
                i,
                client['id'],
                client['nombre'][:30],  # Truncar nombre si es muy largo
                client['telefono'],
                f"${client['deuda']:,.0f}",
                client['corte'] or 'N/A',
                client['intentos']
            ])
            total_deuda += client['deuda']

        headers = ['#', 'ID', 'Nombre', 'Teléfono', 'Deuda', 'Corte', 'Intentos']
        print(tabulate(table_data, headers=headers, tablefmt='grid'))

        print(f"\n💰 Deuda total de clientes a llamar: ${total_deuda:,.0f}")
        print(f"\n📞 Se realizarán hasta {len(clients_to_call)} llamadas (con hasta 3 intentos por cliente)")
    else:
        print("\n✅ No hay clientes programados para llamar hoy")
        print("   Posibles razones:")
        print("   - No es el día de corte de ningún cliente")
        print("   - Todos los clientes ya fueron contactados")
        print("   - No hay clientes con deudas pendientes")

    if excluded_clients:
        print(f"\n{'='*80}")
        print("ℹ️  CLIENTES EXCLUIDOS (no se llamarán hoy)")
        print(f"{'='*80}\n")

        # Preparar datos para tabla de excluidos
        excluded_table = []
        for i, client in enumerate(excluded_clients[:10], 1):  # Mostrar solo primeros 10
            excluded_table.append([
                client['id'],
                client['nombre'][:25],
                client['telefono_original'],
                f"${client['deuda']:,.0f}",
                client['corte'] or 'N/A',
                client['razon_exclusion'][:40]
            ])

        headers = ['ID', 'Nombre', 'Teléfono', 'Deuda', 'Corte', 'Razón de exclusión']
        print(tabulate(excluded_table, headers=headers, tablefmt='grid'))

        if len(excluded_clients) > 10:
            print(f"\n... y {len(excluded_clients) - 10} clientes más excluidos")

    print(f"\n{'='*80}")
    print("ℹ️  NOTAS:")
    print("   - Los clientes se llaman 1 día antes del corte, el día del corte, o hasta 3 días después")
    print("   - Solo se llaman números móviles colombianos válidos (10 dígitos, inician con 3)")
    print("   - Se realizan hasta 3 intentos por cliente si no contestan")
    print("   - Este script NO realiza llamadas, solo muestra quién sería llamado")
    print(f"{'='*80}\n")

def main():
    """Función principal"""
    try:
        clients_to_call, excluded_clients = get_clients_to_call_today()
        display_results(clients_to_call, excluded_clients)

    except KeyboardInterrupt:
        print("\n\n⚠️  Script interrumpido por el usuario")
    except Exception as e:
        print(f"\n❌ Error inesperado: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
