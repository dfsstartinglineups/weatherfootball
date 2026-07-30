import os
import json
import re
import time
import requests
import datetime
import unicodedata
from datetime import timedelta, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

# Optional zoneinfo import for Python 3.9+
try:
    import zoneinfo
    HAS_ZONEINFO = True
except ImportError:
    HAS_ZONEINFO = False

# ==========================================
# AUTOMATIC ROOT DIRECTORY ANCHOR
# ==========================================
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))
os.chdir(ROOT_DIR)  # Forces working directory to repository root

# ==========================================
# CONFIGURATION & CONSTANTS
# ==========================================
SITE_DOMAIN = "https://weatherfootball.com"
STADIUMS_FILE = os.path.join("data", "stadiums.json")
MASTER_REGISTRY_FILE = os.path.join("data", "master_registry.json")
CORE_LEAGUES_URL = "https://sports.core.api.espn.com/v2/sports/soccer/leagues?limit=1000"

# HTTP Session with retry capabilities
HTTP = requests.Session()

KNOWN_LEAGUE_PILLS = {
    "english premier league": "eng.1",
    "english league championship": "eng.2",
    "english league one": "eng.3",
    "english league two": "eng.4",
    "english fa cup": "eng.fa",
    "english carabao cup": "eng.league_cup",
    "spanish laliga": "esp.1",
    "spanish laliga 2": "esp.2",
    "spanish copa del rey": "esp.copa_del_rey",
    "italian serie a": "ita.1",
    "italian serie b": "ita.2",
    "coppa italia": "ita.coppa_italia",
    "german bundesliga": "ger.1",
    "german 2. bundesliga": "ger.2",
    "german cup": "ger.dfb_pokal",
    "french ligue 1": "fra.1",
    "french ligue 2": "fra.2",
    "coupe de france": "fra.coupe_de_france",
    "dutch eredivisie": "ned.1",
    "portuguese primeira liga": "por.1",
    "turkish super lig": "tur.1",
    "scottish premiership": "sco.1",
    "mls": "usa.1",
    "usl championship": "usa.usl.1",
    "nwsl": "usa.w.1",
    "liga mx": "mex.1",
    "liga bbva mx": "mex.1",
    "argentine liga profesional de fútbol": "arg.1",
    "brazilian serie a": "bra.1",
    "colombian primera a": "col.1",
    "chilean primera división": "chi.1",
    "saudi pro league": "sau.1",
    "australian a-league men": "aus.1",
    "japanese j.league": "jpn.1",
    "chinese super league": "chn.1",
    "uefa champions league": "uefa.champions",
    "uefa europa league": "uefa.europa",
    "uefa conference league": "uefa.europa.conf",
    "conmebol libertadores": "conmebol.libertadores",
    "conmebol sudamericana": "conmebol.sudamericana",
    "concacaf champions cup": "concacaf.champions",
}

HUMAN_LEAGUE_FLAGS = {
    "afc asian cup": "https://a.espncdn.com/combiner/i?img=/i/leaguelogos/soccer/500/2243.png",
    "afc asian cup qualifiers": "https://a.espncdn.com/i/leaguelogos/soccer/500/2246.png",
    "afc champions league elite": "https://a.espncdn.com/i/leaguelogos/soccer/500/2200.png",
    "afc champions league two": "https://a.espncdn.com/i/leaguelogos/soccer/500/2243.png",
    "asean championship": "https://a.espncdn.com/i/leaguelogos/soccer/500/2261.png",
    "africa cup of nations": "https://a.espncdn.com/i/leaguelogos/soccer/500/76.png",
    "argentine copa de la superliga": "https://a.espncdn.com/i/leaguelogos/soccer/500/2407.png",
    "argentine liga profesional de fútbol": "https://a.espncdn.com/i/leaguelogos/soccer/500/1.png",
    "argentine nacional b": "https://a.espncdn.com/i/leaguelogos/soccer/500/2294.png",
    "argentine primera b": "https://a.espncdn.com/i/leaguelogos/soccer/500/2308.png",
    "argentine supercopa": "https://a.espncdn.com/i/leaguelogos/soccer/500/2343.png",
    "australian a-league men": "https://a.espncdn.com/i/leaguelogos/soccer/500/1308.png",
    "australian a-league women": "https://a.espncdn.com/i/leaguelogos/soccer/500/2402.png",
    "austrian bundesliga": "https://a.espncdn.com/i/leaguelogos/soccer/500/5.png",
    "belgian pro league": "https://a.espncdn.com/i/leaguelogos/soccer/500/6.png",
    "bolivian liga profesional": "https://a.espncdn.com/i/leaguelogos/soccer/500/1949.png",
    "brazilian campeonato carioca": "https://a.espncdn.com/i/leaguelogos/soccer/500/2265.png",
    "brazilian campeonato gaucho": "https://a.espncdn.com/i/leaguelogos/soccer/500/2272.png",
    "brazilian campeonato mineiro": "https://a.espncdn.com/i/leaguelogos/soccer/500/2360.png",
    "brazilian campeonato paulista": "https://a.espncdn.com/i/leaguelogos/soccer/500/2322.png",
    "brazilian serie a": "https://a.espncdn.com/i/leaguelogos/soccer/500/85.png",
    "brazilian serie b": "https://a.espncdn.com/i/leaguelogos/soccer/500/2299.png",
    "caf champions league": "https://a.espncdn.com/i/leaguelogos/soccer/500/2391.png",
    "conmebol libertadores": "https://a.espncdn.com/i/leaguelogos/soccer/500/58.png",
    "conmebol pre-olympic tournament": "https://a.espncdn.com/i/leaguelogos/soccer/500/19727.png",
    "conmebol recopa": "https://a.espncdn.com/i/leaguelogos/soccer/500/2335.png",
    "conmebol sudamericana": "https://a.espncdn.com/i/leaguelogos/soccer/500/1208.png",
    "chilean primera división": "https://a.espncdn.com/i/leaguelogos/soccer/500/86.png",
    "chinese super league": "https://a.espncdn.com/i/leaguelogos/soccer/500/2350.png",
    "colombian primera a": "https://a.espncdn.com/i/leaguelogos/soccer/500/1543.png",
    "colombian superliga": "https://a.espncdn.com/i/leaguelogos/soccer/500-dark/2405.png",
    "concacaf champions cup": "https://a.espncdn.com/i/leaguelogos/soccer/500/2298.png",
    "concacaf gold cup": "https://a.espncdn.com/i/leaguelogos/soccer/500/59.png",
    "concacaf nations league": "https://a.espncdn.com/i/leaguelogos/soccer/500/2406.png",
    "concacaf w championship": "https://a.espncdn.com/i/leaguelogos/soccer/500/18969.png",
    "copa américa": "https://a.espncdn.com/i/leaguelogos/soccer/500/83.png",
    "copa argentina": "https://a.espncdn.com/i/leaguelogos/soccer/500/2320.png",
    "copa chile": "https://a.espncdn.com/i/leaguelogos/soccer/500/2331.png",
    "copa colombia": "https://a.espncdn.com/i/leaguelogos/soccer/500/2332.png",
    "copa do brasil": "https://a.espncdn.com/i/leaguelogos/soccer/500/528.png",
    "coppa italia": "https://a.espncdn.com/i/leaguelogos/soccer/500/2192.png",
    "costa rican primera division": "https://a.espncdn.com/i/leaguelogos/soccer/500/2245.png",
    "coupe de france": "https://a.espncdn.com/i/leaguelogos/soccer/500/182.png",
    "dutch eredivisie": "https://a.espncdn.com/i/leaguelogos/soccer/500/11.png",
    "dutch knvb beker": "https://a.espncdn.com/i/leaguelogos/soccer/500/2196.png",
    "dutch keuken kampioen divisie": "https://a.espncdn.com/i/leaguelogos/soccer/500/105.png",
    "dutch vrouwen eredivisie": "https://a.espncdn.com/i/leaguelogos/soccer/500/2453.png",
    "english carabao cup": "https://a.espncdn.com/i/leaguelogos/soccer/500/41.png",
    "english efl trophy": "https://a.espncdn.com/i/leaguelogos/soccer/500/42.png",
    "english fa cup": "https://a.espncdn.com/i/leaguelogos/soccer/500/40.png",
    "english league championship": "https://a.espncdn.com/i/leaguelogos/soccer/500/24.png",
    "english league one": "https://a.espncdn.com/i/leaguelogos/soccer/500/25.png",
    "english league two": "https://a.espncdn.com/i/leaguelogos/soccer/500/26.png",
    "english premier league": "https://a.espncdn.com/i/leaguelogos/soccer/500/23.png",
    "english women's super league": "https://a.espncdn.com/i/leaguelogos/soccer/500/2314.png",
    "fifa club world cup": "https://a.espncdn.com/i/leaguelogos/soccer/500/1932.png",
    "fifa under-17 world cup": "https://a.espncdn.com/i/leaguelogos/soccer/500/2288.png",
    "fifa under-20 world cup": "https://a.espncdn.com/i/leaguelogos/soccer/500/2285.png",
    "fifa women's world cup": "https://a.espncdn.com/i/leaguelogos/soccer/500/60.png",
    "fifa world cup": "https://a.espncdn.com/i/leaguelogos/soccer/500/4.png",
    "french ligue 1": "https://a.espncdn.com/i/leaguelogos/soccer/500/9.png",
    "french ligue 2": "https://a.espncdn.com/i/leaguelogos/soccer/500/96.png",
    "german 2. bundesliga": "https://a.espncdn.com/i/leaguelogos/soccer/500/97.png",
    "german bundesliga": "https://a.espncdn.com/i/leaguelogos/soccer/500/10.png",
    "german cup": "https://a.espncdn.com/i/leaguelogos/soccer/500/2061.png",
    "greek super league": "https://a.espncdn.com/i/leaguelogos/soccer/500/98.png",
    "italian serie a": "https://a.espncdn.com/i/leaguelogos/soccer/500/12.png",
    "italian serie b": "https://a.espncdn.com/i/leaguelogos/soccer/500/99.png",
    "japanese j.league": "https://a.espncdn.com/i/leaguelogos/soccer/500/2199.png",
    "leagues cup": "https://a.espncdn.com/i/leaguelogos/soccer/500/2410.png",
    "liga mx": "https://a.espncdn.com/i/leaguelogos/soccer/500/22.png",
    "liga bbva mx": "https://a.espncdn.com/i/leaguelogos/soccer/500/22.png",
    "mls": "https://a.espncdn.com/i/leaguelogos/soccer/500/19.png",
    "nwsl": "https://a.espncdn.com/i/leaguelogos/soccer/500/2323.png",
    "portuguese primeira liga": "https://a.espncdn.com/i/leaguelogos/soccer/500/14.png",
    "saudi pro league": "https://a.espncdn.com/i/leaguelogos/soccer/500/2488.png",
    "scottish premiership": "https://a.espncdn.com/i/leaguelogos/soccer/500/45.png",
    "spanish copa del rey": "https://a.espncdn.com/i/leaguelogos/soccer/500/80.png",
    "spanish laliga": "https://a.espncdn.com/i/leaguelogos/soccer/500/15.png",
    "spanish laliga 2": "https://a.espncdn.com/i/leaguelogos/soccer/500/107.png",
    "swedish allsvenskan": "https://a.espncdn.com/i/leaguelogos/soccer/500/16.png",
    "turkish super lig": "https://a.espncdn.com/i/leaguelogos/soccer/500/18.png",
    "uefa champions league": "https://a.espncdn.com/i/leaguelogos/soccer/500/2.png",
    "uefa conference league": "https://a.espncdn.com/i/leaguelogos/soccer/500/20296.png",
    "uefa europa league": "https://a.espncdn.com/i/leaguelogos/soccer/500/2310.png",
    "usl championship": "https://a.espncdn.com/i/leaguelogos/soccer/500/2292.png",
}

