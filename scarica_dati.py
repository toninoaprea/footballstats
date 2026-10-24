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
import re
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

# ---- CAMPIONATI "EXTRA" di football-data.co.uk (stagione solare, solo risultati finali) ----
# un file per nazione con tutte le stagioni: colonne Season, Date, Home, Away, HG, AG
EXTRA = {"NO1": "https://www.football-data.co.uk/new/NOR.csv",    # Norvegia Eliteserien
         "SW1": "https://www.football-data.co.uk/new/SWZ.csv"}    # Svizzera Super League
for codice, url in EXTRA.items():
    try:
        testo = scarica(url, limite=90)
        blocchi = {}
        for riga in csv.DictReader(io.StringIO(testo)):
            casa, trasf = (riga.get("Home") or "").strip(), (riga.get("Away") or "").strip()
            gc, gt = numero(riga.get("HG")), numero(riga.get("AG"))
            stag = (riga.get("Season") or "").strip()[-4:]
            if not casa or not trasf or gc is None or gt is None or not stag.isdigit():
                continue
            if int(stag) < oggi.year - 3:          # bastano le ultime stagioni
                continue
            b = blocchi.setdefault(stag, {"teams": [], "rows": []})
            for sq in (casa, trasf):
                if sq not in b["teams"]:
                    b["teams"].append(sq)
            valori = {"FTHG": gc, "FTAG": gt}
            b["rows"].append([data_iso(riga["Date"]), b["teams"].index(casa), b["teams"].index(trasf)]
                             + [valori.get(c) for c in COLONNE])
        if not blocchi:
            raise ValueError("nessuna partita trovata")
        dati[codice] = blocchi
        print("OK  ", codice, {k: len(v["rows"]) for k, v in sorted(blocchi.items())}, flush=True)
    except Exception as e:
        print("ERR ", codice, e, flush=True)
        if codice in vecchio:
            dati[codice] = vecchio[codice]
            print("    ", codice, "uso la copia precedente")

# ---- CAMPIONATI CARICATI A MANO (cartella manuali/) ----
# Metti nella cartella "manuali" i file CSV delle partite. Il nome del file dice il campionato:
#   I3A_qualcosa.csv = Serie C Girone A   I3B_... = Girone B   I3C_... = Girone C   B2_... = Challenger Pro League
#   NO2_... = Norvegia OBOS-ligaen   EN_... = National League North   ES_... = National League South
#   IS1_... = Islanda Besta deild    N2_... = Olanda Eerste Divisie
#   NO1_... / SW1_... = Norvegia / Svizzera: se carichi il CSV, sostituisce la fonte automatica (che ha solo i risultati finali)
# Vanno bene i CSV di football-data.co.uk e quelli "matches" di FootyStats.
# Se ricarichi un file aggiornato, le partite già presenti vengono sostituite (niente doppioni).
MANUALI = {"I3A": "Serie C Girone A", "I3B": "Serie C Girone B", "I3C": "Serie C Girone C", "B2": "Challenger Pro League",
           "NO2": "Norvegia OBOS-ligaen", "EN": "National League North", "ES": "National League South",
           "IS1": "Islanda Besta deild", "N2": "Olanda Eerste Divisie",
           "NO1": "Norvegia Eliteserien", "SW1": "Svizzera Super League"}
