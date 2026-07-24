import os
import json
import re
import time
import requests
import datetime
import unicodedata
from datetime import timedelta, timezone

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

# HTTP Session with retry capabilities
HTTP = requests.Session()

# ==========================================
# HELPER FUNCTIONS
# ==========================================
def slugify(text):
    """
    Convert text into clean, ASCII-only, SEO-friendly URL slug.
    Strips accents/diacritics (e.g. 'América' -> 'america', 'Rubio Ñú' -> 'rubio-nu')
    """
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

    effective_time = now_est - timedelta(hours=3)
    return effective_time

# ==========================================
# DATABASE LOADERS
# ==========================================
def load_stadiums_db():
    if os.path.exists(STADIUMS_FILE):
        try:
            with open(STADIUMS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"⚠️ Error loading {STADIUMS_FILE}: {e}")
    return {}

def save_stadiums_db(stadiums_db):
    content = json.dumps(stadiums_db, indent=4, sort_keys=True)
    write_if_changed(STADIUMS_FILE, content)

def load_master_registry():
    if os.path.exists(MASTER_REGISTRY_FILE):
        try:
            with open(MASTER_REGISTRY_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"⚠️ Error loading {MASTER_REGISTRY_FILE}: {e}")
    return {"leagues": {}, "teams": {}}

def save_master_registry(registry):
    content = json.dumps(registry, indent=4, sort_keys=True)
    write_if_changed(MASTER_REGISTRY_FILE, content)

# ==========================================
# STADIUM GEOCODING (OPEN-METEO)
# ==========================================
def geocode_query_open_meteo(query_text):
    """Hits Open-Meteo's fast geocoding API."""
    if not query_text or not query_text.strip():
        return 0.0, 0.0

    url = f"https://geocoding-api.open-meteo.com/v1/search?name={requests.utils.quote(query_text)}&count=1&language=en&format=json"
    try:
        resp = HTTP.get(url, timeout=8)
        if resp.status_code == 200:
            data = resp.json()
            results = data.get("results", [])
            if results:
                return float(results[0]["latitude"]), float(results[0]["longitude"])
    except Exception as e:
        print(f"   ⚠️ Geocode error for '{query_text}': {e}")
    return 0.0, 0.0

def geocode_venue_multi_stage(venue_name, city, country, home_team):
    """
    5-Stage Cascading Geocoder to guarantee coordinates when possible:
    1. Stadium Name + Clean City
    2. Stadium Name Alone
    3. Clean City + Country Fallback
    4. Home Team Name Fallback
    5. Country Fallback (Capital/Centroid)
    """
    clean_city = city.split(',')[0].strip() if city else ""

    if venue_name and venue_name not in ["Unknown Stadium", "Venue Unlisted"] and clean_city:
        lat, lon = geocode_query_open_meteo(f"{venue_name} {clean_city}")
        if lat != 0.0 and lon != 0.0: return lat, lon

    if venue_name and venue_name not in ["Unknown Stadium", "Venue Unlisted"]:
        lat, lon = geocode_query_open_meteo(venue_name)
        if lat != 0.0 and lon != 0.0: return lat, lon

    if clean_city:
        loc_q = f"{clean_city}, {country}".strip(", ") if country else clean_city
        lat, lon = geocode_query_open_meteo(loc_q)
        if lat != 0.0 and lon != 0.0: return lat, lon

    if home_team and home_team != "TBD":
        lat, lon = geocode_query_open_meteo(f"{home_team} stadium")
        if lat != 0.0 and lon != 0.0: return lat, lon

        lat, lon = geocode_query_open_meteo(home_team)
        if lat != 0.0 and lon != 0.0: return lat, lon

    if country:
        lat, lon = geocode_query_open_meteo(country)
        if lat != 0.0 and lon != 0.0: return lat, lon

    return 0.0, 0.0