COUNTRY_FLAG_URLS = {
    "belgian": "be", "chilean": "cl", "chinese": "cn", "dutch": "nl",
    "english": "gb-eng", "french": "fr", "german": "de", "bolivian": "bo",
    "norwegian": "no", "russian": "ru", "portuguese": "pt", "scottish": "gb-sct",
    "swedish": "se", "argentine": "ar", "brazilian": "br", "italian": "it",
    "mexican": "mx", "paraguayan": "py", "japanese": "jp", "spanish": "es",
    "danish": "dk", "indian": "in", "salvadoran": "sv", "costa rican": "cr",
    "peruvian": "pe", "peru": "pe",
    "uruguay": "uy", "uruguayan": "uy", "uruguaya": "uy",
    "brazil": "br",
    "ecuador": "ec", "ecuadorian": "ec",
    "mexico": "mx", "mx": "mx",
    "guatemalan": "gt", "guatemala": "gt",
    "croatian": "hr", "croatia": "hr", "fpd": "hr"
}

# ==========================================
# HELPER FUNCTIONS
# ==========================================
def slugify(text):
    """Convert text into clean, ASCII-only, SEO-friendly URL slug."""
    if not text:
        return "unknown"
    text = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode('utf-8')
    text = text.lower().strip()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[\s_-]+', '-', text)
    return text.strip('-')

def write_if_changed(filepath, new_content):
    """Writes content ONLY if changed or missing to preserve Git history."""
    if os.path.exists(filepath):
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                if f.read() == new_content:
                    print(f"  ⏭️  Unchanged: {filepath}")
                    return False
        except Exception as e:
            print(f"  ⚠️ Error reading {filepath}: {e}")

    dir_path = os.path.dirname(filepath)
    if dir_path:
        os.makedirs(dir_path, exist_ok=True)

    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(new_content)
    print(f"  📝 Updated: {filepath}")
    return True

def get_effective_matchday_date():
    """Calculates date using 3:00 AM EST crossover window."""
    if HAS_ZONEINFO:
        est_tz = zoneinfo.ZoneInfo("America/New_York")
        now_est = datetime.datetime.now(est_tz)
    else:
        utc_now = datetime.datetime.now(timezone.utc)
        now_est = utc_now - timedelta(hours=5)
    return now_est - timedelta(hours=3)

def load_json(filepath, default_val):
    """Safely loads JSON from a file, returning default_val if it fails."""
    if os.path.exists(filepath):
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"⚠️ Error loading {filepath}: {e}")
    return default_val

def save_json(filepath, data):
    """Safely saves data to JSON using the write_if_changed pipeline."""
    content = json.dumps(data, indent=4, sort_keys=True)
    write_if_changed(filepath, content)

def normalize_text(text):
    if not text: return ""
    nfkd_form = unicodedata.normalize('NFD', text)
    return "".join([c for c in nfkd_form if unicodedata.category(c) != 'Mn']).lower().strip()

NORMALIZED_HUMAN_LEAGUE_FLAGS = {
    normalize_text(key): val for key, val in HUMAN_LEAGUE_FLAGS.items()
}

def safe_get(d, *keys):
    """Safely traverse nested dicts, guarding against missing keys and null/None values."""
    for key in keys:
        if isinstance(d, dict) and d.get(key) is not None:
            d = d.get(key)
        else:
            return None
    return d

def fetch_single_league_detail(ref_url):
    try:
        res = HTTP.get(ref_url, timeout=5)
        if res.status_code == 200:
            return res.json()
    except Exception:
        pass
    return None

def build_hydrated_core_index():
    """Builds parallel-hydrated master lookup for IDs, display names, and reverse slug-to-name mappings."""
    print("🔄 Hydrating Master Core API Directory (Parallel Threads)...")
    
    index = {
        "id_map": {},
        "name_map": {
            "club friendly": "club.friendly",
            "international friendly": "fifa.friendly",
            "friendly": "club.friendly",
            "men's international friendly": "fifa.friendly",
            "asean champ": "aff.championship",
            "asean championship": "aff.championship"
        },
        "slug_to_name": {
            "club.friendly": "Club Friendly",
            "fifa.friendly": "International Friendly",
            "aff.championship": "ASEAN Championship"
        }
    }
    
    try:
        master_res = HTTP.get(CORE_LEAGUES_URL, timeout=10).json()
        items = master_res.get('items', [])
        ref_urls = [item['$ref'] for item in items if '$ref' in item]
        
        with ThreadPoolExecutor(max_workers=25) as executor:
            future_to_url = {executor.submit(fetch_single_league_detail, url): url for url in ref_urls}
            for future in as_completed(future_to_url):
                data = future.result()
                if not data: continue
                    
                league_id = str(data.get('id')) if data.get('id') else None
                slug = data.get('slug')
                name = data.get('name')
                short_name = data.get('shortName')
                abbrev = data.get('abbreviation')
                
                if slug:
                    if name: index["slug_to_name"][slug] = name
                    elif short_name: index["slug_to_name"][slug] = short_name
                        
                    if league_id: index["id_map"][league_id] = slug
                        
                    if name: index["name_map"][name.lower().strip()] = slug
                    if short_name: index["name_map"][short_name.lower().strip()] = slug
                    if abbrev: index["name_map"][abbrev.lower().strip()] = slug

        print(f"✅ Core Index Hydrated! Mapped {len(index['id_map'])} League IDs & {len(index['name_map'])} Name Variations.\n")
    except Exception as e:
        print(f"⚠️ Warning: Core API Index hydration failed ({e}). Pipeline will fallback to standard resolution.\n")
        
    return index

def resolve_event_league(event, core_index):
    """4-Tier League Resolver: Returns tuple (league_pill, display_name)"""
    if not core_index: return None, None

    comps = event.get('competitions', [])
    first_comp = comps[0] if comps else {}

    # Tier 1: Direct league.slug
    t1_slug = safe_get(event, 'league', 'slug')
    if t1_slug:
        return t1_slug, core_index['slug_to_name'].get(t1_slug) or safe_get(event, 'league', 'name') or t1_slug.replace('.', ' ').title()

    # Tier 2: Core API Lookup via numeric league.id
    league_id = safe_get(event, 'league', 'id') or safe_get(first_comp, 'league', 'id')
    if league_id and str(league_id) in core_index['id_map']:
        found_slug = core_index['id_map'][str(league_id)]
        return found_slug, core_index['slug_to_name'].get(found_slug) or safe_get(event, 'league', 'name') or found_slug.replace('.', ' ').title()

    # Tier 3: Odds tracking tags metadata
    if comps:
        odds_list = first_comp.get('odds', [])
        if odds_list:
            tags = safe_get(odds_list[0], 'total', 'over', 'close', 'link', 'tracking', 'tags') or safe_get(odds_list[0], 'moneyline', 'home', 'close', 'link', 'tracking', 'tags')
            if isinstance(tags, dict) and tags.get('league'):
                found_slug = tags.get('league')
                return found_slug, core_index['slug_to_name'].get(found_slug) or safe_get(first_comp, 'league', 'name') or found_slug.replace('.', ' ').title()

    # Tier 4: Normalized Name Matching against Core Directory
    candidates = []
    for s in [safe_get(event, 'league', 'name'), safe_get(event, 'league', 'shortName'), safe_get(first_comp, 'league', 'name'), safe_get(first_comp, 'league', 'shortName'), first_comp.get('altGameNote')]:
        if not s or not isinstance(s, str): continue
        s_clean = s.strip()
        candidates.append(s_clean.lower())
        for delimiter in [',', '-', '|', '–']:
            if delimiter in s_clean:
                base_part = s_clean.split(delimiter)[0].strip()
                if base_part: candidates.append(base_part.lower())

    for cand in list(dict.fromkeys(candidates)):
        if cand in core_index['name_map']:
            found_slug = core_index['name_map'][cand]
            return found_slug, core_index['slug_to_name'].get(found_slug) or cand.title()

    for cand in candidates:
        for name_key, found_slug in core_index['name_map'].items():
            if len(name_key) > 3 and name_key in cand:
                return found_slug, core_index['slug_to_name'].get(found_slug) or name_key.title()

    return None, None

