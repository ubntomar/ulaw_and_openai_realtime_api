#!/usr/bin/env python3
"""
F2 - Conciliacion de debitos de creditos de comunicaciones (llamadas de cobranza).
Subsistema multi-tenant de llamadas (ver tenant_comms_account / comms_ledger).

Corre DESPUES del dialer (run_outbound_calls.sh). Lee el estado de la DB
(afiliados con outbound_call_is_sent=1 y outbound_call_completed_at de ESTE mes) y
registra 1 debito en comms_ledger por cada cliente CONECTADO este mes cuyo tenant:
  - feature_voz_activa = 1  Y  ilimitado = 0
Los tenants ilimitado=1 (la casa / Omar) NO debitan -> cero escrituras -> prod
byte-identico mientras no exista un tenant cobrable.

Idempotente: ref_idem = 'voz:<id-afiliado>:<YYYY-MM>' con UNIQUE en comms_ledger
=> reejecutar no duplica. Solo en debitos NUEVOS:
  - usados_mes = COUNT(debitos del tenant este mes)   (derivado, auto-reset mensual)
  - saldo_creditos -= 1 si el debito supera el free_mensual (consume comprado)

Fail-open: cualquier error se loguea y el script sale 0 (las llamadas ya
ocurrieron; nunca rompe el flujo). Dry-run por defecto; --apply escribe.

Limitacion conocida (MVP): el gate del dialer es por-CORRIDA, no por-llamada, asi
que un tenant casi sin saldo puede sobrepasar hasta los llamables de un dia.
Aceptable para cobro pass-through; endurecer a gate por-llamada si hiciera falta.
"""
import os
import sys
import argparse
from datetime import datetime
import mysql.connector


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="escribe los debitos (sin esta flag = dry-run)")
    args = ap.parse_args()
    dry = not args.apply
    ym = datetime.now().strftime("%Y-%m")
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    conn = mysql.connector.connect(
        host=os.getenv("MYSQL_SERVER"),
        database=os.getenv("MYSQL_DATABASE"),
        user=os.getenv("MYSQL_USER"),
        password=os.getenv("MYSQL_PASSWORD"),
    )
    cur = conn.cursor(dictionary=True)

    # Clientes conectados este mes de tenants cobrables (feature on, no ilimitado)
    # que AUN no tienen su debito del mes (LEFT JOIN ... IS NULL).
    cur.execute(
        """
        SELECT a.id AS af, a.`id-empresa` AS emp,
               acc.free_mensual AS free_m
        FROM afiliados a
        JOIN tenant_comms_account acc ON acc.`id-empresa` = a.`id-empresa`
        LEFT JOIN comms_ledger l ON l.ref_idem = CONCAT('voz:', a.id, ':', %s)
        WHERE a.outbound_call_is_sent = 1
          AND a.outbound_call_completed_at IS NOT NULL
          AND DATE_FORMAT(a.outbound_call_completed_at, '%%Y-%%m') = %s
          AND acc.feature_voz_activa = 1
          AND acc.ilimitado = 0
          AND l.id IS NULL
        ORDER BY a.`id-empresa`, a.id
        """,
        (ym, ym),
    )
    pendientes = cur.fetchall()
    print("[%s] conciliar_debitos_comms (%s) mes=%s | debitos nuevos a registrar: %d"
          % (ts, "DRY-RUN" if dry else "APPLY", ym, len(pendientes)))

    if not pendientes:
        cur.close(); conn.close()
        return 0

    if dry:
        for r in pendientes:
            print("   [dry] emp=%s af=%s ref=voz:%s:%s" % (r["emp"], r["af"], r["af"], ym))
        cur.close(); conn.close()
        return 0

    w = conn.cursor()
    aplicados = 0
    for r in pendientes:
        af = r["af"]; emp = r["emp"]; free_m = int(r["free_m"] or 0)
        ref = "voz:%s:%s" % (af, ym)
        w.execute(
            """
            INSERT IGNORE INTO comms_ledger
                (`id-empresa`, tipo, canal, cantidad, `id-afiliado`, ref_idem, detalle)
            VALUES (%s, 'debito_llamada', 'voz', -1, %s, %s, 'llamada cobranza conectada')
            """,
            (emp, af, ref),
        )
        if w.rowcount == 1:  # debito NUEVO (no duplicado del mes)
            w.execute(
                """SELECT COUNT(*) FROM comms_ledger
                   WHERE `id-empresa`=%s AND tipo='debito_llamada'
                     AND DATE_FORMAT(creado_at,'%%Y-%%m')=%s""",
                (emp, ym),
            )
            usados = int(w.fetchone()[0])
            dec = 1 if usados > free_m else 0  # supera el free -> consume saldo comprado
            w.execute(
                """UPDATE tenant_comms_account
                   SET usados_mes=%s, saldo_creditos=GREATEST(saldo_creditos-%s,0)
                   WHERE `id-empresa`=%s""",
                (usados, dec, emp),
            )
            aplicados += 1
    conn.commit()
    print("   debitos aplicados: %d" % aplicados)
    w.close(); cur.close(); conn.close()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print("WARN conciliar_debitos_comms fallo (no afecta llamadas): %s" % e)
        sys.exit(0)  # fail-open