STAGIONE_SOLARE = {"NO1", "NO2", "IS1"}   # campionati che si giocano nell'anno solare (marzo-novembre)
# stesse colonne del robot, con i nomi usati da FootyStats
SINONIMI = {
    "HomeTeam": ["HomeTeam", "home_team_name"], "AwayTeam": ["AwayTeam", "away_team_name"],
    "FTHG": ["FTHG", "home_team_goal_count"], "FTAG": ["FTAG", "away_team_goal_count"],
    "HTHG": ["HTHG", "home_team_goal_count_half_time"], "HTAG": ["HTAG", "away_team_goal_count_half_time"],
    "HS": ["HS", "home_team_shots"], "AS": ["AS", "away_team_shots"],
    "HST": ["HST", "home_team_shots_on_target"], "AST": ["AST", "away_team_shots_on_target"],
    "HF": ["HF", "home_team_fouls"], "AF": ["AF", "away_team_fouls"],
    "HC": ["HC", "home_team_corner_count"], "AC": ["AC", "away_team_corner_count"],
    "HY": ["HY", "home_team_yellow_cards"], "AY": ["AY", "away_team_yellow_cards"],
    "HR": ["HR", "home_team_red_cards"], "AR": ["AR", "away_team_red_cards"],
}
MESI = {m: i + 1 for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}


def data_manuale(riga):
    ts = (riga.get("timestamp") or "").strip()
    if ts.isdigit():
        return datetime.datetime.fromtimestamp(int(ts), datetime.timezone.utc).strftime("%Y-%m-%d")
    d = (riga.get("date_GMT") or riga.get("Date") or "").strip()
    if not d:
        return None
    if d[:3].lower() in MESI:                      # FootyStats: "Aug 23 2025 - 6:30pm"
        p = d.replace("-", " ").split()
        return f"{int(p[2]):04d}-{MESI[p[0][:3].lower()]:02d}-{int(p[1]):02d}"
    return data_iso(d)


def stagione_di(d):
    y, m = int(d[:4]), int(d[5:7])
    a = y if m >= 7 else y - 1
    return f"{a % 100:02d}{(a + 1) % 100:02d}"


def chiave(nome):
    """Nome semplificato per far combaciare fonti diverse: 'US Salernitana 1919' -> 'salernitana'."""
    parole = re.sub(r"[^a-z0-9 ]", " ", nome.lower()).split()
    togli = {"fc", "ac", "as", "us", "ss", "ssc", "ssd", "asd", "calcio", "cf", "sc", "afc", "kv", "kfc", "rsc", "sk",
             "fk", "il", "bk", "if", "ik", "ff", "aif", "sv", "vv", "bc", "cd", "ud", "rc", "kaa", "krc", "rfc", "umf", "ia"}
    return "".join(p for p in parole if p not in togli and not re.fullmatch(r"(18|19|20)\d\d", p))


# nomi di squadra già noti (per far combaciare per es. una squadra passata dalla Serie B alla C)
NOMI_NOTI = {chiave(t): t for blocchi in dati.values() for b in blocchi.values() for t in b["teams"]}

manuali = {}
calendario = {}   # (codice, data, casa, trasferta) -> orario  — partite ancora da giocare
oggi_iso = oggi.isoformat()
for percorso in sorted(glob.glob(os.path.join("manuali", "*.csv"))):
    nome_file = os.path.basename(percorso)
    codice = nome_file.split("_")[0].split(".")[0].upper()
    if codice not in MANUALI:
        print("SALTO", nome_file, "- il nome deve iniziare con", ", ".join(MANUALI))
        continue
    with open(percorso, encoding="utf-8-sig", errors="replace") as f:
        righe_csv = list(csv.DictReader(f))
    if not righe_csv:
        continue
    intest = righe_csv[0].keys()
    col = {k: next((x for x in v if x in intest), None) for k, v in SINONIMI.items()}
    if not col["HomeTeam"] or not col["FTHG"]:
        print("SALTO", nome_file, "- non trovo le colonne delle squadre o dei gol")
        continue
    n = 0
    for riga in righe_csv:
        try:
            d = data_manuale(riga)
        except Exception:
            d = None
        casa, trasf = (riga.get(col["HomeTeam"]) or "").strip(), (riga.get(col["AwayTeam"]) or "").strip()
        if not d or not casa or not trasf:
            continue
        casa, trasf = NOMI_NOTI.get(chiave(casa), casa), NOMI_NOTI.get(chiave(trasf), trasf)
        NOMI_NOTI.setdefault(chiave(casa), casa)
        NOMI_NOTI.setdefault(chiave(trasf), trasf)
        if (riga.get("status") or "complete").strip().lower() not in ("complete", "completed", "ft"):
            if d >= oggi_iso:                      # partita ancora da giocare: va nel calendario
                calendario[(codice, d, casa, trasf)] = ""
            continue
        if numero(riga.get(col["FTHG"])) is None:
            continue
        valori = []
        for c in COLONNE:
            v = numero(riga.get(col[c])) if col.get(c) else None
            valori.append(None if v is not None and v < 0 else v)   # FootyStats usa -1 per "dato mancante"
        manuali[(codice, d, casa, trasf)] = valori   # stessa partita in due file: vince l'ultimo
        n += 1
    print("OK   manuale", nome_file, "→", MANUALI[codice], n, "partite")