def fetch_espn_events_for_pill(pill, start_date_str, end_date_str):
    """Fetches a 14-day schedule for a specific league using its official pill."""
    if not pill:
        return []
    url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{pill}/scoreboard?dates={start_date_str}-{end_date_str}&limit=1000"
    try:
        res = HTTP.get(url, timeout=15)
        if res.status_code == 200:
            return res.json().get('events', [])
    except Exception as e:
        print(f"  ⚠️ Error fetching 14-day schedule for pill '{pill}': {e}")
    return []

# ==========================================
# STADIUM GEOCODING & CACHE SANITIZATION
# ==========================================
def validate_and_clean_stadiums_db(stadiums_db):
    """Purges stadium cache entries that have blatantly impossible coordinates."""
    purged_count = 0
    for v_id, s in list(stadiums_db.items()):
        country = str(s.get("country", "")).upper()
        lat = s.get("lat", 0.0)
        lon = s.get("lon", 0.0)

        # Sanity Check: Americas (USA, Canada, Mexico, etc.) must have negative longitude
        is_americas = country in ["USA", "UNITED STATES", "CANADA", "MEXICO", "US"] or "USA" in country
        if is_americas and lon > 0:
            print(f"  🧹 Purging corrupted cache for [{v_id}] {s.get('name')} (Longitude {lon}° East is in Europe/Asia!)")
            del stadiums_db[v_id]
            purged_count += 1
        elif lat == 0.0 and lon == 0.0:
            del stadiums_db[v_id]
            purged_count += 1
            
    if purged_count > 0:
        print(f"  ✨ Sanitized {purged_count} bad entries from stadiums database.")

def geocode_query_open_meteo(query_text, country_hint=""):
    """Hits Open-Meteo's fast geocoding API with explicit country filtering."""
    if not query_text or not query_text.strip(): return 0.0, 0.0

    clean_q = re.sub(r'[^\w\s]', ' ', query_text).strip()
    clean_q = re.sub(r'\s+', ' ', clean_q)
    if not clean_q: return 0.0, 0.0

    url = f"https://geocoding-api.open-meteo.com/v1/search?name={requests.utils.quote(clean_q)}&count=10&language=en&format=json"
    try:
        resp = HTTP.get(url, timeout=8)
        if resp.status_code == 200:
            results = resp.json().get("results", [])
            if results:
                if country_hint:
                    ch_lower = country_hint.lower()
                    for r in results:
                        r_country = r.get("country", "").lower()
                        r_code = r.get("country_code", "").lower()
                        if ch_lower in r_country or r_code == ch_lower or (ch_lower in ["usa", "united states", "us"] and r_code == "us"):
                            return float(r.get("latitude") if r.get("latitude") is not None else 0.0), float(r.get("longitude") if r.get("longitude") is not None else 0.0)
                            
                return float(results[0].get("latitude") if results[0].get("latitude") is not None else 0.0), float(results[0].get("longitude") if results[0].get("longitude") is not None else 0.0)
    except Exception as e:
        print(f"   ⚠️ Geocode error for '{query_text}': {e}")
    return 0.0, 0.0

def geocode_venue_multi_stage(venue_name, city, country, home_team):
    """Cascading Geocoder with country validation to prevent cross-continent mismapping."""
    city_parts = [p.strip() for p in city.split(',') if p.strip()] if city else []
    clean_city = city_parts[0] if city_parts else ""
    country_hint = country.strip() if country else ""

    # Stage 1: Stadium Name + City (Filtered by Country)
    if venue_name and venue_name not in ["Unknown Stadium", "Venue Unlisted"] and clean_city:
        lat, lon = geocode_query_open_meteo(f"{venue_name} {clean_city}", country_hint)
        if lat != 0.0 and lon != 0.0: return lat, lon

    # Stage 2: Stadium Name Alone (Filtered by Country)
    if venue_name and venue_name not in ["Unknown Stadium", "Venue Unlisted"]:
        lat, lon = geocode_query_open_meteo(venue_name, country_hint)
        if lat != 0.0 and lon != 0.0: return lat, lon

    # Stage 3: Clean City Alone (Filtered by Country)
    if clean_city:
        lat, lon = geocode_query_open_meteo(clean_city, country_hint)
        if lat != 0.0 and lon != 0.0: return lat, lon

    # Stage 4: Home Team Fallback
    if home_team and home_team != "TBD":
        lat, lon = geocode_query_open_meteo(f"{home_team} stadium", country_hint)
        if lat != 0.0 and lon != 0.0: return lat, lon

        lat, lon = geocode_query_open_meteo(home_team, country_hint)
        if lat != 0.0 and lon != 0.0: return lat, lon

    # Stage 5: Country Centroid
    if country_hint:
        lat, lon = geocode_query_open_meteo(country_hint)
        if lat != 0.0 and lon != 0.0: return lat, lon

    return 0.0, 0.0

def get_or_update_stadium(stadiums_db, venue_id, venue_info, home_team=""):
    if venue_id in stadiums_db:
        cached = stadiums_db[venue_id]
        if cached.get("lat") != 0.0 and cached.get("lon") != 0.0:
            return cached

    raw_name = venue_info.get("fullName") or venue_info.get("displayName") or ""
    name = raw_name if raw_name else "Venue Unlisted"
    city = venue_info.get("address", {}).get("city", "")
    country = venue_info.get("address", {}).get("country", "")
    is_indoor = venue_info.get("indoor", False)

    lat = float(venue_info.get("geometry", {}).get("coordinates", [0, 0])[1]) if "geometry" in venue_info else 0.0
    lon = float(venue_info.get("geometry", {}).get("coordinates", [0, 0])[0]) if "geometry" in venue_info else 0.0

    if lat == 0.0 or lon == 0.0:
        print(f"  🔍 Geocoding venue: {name} ({city}, {country}) | Home: {home_team}...")
        lat, lon = geocode_venue_multi_stage(name, city, country, home_team)

    stadium_entry = {
        "id": venue_id, "name": name, "city": city, "country": country,
        "roof": "Dome" if is_indoor else "Open", "surface": "Grass",
        "lat": lat, "lon": lon
    }
    stadiums_db[venue_id] = stadium_entry
    return stadium_entry

# ==========================================
# WEATHER PIPELINE
# ==========================================
def fetch_open_meteo_hourly(lat, lon, kickoff_iso_str):
    if lat == 0.0 or lon == 0.0:
        return {"status": "no_coords", "temp": "--", "humidity": 0, "windSpeed": 0, "precip": 0, "hourly": []}

    try:
        utc_time = datetime.datetime.fromisoformat(kickoff_iso_str.replace('Z', '+00:00'))
    except Exception:
        return None

    game_date_str = utc_time.strftime('%Y-%m-%d')
    next_day_str = (utc_time + timedelta(days=1)).strftime('%Y-%m-%d')
    days_diff = (utc_time.date() - datetime.datetime.now(timezone.utc).date()).days

    if days_diff > 14:
        return {"status": "too_early", "temp": "--", "humidity": 0, "windSpeed": 0, "precip": 0, "hourly": []}

    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": lat, "longitude": lon,
        "current": "temperature_2m,relative_humidity_2m,wind_speed_10m,precipitation",
        "hourly": "temperature_2m,relative_humidity_2m,precipitation_probability,precipitation,weather_code",
        "temperature_unit": "fahrenheit", "wind_speed_unit": "mph", "precipitation_unit": "inch",
        "timezone": "GMT", "start_date": game_date_str, "end_date": next_day_str
    }

    for attempt in range(3):
        try:
            res = HTTP.get(url, params=params, timeout=15)
            if res.status_code == 200:
                data = res.json()
                current = data.get('current', {})
                time_array = data.get('hourly', {}).get('time', [])
                target_time_str = utc_time.strftime('%Y-%m-%dT%H:00')

                try:
                    start_idx = time_array.index(target_time_str)
                except ValueError:
                    start_idx = 1

                actual_start = max(0, start_idx - 1)
                actual_end = min(len(time_array), start_idx + 4)

                hourly_slice = []
                for i in range(actual_start, actual_end):
                    code_arr = data['hourly'].get("weather_code", [])
                    code_val = code_arr[i] if i < len(code_arr) and code_arr[i] is not None else 0
                    
                    t_arr = data['hourly'].get("temperature_2m", [])
                    t_val = t_arr[i] if i < len(t_arr) and t_arr[i] is not None else 72
                    
                    h_arr = data['hourly'].get("relative_humidity_2m", [])
                    h_val = h_arr[i] if i < len(h_arr) and h_arr[i] is not None else 50
                    
                    p_arr = data['hourly'].get("precipitation_probability", [])
                    p_val = p_arr[i] if i < len(p_arr) and p_arr[i] is not None else 0

                    hourly_slice.append({
                        "timestamp": time_array[i] + "Z",
                        "temp": int(t_val),
                        "humidity": int(h_val),
                        "precipChance": p_val,
                        "isThunderstorm": code_val in [95, 96, 99],
                        "isSnow": code_val in [71, 73, 75, 77, 85, 86]
                    })

                c_temp = current.get('temperature_2m')
                c_hum = current.get('relative_humidity_2m')
                c_wind = current.get('wind_speed_10m')
                c_precip = current.get('precipitation')

                return {
                    "status": "ok",
                    "temp": int(c_temp if c_temp is not None else 72),
                    "humidity": int(c_hum if c_hum is not None else 50),
                    "windSpeed": int(c_wind if c_wind is not None else 0),
                    "precip": round(float(c_precip if c_precip is not None else 0.0), 2),
                    "hourly": hourly_slice
                }
        except requests.RequestException:
            time.sleep(1)

    return None

