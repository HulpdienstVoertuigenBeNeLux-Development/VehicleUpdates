import json
import os
import re
import pandas as pd
import requests
from bs4 import BeautifulSoup

# Standaard NH-90 registraties van de Koninklijke Marine / Luchtmacht
NH90_REGISTRATIES = [
    "N-088", "N-102", "N-110", "N-164", "N-175", "N-195", "N-227", "N-228",
    "N-233", "N-234", "N-258", "N-277", "N-316", "N-317", "N-318", "N-319",
    "N-324", "N-325", "N-326", "N-327"
]

# Standaard sjabloon voor alle niet-ILT toestellen (Kustwacht + NH-90 militaire helikopters)
DEFAULT_CUSTOM_AIRCRAFT = {
    # Canadese Kustwacht toestellen
    "C-FCGE": {
        "registration": "C-FCGE",
        "manufacturer": "DE HAVILLAND CANADA",
        "model": "DHC-8-102",
        "airw_expiry": "",
        "built": "1986",
        "mtom": "15649",
        "hex_code": "C00B21"
    },
    "C-GNDB": {
        "registration": "C-GNDB",
        "manufacturer": "DE HAVILLAND CANADA",
        "model": "DHC-8-102",
        "airw_expiry": "",
        "built": "1986",
        "mtom": "15649",
        "hex_code": ""
    }
}

# Voeg de 20 NH-90 toestellen toe aan het standaard custom sjabloon
for nh_reg in NH90_REGISTRATIES:
    DEFAULT_CUSTOM_AIRCRAFT[nh_reg] = {
        "registration": nh_reg,
        "manufacturer": "NHIndustries",
        "model": "NH90 NFH",
        "airw_expiry": "",
        "built": "",
        "mtom": "11000",
        "hex_code": ""
    }


def haal_nieuwste_ilt_ods_url():
    """Haalt de actuele .ods downloadlink op van de ILT overzichtspagina."""
    pagina_url = "https://www.ilent.nl/documenten/lijsten/luchtvaart/databestanden/luchtvaartregister-data"
    headers = {
        'User-Agent': (
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        )
    }

    print("1. Ophalen van ILT-pagina en zoeken naar de nieuwste .ods link...")
    response = requests.get(pagina_url, headers=headers)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, 'html.parser')

    ods_link = None
    for a in soup.find_all('a', href=True):
        if a['href'].lower().endswith('.ods'):
            ods_link = a['href']
            break

    if not ods_link:
        raise Exception("Geen .ods bestand gevonden op de ILT-pagina.")

    if not ods_link.startswith('http'):
        ods_link = "https://www.ilent.nl" + ods_link

    print(f"   Gevonden bestand: {ods_link.split('/')[-1]}")
    return ods_link


def opschonen_alle_kolomnamen(df):
    """Schoont ALLE kolomnamen op: stript meta-tags en zet om naar snake_case."""
    schone_koppen = {}

    for col in df.columns:
        basis = col.split('[')[0].strip()
        basis = (
            basis.replace('X-Ponder', 'hex_code')
            .replace('CofA (Form24/25)_Iss.', 'cofa_issued')
            .replace('83Bis', '83bis')
        )
        s1 = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', basis)
        snake_naam = re.sub('([a-z0-9])([A-Z])', r'\1_\2', s1).lower()
        snake_naam = re.sub(r'[\s\-\(\)/]+', '_', snake_naam).strip('_')
        schone_koppen[col] = snake_naam

    return df.rename(columns=schone_koppen)


def laad_of_maak_custom_aircraft_data(storage_dir):
    """
    Laadt storage/custom_aircraft.json.
    Als het bestand niet bestaat, maakt het een standaard sjabloon aan inclusief NH-90.
    """
    custom_path = os.path.join(storage_dir, 'custom_aircraft.json')

    if not os.path.exists(custom_path):
        print(f"   Aanmaken standaard custom data bestand in '{custom_path}'...")
        with open(custom_path, 'w', encoding='utf-8') as f:
            json.dump(DEFAULT_CUSTOM_AIRCRAFT, f, ensure_ascii=False, indent=2)
        return DEFAULT_CUSTOM_AIRCRAFT

    try:
        with open(custom_path, 'r', encoding='utf-8') as f:
            print(f"   Custom data geladen uit '{custom_path}'.")
            data = json.load(f)
            # Zorg ervoor dat eventuele ontbrekende NH90-sleutels alsnog aanwezig zijn
            for reg, record in DEFAULT_CUSTOM_AIRCRAFT.items():
                if reg not in data:
                    data[reg] = record
            return data
    except Exception as e:
        print(f"   [Waarschuwing] Kon custom_aircraft.json niet lezen ({e}). Gebruik standaardwaarden.")
        return DEFAULT_CUSTOM_AIRCRAFT


def schonen_bouwjaar(waarde):
    """Zet '2019.0' om naar '2019' en behandeld lege waarden netjes."""
    if pd.isna(waarde) or waarde == "":
        return ""
    s_waarde = str(waarde).strip()
    if s_waarde.endswith('.0'):
        return s_waarde[:-2]
    return s_waarde


