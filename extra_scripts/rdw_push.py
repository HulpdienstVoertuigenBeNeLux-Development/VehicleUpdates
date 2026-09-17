import json
import os
import time
from typing import Any

import requests

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)

# RDW Voertuigen instellingen
FULL_COMBINED_FILE = os.path.join(PROJECT_ROOT, "storage", "rdw_full_combined.json")
API_URL = "https://hulpdienstvoertuigenbenelux.nl/api/rdw/vehicles"

# Aircraft instellingen
AIRCRAFT_DATA_FILE = os.path.join(PROJECT_ROOT, "storage", "aircraft_data.json")
AIRCRAFT_API_URL = "https://hulpdienstvoertuigenbenelux.nl/api/rdw/vehicles"  # Pas de API URL aan indien nodig

REQUEST_TIMEOUT_SECONDS = 30
RED_COLOR = 15158332
GREEN_COLOR = 3066993
DISCORD_EMBED_DESCRIPTION_LIMIT = 4096


def _strip_url(message: str, url: str) -> str:
    return message.replace(url, "").strip()


# ==========================================
# GENERIEKE DISCORD NOTIFICATIES
# ==========================================

def notify_fetch_failure(error: str, prefix: str = "RDW", target_url: str = API_URL) -> None:
    webhook_url = os.getenv("DISCORD_WEBHOOK_URL_RDW_API_PUSH", "")
    if not webhook_url:
        print(f"Discord notificatie overgeslagen: geen webhook URL ({error})")
        return

    payload = {
        "username": f"HulpdienstVoertuigenBeNeLux {prefix} Push",
        "embeds": [
            {
                "title": f"{prefix} push: ophalen mislukt",
                "description": _strip_url(error, target_url)[:DISCORD_EMBED_DESCRIPTION_LIMIT],
                "color": RED_COLOR,
            }
        ],
    }
    try:
        requests.post(webhook_url, json=payload, timeout=10)
    except requests.RequestException as exc:
        print(f"Discord notificatie mislukt: {exc}")
    finally:
        time.sleep(10)


def notify_push_summary(pushed: int, failures: list[tuple[str, str]], prefix: str = "RDW", target_url: str = API_URL) -> None:
    webhook_url = os.getenv("DISCORD_WEBHOOK_URL_RDW_API_PUSH", "")
    if not webhook_url:
        print(f"Discord {prefix} sync samenvatting overgeslagen: geen webhook URL")
        return

    summary_line = f"Gepusht: {pushed}, mislukt: {len(failures)}"
    failure_lines = [
        f"- {identifier}: {_strip_url(error, target_url)}"[:DISCORD_EMBED_DESCRIPTION_LIMIT]
        for identifier, error in failures
    ]

    descriptions = [summary_line]
    for line in failure_lines:
        candidate = f"{descriptions[-1]}\n{line}"
        if len(candidate) <= DISCORD_EMBED_DESCRIPTION_LIMIT:
            descriptions[-1] = candidate
        else:
            descriptions.append(line)

    for index, description in enumerate(descriptions, start=1):
        title = f"{prefix} push sync voltooid" if index == 1 else f"{prefix} push sync voltooid (vervolg {index})"
        payload = {
            "username": f"HulpdienstVoertuigenBeNeLux {prefix} Push",
            "embeds": [
                {
                    "title": title,
                    "description": description,
                    "color": GREEN_COLOR if not failures else RED_COLOR,
                }
            ],
        }
        try:
            requests.post(webhook_url, json=payload, timeout=10)
        except requests.RequestException as exc:
            print(f"Discord sync samenvatting mislukt: {exc}")
        finally:
            time.sleep(10)


def _normalize_value(value: Any) -> Any:
    # Normalisatie voor zowel nummers als lege strings/nulls
    if value is None or (isinstance(value, str) and value.strip().lower() in ("null", "")):
        return None
    if not isinstance(value, bool) and isinstance(value, (int, float, str)) and str(value).strip() == "0":
        return None
    return value


# ==========================================
# RDW VOERTUIGEN LOGICA
# ==========================================

def fetch_vehicles() -> list:
    last_error: Exception | None = None
    for attempt in range(1, 3):
        try:
            response = requests.get(API_URL, timeout=REQUEST_TIMEOUT_SECONDS)
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, requests.exceptions.JSONDecodeError) as exc:
            last_error = exc
            print(f"Ophalen mislukt (poging {attempt}/2): {exc}")

    raise RuntimeError(f"Ophalen van {API_URL} definitief mislukt: {last_error}") from last_error


