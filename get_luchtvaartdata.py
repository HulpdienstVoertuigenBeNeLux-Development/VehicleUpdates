import io
import json
import os
import re
import pandas as pd
import requests
from bs4 import BeautifulSoup


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


def ilt_exporteren_alle_kolommen():
    headers = {
        'User-Agent': (
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        )
    }

    # Bepaal het absolute pad van de map waarin DIT script staat
    script_dir = os.path.dirname(os.path.abspath(__file__))

    # Maak relatieve paden aan binnen het project
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
                print(f"   Oud bestand verwijderd: {file}")

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

    # 6. Opslaan in JSON
    json_records = df_schoon.to_dict(orient='records')
    output_filename = 'nederlandse_luchtvaartregister_ilt_alle_kolommen.json'
    storage_path = os.path.join(storage_dir, output_filename)

    with open(storage_path, 'w', encoding='utf-8') as f:
        json.dump(json_records, f, ensure_ascii=False, indent=2, default=str)

    print(
        f"\nKlaar! {len(json_records)} records opgeslagen met ALLE"
        f" ({len(df_schoon.columns)}) kolommen in:\n'{storage_path}'"
    )


if __name__ == '__main__':
    ilt_exporteren_alle_kolommen()
