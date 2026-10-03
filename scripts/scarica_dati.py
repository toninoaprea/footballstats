"""
Robot di aggiornamento per footballstats.
Scarica i risultati da football-data.co.uk, tiene solo le colonne che servono
e salva tutto in un unico file compatto: data/partite.json (letto dal sito).
Viene eseguito automaticamente da GitHub Actions (.github/workflows/aggiorna-dati.yml).
"""
import csv
import datetime
import glob
import io
import json
import os
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

# ---- CAMPIONATI da scaricare (codici football-data.co.uk) ----
CAMPIONATI = [
    "I1", "I2",                    # Serie A, Serie B
    "E0", "E1", "E2", "E3", "EC",  # Premier, Championship, League One, League Two, National League
    "SC0", "SC1", "SC2", "SC3",    # Scozia
    "SP1", "SP2",                  # Liga, Segunda
    "D1", "D2",                    # Bundesliga, 2. Bundesliga
    "F1", "F2",                    # Ligue 1, Ligue 2
    "N1", "B1", "P1", "T1", "G1",  # Olanda, Belgio, Portogallo, Turchia, Grecia
]

# ---- COLONNE da tenere (per aggiungere una statistica basta aggiungere qui il nome) ----
# FTHG/FTAG gol finali, HTHG/HTAG gol primo tempo, HS/AS tiri, HST/AST tiri in porta,
# HF/AF falli, HC/AC angoli, HY/AY ammonizioni, HR/AR espulsioni
COLONNE = ["FTHG", "FTAG", "HTHG", "HTAG", "HS", "AS", "HST", "AST",
           "HF", "AF", "HC", "AC", "HY", "AY", "HR", "AR"]

N_STAGIONI = 4  # bastano per coprire le ultime 100 partite di ogni squadra
FILE_OUT = os.path.join("data", "partite.json")

oggi = datetime.date.today()
anno_inizio = oggi.year if oggi.month >= 7 else oggi.year - 1
stagioni = [f"{(a % 100):02d}{((a + 1) % 100):02d}"
            for a in range(anno_inizio - N_STAGIONI + 1, anno_inizio + 1)]

# dati della volta precedente: se un download fallisce si tiene la copia vecchia
vecchio = {}
if os.path.exists(FILE_OUT):
    try:
        with open(FILE_OUT, encoding="utf-8") as f:
            v = json.load(f)
        if v.get("cols") == COLONNE:
            vecchio = v.get("data", {})
    except Exception:
        pass


def data_iso(d):
    d = d.strip()
    if "-" in d:
        return d
    g, m, y = d.split("/")
    if len(y) == 2:
        y = "20" + y
    return f"{y}-{int(m):02d}-{int(g):02d}"


def numero(v):
    v = (v or "").strip()
    if v == "":
        return None
    try:
        return int(float(v))
    except ValueError:
        return None


def scarica(url, limite=60):
    """Scarica un file; rinuncia se il server è troppo lento (oltre `limite` secondi)."""
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    inizio = time.time()
    parti = []
    with urllib.request.urlopen(req, timeout=20) as r:
        while True:
            if time.time() - inizio > limite:
                raise TimeoutError(f"troppo lento (oltre {limite} secondi)")
            pezzo = r.read(65536)
            if not pezzo:
                break
            parti.append(pezzo)
    return b"".join(parti).decode("utf-8-sig", errors="replace")


def scarica_campionato(lavoro):
    camp, stag = lavoro
    url = f"https://www.football-data.co.uk/mmz4281/{stag}/{camp}.csv"
    try:
        testo = scarica(url)
        squadre, righe = [], []
        for riga in csv.DictReader(io.StringIO(testo)):
            casa, trasf = (riga.get("HomeTeam") or "").strip(), (riga.get("AwayTeam") or "").strip()
            if not casa or not trasf or numero(riga.get("FTHG")) is None:
                continue
            try:
                d = data_iso(riga["Date"])
            except Exception:
                continue
            for s in (casa, trasf):
                if s not in squadre:
                    squadre.append(s)
            righe.append([d, squadre.index(casa), squadre.index(trasf)]
                         + [numero(riga.get(c)) for c in COLONNE])
        if righe:
            print("OK  ", camp, stag, len(righe), "partite", flush=True)
            return camp, stag, {"teams": squadre, "rows": righe}
        print("--  ", camp, stag, "nessuna partita", flush=True)
    except Exception as e:
        print("ERR ", camp, stag, e, flush=True)
    return camp, stag, None


dati = {}
lavori = [(c, s) for c in CAMPIONATI for s in stagioni]
print("Scarico", len(lavori), "file…", flush=True)
with ThreadPoolExecutor(max_workers=6) as pool:     # 6 download alla volta
    risultati = list(pool.map(scarica_campionato, lavori))
for camp, stag, blocco in risultati:
    if blocco is None and stag in vecchio.get(camp, {}):
        blocco = vecchio[camp][stag]
        print("    ", camp, stag, "uso la copia precedente")
    if blocco:
        dati.setdefault(camp, {})[stag] = blocco