def push_vehicle(record: dict[str, Any]) -> None:
    api_key = os.getenv("HVNBL_RDW_API_KEY", "")
    headers = {"X-RDW-API-Key": api_key}
    response = requests.post(API_URL, headers=headers, json=record, timeout=REQUEST_TIMEOUT_SECONDS)
    response.raise_for_status()


def load_full_combined() -> list:
    with open(FULL_COMBINED_FILE, encoding="utf-8") as infile:
        return json.load(infile)


def _normalize_kenteken(value: Any) -> str:
    return str(value or "").strip().upper()


def _kentekens_by_record(records: list) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for record in records:
        if not isinstance(record, dict):
            continue
        kenteken = _normalize_kenteken(record.get("kenteken"))
        if kenteken:
            result[kenteken] = record
    return result


def compare_with_full_combined(vehicles: list) -> None:
    api_by_kenteken = _kentekens_by_record(vehicles)
    combined_by_kenteken = _kentekens_by_record(load_full_combined())

    shared = set(api_by_kenteken) & set(combined_by_kenteken)
    only_in_combined = set(combined_by_kenteken) - set(api_by_kenteken)
    only_in_api = set(api_by_kenteken) - set(combined_by_kenteken)

    same = 0
    different_kentekens: set[str] = set()
    diffs_by_kenteken: dict[str, set[str]] = {}
    for kenteken in shared:
        api_record = api_by_kenteken[kenteken]
        combined_record = combined_by_kenteken[kenteken]
        changed_keys = {
            key for key in set(api_record) | set(combined_record)
            if _normalize_value(api_record.get(key)) != _normalize_value(combined_record.get(key))
        }
        if changed_keys:
            different_kentekens.add(kenteken)
            diffs_by_kenteken[kenteken] = changed_keys
        else:
            same += 1

    print(f"\n--- RDW VOERTUIGEN SUMMARY ---")
    print(f"Zelfde in beide: {same}")
    print(f"Verschillend (zelfde kenteken, andere waarden): {len(different_kentekens)}")
    print(f"Alleen in full combined (niet in API): {len(only_in_combined)}")
    print(f"Alleen in API (niet in full combined): {len(only_in_api)}")

    for kenteken in sorted(different_kentekens):
        api_record = api_by_kenteken[kenteken]
        combined_record = combined_by_kenteken[kenteken]
        print(f"Verschil voor {combined_record.get('kenteken')}:")
        for key in sorted(diffs_by_kenteken[kenteken]):
            api_value = api_record.get(key)
            combined_value = combined_record.get(key)
            api_display = json.dumps("null" if api_value is None else api_value, ensure_ascii=False)
            combined_display = json.dumps("null" if combined_value is None else combined_value, ensure_ascii=False)
            print(f"  {key}: API={api_display} FullCombined={combined_display}")

    pushed = 0
    failures: list[tuple[str, str]] = []
    for kenteken in only_in_combined | different_kentekens:
        record = combined_by_kenteken[kenteken]
        try:
            push_vehicle(record)
            print(f"Gepusht naar API: {record.get('kenteken')}")
            pushed += 1
        except requests.RequestException as exc:
            print(f"Push mislukt voor {record.get('kenteken')}: {exc}")
            failures.append((str(record.get("kenteken")), str(exc)))

    if pushed + len(failures) > 0:
        notify_push_summary(pushed, failures, prefix="RDW Voertuigen", target_url=API_URL)


# ==========================================
# AIRCRAFT LOGICA
# ==========================================

def fetch_aircraft() -> list:
    last_error: Exception | None = None
    for attempt in range(1, 3):
        try:
            response = requests.get(AIRCRAFT_API_URL, timeout=REQUEST_TIMEOUT_SECONDS)
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, requests.exceptions.JSONDecodeError) as exc:
            last_error = exc
            print(f"Vliegtuigen ophalen mislukt (poging {attempt}/2): {exc}")

    raise RuntimeError(f"Ophalen van {AIRCRAFT_API_URL} definitief mislukt: {last_error}") from last_error


def push_aircraft(record: dict[str, Any]) -> None:
    api_key = os.getenv("HVNBL_RDW_API_KEY", "")
    headers = {"X-RDW-API-Key": api_key}
    response = requests.post(AIRCRAFT_API_URL, headers=headers, json=record, timeout=REQUEST_TIMEOUT_SECONDS)
    response.raise_for_status()