# ==========================================
# CARD HTML GENERATORS
# ==========================================
def render_game_card_html(game, is_compact_default=True):
    w = game['weather']
    is_dome = game['stadium']['roof'] in ["Dome", "Retractable"]
    is_no_coords = w.get('status') == "no_coords"
    is_too_early = w.get('status') in ["too_early"] or w.get('temp') == "--"

    hourly = w.get('hourly', [])
    max_pop = max([(h.get('precipChance') if h.get('precipChance') is not None else 0) for h in hourly], default=0) if hourly else 0
    humidity = w.get('humidity', 50)
    
    w_precip = w.get('precip') if w.get('precip') is not None else 0.0
    w_wind = w.get('windSpeed') if w.get('windSpeed') is not None else 0

    bg_class = "bg-weather-sunny"
    border_class = ""
    if is_no_coords or is_too_early:
        bg_class = "bg-light"
    elif is_dome:
        bg_class = "bg-weather-roof"
    elif max_pop >= 50 or w_precip > 0.5:
        border_class = "border-danger border-3"
        bg_class = "bg-weather-storm"
    elif max_pop >= 20 or w_precip > 0:
        border_class = "border-warning border-3"
        bg_class = "bg-weather-rain"
    elif w_wind >= 15:
        bg_class = "bg-weather-cloudy"

    # Grab scores (default to 0 if missing)
    home_score = game.get('home_score', '0')
    away_score = game.get('away_score', '0')

    # Format the score string with a clean pipe divider
    score_str = f" &nbsp;|&nbsp; {home_score}-{away_score}"

    if game['status'] == 'in':
        badge_text = game.get('clock') or 'LIVE'
        badge_html = f'<span class="badge bg-success text-white border-success flex-shrink-0" style="font-size: 0.65rem;">{badge_text}{score_str}</span>'
    elif game['status'] == 'post':
        badge_text = "FINAL"
        badge_html = f'<span class="badge bg-secondary text-white border-secondary flex-shrink-0" style="font-size: 0.65rem;">{badge_text}{score_str}</span>'
    else:
        try:
            d = datetime.datetime.fromisoformat(game['game_time'].replace('Z', '+00:00'))
            fallback_text = d.strftime('%b %d, %I:%M %p UTC')
        except Exception:
            fallback_text = "SCHEDULED"
        
        badge_html = f'<span class="badge bg-light text-dark border border-secondary flex-shrink-0 local-time-badge" data-gametime="{game["game_time"]}" style="font-size: 0.65rem;">{fallback_text}</span>'

    # Rich parameters for Windy radar initialization
    radar_url = f"https://embed.windy.com/embed2.html?lat={game['stadium']['lat']}&lon={game['stadium']['lon']}&detailLat={game['stadium']['lat']}&detailLon={game['stadium']['lon']}&width=650&height=450&zoom=11&level=surface&overlay=rain&product=ecmwf&menu=&message=&marker=&calendar=now&pressure=&type=map&location=coordinates&detail=&metricWind=mph&metricTemp=%C2%B0F&radarRange=-1"

    if is_no_coords:
        weather_emoji_line = "⚠️No Weather Info"
    elif is_dome:
        weather_emoji_line = f"🏠Closed 🌡️{w['temp']}° 💧{humidity}%"
    elif is_too_early:
        weather_emoji_line = "🔭Forecast Pending"
    else:
        # Formatted tightly with no spaces after emojis to prevent truncation
        weather_emoji_line = f"🌧️{max_pop}% 🌡️{w['temp']}° 💨{w['windSpeed']}mph"

    show_ribbon = "block" if is_compact_default else "none"
    show_full = "none" if is_compact_default else "block"

    hourly_html = ""
    if not is_too_early and not is_no_coords and not is_dome and hourly:
        hours_markup = ""
        for h in hourly[:5]:
            try:
                dt = datetime.datetime.fromisoformat(h['timestamp'].replace('Z', '+00:00'))
                hr_str = dt.strftime('%I%p').lstrip('0')
            except Exception:
                hr_str = "--"

            icon = "☀️"
            pc = h.get('precipChance') if h.get('precipChance') is not None else 0
            
            if pc >= 30:
                icon = "⛈️" if h.get('isThunderstorm') else ("🌨️" if h.get('isSnow') else "🌧️")
            elif pc > 0:
                icon = "⛅"

            pop_str = f"{pc}%" if pc >= 20 else "&nbsp;"
            hours_markup += f"""
                <div class="hour-card">
                    <div class="hour-time local-hour-time" data-timestamp="{h['timestamp']}">{hr_str}</div>
                    <div class="hour-icon">{icon}</div>
                    <div class="hour-pop">{pop_str}</div>
                    <div class="hour-temp">{h['temp']}°</div>
                </div>"""
        hourly_html = f'<div class="hourly-scroll-container">{hours_markup}</div>'

    if is_no_coords:
        weather_section = """
        <div class="text-center p-3 mt-2 border-top">
            <h6 class="text-warning fw-bold mb-1">⚠️ Weather Info Not Available</h6>
            <p class="small text-muted mb-0" style="font-size: 0.75rem;">Stadium coordinates unlisted.</p>
        </div>"""
    elif is_too_early:
        weather_section = """
        <div class="text-center p-3 mt-2 border-top">
            <h6 class="text-muted mb-1">🔭 Early Forecast</h6>
            <p class="small text-muted mb-0" style="font-size: 0.75rem;">Weather available ~14 days before kickoff.</p>
        </div>"""
    else:
        weather_section = f"""
        <div class="weather-row row text-center align-items-center mt-2 mx-0">
            <div class="col-3 border-end px-1">
                <div class="fw-bold">{w['temp']}°F</div>
                <div class="small text-muted" style="font-size: 0.7rem;">Temp</div>
            </div>
            <div class="col-3 border-end px-1">
                <div class="fw-bold text-dark">💧 {humidity}%</div>
                <div class="small text-muted" style="font-size: 0.7rem;">Humidity</div>
            </div>
            <div class="col-3 border-end px-1">
                <div class="fw-bold text-primary">{max_pop}%</div>
                <div class="small text-muted" style="font-size: 0.7rem;">Rain</div>
            </div>
            <div class="col-3 px-1">
                <div class="fw-bold">{w['windSpeed']} <span style="font-size:0.7em">mph</span></div>
                <span class="wind-badge bg-secondary text-white" style="font-size: 0.55rem; padding: 2px 4px;">💨</span>
            </div>
        </div>
        {hourly_html}
        <div class="mt-2 mb-1">
            <button class="btn btn-sm btn-outline-primary w-100 py-1 fw-bold" style="font-size: 0.8rem;" onclick="event.stopPropagation(); showRadar('{radar_url}', '{game['stadium']['name']}')">
                🗺️ Live Weather Radar
            </button>
        </div>"""

    # Optional UI injection for the league logo inside the expanded dark header
    league_logo_html = f'<img src="{game.get("league_logo", "")}" style="width: 18px; height: 18px; object-fit: contain;" class="me-2 bg-light rounded-circle p-1" onerror="this.style.display=\'none\'">' if game.get("league_logo") and game.get("league_logo").startswith('http') else (f'<span style="font-size: 1.1rem; margin-right: 6px; vertical-align: middle; line-height: 1;">{game.get("league_logo")}</span>' if game.get("league_logo") else '')

    return f"""
    <div class="col-md-6 col-lg-3 animate-card mb-3 px-1" id="game-{game['id']}">
        <div class="card game-card shadow-sm {border_class} {bg_class}">
            <!-- COMPACT RIBBON VIEW (MLB STYLE) -->
            <div class="ribbon-view p-2 position-relative" onclick="toggleSingleCard(this)" style="cursor: pointer; display: {show_ribbon};">
                
                <!-- Top Line: Time Badge & Weather (Left aligned together) -->
                <div class="d-flex align-items-center justify-content-start mb-1 gap-2">
                    {badge_html}
                    <div class="fw-bold text-primary text-truncate" style="font-size: 0.72rem;">
                        {weather_emoji_line}
                    </div>
                </div>
                
                <!-- Bottom Line: Teams Inline (Home vs Away) -->
                <div class="d-flex align-items-center justify-content-between w-100 mt-1">
                    <div class="d-flex align-items-center text-truncate" style="font-size: 0.75rem; flex: 1; min-width: 0;">
                        <img src="{game['home_logo']}" style="width: 16px; height: 16px; object-fit: contain;" onerror="this.style.display='none'">
                        <span class="fw-bold text-dark text-truncate ms-1">{game['home_team']}</span>
                        
                        <span class="mx-2 text-muted fw-bold" style="font-size: 0.70rem;">vs</span>
                        
                        <img src="{game['away_logo']}" style="width: 16px; height: 16px; object-fit: contain;" onerror="this.style.display='none'">
                        <span class="fw-bold text-dark text-truncate ms-1">{game['away_team']}</span>
                    </div>
                </div>

            </div>

            <!-- EXPANDED FULL CARD VIEW (HOME LEFT - AWAY RIGHT) -->
            <div class="full-card-view" onclick="toggleSingleCard(this)" style="cursor: pointer; display: {show_full};">
                <div class="d-flex align-items-center justify-content-between p-2 bg-dark text-white">
                    <div class="d-flex align-items-center text-truncate">
                        {league_logo_html}
                        <span class="fw-bold text-truncate" style="font-size: 0.75rem;">{game['league_name']}</span>
                    </div>
                    {badge_html}
                </div>
                <div class="card-body px-2 pt-2 pb-2">
                    <div class="d-flex justify-content-between align-items-center mb-2">
                        <span class="stadium-name text-truncate fw-bold" style="font-size: 0.8rem;">📍 {game['stadium']['name']}</span>
                    </div>
                    <div class="d-flex justify-content-between align-items-center px-1 mb-1">
                        <div class="d-flex align-items-center text-truncate" style="width: 45%;">
                            <img src="{game['home_logo']}" class="me-2 flex-shrink-0" style="width: 24px; height: 24px; object-fit: contain;" onerror="this.style.display='none'">
                            <div class="d-flex flex-column text-start text-truncate">
                                <a href="/teams/{game['home_slug']}/" class="text-dark text-decoration-none fw-bold text-truncate" style="font-size: 0.95rem;" onclick="event.stopPropagation();">{game['home_team']}</a>
                                <a href="https://futbolstartingeleven.com/teams/{game['home_slug']}/lineup/" class="text-primary text-decoration-none text-truncate" style="font-size: 0.65rem; margin-top: -2px;" onclick="event.stopPropagation();">lineup</a>
                            </div>
                        </div>
                        <div class="text-center text-muted fw-bold" style="width: 10%; font-size: 0.8rem;">vs</div>
                        <div class="d-flex align-items-center justify-content-end text-truncate" style="width: 45%;">
                            <div class="d-flex flex-column text-end text-truncate me-2">
                                <a href="/teams/{game['away_slug']}/" class="text-dark text-decoration-none fw-bold text-truncate" style="font-size: 0.95rem;" onclick="event.stopPropagation();">{game['away_team']}</a>
                                <a href="https://futbolstartingeleven.com/teams/{game['away_slug']}/lineup/" class="text-primary text-decoration-none text-truncate" style="font-size: 0.65rem; margin-top: -2px;" onclick="event.stopPropagation();">lineup</a>
                            </div>
                            <img src="{game['away_logo']}" class="flex-shrink-0" style="width: 24px; height: 24px; object-fit: contain;" onerror="this.style.display='none'">
                        </div>
                    </div>
                    {weather_section}
                </div>
            </div>
        </div>
    </div>"""