def get_or_update_stadium(stadiums_db, venue_id, venue_info, home_team=""):
    """Retrieves cached stadium data or geocodes with multi-tier fallback."""
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
        "id": venue_id,
        "name": name,
        "city": city,
        "country": country,
        "roof": "Dome" if is_indoor else "Open",
        "surface": "Grass",
        "lat": lat,
        "lon": lon
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
        "latitude": lat,
        "longitude": lon,
        "current": "temperature_2m,relative_humidity_2m,wind_speed_10m,precipitation",
        "hourly": "temperature_2m,relative_humidity_2m,precipitation_probability,precipitation,weather_code",
        "temperature_unit": "fahrenheit",
        "wind_speed_unit": "mph",
        "precipitation_unit": "inch",
        "timezone": "GMT",
        "start_date": game_date_str,
        "end_date": next_day_str
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
                    code = data['hourly'].get("weather_code", [0])[i]
                    hourly_slice.append({
                        "timestamp": time_array[i] + "Z",
                        "temp": int(data['hourly'].get("temperature_2m", [72])[i]),
                        "humidity": int(data['hourly'].get("relative_humidity_2m", [50])[i]),
                        "precipChance": data['hourly'].get("precipitation_probability", [0])[i],
                        "isThunderstorm": code in [95, 96, 99],
                        "isSnow": code in [71, 73, 75, 77, 85, 86]
                    })

                return {
                    "status": "ok",
                    "temp": int(current.get('temperature_2m', 72)),
                    "humidity": int(current.get('relative_humidity_2m', 50)),
                    "windSpeed": int(current.get('wind_speed_10m', 0)),
                    "precip": round(float(current.get('precipitation', 0.0)), 2),
                    "hourly": hourly_slice
                }
        except requests.RequestException:
            time.sleep(1)

    print(f"   ⚠️ Open-Meteo request failed after retries for ({lat}, {lon})")
    return None