def load_aircraft_data() -> list:
    with open(AIRCRAFT_DATA_FILE, encoding="utf-8") as infile:
        return json.load(infile)


def _normalize_registration(value: Any) -> str:
    return str(value or "").strip().upper()


def _registrations_by_record(records: list) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for record in records:
        if not isinstance(record, dict):
            continue
        reg = _normalize_registration(record.get("registration"))
        if reg:
            result[reg] = record
    return result


def compare_aircraft_with_data(api_aircraft: list) -> None:
    api_by_reg = _registrations_by_record(api_aircraft)
    file_by_reg = _registrations_by_record(load_aircraft_data())

    shared = set(api_by_reg) & set(file_by_reg)
    only_in_file = set(file_by_reg) - set(api_by_reg)
    only_in_api = set(api_by_reg) - set(file_by_reg)

    same = 0
    different_regs: set[str] = set()
    diffs_by_reg: dict[str, set[str]] = {}
    for reg in shared:
        api_record = api_by_reg[reg]
        file_record = file_by_reg[reg]
        changed_keys = {
            key for key in set(api_record) | set(file_record)
            if _normalize_value(api_record.get(key)) != _normalize_value(file_record.get(key))
        }
        if changed_keys:
            different_regs.add(reg)
            diffs_by_reg[reg] = changed_keys
        else:
            same += 1

    print(f"\n--- AIRCRAFT SUMMARY ---")
    print(f"Zelfde in beide: {same}")
    print(f"Verschillend (zelfde registratie, andere waarden): {len(different_regs)}")
    print(f"Alleen in bestand (niet in API): {len(only_in_file)}")
    print(f"Alleen in API (niet in bestand): {len(only_in_api)}")

    for reg in sorted(different_regs):
        api_record = api_by_reg[reg]
        file_record = file_by_reg[reg]
        print(f"Verschil voor {file_record.get('registration')}:")
        for key in sorted(diffs_by_reg[reg]):
            api_value = api_record.get(key)
            file_value = file_record.get(key)
            api_display = json.dumps("null" if api_value is None else api_value, ensure_ascii=False)
            file_display = json.dumps("null" if file_value is None else file_value, ensure_ascii=False)
            print(f"  {key}: API={api_display} File={file_display}")

    pushed = 0
    failures: list[tuple[str, str]] = []
    for reg in only_in_file | different_regs:
        record = file_by_reg[reg]
        try:
            push_aircraft(record)
            print(f"Gepusht naar API: {record.get('registration')}")
            pushed += 1
        except requests.RequestException as exc:
            print(f"Push mislukt voor {record.get('registration')}: {exc}")
            failures.append((str(record.get("registration")), str(exc)))

    if pushed + len(failures) > 0:
        notify_push_summary(pushed, failures, prefix="Aircraft", target_url=AIRCRAFT_API_URL)


# ==========================================
# RUN PROCESS
# ==========================================

def run_rdw_vehicles() -> None:
    try:
        vehicles = fetch_vehicles()
    except RuntimeError as exc:
        print(str(exc))
        notify_fetch_failure(str(exc), prefix="RDW Voertuigen", target_url=API_URL)
        return

    print(f"Opgehaald: {len(vehicles)} voertuigen van {API_URL}")
    if not vehicles:
        message = f"Lege lijst ontvangen van {API_URL}, sync overgeslagen (niets gepusht)."
        print(message)
        notify_fetch_failure(message, prefix="RDW Voertuigen", target_url=API_URL)
        return
    compare_with_full_combined(vehicles)


def run_aircraft() -> None:
    try:
        aircraft = fetch_aircraft()
    except RuntimeError as exc:
        print(str(exc))
        notify_fetch_failure(str(exc), prefix="Aircraft", target_url=AIRCRAFT_API_URL)
        return

    print(f"Opgehaald: {len(aircraft)} vliegtuigen van {AIRCRAFT_API_URL}")
    if not aircraft:
        message = f"Lege lijst ontvangen van {AIRCRAFT_API_URL}, sync overgeslagen (niets gepusht)."
        print(message)
        notify_fetch_failure(message, prefix="Aircraft", target_url=AIRCRAFT_API_URL)
        return
    compare_aircraft_with_data(aircraft)


def run() -> None:
    print(">>> Starten RDW Voertuigen sync...")
    run_rdw_vehicles()

    print("\n>>> Starten Aircraft sync...")
    run_aircraft()


if __name__ == "__main__":
    run()