def render_dormant_banner():
    return """
    <div class="col-12 mb-3 px-2">
        <div class="card p-5 text-center border rounded bg-light shadow-sm">
            <span class="fs-1 mb-2 d-block">💤</span>
            <h6 class="fw-bold text-secondary mb-1">No Upcoming Fixtures</h6>
            <p class="small text-muted mb-0">This team or league does not have a scheduled match in the next 14 days.</p>
        </div>
    </div>
    """

# ==========================================
# MASTER HTML PAGE TEMPLATE
# ==========================================
MASTER_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>__PAGE_TITLE__</title>
    
    <!-- Google tag (gtag.js) -->
    <script async src="https://www.googletagmanager.com/gtag/js?id=G-XL59G5DSWQ"></script>
    <script>
      window.dataLayer = window.dataLayer || [];
      function gtag(){dataLayer.push(arguments);}
      gtag('js', new Date());

      gtag('config', 'G-XL59G5DSWQ');
    </script>
    
    <meta name="description" content="__META_DESC__">
    <meta name="keywords" content="__SEO_KEYWORDS__">
    <link rel="canonical" href="__CANONICAL_URL__" />

    <link rel="icon" type="image/svg+xml" href="/favicon.svg">
    <link rel="icon" type="image/png" sizes="96x96" href="/favicon-96x96.png">
    <link rel="shortcut icon" href="/favicon.ico">
    <link rel="apple-touch-icon" sizes="180x180" href="/apple-touch-icon.png">
    <link rel="manifest" href="/site.webmanifest">
    
    <meta property="og:title" content="__OG_TITLE__">
    <meta property="og:description" content="__OG_DESC__">
    <meta property="og:url" content="__CANONICAL_URL__">
    <meta property="og:type" content="website">
    
    <meta name="twitter:card" content="summary">
    <meta name="twitter:title" content="__OG_TITLE__">
    <meta name="twitter:description" content="__OG_DESC__">
    
    <script type="application/ld+json">
