"""
Scarica i risultati da football-data.co.uk (gol, primo tempo, ammonizioni, espulsioni)
e li salva nella cartella data/ del repository, insieme a data/meta.json.
Viene eseguito automaticamente da GitHub Actions (vedi .github/workflows/aggiorna-dati.yml).
"""
import datetime
import json
import os
import urllib.request

# codici football-data.co.uk dei campionati da scaricare
CAMPIONATI = ["I1", "E0", "SP1", "D1", "F1", "P1", "N1"]
N_STAGIONI = 4  # bastano per coprire le ultime 100 partite di ogni squadra

oggi = datetime.date.today()
anno_inizio = oggi.year if oggi.month >= 7 else oggi.year - 1
stagioni = [f"{(a % 100):02d}{((a + 1) % 100):02d}" for a in range(anno_inizio - N_STAGIONI + 1, anno_inizio + 1)]

os.makedirs("data", exist_ok=True)
files = []
for stag in stagioni:
    for camp in CAMPIONATI:
        url = f"https://www.football-data.co.uk/mmz4281/{stag}/{camp}.csv"
        nome = f"{camp}_{stag}.csv"
        percorso = os.path.join("data", nome)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                testo = r.read().decode("utf-8-sig", errors="replace")
            if testo.count("\n") > 1:
                with open(percorso, "w", encoding="utf-8") as f:
                    f.write(testo)
                print("OK  ", nome)
        except Exception as e:
            print("ERR ", nome, e)
        if os.path.exists(percorso):  # tiene la copia precedente se il download fallisce
            files.append({"code": camp, "season": stag, "file": nome})

with open(os.path.join("data", "meta.json"), "w", encoding="utf-8") as f:
    json.dump({"updated": datetime.datetime.utcnow().isoformat() + "Z", "files": files}, f, indent=1)
print(len(files), "file pronti")