# ---- NAZIONALI (solo risultati finali) ----
# archivio pubblico di tutte le partite internazionali: github.com/martj42/international_results
URL_NAZ = "https://raw.githubusercontent.com/martj42/international_results/master/results.csv"
NOMI_IT = {
    "Italy": "Italia", "Spain": "Spagna", "Germany": "Germania", "France": "Francia", "England": "Inghilterra",
    "Netherlands": "Olanda", "Portugal": "Portogallo", "Belgium": "Belgio", "Brazil": "Brasile",
    "Croatia": "Croazia", "Switzerland": "Svizzera", "Scotland": "Scozia", "Wales": "Galles",
    "Denmark": "Danimarca", "Sweden": "Svezia", "Norway": "Norvegia", "Poland": "Polonia",
    "Turkey": "Turchia", "Greece": "Grecia", "United States": "Stati Uniti", "Mexico": "Messico",
    "Japan": "Giappone", "Morocco": "Marocco", "Ukraine": "Ucraina", "Czech Republic": "Rep. Ceca",
    "Hungary": "Ungheria", "Republic of Ireland": "Irlanda", "Northern Ireland": "Irlanda del Nord",
    "Egypt": "Egitto", "South Korea": "Corea del Sud", "Slovakia": "Slovacchia", "Slovenia": "Slovenia",
    "Albania": "Albania", "Finland": "Finlandia", "Iceland": "Islanda", "Bosnia and Herzegovina": "Bosnia",
    "North Macedonia": "Macedonia del Nord", "Bulgaria": "Bulgaria", "Georgia": "Georgia",
    "Saudi Arabia": "Arabia Saudita", "South Africa": "Sudafrica", "Ivory Coast": "Costa d'Avorio",
    "Cameroon": "Camerun", "Algeria": "Algeria", "Tunisia": "Tunisia", "Ecuador": "Ecuador",
    "Paraguay": "Paraguay", "Peru": "Perù", "Chile": "Cile", "Israel": "Israele", "Luxembourg": "Lussemburgo",
    "Cyprus": "Cipro", "Estonia": "Estonia", "Latvia": "Lettonia", "Lithuania": "Lituania",
    "Belarus": "Bielorussia", "Moldova": "Moldavia", "Armenia": "Armenia", "Azerbaijan": "Azerbaigian",
    "Kazakhstan": "Kazakistan", "Malta": "Malta", "San Marino": "San Marino", "Faroe Islands": "Far Oer",
    "Montenegro": "Montenegro", "Kosovo": "Kosovo", "Romania": "Romania", "Serbia": "Serbia",
    "Austria": "Austria", "Russia": "Russia", "Australia": "Australia", "Canada": "Canada", "Iran": "Iran",
    "Qatar": "Qatar", "China PR": "Cina", "New Zealand": "Nuova Zelanda", "Colombia": "Colombia",
    "Uruguay": "Uruguay", "Argentina": "Argentina", "Senegal": "Senegal", "Nigeria": "Nigeria", "Ghana": "Ghana",
}
TORNEI_IT = {
    "Friendly": "Amichevole", "FIFA World Cup": "Mondiali", "FIFA World Cup qualification": "Qual. Mondiali",
    "UEFA Euro": "Europei", "UEFA Euro qualification": "Qual. Europei", "UEFA Nations League": "Nations League",
    "Copa América": "Copa América", "African Cup of Nations": "Coppa d'Africa",
}
PARTITE_PER_SQUADRA = 100
DAL_ANNO = "2012"  # le partite più vecchie non servono (100 partite = circa 10 anni per una nazionale)
try:
    testo = scarica(URL_NAZ, limite=120)
    partite = []
    for riga in csv.DictReader(io.StringIO(testo)):
        gc, gt = numero(riga.get("home_score")), numero(riga.get("away_score"))
        if gc is None or gt is None or riga["date"] < DAL_ANNO:
            continue
        casa = NOMI_IT.get(riga["home_team"], riga["home_team"])
        trasf = NOMI_IT.get(riga["away_team"], riga["away_team"])
        partite.append((riga["date"], casa, trasf, gc, gt, TORNEI_IT.get(riga["tournament"], riga["tournament"])))
    partite.sort(key=lambda p: p[0], reverse=True)
    # tiene solo le partite che rientrano nelle ultime 100 di almeno una delle due nazionali
    conta, tenute = {}, []
    for p in partite:
        if conta.get(p[1], 0) < PARTITE_PER_SQUADRA or conta.get(p[2], 0) < PARTITE_PER_SQUADRA:
            tenute.append(p)
        conta[p[1]] = conta.get(p[1], 0) + 1
        conta[p[2]] = conta.get(p[2], 0) + 1
    squadre, tornei, righe = [], [], []
    for d, casa, trasf, gc, gt, torneo in tenute:
        for s in (casa, trasf):
            if s not in squadre:
                squadre.append(s)
        if torneo not in tornei:
            tornei.append(torneo)
        # formato corto: data, casa, trasferta, gol casa, gol trasferta, torneo
        righe.append([d, squadre.index(casa), squadre.index(trasf), gc, gt, tornei.index(torneo)])
    dati["NAZ"] = {"tutte": {"mini": True, "teams": squadre, "tour": tornei, "rows": righe}}
    print("OK   Nazionali", len(righe), "partite")
except Exception as e:
    print("ERR  Nazionali", e)
    if "NAZ" in vecchio:
        dati["NAZ"] = vecchio["NAZ"]
        print("     Nazionali: uso la copia precedente")

os.makedirs("data", exist_ok=True)
with open(FILE_OUT, "w", encoding="utf-8") as f:
    json.dump({"updated": datetime.datetime.now(datetime.timezone.utc).isoformat(),
               "cols": COLONNE, "data": dati}, f, separators=(",", ":"), ensure_ascii=False)

# elimina i vecchi file CSV della prima versione
for vecchio_csv in glob.glob(os.path.join("data", "*.csv")) + [os.path.join("data", "meta.json")]:
    if os.path.exists(vecchio_csv):
        os.remove(vecchio_csv)

print("Salvato", FILE_OUT, round(os.path.getsize(FILE_OUT) / 1024), "KB")