__SCHEMA_JSON__
    </script>
    
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
        body { background-color: #f8f9fa; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
        .main-container { max-width: 1200px; margin: 20px auto; padding: 0 15px; }
        .game-card { border: 1px solid #dee2e6; border-radius: 12px; background: white; overflow: hidden; }
        .weather-row { font-size: 0.9rem; border-top: 1px solid #f1f3f5; padding-top: 8px; margin-top: 8px; }
        .stadium-name { color: #6c757d; text-transform: uppercase; letter-spacing: 0.5px; }
        
        .hourly-scroll-container { display: flex; overflow-x: auto; gap: 8px; padding: 8px 4px; margin-top: 8px; border-top: 1px solid rgba(0,0,0,0.05); }
        .hour-card { display: flex; flex-direction: column; align-items: center; min-width: 55px; text-align: center; }
        .hour-time { font-size: 0.7rem; font-weight: 600; color: #6c757d; }
        .hour-icon { font-size: 1.2rem; }
        .hour-pop { font-size: 0.65rem; color: #0d6efd; font-weight: 700; height: 12px; }
        .hour-temp { font-size: 0.8rem; font-weight: 600; }
        
        /* SLEEK LEAGUE HEADER DIVIDER - 100px scroll-margin gives clearance under sticky header */
        .league-section-title { font-size: 0.75rem; font-weight: 800; text-transform: uppercase; letter-spacing: 0.5px; color: #6c757d; margin: 1.5rem 0 0.5rem 0.25rem; display: flex; align-items: center; scroll-margin-top: 100px; }
        .league-section-title a { color: inherit; text-decoration: none; transition: color 0.2s; display: flex; align-items: center; }
        .league-section-title a:hover { color: #0d6efd; }
        .league-section-title::after { content: ""; flex: 1; border-bottom: 1px solid #e9ecef; margin-left: 10px; }

        @keyframes weather-flow { 0% { background-position: 0% 50%; } 50% { background-position: 100% 50%; } 100% { background-position: 0% 50%; } }
        .bg-weather-sunny { background: linear-gradient(-45deg, #e3f2fd, #e1f5fe, #f1f8e9); background-size: 300% 300%; animation: weather-flow 15s ease infinite; }
        .bg-weather-cloudy { background: linear-gradient(-45deg, #f5f5f5, #e0e0e0, #eeeeee); background-size: 300% 300%; animation: weather-flow 20s ease infinite; }
        .bg-weather-rain { background: linear-gradient(180deg, #e3f2fd, #cfd8dc, #eceff1); background-size: 200% 200%; animation: weather-flow 8s ease infinite; }
        .bg-weather-storm { background: linear-gradient(-45deg, #e1bee7, #cfd8dc, #e0e0e0); background-size: 300% 300%; animation: weather-flow 10s ease infinite; }
        .bg-weather-roof { background-color: #ffffff; }
    </style>
</head>
<body>
    <nav class="navbar shadow-sm py-2 sticky-top" style="background-color: #0f172a;">
        <div class="container d-flex justify-content-between align-items-center flex-wrap gap-2">
            <a href="/" class="navbar-brand text-white fw-bold m-0" style="font-style: italic; font-size: 1.5rem;">
                Weather <span style="color: #5ac8fa;">Football</span>
            </a>
            
            <div class="d-flex align-items-center gap-2 flex-wrap">
                <input list="league-search-options" id="league-search-input" class="form-control form-control-sm fw-bold shadow-sm" style="background-color: #1e293b; color: #f8f9fa; border: 1px solid #334155; max-width: 160px;" placeholder="🏆 League..." onchange="if(this.value) { const opt = document.querySelector('#league-search-options option[value=\\''+this.value+'\\']'); if(opt) window.location.href = opt.dataset.url; }">
                <datalist id="league-search-options">__LEAGUE_SEARCH_OPTIONS__</datalist>

                <input list="team-search-options" id="team-search-input" class="form-control form-control-sm fw-bold shadow-sm" style="background-color: #1e293b; color: #f8f9fa; border: 1px solid #334155; max-width: 160px;" placeholder="🔍 Team..." onchange="if(this.value) { const opt = document.querySelector('#team-search-options option[value=\\''+this.value+'\\']'); if(opt) window.location.href = opt.dataset.url; }">
                <datalist id="team-search-options">__TEAM_SEARCH_OPTIONS__</datalist>

                <a href="/" class="btn btn-sm btn-outline-light px-3 fw-bold" style="font-size: 0.75rem;">Full Slate</a>
            </div>
        </div>
    </nav>

    <div class="main-container">
        <div class="text-center mb-3">
            <h1 class="fw-bold h3">__HERO_HEADING__</h1>
            <p class="text-muted small m-0">__HERO_SUBHEADING__</p>
        </div>
        __TOGGLE_CONTROLS_ROW__
        <div class="row w-100 m-0 p-0 justify-content-start">
__MATCH_CARDS_GRID__
        </div>
    </div>

    <!-- LIVE RADAR MODAL -->
    <div class="modal fade" id="radarModal" tabindex="-1" aria-hidden="true">
        <div class="modal-dialog modal-lg modal-dialog-centered">
            <div class="modal-content shadow">
                <div class="modal-header bg-dark text-white border-0 py-2">
                    <h5 class="modal-title fw-bold" style="font-size: 1rem;" id="radarModalTitle">Live Weather Radar</h5>
                    <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal"></button>
                </div>
                <div class="modal-body p-0 bg-light" style="height: 60vh;">
                    <iframe id="radarFrame" src="" class="w-100 h-100 border-0" allowfullscreen></iframe>
                </div>
            </div>
        </div>
    </div>

    <script>
        document.addEventListener('DOMContentLoaded', () => {
            // Localize scheduled game times (including Month and Day for multi-week slates)
            document.querySelectorAll('.local-time-badge').forEach(el => {
                const dt = new Date(el.dataset.gametime);
                if (!isNaN(dt)) {
                    el.textContent = dt.toLocaleString(undefined, {month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit'});
                }
            });

            // Localize 5-hour forecast hourly timestamps into visitor's local timezone
            document.querySelectorAll('.local-hour-time').forEach(el => {
                const dt = new Date(el.dataset.timestamp);
                if (!isNaN(dt)) {
                    let hr = dt.getHours();
                    const ampm = hr >= 12 ? 'PM' : 'AM';
                    hr = hr % 12 || 12;
                    el.textContent = `${hr}${ampm}`;
                }
            });

            // Radar Modal cleanup listener
            const radarModal = document.getElementById('radarModal');
            if (radarModal) {
                radarModal.addEventListener('hidden.bs.modal', () => {
                    const iframe = document.getElementById('radarFrame');
                    if (iframe) iframe.src = '';
                });
            }
        });

        function showRadar(url, venueName) {
            const modalElement = document.getElementById('radarModal');
            const modalTitle = document.getElementById('radarModalTitle');
            const iframe = document.getElementById('radarFrame');
            
            if (modalTitle) modalTitle.innerText = 'Radar: ' + venueName;

            const myModal = bootstrap.Modal.getOrCreateInstance(modalElement);

            // Clear map frame before open
            if (iframe) iframe.src = '';

            const loadMap = function () {
                if (iframe) iframe.src = url; 
                modalElement.removeEventListener('shown.bs.modal', loadMap); 
            };

            modalElement.addEventListener('shown.bs.modal', loadMap);
            myModal.show();
        }

        function toggleSingleCard(element) {
            const card = element.closest('.game-card');
            const ribbon = card.querySelector('.ribbon-view');
            const full = card.querySelector('.full-card-view');
            if (ribbon.style.display === 'none') {
                ribbon.style.display = 'block';
                full.style.display = 'none';
            } else {
                ribbon.style.display = 'none';
                full.style.display = 'block';
            }
        }

        function toggleAllCards() {
            const ribbons = document.querySelectorAll('.ribbon-view');
            const fulls = document.querySelectorAll('.full-card-view');
            const btn = document.getElementById('expand-toggle-btn');
            if (!ribbons.length) return;
            
            const isCurrentlyCompact = Array.from(ribbons).some(r => r.style.display !== 'none');
            
            ribbons.forEach(r => r.style.display = isCurrentlyCompact ? 'none' : 'block');
            fulls.forEach(f => f.style.display = isCurrentlyCompact ? 'block' : 'none');
            
            if (btn) {
                btn.innerHTML = isCurrentlyCompact ? '▲ Collapse All Cards' : '▼ Expand All Cards';
            }
        }
    </script>
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>"""

# ==========================================
# MAIN INGESTION & GENERATION ENGINE
# ==========================================
def main():
    print(f"🚀 Running WeatherFootball Static Site Builder from root: {os.getcwd()}")

    effective_dt = get_effective_matchday_date()
    date_str_today = effective_dt.strftime("%Y%m%d")
    date_str_display = effective_dt.strftime("%A, %B %d, %Y")
    date_str_seo = effective_dt.strftime("%B %d, %Y")
    current_date_iso = effective_dt.strftime("%Y-%m-%d")
    
    start_future_dt = effective_dt + timedelta(days=1)
    end_future_dt = effective_dt + timedelta(days=14)
    start_date_str = start_future_dt.strftime('%Y%m%d')
    end_date_str = end_future_dt.strftime('%Y%m%d')
    date_str_future = f"{start_date_str}-{end_date_str}"

    stadiums_db = load_json(STADIUMS_FILE, {})
    validate_and_clean_stadiums_db(stadiums_db)

    master_registry = load_json(MASTER_REGISTRY_FILE, {"leagues": {}, "teams": {}})
    if "leagues" not in master_registry: master_registry["leagues"] = {}
    if "teams" not in master_registry: master_registry["teams"] = {}

    # === 1. HYDRATE CORE DIRECTORY ===
    core_index = build_hydrated_core_index()
    league_pill_map = {}

    print(f"📡 Fetching Today's Slate ({date_str_today})...")
    espn_url_today = f"https://site.api.espn.com/apis/site/v2/sports/soccer/all/scoreboard?dates={date_str_today}"
    try:
        res_today = HTTP.get(espn_url_today, timeout=15)
        if res_today.status_code == 200:
            json_today = res_today.json()
            events_today = json_today.get('events', [])
            for lg in json_today.get('leagues', []):
                if lg.get('id') and lg.get('slug'):
                    league_pill_map[str(lg['id'])] = lg['slug']
        else:
            events_today = []
    except Exception as e:
        print(f"❌ Error fetching Today: {e}")
        events_today = []

    print(f"🔭 Fetching 14-Day Global Look-Ahead ({date_str_future})...")
    espn_url_future = f"https://site.api.espn.com/apis/site/v2/sports/soccer/all/scoreboard?dates={date_str_future}"
    try:
        res_future = HTTP.get(espn_url_future, timeout=15)
        if res_future.status_code == 200:
            json_future = res_future.json()
            events_future = json_future.get('events', [])
            for lg in json_future.get('leagues', []):
                if lg.get('id') and lg.get('slug'):
                    league_pill_map[str(lg['id'])] = lg['slug']
        else:
            events_future = []
    except Exception as e:
        print(f"❌ Error fetching Future: {e}")
        events_future = []

    # Combine initial bulk events
    all_events_raw = events_today + events_future

    # === 2. CROSSOVER 14-DAY REFRESH FOR ACTIVE LEAGUES ===
    today_league_slugs = set()
    for ev in events_today:
        r_pill, r_name = resolve_event_league(ev, core_index)
        l_name = r_name or (ev.get('competitions', [{}])[0].get('altGameNote') or ev.get('league', {}).get('name') or "Global Football")
        today_league_slugs.add(slugify(l_name))

    for l_slug in today_league_slugs:
        l_meta = master_registry["leagues"].get(l_slug, {})
        l_pill = l_meta.get("pill")
        if l_pill and l_meta.get("last_crossover_date") != current_date_iso:
            print(f"🔄 CROSSOVER: Fetching targeted 14-day schedule for active league -> {l_meta.get('name', l_slug)}")
            targeted_events = fetch_espn_events_for_pill(l_pill, start_date_str, end_date_str)
            all_events_raw.extend(targeted_events)
            master_registry["leagues"][l_slug]["last_crossover_date"] = current_date_iso

    # === 3. DORMANT LEAGUE TRICKLE UPDATE (1 LEAGUE PER RUN) ===
    active_slugs_this_run = today_league_slugs
    dormant_candidates = [
        (s, data) for s, data in master_registry["leagues"].items()
        if s not in active_slugs_this_run and data.get("pill")
    ]
    if dormant_candidates:
        dormant_candidates.sort(key=lambda x: x[1].get("last_updated", 0))
        target_dormant_slug, target_dormant_data = dormant_candidates[0]
        print(f"🔄 TRICKLE UPDATE: Fetching 14-day schedule for dormant league -> {target_dormant_data.get('name')}")
        dormant_events = fetch_espn_events_for_pill(target_dormant_data["pill"], start_date_str, end_date_str)
        all_events_raw.extend(dormant_events)

    # Deduplicate events by ID
    unique_events = {}
    for ev in all_events_raw:
        if ev.get('id') and ev['id'] not in unique_events:
            unique_events[ev['id']] = ev

    today_event_ids = {e['id'] for e in events_today}
    all_games_processed = []

    print(f"⚽ Processing {len(unique_events)} total unique fixtures across the 14-day window...")
    for game_id, event in unique_events.items():
        comp = event['competitions'][0]
        
        # === 4-TIER RESOLUTION ENGINE & PILL ASSIGNMENT ===
        resolved_pill, resolved_display_name = resolve_event_league(event, core_index)

        league_list = event.get('leagues', [])
        first_league = league_list[0] if isinstance(league_list, list) and len(league_list) > 0 else {}
        league_obj = event.get('league') or comp.get('league') or first_league
        league_id = str(league_obj.get('id', ''))

        raw_name = resolved_display_name or str(comp.get('altGameNote') or league_obj.get('name') or league_obj.get('displayName') or "Global Football")
        league_name = re.sub(r'^\d{4}-\d{4}\s+', '', raw_name).strip()
        
        if ',' in league_name and not resolved_display_name:
            league_name = league_name.split(',')[0].strip()

        league_slug = slugify(league_name)

        extracted_numeric_pill = ""
        uid = event.get('uid', '')
        if uid:
            for part in uid.split('~'):
                if part.startswith('l:'):
                    extracted_numeric_pill = part.replace('l:', '')
                    break

        league_pill = (
            resolved_pill or
            extracted_numeric_pill or
            league_pill_map.get(league_id) or 
            first_league.get('slug') or 
            league_obj.get('slug') or 
            KNOWN_LEAGUE_PILLS.get(normalize_text(league_name), '')
        )

        # === EXTRACT LEAGUE LOGO ===
        clean_league = normalize_text(league_name)
        league_logo = NORMALIZED_HUMAN_LEAGUE_FLAGS.get(clean_league, "")
        
        # Bridge the 4-Tier Pill directly to the Image Dictionary if exact match fails
        if not league_logo and league_pill:
            for known_name, known_pill in KNOWN_LEAGUE_PILLS.items():
                if known_pill == league_pill and known_name in NORMALIZED_HUMAN_LEAGUE_FLAGS:
                    league_logo = NORMALIZED_HUMAN_LEAGUE_FLAGS[known_name]
                    break

        # Fallback to removing qualifying/playoff text
        if not league_logo: 
            league_logo = NORMALIZED_HUMAN_LEAGUE_FLAGS.get(re.sub(r'\s+(qualifying|qualifiers|playoffs?)\b', '', clean_league), "")
            
        # Fallback to API provided logos
        if not league_logo:
            league_logos = league_obj.get('logos', [])
            if not league_logos and first_league:
                league_logos = first_league.get('logos', [])
            league_logo = league_obj.get('logo') or (league_logos[0].get('href', '') if league_logos else '')

        # Fallback to flag CDN or emojis for obscure leagues
        if not league_logo or 'default-team-logo' in str(league_logo):
            for ctry, code in COUNTRY_FLAG_URLS.items():
                if re.search(rf'\b{ctry}\b', clean_league): 
                    league_logo = f"https://flagcdn.com/w40/{code}.png"
                    break
            if not league_logo and re.search(r'\b(africa|african|caf)\b', clean_league): league_logo = "🌍"
            if not league_logo and re.search(r'\b(international|concacaf|conmebol|uefa|olympic|nations|saff|americ)\b', clean_league): league_logo = "🌎"
            if not league_logo and 'friendly' in clean_league: league_logo = "🤝"
            if not league_logo and 'cup' in clean_league: league_logo = "🏆"
            
        league_logo = str(league_logo or "")

        home_comp = next((c for c in comp['competitors'] if c['homeAway'] == 'home'), None)
        away_comp = next((c for c in comp['competitors'] if c['homeAway'] == 'away'), None)

        if not home_comp or not away_comp: continue

        home_team = home_comp['team']['displayName']
        away_team = away_comp['team']['displayName']
        home_slug = slugify(home_team)
        away_slug = slugify(away_team)
        
        home_logos = home_comp['team'].get('logos', [])
        home_logo = home_comp['team'].get('logo', '') or (home_logos[0].get('href', '') if home_logos else '')
        away_logos = away_comp['team'].get('logos', [])
        away_logo = away_comp['team'].get('logo', '') or (away_logos[0].get('href', '') if away_logos else '')

        # === SAVE LOGO, PILL, AND TIMESTAMPS TO MASTER REGISTRY ===
        master_registry["leagues"][league_slug] = {
            "name": league_name,
            "slug": league_slug,
            "pill": league_pill,
            "logo": league_logo,
            "last_updated": datetime.datetime.now().timestamp(),
            "last_crossover_date": master_registry["leagues"].get(league_slug, {}).get("last_crossover_date", "")
        }
        master_registry["teams"][home_slug] = {"name": home_team, "slug": home_slug, "league": league_name}
        master_registry["teams"][away_slug] = {"name": away_team, "slug": away_slug, "league": league_name}

        espn_venue = comp.get('venue') or event.get('venue') or {}
        venue_id = str(espn_venue.get('id', slugify(espn_venue.get('fullName') or espn_venue.get('displayName') or home_team)))
        stadium_info = get_or_update_stadium(stadiums_db, venue_id, espn_venue, home_team=home_team)

        if stadium_info['roof'] in ["Dome", "Retractable"]:
            weather = {"status": "ok", "temp": 70, "humidity": 45, "windSpeed": 0, "precip": 0.0, "hourly": []}
        else:
            weather = fetch_open_meteo_hourly(stadium_info['lat'], stadium_info['lon'], event['date']) or {
                "status": "error", "temp": "--", "humidity": 0, "windSpeed": 0, "precip": 0.0, "hourly": []
            }

        all_games_processed.append({
            "id": game_id,
            "game_time": event['date'],
            "status": event['status']['type']['state'],
            "clock": event['status']['type'].get('shortDetail', ''),
            "league_name": league_name,
            "league_slug": league_slug,
            "league_logo": league_logo, # Injected here for the HTML renderer
            "home_team": home_team,
            "home_slug": home_slug,
            "home_logo": home_logo,
            "home_score": home_comp.get('score', '0'),
            "away_team": away_team,
            "away_slug": away_slug,
            "away_logo": away_logo,
            "away_score": away_comp.get('score', '0'),
            "stadium": stadium_info,
            "weather": weather
        })
        time.sleep(0.02)

    save_json(STADIUMS_FILE, stadiums_db)
    save_json(MASTER_REGISTRY_FILE, master_registry)

    all_games_processed.sort(key=lambda x: x['game_time'])

    league_search_options_html = "".join([f'<option value="{data["name"]}" data-url="/leagues/{slug}/"></option>\n' 
                                          for slug, data in sorted(master_registry['leagues'].items(), key=lambda x: x[1]['name']) 
                                          if slug != "global-football"])
                                          
    team_search_options_html = "".join([f'<option value="{data["name"]}" data-url="/teams/{slug}/"></option>\n' 
                                        for slug, data in sorted(master_registry['teams'].items(), key=lambda x: x[1]['name'])])

    toggle_row_html = """
        <div class="d-flex justify-content-end mb-3 px-1">
            <button id="expand-toggle-btn" class="btn btn-sm btn-white shadow-sm border fw-bold text-secondary" style="border-radius: 20px; font-size: 0.8rem;" onclick="toggleAllCards()">
                ▼ Expand All Cards
            </button>
        </div>"""

    league_urls = []
    team_urls = []

    # 7. Generate Homepage (ONLY matches strictly in Today's Slate)
    print("\n🌐 Generating Homepage (/index.html)...")
    home_games = [g for g in all_games_processed if g['id'] in today_event_ids]
    home_cards_html = ""
    
    if home_games:
        grouped_games = {}
        for g in home_games:
            lname = g['league_name']
            if lname not in grouped_games: grouped_games[lname] = {"slug": g['league_slug'], "games": []}
            grouped_games[lname]["games"].append(g)

        # Build Homepage Quick-Jump Select options from leagues on today's schedule
        home_jump_options = '<option value="" selected disabled>⚽ Jump to League...</option>\n'
        for lname, ldata in sorted(grouped_games.items(), key=lambda x: x[0]):
            home_jump_options += f'                    <option value="league-section-{ldata["slug"]}">{lname}</option>\n'

        home_toggle_row_html = f"""
        <div class="d-flex justify-content-between align-items-center mb-3 px-1 flex-wrap gap-2">
            <div>
                <select class="form-select form-select-sm fw-bold shadow-sm text-secondary" style="max-width: 240px; border-radius: 20px; font-size: 0.8rem;" onchange="if(this.value) {{ const target = document.getElementById(this.value); if(target) target.scrollIntoView({{behavior: 'smooth', block: 'start'}}); }}">
                    {home_jump_options}
                </select>
            </div>
            <div>
                <button id="expand-toggle-btn" class="btn btn-sm btn-white shadow-sm border fw-bold text-secondary" style="border-radius: 20px; font-size: 0.8rem;" onclick="toggleAllCards()">
                    ▼ Expand All Cards
                </button>
            </div>
        </div>"""

        for lname, ldata in sorted(grouped_games.items(), key=lambda x: x[0]):
            # Optional: Get the league logo to display in the section header!
            section_league_logo = ldata['games'][0].get('league_logo', '') if ldata['games'] else ''
            
            # Format the logo dynamically based on whether it is a URL or an emoji
            if section_league_logo and section_league_logo.startswith('http'):
                sec_logo_img = f'<img src="{section_league_logo}" style="width: 20px; height: 20px; object-fit: contain; margin-right: 6px;" onerror="this.style.display=\'none\'">'
            elif section_league_logo:
                sec_logo_img = f'<span style="font-size: 1.1rem; margin-right: 6px;">{section_league_logo}</span>'
            else:
                sec_logo_img = ''
                
            home_cards_html += f"""
            <div class="col-12 w-100 px-1" id="league-section-{ldata['slug']}">
                <div class="league-section-title">
                    <a href="/leagues/{ldata['slug']}/">{sec_logo_img}{lname} <span style="font-size: 0.65rem; margin-left: 4px;">➔</span></a>
                </div>
            </div>"""
            for g in ldata['games']:
                home_cards_html += render_game_card_html(g, is_compact_default=True)
    else:
        home_toggle_row_html = ""
        home_cards_html = """
        <div class="col-12 text-center py-5">
            <div class="alert alert-light border shadow-sm d-inline-block px-4 py-3">
                <h5>⚽ No Football Matches Scheduled Today</h5>
                <p class="text-muted mb-0 small">Use the search bars above to view upcoming match schedules, pitch conditions, and stadium wind forecasts.</p>
            </div>
        </div>"""

    schema_json = json.dumps({"@context": "https://schema.org", "@type": "WebSite", "name": "Weather Football", "url": SITE_DOMAIN}, indent=2)
    home_content = MASTER_HTML_TEMPLATE
    home_content = home_content.replace("__PAGE_TITLE__", f"Today's Football Game Weather Forecasts & Stadium Pitch Conditions ({date_str_seo})")
    home_content = home_content.replace("__META_DESC__", f"View live game weather today ({date_str_seo}) across global football leagues. Track stadium wind speed, hourly rain risks, relative humidity, and pitch impact analytics.")
    home_content = home_content.replace("__SEO_KEYWORDS__", "today game weather, live football stadium weather, pitch wind speed, rain delay football, today match weather forecast")
    home_content = home_content.replace("__CANONICAL_URL__", f"{SITE_DOMAIN}/")
    home_content = home_content.replace("__OG_TITLE__", f"Today's Live Football Stadium Weather & Wind Forecasts")
    home_content = home_content.replace("__OG_DESC__", f"Track real-time pitch rain risks, stadium wind direction, and weather impact analytics for today's football matches.")
    home_content = home_content.replace("__HERO_HEADING__", "Today's Live Football Game Weather")
    home_content = home_content.replace("__HERO_SUBHEADING__", f"Matchday Slate & Stadium Pitch Forecasts for {date_str_display}")
    home_content = home_content.replace("__TOGGLE_CONTROLS_ROW__", home_toggle_row_html)
    home_content = home_content.replace("__LEAGUE_SEARCH_OPTIONS__", league_search_options_html)
    home_content = home_content.replace("__TEAM_SEARCH_OPTIONS__", team_search_options_html)
    home_content = home_content.replace("__MATCH_CARDS_GRID__", home_cards_html)
    home_content = home_content.replace("__SCHEMA_JSON__", schema_json)
    write_if_changed("index.html", home_content)

    # 8. Generate League Pages (From Master Registry - Shows ALL 14-day games)
    print(f"\n🏆 Generating {len(master_registry['leagues'])} League Pages (/leagues/)...")
    for l_slug, l_data in master_registry['leagues'].items():
        if l_slug == "global-football": continue
        
        league_urls.append(f"{SITE_DOMAIN}/leagues/{l_slug}/")
        league_games = [g for g in all_games_processed if g['league_slug'] == l_slug]
        has_game_today = any(g['id'] in today_event_ids for g in league_games)
        
        if league_games:
            # === NEW: Date Grouping Headers for non-today multi-date leagues ===
            unique_dates = list(dict.fromkeys([g['game_time'][:10] for g in league_games]))
            if not has_game_today and len(unique_dates) > 1:
                cards_html = ""
                grouped_by_date = {}
                for g in league_games:
                    d_str = g['game_time'][:10]
                    if d_str not in grouped_by_date:
                        grouped_by_date[d_str] = []
                    grouped_by_date[d_str].append(g)
                    
                for d_str, date_games in sorted(grouped_by_date.items(), key=lambda x: x[0]):
                    try:
                        d_obj = datetime.datetime.strptime(d_str, '%Y-%m-%d')
                        display_date = d_obj.strftime('%A, %B %d')
                    except Exception:
                        display_date = d_str
                        
                    cards_html += f"""
            <div class="col-12 w-100 px-1">
                <div class="league-section-title">
                    📅 {display_date}
                </div>
            </div>"""
                    for g in date_games:
                        cards_html += render_game_card_html(g, is_compact_default=True)
            else:
                cards_html = "".join([render_game_card_html(g, is_compact_default=True) for g in league_games])
        else:
            cards_html = render_dormant_banner()

        if has_game_today:
            page_title = f"Today's {l_data['name']} Match Weather Forecasts & Stadium Pitch Wind ({date_str_seo})"
            meta_desc = f"Today's {l_data['name']} match weather forecasts and stadium pitch conditions for {date_str_seo}. Check stadium wind speeds, rain delay risks, pitch humidity, and hourly forecasts."
            hero_heading = f"Today's {l_data['name']} Match Weather ({date_str_seo})"
            hero_subheading = f"Live Stadium Wind, Rain Risks & Pitch Analytics for {date_str_display}"
        else:
            page_title = f"{l_data['name']} Match Weather Forecasts & Stadium Pitch Wind"
            meta_desc = f"Live game weather and forecasts for {l_data['name']} matches. Check stadium wind speeds, rain delay risks, pitch humidity, and hourly forecasts."
            hero_heading = f"{l_data['name']} Weather"
            hero_subheading = f"Live Stadium Wind, Rain Risks & Upcoming Pitch Analytics"

        content = MASTER_HTML_TEMPLATE
        content = content.replace("__PAGE_TITLE__", page_title)
        content = content.replace("__META_DESC__", meta_desc)
        content = content.replace("__SEO_KEYWORDS__", f"{l_data['name']} weather today, {l_data['name']} stadium wind, {l_data['name']} rain forecast, football match weather today")
        content = content.replace("__CANONICAL_URL__", f"{SITE_DOMAIN}/leagues/{l_slug}/")
        content = content.replace("__OG_TITLE__", page_title)
        content = content.replace("__OG_DESC__", meta_desc)
        content = content.replace("__HERO_HEADING__", hero_heading)
        content = content.replace("__HERO_SUBHEADING__", hero_subheading)
        content = content.replace("__TOGGLE_CONTROLS_ROW__", toggle_row_html if league_games else "")
        content = content.replace("__LEAGUE_SEARCH_OPTIONS__", league_search_options_html)
        content = content.replace("__TEAM_SEARCH_OPTIONS__", team_search_options_html)
        content = content.replace("__MATCH_CARDS_GRID__", cards_html)
        content = content.replace("__SCHEMA_JSON__", "")

        write_if_changed(os.path.join("leagues", l_slug, "index.html"), content)

    # 9. Generate Team Pages (From Master Registry - Shows ALL 14-day games fully expanded)
    print(f"\n🛡️ Generating {len(master_registry['teams'])} Team Pages (/teams/)...")
    for t_slug, t_data in master_registry['teams'].items():
        team_urls.append(f"{SITE_DOMAIN}/teams/{t_slug}/")
        team_games = [g for g in all_games_processed if g['home_slug'] == t_slug or g['away_slug'] == t_slug]
        
        today_games_for_team = [g for g in team_games if g['id'] in today_event_ids]
        has_game_today = len(today_games_for_team) > 0
        
        if team_games:
            cards_html = "".join([render_game_card_html(g, is_compact_default=False) for g in team_games])
            next_game = today_games_for_team[0] if has_game_today else team_games[0]
            matchup_str = f"{next_game['home_team']} vs {next_game['away_team']}"
            venue_str = next_game['stadium']['name']
        else:
            cards_html = render_dormant_banner()
            matchup_str = ""
            venue_str = ""

        if has_game_today:
            page_title = f"Today's {matchup_str} Weather Forecast at {venue_str} ({date_str_seo})"
            meta_desc = f"Today's {matchup_str} match weather forecast at {venue_str} for {date_str_seo}. Track stadium wind speed, rain delay risks, temperature, and live pitch conditions."
            hero_heading = f"Today's {matchup_str} Weather at {venue_str} ({date_str_seo})"
            hero_subheading = f"League: {t_data.get('league', 'Global Football')} | Stadium Pitch Analytics for {date_str_display}"
        else:
            if team_games:
                page_title = f"Weather Forecast for {matchup_str} at {venue_str} | Pitch Wind & Rain"
                meta_desc = f"Live weather forecast for the upcoming {matchup_str} match at {venue_str}. Track stadium wind speed, rain delay risks, and pitch conditions."
            else:
                page_title = f"{t_data['name']} Game Weather Forecast | Stadium Wind & Rain"
                meta_desc = f"Game weather analytics, stadium wind speed, and rain delay risks for {t_data['name']}."
            hero_heading = f"{t_data['name']} Weather"
            hero_subheading = f"League: {t_data.get('league', 'Global Football')} | Stadium Pitch Analytics"

        content = MASTER_HTML_TEMPLATE
        content = content.replace("__PAGE_TITLE__", page_title)
        content = content.replace("__META_DESC__", meta_desc)
        content = content.replace("__SEO_KEYWORDS__", f"{t_data['name']} game weather, {t_data['name']} stadium wind, {t_data['name']} pitch forecast, {t_data['name']} rain delay risk")
        content = content.replace("__CANONICAL_URL__", f"{SITE_DOMAIN}/teams/{t_slug}/")
        content = content.replace("__OG_TITLE__", page_title)
        content = content.replace("__OG_DESC__", meta_desc)
        content = content.replace("__HERO_HEADING__", hero_heading)
        content = content.replace("__HERO_SUBHEADING__", hero_subheading)
        content = content.replace("__TOGGLE_CONTROLS_ROW__", "")
        content = content.replace("__LEAGUE_SEARCH_OPTIONS__", league_search_options_html)
        content = content.replace("__TEAM_SEARCH_OPTIONS__", team_search_options_html)
        content = content.replace("__MATCH_CARDS_GRID__", cards_html)
        content = content.replace("__SCHEMA_JSON__", "")

        write_if_changed(os.path.join("teams", t_slug, "index.html"), content)

    # 10. Generate Sitemaps
    print("\n🗺️ Generating Sitemaps...")
    lastmod_date = datetime.datetime.now(timezone.utc).strftime("%Y-%m-%d")

    sitemap_main_content = f'''<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>{SITE_DOMAIN}/</loc>
    <lastmod>{lastmod_date}</lastmod>
    <changefreq>always</changefreq>
    <priority>1.0</priority>
  </url>
</urlset>'''
    write_if_changed("sitemap-main.xml", sitemap_main_content)

    sitemap_leagues_content = '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
    for url in league_urls:
        sitemap_leagues_content += f"  <url>\n    <loc>{url}</loc>\n    <lastmod>{lastmod_date}</lastmod>\n    <changefreq>daily</changefreq>\n  </url>\n"
    sitemap_leagues_content += "</urlset>"
    write_if_changed("sitemap-leagues.xml", sitemap_leagues_content)

    sitemap_teams_content = '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
    for url in team_urls:
        sitemap_teams_content += f"  <url>\n    <loc>{url}</loc>\n    <lastmod>{lastmod_date}</lastmod>\n    <changefreq>daily</changefreq>\n  </url>\n"
    sitemap_teams_content += "</urlset>"
    write_if_changed("sitemap-teams.xml", sitemap_teams_content)

    sitemap_index_content = f'''<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap>
    <loc>{SITE_DOMAIN}/sitemap-main.xml</loc>
    <lastmod>{lastmod_date}</lastmod>
  </sitemap>
  <sitemap>
    <loc>{SITE_DOMAIN}/sitemap-leagues.xml</loc>
    <lastmod>{lastmod_date}</lastmod>
  </sitemap>
  <sitemap>
    <loc>{SITE_DOMAIN}/sitemap-teams.xml</loc>
    <lastmod>{lastmod_date}</lastmod>
  </sitemap>
</sitemapindex>'''
    write_if_changed("sitemap.xml", sitemap_index_content)

    print("✅ Build complete! Weather Football static generator updated with 4-tier league/pill resolution.")

if __name__ == "__main__":
    main()
