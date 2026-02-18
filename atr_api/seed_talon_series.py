#!/usr/bin/env python3
# seed_talon_series.py

import argparse
import json
import sys
from typing import List, Dict, Optional
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError


SERIES: List[Dict[str, str]] = [
    {"folio": "VWP", "cliente_nombre": "VOLKS WAGEN PUEBLA"},
    {"folio": "VWV", "cliente_nombre": "VOLKS WAGEN VERACRUZ"},
    {"folio": "GML", "cliente_nombre": "GENERAL MOTORS LAZARO"},
    {"folio": "GMS", "cliente_nombre": "GENERAL MOTORS S.L.P."},
    {"folio": "MNS", "cliente_nombre": "MAZDA NACIONAL SALAMANCA"},
    {"folio": "MNL", "cliente_nombre": "MAZDA NACIONAL LAZARO"},
    {"folio": "MZS", "cliente_nombre": "MAZDA SALAMANCA"},
    {"folio": "NIV", "cliente_nombre": "NISSAN VERACRUZ"},
    {"folio": "NIC", "cliente_nombre": "NISSAN CUERNAVACA"},
    {"folio": "NIA", "cliente_nombre": "NISSAN AGUASCALIENTES"},
    {"folio": "REV", "cliente_nombre": "RENAULT VERACRUZ"},
    {"folio": "REL", "cliente_nombre": "RENAULT LAZARO"},
    {"folio": "TOL", "cliente_nombre": "TOYOTA LAZARO"},
    {"folio": "MIT", "cliente_nombre": "MITSUBISHI"},
    {"folio": "HCV", "cliente_nombre": "HONDA CELAYA Y VERACRUZ"},
    {"folio": "ESP", "cliente_nombre": "ESPECIALES"},
    {"folio": "PRO", "cliente_nombre": "PRUEBAS"},
]


def _read_http_error_body(e: HTTPError) -> str:
    try:
        raw = e.read()
        return raw.decode("utf-8", errors="replace") if raw else ""
    except Exception:
        return ""


def _pretty_error_body(text: str) -> str:
    t = (text or "").strip()
    if not t:
        return ""
    # intenta pretty JSON si aplica
    try:
        obj = json.loads(t)
        return json.dumps(obj, ensure_ascii=False)
    except Exception:
        return t


def http_post_json(url: str, payload: dict, token: Optional[str] = None, timeout: int = 30) -> tuple[int, str]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    req = Request(url=url, data=body, headers=headers, method="POST")

    try:
        with urlopen(req, timeout=timeout) as resp:
            status = int(getattr(resp, "status", 200))
            raw = resp.read()
            text = raw.decode("utf-8", errors="replace") if raw else ""
            return status, text

    except HTTPError as e:
        status = int(getattr(e, "code", 0) or 0)
        text = _read_http_error_body(e)
        return status, text

    except URLError as e:
        # no hay status code porque ni siquiera conectó
        return 0, f"URLError: {e.reason}"

    except Exception as e:
        return 0, f"Error: {e}"


def main() -> int:
    ap = argparse.ArgumentParser(description="Seed TalonSeries (hardcoded list) into backend (no requests).")
    ap.add_argument("--base-url", default="http://localhost:5000", help="Ej: http://localhost:5000")
    ap.add_argument("--client-id", type=int, required=True, help="ID numérico del cliente (ej: 1)")
    ap.add_argument("--padding", type=int, default=5, help="Padding default (1..10). Ej: 5 => 00001")
    ap.add_argument("--activo", action="store_true", help="Marca activo=true (default)")
    ap.add_argument("--inactivo", action="store_true", help="Marca activo=false")
    ap.add_argument("--token", default=None, help="Bearer token (opcional si tu API lo requiere)")
    ap.add_argument("--dry-run", action="store_true", help="No crea nada, solo imprime lo que haría")
    ap.add_argument("--timeout", type=int, default=30, help="Timeout en segundos (default 30)")
    args = ap.parse_args()

    if args.inactivo and args.activo:
        print("No uses --activo y --inactivo al mismo tiempo.", file=sys.stderr)
        return 2

    if not (1 <= args.padding <= 10):
        print("padding debe estar entre 1 y 10.", file=sys.stderr)
        return 2

    activo = True
    if args.inactivo:
        activo = False

    url = f"{args.base_url.rstrip('/')}/api/clients/{args.client_id}/talon-series"

    created = 0
    skipped = 0
    failed = 0

    for item in SERIES:
        folio = (item.get("folio") or "").strip().upper()
        cliente_nombre = (item.get("cliente_nombre") or "").strip() or None
        if not folio:
            continue

        payload = {
            "folio": folio,
            "cliente_nombre": cliente_nombre,
            "padding": args.padding,
            "activo": activo,
        }

        if args.dry_run:
            print(f"[DRY] POST {url} payload={payload}")
            continue

        status, text = http_post_json(url, payload, token=args.token, timeout=args.timeout)

        if status in (200, 201):
            created += 1
            print(f"[OK] {folio} -> creado")
            continue

        if status == 409:
            skipped += 1
            print(f"[SKIP] {folio} -> ya existe (409)")
            continue

        failed += 1
        err = _pretty_error_body(text)
        if status == 0:
            print(f"[FAIL] {folio} -> no conectó / error de red: {err}")
        else:
            print(f"[FAIL] {folio} -> {status}  {err}")

    print("\nResumen:")
    print(f"  creadas : {created}")
    print(f"  skip    : {skipped}")
    print(f"  fallidas: {failed}")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