for codice in {k[0] for k in manuali} & set(EXTRA):
    dati.pop(codice, None)        # c'è il CSV completo: la fonte automatica (solo risultati) non serve
    print("     ", codice, "uso il CSV caricato a mano al posto della fonte automatica")
for (codice, d, casa, trasf), valori in sorted(manuali.items(), key=lambda x: x[0][1]):
    stag = d[:4] if codice in STAGIONE_SOLARE else stagione_di(d)
    b = dati.setdefault(codice, {}).setdefault(stag, {"teams": [], "rows": []})
    for sq in (casa, trasf):
        if sq not in b["teams"]:
            b["teams"].append(sq)
    b["rows"].append([d, b["teams"].index(casa), b["teams"].index(trasf)] + valori)

# ---- CALENDARIO: prossime partite (football-data.co.uk) ----
# fixtures.csv = campionati principali; new_league_fixtures.csv = campionati "extra" (es. Norvegia)
PAESI_EXTRA = {"Norway": "NO1", "Switzerland": "SW1"}
NOMI_SQUADRE = {t for blocchi in dati.values() for b in blocchi.values() for t in b["teams"]}
for url in ["https://www.football-data.co.uk/fixtures.csv", "https://www.football-data.co.uk/new_league_fixtures.csv"]:
    try:
        testo = scarica(url)
        n = 0
        for riga in csv.DictReader(io.StringIO(testo)):
            codice = (riga.get("Div") or "").strip() or PAESI_EXTRA.get((riga.get("Country") or "").strip(), "")
            if codice not in dati:
                continue
            casa = (riga.get("HomeTeam") or riga.get("Home") or "").strip()
            trasf = (riga.get("AwayTeam") or riga.get("Away") or "").strip()
            if not casa or not trasf or not riga.get("Date"):
                continue
            d = data_iso(riga["Date"])
            if d < oggi_iso:
                continue
            if casa not in NOMI_SQUADRE:
                casa = NOMI_NOTI.get(chiave(casa), casa)
            if trasf not in NOMI_SQUADRE:
                trasf = NOMI_NOTI.get(chiave(trasf), trasf)
            calendario[(codice, d, casa, trasf)] = (riga.get("Time") or "").strip()
            n += 1
        print("OK   calendario", url.rsplit("/", 1)[1], n, "partite", flush=True)
    except Exception as e:
        print("ERR  calendario", url.rsplit("/", 1)[1], e, flush=True)
prossime = [[d, ora, codice, casa, trasf] for (codice, d, casa, trasf), ora in calendario.items()]
prossime.sort(key=lambda p: (p[0], p[1], p[2]))
print("Calendario:", len(prossime), "partite in programma")

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
               "cols": COLONNE, "data": dati, "fixtures": prossime}, f, separators=(",", ":"), ensure_ascii=False)

# elimina i vecchi file CSV della prima versione
for vecchio_csv in glob.glob(os.path.join("data", "*.csv")) + [os.path.join("data", "meta.json")]:
    if os.path.exists(vecchio_csv):
        os.remove(vecchio_csv)

print("Salvato", FILE_OUT, round(os.path.getsize(FILE_OUT) / 1024), "KB")