def ilt_exporteren_alle_kolommen():
    headers = {
        'User-Agent': (
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        )
    }

    script_dir = os.path.dirname(os.path.abspath(__file__))
    raw_subdir = os.path.join(script_dir, "raw", "ilt_luchtvaartregister")
    storage_dir = os.path.join(script_dir, "storage")

    os.makedirs(raw_subdir, exist_ok=True)
    os.makedirs(storage_dir, exist_ok=True)

    # 1. Vind de nieuwste URL
    ods_url = haal_nieuwste_ilt_ods_url()
    ods_filename = ods_url.split('/')[-1]
    raw_path = os.path.join(raw_subdir, ods_filename)

    # 2. Oude .ods bestanden in de specifieke map opruimen
    print(f"2. Oude .ods bestanden opruimen in '{raw_subdir}'...")
    for file in os.listdir(raw_subdir):
        if file.lower().endswith('.ods'):
            file_path = os.path.join(raw_subdir, file)
            if os.path.isfile(file_path):
                os.remove(file_path)

    # 3. Download ODS
    print(f"3. Downloaden van ODS-databestand naar '{raw_path}'...")
    res = requests.get(ods_url, headers=headers)
    res.raise_for_status()

    with open(raw_path, 'wb') as f:
        f.write(res.content)

    # 4. Inlezen met Pandas via ODF
    print("4. Bestand verwerken met Pandas...")
    df = pd.read_excel(raw_path, engine='odf')

    # 5. Kolommen opschonen
    print("5. Alle kolomnamen opschonen naar snake_case JSON sleutels...")
    df_schoon = opschonen_alle_kolomnamen(df)

    for col in df_schoon.columns:
        if pd.api.types.is_datetime64_any_dtype(df_schoon[col]):
            df_schoon[col] = df_schoon[col].dt.strftime('%Y-%m-%d')

    df_schoon = df_schoon.fillna('')

    # 6. Opslaan van het volledige register in JSON
    json_records = df_schoon.to_dict(orient='records')
    output_filename = 'nederlandse_luchtvaartregister_ilt_alle_kolommen.json'
    storage_path = os.path.join(storage_dir, output_filename)

    with open(storage_path, 'w', encoding='utf-8') as f:
        json.dump(json_records, f, ensure_ascii=False, indent=2, default=str)

    print(f"Volledig register opgeslagen in '{storage_path}'.")

    # 7. Luchtvaartuigen Filterfunctie uitvoeren
    verwerk_hulpdienst_luchtvaartuigen(json_records, storage_dir, headers)


def verwerk_hulpdienst_luchtvaartuigen(ilt_data, storage_dir, headers):
    """
    Haalt hulpdienst-kentekens op en slaat ALLEEN de 7 gespecificeerde velden op.
    Gebruikt 'storage/custom_aircraft.json' voor niet-ILT toestellen (Canada / NH-90).
    """
    print("6. Hulpdienst kentekens ophalen en 7 velden selecteren...")
    hulpdienst_url = "https://raw.githubusercontent.com/HulpdienstVoertuigenBeNeLux/VehicleUpdates/refs/heads/master/raw/hulpdienstvoertuigenbenelux_raw.json"

    response = requests.get(hulpdienst_url, headers=headers)
    response.raise_for_status()
    hulpdienst_data = response.json()

    doel_afkortingen = {'MMTL', 'PAL-RA', 'POL-HELI', 'SAR-HELI', 'KW-VLIEGTUIG'}

    # Laad custom uitzonderingen (Canada + NH-90)
    custom_data = laad_of_maak_custom_aircraft_data(storage_dir)

    # Verzamel doel-kentekens uit de hulpdienst JSON + de NH-90 lijst
    doel_kentekens = {
        str(v.get('Kenteken', '')).strip().upper()
        for v in hulpdienst_data
        if str(v.get('Afkorting', '')).strip().upper() in doel_afkortingen and v.get('Kenteken')
    }
    
    # Voeg ook de NH-90 kentekens toe aan de controle
    for nh_reg in NH90_REGISTRATIES:
        doel_kentekens.add(nh_reg)

    resultaat_records = []

    for kenteken in sorted(doel_kentekens):
        # Zoek in ILT-data (Nederlands civiel register)
        ilt_match = next(
            (rec for rec in ilt_data if str(rec.get('registration', '')).strip().upper() == kenteken),
            None
        )

        if ilt_match:
            gefilterd_record = {
                "registration": ilt_match.get("registration", ""),
                "manufacturer": ilt_match.get("manufacturer", ""),
                "model": ilt_match.get("model", ""),
                "airw_expiry": ilt_match.get("airw_expiry", ""),
                "built": schonen_bouwjaar(ilt_match.get("built", "")),
                "mtom": ilt_match.get("mtom", ""),
                "hex_code": ilt_match.get("hex_code", "")
            }
            resultaat_records.append(gefilterd_record)

        elif kenteken in custom_data:
            print(f"   [Custom Data] Handmatige/Militaire data gebruikt voor: {kenteken}")
            custom_rec = custom_data[kenteken]
            gefilterd_record = {
                "registration": custom_rec.get("registration", kenteken),
                "manufacturer": custom_rec.get("manufacturer", ""),
                "model": custom_rec.get("model", ""),
                "airw_expiry": custom_rec.get("airw_expiry", ""),
                "built": schonen_bouwjaar(custom_rec.get("built", "")),
                "mtom": custom_rec.get("mtom", ""),
                "hex_code": custom_rec.get("hex_code", "")
            }
            resultaat_records.append(gefilterd_record)

        else:
            resultaat_records.append({
                "registration": kenteken,
                "manufacturer": "",
                "model": "",
                "airw_expiry": "",
                "built": "",
                "mtom": "",
                "hex_code": ""
            })

    output_aircraft_path = os.path.join(storage_dir, 'aircraft_data.json')
    with open(output_aircraft_path, 'w', encoding='utf-8') as f:
        json.dump(resultaat_records, f, ensure_ascii=False, indent=2, default=str)

    print(f"Klaar! {len(resultaat_records)} luchtvaartuig-records met 7 velden opgeslagen in '{output_aircraft_path}'.")


if __name__ == '__main__':
    ilt_exporteren_alle_kolommen()