# ==========================================
# HTML GENERATORS
# ==========================================
def render_game_card_html(game, is_compact_default=True):
    """Generates the full weather card HTML for a game happening today."""
    w = game['weather']
    is_dome = game['stadium']['roof'] in ["Dome", "Retractable"]
    is_no_coords = w.get('status') == "no_coords"
    is_too_early = w.get('status') in ["too_early"] or w.get('temp') == "--"

    hourly = w.get('hourly', [])
    max_pop = max([h.get('precipChance', 0) for h in hourly], default=0) if hourly else 0
    humidity = w.get('humidity', 50)

    bg_class = "bg-weather-sunny"
    border_class = ""
    if is_no_coords or is_too_early:
        bg_class = "bg-light"
    elif is_dome:
        bg_class = "bg-weather-roof"
    elif max_pop >= 50 or w['precip'] > 0.5:
        border_class = "border-danger border-3"
        bg_class = "bg-weather-storm"
    elif max_pop >= 20 or w['precip'] > 0:
        border_class = "border-warning border-3"
        bg_class = "bg-weather-rain"
    elif w['windSpeed'] >= 15:
        bg_class = "bg-weather-cloudy"

    if game['status'] == 'in':
        badge_text = game.get('clock') or 'LIVE'
        badge_style = "bg-danger text-white border-danger"
    elif game['status'] == 'post':
        badge_text = "FINAL"
        badge_style = "bg-secondary text-white border-secondary"
    else:
        try:
            d = datetime.datetime.fromisoformat(game['game_time'].replace('Z', '+00:00'))
            badge_text = d.strftime('%a %I:%M %p')
        except Exception:
            badge_text = "SCHEDULED"
        badge_style = "bg-light text-dark border"

    radar_url = f"https://embed.windy.com/embed2.html?lat={game['stadium']['lat']}&lon={game['stadium']['lon']}&zoom=10&level=surface&overlay=rain&product=ecmwf"

    if is_no_coords:
        weather_emoji_line = "⚠️ Weather Info<br>Not Available"
    elif is_dome:
        weather_emoji_line = f"Roof Closed<br>🌡️{w['temp']}° 💧{humidity}%"
    elif is_too_early:
        weather_emoji_line = "🔭 Forecast<br>Pending"
    else:
        weather_emoji_line = f"🌧️{max_pop}% 🌡️{w['temp']}°<br>💨{w['windSpeed']}mph 💧{humidity}%"

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
            if h['precipChance'] >= 30:
                icon = "⛈️" if h['isThunderstorm'] else ("🌨️" if h['isSnow'] else "🌧️")
            elif h['precipChance'] > 0:
                icon = "⛅"

            pop_str = f"{h['precipChance']}%" if h['precipChance'] >= 20 else "&nbsp;"
            hours_markup += f"""
                <div class="hour-card">
                    <div class="hour-time">{hr_str}</div>
                    <div class="hour-icon">{icon}</div>
                    <div class="hour-pop">{pop_str}</div>
                    <div class="hour-temp">{h['temp']}°</div>
                </div>"""
        hourly_html = f'<div class="hourly-scroll-container">{hours_markup}</div>'

    if is_no_coords:
        weather_section = """
        <div class="text-center p-3 mt-2 border-top">
            <h6 class="text-warning fw-bold mb-1">⚠️ Weather Info Not Available</h6>
            <p class="small text-muted mb-0" style="font-size: 0.75rem;">Stadium coordinates or venue location unlisted for this fixture.</p>
        </div>"""
    elif is_too_early:
        weather_section = """
        <div class="text-center p-3 mt-2 border-top">
            <h6 class="text-muted mb-1">🔭 Early Forecast</h6>
            <p class="small text-muted mb-0" style="font-size: 0.75rem;">Stadium weather details available ~14 days before kickoff.</p>
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

    return f"""
    <div class="col-md-6 col-lg-4 animate-card mb-3 px-1" id="game-{game['id']}">
        <div class="card game-card shadow-sm {border_class} {bg_class}">
            <!-- COMPACT RIBBON VIEW -->
            <div class="ribbon-view p-2 position-relative" onclick="toggleSingleCard(this)" style="cursor: pointer; display: {show_ribbon};">
                <div class="d-flex align-items-center justify-content-start mb-2">
                    <span class="badge {badge_style} flex-shrink-0" style="font-size: 0.65rem;">{badge_text}</span>
                </div>
                
                <div class="d-flex align-items-center justify-content-between gap-2">
                    <div class="d-flex flex-column gap-1 text-truncate" style="flex: 1; min-width: 0;">
                        <div class="d-flex align-items-center text-truncate gap-1">
                            <img src="{game['away_logo']}" style="width: 18px; height: 18px; object-fit: contain;" onerror="this.style.display='none'">
                            <span class="fw-bold text-dark text-truncate" style="font-size: 0.85rem;">{game['away_team']}</span>
                        </div>
                        <div class="d-flex align-items-center text-truncate gap-1">
                            <img src="{game['home_logo']}" style="width: 18px; height: 18px; object-fit: contain;" onerror="this.style.display='none'">
                            <span class="fw-bold text-dark text-truncate" style="font-size: 0.85rem;">{game['home_team']}</span>
                        </div>
                    </div>
                    <div class="d-flex align-items-center justify-content-center ps-2 border-start flex-shrink-0" style="min-width: 120px;">
                        <span class="fw-bold text-primary text-end" style="font-size: 0.72rem; line-height: 1.35;">
                            {weather_emoji_line}
                        </span>
                    </div>
                </div>
            </div>

            <!-- EXPANDED FULL CARD VIEW -->
            <div class="full-card-view" onclick="toggleSingleCard(this)" style="cursor: pointer; display: {show_full};">
                <div class="d-flex align-items-center justify-content-between p-2 bg-dark text-white">
                    <div class="d-flex align-items-center text-truncate">
                        <span class="fw-bold text-truncate" style="font-size: 0.75rem;">{game['league_name']}</span>
                    </div>
                    <span class="badge {badge_style} flex-shrink-0" style="font-size: 0.65rem;">{badge_text}</span>
                </div>
                
                <div class="card-body px-2 pt-2 pb-2">
                    <div class="d-flex justify-content-between align-items-center mb-2">
                        <span class="stadium-name text-truncate fw-bold" style="font-size: 0.8rem;">📍 {game['stadium']['name']}</span>
                    </div>
                    
                    <div class="d-flex justify-content-between align-items-center px-1 mb-1">
                        <div class="d-flex align-items-center text-truncate" style="width: 45%;">
                            <img src="{game['away_logo']}" class="me-2" style="width: 24px; height: 24px; object-fit: contain;" onerror="this.style.display='none'">
                            <a href="/teams/{game['away_slug']}/" class="text-dark text-decoration-none fw-bold text-truncate" style="font-size: 0.95rem;" onclick="event.stopPropagation();">{game['away_team']}</a>
                        </div>
                        <div class="text-center text-muted fw-bold" style="width: 10%; font-size: 0.8rem;">vs</div>
                        <div class="d-flex align-items-center justify-content-end text-truncate" style="width: 45%;">
                            <a href="/teams/{game['home_slug']}/" class="text-dark text-decoration-none fw-bold text-truncate text-end me-2" style="font-size: 0.95rem;" onclick="event.stopPropagation();">{game['home_team']}</a>
                            <img src="{game['home_logo']}" style="width: 24px; height: 24px; object-fit: contain;" onerror="this.style.display='none'">
                        </div>
                    </div>
                    
                    {weather_section}
                </div>
            </div>
        </div>
    </div>"""

def render_future_card_html(game):
    """Generates the static banner for the 14-day look-ahead."""
    try:
        dt = datetime.datetime.fromisoformat(game['game_time'].replace('Z', '+00:00'))
        formatted_date = dt.strftime('%a, %b %d at %I:%M %p UTC')
    except Exception:
        formatted_date = "Date TBD"

    return f"""
    <div class="col-12 mb-3 px-2">
        <div class="card p-4 text-center border shadow-sm bg-light h-100" style="border-radius: 12px;">
            <div class="mb-2">
                <span class="badge bg-secondary px-3 py-1">NO MATCH TODAY</span>
            </div>
            <h6 class="fw-bold text-muted mb-3 text-uppercase" style="font-size: 0.75rem; letter-spacing: 1px;">Next Scheduled Match</h6>
            
            <div class="d-flex justify-content-center align-items-center mb-3 gap-2">
                <div class="text-end" style="flex:1;">
                    <img src="{game.get('away_logo', '')}" style="width: 24px; height: 24px; object-fit: contain;" onerror="this.style.display='none'">
                    <div class="fw-bold text-dark mt-1" style="font-size: 0.85rem;">{game['away_team']}</div>
                </div>
                <div class="text-muted fw-bold" style="font-size: 0.8rem;">@</div>
                <div class="text-start" style="flex:1;">
                    <img src="{game.get('home_logo', '')}" style="width: 24px; height: 24px; object-fit: contain;" onerror="this.style.display='none'">
                    <div class="fw-bold text-dark mt-1" style="font-size: 0.85rem;">{game['home_team']}</div>
                </div>
            </div>

            <div class="text-primary fw-bold" style="font-size: 0.85rem;">📅 {formatted_date}</div>
            <div class="small text-muted mt-1">📍 {game.get('stadium_name', 'TBD Stadium')}</div>
            <div class="small text-muted mt-3 pt-3 border-top" style="font-size: 0.7rem;">Weather forecast will be available roughly 14 days before kickoff.</div>
        </div>
    </div>
    """

def render_dormant_banner():
    """Generates the static banner for teams with no games in 14 days."""
    return """
    <div class="col-12 mb-3 px-2">
        <div class="card p-5 text-center border rounded bg-light shadow-sm">
            <span class="fs-1 mb-2 d-block">💤</span>
            <h6 class="fw-bold text-secondary mb-1">No Upcoming Fixtures</h6>
            <p class="small text-muted mb-0">This team does not have a scheduled match in the next 14 days.</p>
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
    <meta name="description" content="__META_DESC__">
    <meta name="keywords" content="__SEO_KEYWORDS__">
    <link rel="canonical" href="__CANONICAL_URL__" />

    <!-- Favicons -->
    <link rel="icon" type="image/svg+xml" href="/favicon.svg">
    <link rel="icon" type="image/png" sizes="96x96" href="/favicon-96x96.png">
    <link rel="shortcut icon" href="/favicon.ico">
    <link rel="apple-touch-icon" sizes="180x180" href="/apple-touch-icon.png">
    <link rel="manifest" href="/site.webmanifest">
    
    <!-- OpenGraph / Social Meta -->
    <meta property="og:title" content="__OG_TITLE__">
    <meta property="og:description" content="__OG_DESC__">
    <meta property="og:url" content="__CANONICAL_URL__">
    <meta property="og:type" content="website">
    
    <!-- Twitter Tags -->
    <meta name="twitter:card" content="summary">
    <meta name="twitter:title" content="__OG_TITLE__">
    <meta name="twitter:description" content="__OG_DESC__">
    
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
        
        /* SLEEK LEAGUE HEADER DIVIDER */
        .league-section-title { 
            font-size: 0.75rem; 
            font-weight: 800; 
            text-transform: uppercase; 
            letter-spacing: 0.5px; 
            color: #6c757d; 
            margin: 1.5rem 0 0.5rem 0.25rem; 
            display: flex; 
            align-items: center; 
        }
        .league-section-title a { 
            color: inherit; 
            text-decoration: none; 
            transition: color 0.2s; 
            display: flex; 
            align-items: center; 
        }
        .league-section-title a:hover { color: #0d6efd; }
        .league-section-title::after { 
            content: ""; 
            flex: 1; 
            border-bottom: 1px solid #e9ecef; 
            margin-left: 10px; 
        }

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
                <!-- LEAGUE SEARCH -->
                <input list="league-search-options" id="league-search-input" class="form-control form-control-sm fw-bold shadow-sm" style="background-color: #1e293b; color: #f8f9fa; border: 1px solid #334155; max-width: 160px;" placeholder="🏆 League..." onchange="if(this.value) { const opt = document.querySelector('#league-search-options option[value=\\''+this.value+'\\']'); if(opt) window.location.href = opt.dataset.url; }">
                <datalist id="league-search-options">
__LEAGUE_SEARCH_OPTIONS__
                </datalist>

                <!-- TEAM SEARCH -->
                <input list="team-search-options" id="team-search-input" class="form-control form-control-sm fw-bold shadow-sm" style="background-color: #1e293b; color: #f8f9fa; border: 1px solid #334155; max-width: 160px;" placeholder="🔍 Team..." onchange="if(this.value) { const opt = document.querySelector('#team-search-options option[value=\\''+this.value+'\\']'); if(opt) window.location.href = opt.dataset.url; }">
                <datalist id="team-search-options">
__TEAM_SEARCH_OPTIONS__
                </datalist>

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
        
        <div class="row w-100 m-0 p-0 justify-content-center">
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
        function showRadar(url, venueName) {
            document.getElementById('radarModalTitle').innerText = 'Radar: ' + venueName;
            document.getElementById('radarFrame').src = url;
            new bootstrap.Modal(document.getElementById('radarModal')).show();
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

    # 1. Effective Date Calculation
    effective_dt = get_effective_matchday_date()
    date_str_today = effective_dt.strftime("%Y%m%d")
    date_str_display = effective_dt.strftime("%A, %B %d, %Y")
    date_str_seo = effective_dt.strftime("%B %d, %Y")
    
    start_future_dt = effective_dt + timedelta(days=1)
    end_future_dt = effective_dt + timedelta(days=14)
    date_str_future = f"{start_future_dt.strftime('%Y%m%d')}-{end_future_dt.strftime('%Y%m%d')}"

    # 2. Load Databases
    stadiums_db = load_stadiums_db()
    master_registry = load_master_registry()

    # 3. Fetch Master ESPN Scoreboards (Today + Future)
    print(f"📡 Fetching Today's Slate ({date_str_today})...")
    espn_url_today = f"https://site.api.espn.com/apis/site/v2/sports/soccer/all/scoreboard?dates={date_str_today}"
    try:
        res_today = HTTP.get(espn_url_today, timeout=15)
        events_today = res_today.json().get('events', []) if res_today.status_code == 200 else []
    except Exception as e:
        print(f"❌ Error fetching Today: {e}")
        events_today = []

    print(f"🔭 Fetching 14-Day Look-Ahead ({date_str_future})...")
    espn_url_future = f"https://site.api.espn.com/apis/site/v2/sports/soccer/all/scoreboard?dates={date_str_future}"
    try:
        res_future = HTTP.get(espn_url_future, timeout=15)
        events_future = res_future.json().get('events', []) if res_future.status_code == 200 else []
    except Exception as e:
        print(f"❌ Error fetching Future: {e}")
        events_future = []

    # 4. Process Today's Games & Update Registry
    today_games = []
    
    for event in events_today:
        game_id = event['id']
        comp = event['competitions'][0]
        
        league_name = (
            comp.get('altGameNote') or 
            event.get('league', {}).get('name') or 
            comp.get('league', {}).get('name') or 
            "Global Football"
        )
        league_slug = slugify(league_name)

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

        # Update Master Registry
        master_registry["leagues"][league_slug] = {"name": league_name, "slug": league_slug}
        master_registry["teams"][home_slug] = {"name": home_team, "slug": home_slug, "league": league_name}
        master_registry["teams"][away_slug] = {"name": away_team, "slug": away_slug, "league": league_name}

        # Setup Game Payload (Geocode & Weather)
        espn_venue = comp.get('venue') or event.get('venue') or {}
        venue_id = str(espn_venue.get('id', slugify(espn_venue.get('fullName') or espn_venue.get('displayName') or home_team)))
        stadium_info = get_or_update_stadium(stadiums_db, venue_id, espn_venue, home_team=home_team)

        if stadium_info['roof'] in ["Dome", "Retractable"]:
            weather = {"status": "ok", "temp": 70, "humidity": 45, "windSpeed": 0, "precip": 0.0, "hourly": []}
        else:
            weather = fetch_open_meteo_hourly(stadium_info['lat'], stadium_info['lon'], event['date']) or {
                "status": "error", "temp": "--", "humidity": 0, "windSpeed": 0, "precip": 0.0, "hourly": []
            }

        today_games.append({
            "id": game_id,
            "game_time": event['date'],
            "status": event['status']['type']['state'],
            "clock": event['status']['type'].get('shortDetail', ''),
            "league_name": league_name,
            "league_slug": league_slug,
            "home_team": home_team,
            "home_slug": home_slug,
            "home_logo": home_logo,
            "away_team": away_team,
            "away_slug": away_slug,
            "away_logo": away_logo,
            "stadium": stadium_info,
            "weather": weather
        })

    # 5. Process Future Games (Light Parse) & Update Registry
    future_games = []
    for event in events_future:
        comp = event['competitions'][0]
        league_name = comp.get('altGameNote') or event.get('league', {}).get('name') or comp.get('league', {}).get('name') or "Global Football"
        league_slug = slugify(league_name)
        
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
        
        # Update Master Registry
        master_registry["leagues"][league_slug] = {"name": league_name, "slug": league_slug}
        master_registry["teams"][home_slug] = {"name": home_team, "slug": home_slug, "league": league_name}
        master_registry["teams"][away_slug] = {"name": away_team, "slug": away_slug, "league": league_name}
        
        espn_venue = comp.get('venue') or event.get('venue') or {}
        
        future_games.append({
            "game_time": event['date'],
            "league_slug": league_slug,
            "home_team": home_team,
            "home_slug": home_slug,
            "home_logo": home_logo,
            "away_team": away_team,
            "away_slug": away_slug,
            "away_logo": away_logo,
            "stadium_name": espn_venue.get('fullName') or espn_venue.get('displayName') or 'TBD Stadium'
        })

    # Save cleanly using existing helper function implementations
    save_stadiums_db(stadiums_db)
    save_master_registry(master_registry)

    today_games.sort(key=lambda x: x['game_time'])

    # 6. Build Master Search Options
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

    sitemap_urls = [f"{SITE_DOMAIN}/"]

    # 7. Generate Homepage
    print("\n🌐 Generating Homepage (/index.html)...")
    home_cards_html = ""
    if today_games:
        grouped_games = {}
        for g in today_games:
            lname = g['league_name']
            if lname not in grouped_games: grouped_games[lname] = {"slug": g['league_slug'], "games": []}
            grouped_games[lname]["games"].append(g)

        for lname, ldata in sorted(grouped_games.items(), key=lambda x: x[0]):
            ldata['games'].sort(key=lambda x: x['game_time'])
            home_cards_html += f"""
            <div class="col-12 w-100 px-1">
                <div class="league-section-title">
                    <a href="/leagues/{ldata['slug']}/">{lname} <span style="font-size: 0.65rem; margin-left: 4px;">➔</span></a>
                </div>
            </div>"""
            for g in ldata['games']:
                home_cards_html += render_game_card_html(g, is_compact_default=True)
    else:
        home_cards_html = """
        <div class="col-12 text-center py-5">
            <div class="alert alert-light border shadow-sm d-inline-block px-4 py-3">
                <h5>⚽ No Football Matches Scheduled Today</h5>
                <p class="text-muted mb-0 small">Use the search bars above to view upcoming match schedules, pitch conditions, and stadium wind forecasts.</p>
            </div>
        </div>"""

    # Schema output
    schema_json = "" 

    home_content = MASTER_HTML_TEMPLATE
    home_content = home_content.replace("__PAGE_TITLE__", f"Today's Football Game Weather Forecasts & Stadium Pitch Conditions ({date_str_seo})")
    home_content = home_content.replace("__META_DESC__", f"View live game weather today ({date_str_seo}) across global football leagues. Track stadium wind speed, hourly rain risks, relative humidity, and pitch impact analytics.")
    home_content = home_content.replace("__SEO_KEYWORDS__", "today game weather, live football stadium weather, pitch wind speed, rain delay football, today match weather forecast")
    home_content = home_content.replace("__CANONICAL_URL__", f"{SITE_DOMAIN}/")
    home_content = home_content.replace("__OG_TITLE__", f"Today's Live Football Stadium Weather & Wind Forecasts")
    home_content = home_content.replace("__OG_DESC__", f"Track real-time pitch rain risks, stadium wind direction, and weather impact analytics for today's football matches.")
    home_content = home_content.replace("__HERO_HEADING__", "Today's Live Football Game Weather")
    home_content = home_content.replace("__HERO_SUBHEADING__", f"Matchday Slate & Stadium Pitch Forecasts for {date_str_display}")
    home_content = home_content.replace("__TOGGLE_CONTROLS_ROW__", toggle_row_html if today_games else "")
    home_content = home_content.replace("__LEAGUE_SEARCH_OPTIONS__", league_search_options_html)
    home_content = home_content.replace("__TEAM_SEARCH_OPTIONS__", team_search_options_html)
    home_content = home_content.replace("__MATCH_CARDS_GRID__", home_cards_html)
    home_content = home_content.replace("__SCHEMA_JSON__", schema_json)

    write_if_changed("index.html", home_content)

    # 8. Generate League Pages (From Master Registry)
    print(f"\n🏆 Generating {len(master_registry['leagues'])} League Pages (/leagues/)...")
    for l_slug, l_data in master_registry['leagues'].items():
        if l_slug == "global-football": continue
        
        sitemap_urls.append(f"{SITE_DOMAIN}/leagues/{l_slug}/")
        l_today = [g for g in today_games if g['league_slug'] == l_slug]
        
        if l_today:
            cards_html = "".join([render_game_card_html(g, is_compact_default=True) for g in l_today])
        else:
            # Show future matches or dormant banner for league
            l_future = [g for g in future_games if g['league_slug'] == l_slug]
            if l_future:
                l_future.sort(key=lambda x: x['game_time'])
                cards_html = "".join([render_future_card_html(g) for g in l_future])
            else:
                cards_html = render_dormant_banner()

        content = MASTER_HTML_TEMPLATE
        content = content.replace("__PAGE_TITLE__", f"{l_data['name']} Match Weather Forecasts & Stadium Pitch Wind")
        content = content.replace("__META_DESC__", f"Live game weather today for {l_data['name']} matches. Check stadium wind speeds, rain delay risks, pitch humidity, and hourly forecasts.")
        content = content.replace("__SEO_KEYWORDS__", f"{l_data['name']} weather today, {l_data['name']} stadium wind, {l_data['name']} rain forecast, football match weather today")
        content = content.replace("__CANONICAL_URL__", f"{SITE_DOMAIN}/leagues/{l_slug}/")
        content = content.replace("__OG_TITLE__", f"{l_data['name']} Game Weather & Stadium Wind Forecasts")
        content = content.replace("__OG_DESC__", f"Real-time pitch rain risks and stadium wind metrics for {l_data['name']} matches.")
        content = content.replace("__HERO_HEADING__", f"{l_data['name']} Weather")
        content = content.replace("__HERO_SUBHEADING__", f"Live Stadium Wind, Rain Risks & Pitch Analytics")
        content = content.replace("__TOGGLE_CONTROLS_ROW__", toggle_row_html if l_today else "")
        content = content.replace("__LEAGUE_SEARCH_OPTIONS__", league_search_options_html)
        content = content.replace("__TEAM_SEARCH_OPTIONS__", team_search_options_html)
        content = content.replace("__MATCH_CARDS_GRID__", cards_html)
        content = content.replace("__SCHEMA_JSON__", "")

        write_if_changed(os.path.join("leagues", l_slug, "index.html"), content)

    # 9. Generate Team Pages (From Master Registry)
    print(f"\n🛡️ Generating {len(master_registry['teams'])} Team Pages (/teams/)...")
    for t_slug, t_data in master_registry['teams'].items():
        sitemap_urls.append(f"{SITE_DOMAIN}/teams/{t_slug}/")
        t_today = [g for g in today_games if g['home_slug'] == t_slug or g['away_slug'] == t_slug]
        
        if t_today:
            cards_html = "".join([render_game_card_html(g, is_compact_default=False) for g in t_today])
            matchup_str = f"{t_today[0]['home_team']} vs {t_today[0]['away_team']}"
            venue_str = t_today[0]['stadium']['name']
            page_title = f"Today's Weather for {matchup_str} match at {venue_str} | Pitch Wind & Rain Forecast"
            meta_desc = f"Live weather forecast for today's {matchup_str} match at {venue_str}. Track stadium wind speed, rain delay risks, temperature, and live pitch conditions."
        else:
            t_future = [g for g in future_games if g['home_slug'] == t_slug or g['away_slug'] == t_slug]
            if t_future:
                t_future.sort(key=lambda x: x['game_time'])
                cards_html = render_future_card_html(t_future[0])
                page_title = f"{t_data['name']} Next Match Forecast | Pitch Wind & Rain"
                meta_desc = f"View the upcoming schedule and future stadium weather forecasts for {t_data['name']}."
            else:
                cards_html = render_dormant_banner()
                page_title = f"{t_data['name']} Game Weather Forecast | Stadium Wind & Rain"
                meta_desc = f"Game weather analytics, stadium wind speed, and rain delay risks for {t_data['name']}."

        content = MASTER_HTML_TEMPLATE
        content = content.replace("__PAGE_TITLE__", page_title)
        content = content.replace("__META_DESC__", meta_desc)
        content = content.replace("__SEO_KEYWORDS__", f"{t_data['name']} game weather, {t_data['name']} stadium wind, {t_data['name']} pitch forecast, {t_data['name']} rain delay risk")
        content = content.replace("__CANONICAL_URL__", f"{SITE_DOMAIN}/teams/{t_slug}/")
        content = content.replace("__OG_TITLE__", f"{t_data['name']} Game Weather")
        content = content.replace("__OG_DESC__", f"Matchday weather analytics and stadium wind forecasts for {t_data['name']}.")
        content = content.replace("__HERO_HEADING__", f"{t_data['name']} Weather")
        content = content.replace("__HERO_SUBHEADING__", f"League: {t_data.get('league', 'Global Football')} | Stadium Pitch Analytics")
        content = content.replace("__TOGGLE_CONTROLS_ROW__", "")
        content = content.replace("__LEAGUE_SEARCH_OPTIONS__", league_search_options_html)
        content = content.replace("__TEAM_SEARCH_OPTIONS__", team_search_options_html)
        content = content.replace("__MATCH_CARDS_GRID__", cards_html)
        content = content.replace("__SCHEMA_JSON__", "")

        write_if_changed(os.path.join("teams", t_slug, "index.html"), content)

    # 10. Generate sitemap.xml
    print("\n🗺️ Generating sitemap.xml...")
    sitemap_content = '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
    for url in sitemap_urls:
        sitemap_content += f"  <url>\n    <loc>{url}</loc>\n    <changefreq>daily</changefreq>\n  </url>\n"
    sitemap_content += "</urlset>"
    
    write_if_changed("sitemap.xml", sitemap_content)

    print("✅ Build complete! Master registry updated, all static pages generated, sitemap created.")

if __name__ == "__main__":
    main()
