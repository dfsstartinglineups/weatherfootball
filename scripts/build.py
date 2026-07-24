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
# STADIUM DATABASE & FAST GEOCODING (OPEN-METEO)
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

def geocode_venue_cascading(venue_name, city, country):
    """
    3-Stage Cascading Geocoder with City Sanitization (e.g. "Houston, Texas" -> "Houston")
    1. Stadium Name + Clean City
    2. Stadium Name Alone
    3. Clean City Fallback
    """
    clean_city = city.split(',')[0].strip() if city else ""

    if venue_name and clean_city:
        lat, lon = geocode_query_open_meteo(f"{venue_name} {clean_city}")
        if lat != 0.0 and lon != 0.0:
            return lat, lon

    if venue_name and venue_name != "Unknown Stadium":
        lat, lon = geocode_query_open_meteo(venue_name)
        if lat != 0.0 and lon != 0.0:
            return lat, lon

    if clean_city:
        lat, lon = geocode_query_open_meteo(clean_city)
        if lat != 0.0 and lon != 0.0:
            return lat, lon

    return 0.0, 0.0

def get_or_update_stadium(stadiums_db, venue_id, venue_info):
    """Retrieves cached stadium data or geocodes with cascading fallback."""
    if venue_id in stadiums_db:
        cached = stadiums_db[venue_id]
        if cached.get("lat") != 0.0 and cached.get("lon") != 0.0:
            return cached

    name = venue_info.get("fullName", "Unknown Stadium")
    city = venue_info.get("address", {}).get("city", "")
    country = venue_info.get("address", {}).get("country", "")
    is_indoor = venue_info.get("indoor", False)

    lat = float(venue_info.get("geometry", {}).get("coordinates", [0, 0])[1]) if "geometry" in venue_info else 0.0
    lon = float(venue_info.get("geometry", {}).get("coordinates", [0, 0])[0]) if "geometry" in venue_info else 0.0

    if lat == 0.0 or lon == 0.0:
        print(f"  🔍 Geocoding venue: {name} ({city}, {country})...")
        lat, lon = geocode_venue_cascading(name, city, country)

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
# WEATHER PIPELINE (OPEN-METEO + RETRIES)
# ==========================================
def fetch_open_meteo_hourly(lat, lon, kickoff_iso_str):
    if lat == 0.0 or lon == 0.0:
        return {"status": "no_coords", "temp": "--", "windSpeed": 0, "precip": 0, "hourly": []}

    try:
        utc_time = datetime.datetime.fromisoformat(kickoff_iso_str.replace('Z', '+00:00'))
    except Exception:
        return None

    game_date_str = utc_time.strftime('%Y-%m-%d')
    next_day_str = (utc_time + timedelta(days=1)).strftime('%Y-%m-%d')
    days_diff = (utc_time.date() - datetime.datetime.now(timezone.utc).date()).days

    if days_diff > 14:
        return {"status": "too_early", "temp": "--", "windSpeed": 0, "precip": 0, "hourly": []}

    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": lat,
        "longitude": lon,
        "current": "temperature_2m,wind_speed_10m,precipitation",
        "hourly": "temperature_2m,precipitation_probability,precipitation,weather_code",
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
                        "precipChance": data['hourly'].get("precipitation_probability", [0])[i],
                        "isThunderstorm": code in [95, 96, 99],
                        "isSnow": code in [71, 73, 75, 77, 85, 86]
                    })

                return {
                    "status": "ok",
                    "temp": int(current.get('temperature_2m', 72)),
                    "windSpeed": int(current.get('wind_speed_10m', 0)),
                    "precip": round(float(current.get('precipitation', 0.0)), 2),
                    "hourly": hourly_slice
                }
        except requests.RequestException:
            time.sleep(1)

    print(f"   ⚠️ Open-Meteo request failed after retries for ({lat}, {lon})")
    return None

def generate_soccer_matchup_analysis(weather, is_dome):
    if is_dome:
        return "🏟️ <b>Indoor Environment:</b> Controlled stadium climate. Zero wind or rain impact on ball movement or pitch velocity."

    notes = []
    if weather['windSpeed'] >= 15 and weather['precip'] > 0:
        notes.append("🌧️💨 <b>Heavy Weather Alert:</b> Rain wet pitch accelerates ball skidding while gusty winds severely affect long balls and goal kicks.")
    elif weather['windSpeed'] >= 15:
        notes.append("💨 <b>High Winds:</b> Wind speeds over 15 mph will cause trajectory drift on aerial crosses, long passes, and goal kicks.")
    elif weather['precip'] > 0:
        notes.append("🌧️ <b>Slippery Pitch:</b> Rain will speed up pitch play, leading to faster ball skidding and potential slipping risks.")

    if weather['temp'] >= 85:
        notes.append("🔥 <b>Heat Warning:</b> High temperatures may prompt official hydration breaks mid-half.")
    elif weather['temp'] <= 32:
        notes.append("❄️ <b>Freezing Turf:</b> Cold conditions cause a firm pitch and reduced ball bounce elasticity.")

    if not notes:
        return "✅ <b>Optimal Pitch Conditions:</b> Mild temperatures and light winds. No adverse weather impact expected."
    return "<br>".join(notes)

# ==========================================
# CARD HTML GENERATOR (DUAL COMPACT / EXPANDED)
# ==========================================
def render_game_card_html(game, is_compact_default=True):
    w = game['weather']
    is_dome = game['stadium']['roof'] in ["Dome", "Retractable"]
    is_too_early = w.get('status') in ["too_early", "no_coords"] or w.get('temp') == "--"

    # Compute Max Rain Chance (%) during match window
    hourly = w.get('hourly', [])
    max_pop = max([h.get('precipChance', 0) for h in hourly], default=0) if hourly else 0

    # Dynamic Color Coding Logic
    bg_class = "bg-weather-sunny"
    border_class = ""
    if is_too_early:
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

    weather_emoji_line = f"Roof Closed<br>🌡️{w['temp']}°" if is_dome else f"🌧️{max_pop}%<br>🌡️{w['temp']}° 💨{w['windSpeed']}mph"
    if is_too_early:
        weather_emoji_line = "Roof Closed" if is_dome else "🔭 Forecast<br>pending"

    show_ribbon = "block" if is_compact_default else "none"
    show_full = "none" if is_compact_default else "block"

    hourly_html = ""
    if not is_too_early and not is_dome and hourly:
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

    weather_section = f"""
        <div class="weather-row row text-center align-items-center mt-2 mx-0">
            <div class="col-3 border-end px-1">
                <div class="fw-bold">{w['temp']}°F</div>
                <div class="small text-muted" style="font-size: 0.7rem;">Temp</div>
            </div>
            <div class="col-3 border-end px-1">
                <div class="fw-bold text-dark">🌱</div>
                <div class="small text-muted" style="font-size: 0.7rem;">{game['stadium'].get('surface', 'Grass')}</div>
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
        <div class="mt-2 mb-2">
            <button class="btn btn-sm btn-outline-primary w-100 py-1 fw-bold" style="font-size: 0.8rem;" onclick="event.stopPropagation(); showRadar('{radar_url}', '{game['stadium']['name']}')">
                🗺️ Live Weather Radar
            </button>
        </div>
        <div class="analysis-box">
            <span class="analysis-title">✨ Soccer Weather Impact</span>
            {generate_soccer_matchup_analysis(w, is_dome)}
        </div>""" if not is_too_early else """
        <div class="text-center p-3 mt-2 border-top">
            <h6 class="text-muted mb-1">🔭 Early Forecast</h6>
            <p class="small text-muted mb-0" style="font-size: 0.75rem;">Stadium weather details available ~14 days before kickoff.</p>
        </div>"""

    league_logo_img = f'<img src="{game["league_logo"]}" style="width: 16px; height: 16px; object-fit: contain;" class="me-1">' if game.get("league_logo") else ''

    return f"""
    <div class="col-md-6 col-lg-4 animate-card mb-3 px-1" id="game-{game['id']}">
        <div class="card game-card shadow-sm {border_class} {bg_class}">
            <!-- COMPACT RIBBON VIEW (STACKED TEAMS) -->
            <div class="ribbon-view p-2 position-relative" onclick="toggleSingleCard(this)" style="cursor: pointer; display: {show_ribbon};">
                <div class="d-flex align-items-center justify-content-between mb-2">
                    <div class="d-flex align-items-center text-truncate me-2">
                        {league_logo_img}
                        <span class="fw-bold text-truncate" style="font-size: 0.75rem;">{game['league_name']}</span>
                    </div>
                    <span class="badge {badge_style} flex-shrink-0" style="font-size: 0.65rem;">{badge_text}</span>
                </div>
                
                <div class="d-flex align-items-center justify-content-between gap-2">
                    <!-- Stacked Teams Column (Left) -->
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

                    <!-- Weather Info Vertical Column (Right) -->
                    <div class="d-flex align-items-center justify-content-center ps-2 border-start flex-shrink-0" style="min-width: 110px;">
                        <span class="fw-bold text-primary text-end" style="font-size: 0.75rem; line-height: 1.3;">
                            {weather_emoji_line}
                        </span>
                    </div>
                </div>
            </div>

            <!-- EXPANDED FULL CARD VIEW -->
            <div class="full-card-view" onclick="toggleSingleCard(this)" style="cursor: pointer; display: {show_full};">
                <div class="d-flex align-items-center justify-content-between p-2 bg-dark text-white">
                    <div class="d-flex align-items-center text-truncate">
                        {league_logo_img}
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
        .analysis-box { background-color: rgba(255, 255, 255, 0.7); border-left: 4px solid #0d6efd; padding: 8px 12px; margin-top: 10px; font-size: 0.8rem; border-radius: 0 4px 4px 0; }
        .analysis-title { font-weight: 800; text-transform: uppercase; font-size: 0.7rem; color: #0d6efd; display: block; margin-bottom: 2px; }
        
        .hourly-scroll-container { display: flex; overflow-x: auto; gap: 8px; padding: 8px 4px; margin-top: 8px; border-top: 1px solid rgba(0,0,0,0.05); }
        .hour-card { display: flex; flex-direction: column; align-items: center; min-width: 55px; text-align: center; }
        .hour-time { font-size: 0.7rem; font-weight: 600; color: #6c757d; }
        .hour-icon { font-size: 1.2rem; }
        .hour-pop { font-size: 0.65rem; color: #0d6efd; font-weight: 700; height: 12px; }
        .hour-temp { font-size: 0.8rem; font-weight: 600; }

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

    # 1. Effective Date Calculation (3:00 AM EST Rollover)
    effective_dt = get_effective_matchday_date()
    date_str_espn = effective_dt.strftime("%Y%m%d")
    date_str_display = effective_dt.strftime("%A, %B %d, %Y")
    print(f"📅 Target Matchday Date: {date_str_display} (ESPN param: {date_str_espn})")

    # 2. Load Stadium Database
    stadiums_db = load_stadiums_db()

    # 3. Fetch Master ESPN Scoreboard
    espn_url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/all/scoreboard?dates={date_str_espn}"
    print(f"📡 Ingesting ESPN Master Board...")
    
    try:
        res = HTTP.get(espn_url, timeout=15)
        scoreboard_data = res.json() if res.status_code == 200 else {}
    except Exception as e:
        print(f"❌ Error fetching ESPN Scoreboard: {e}")
        scoreboard_data = {}

    events = scoreboard_data.get('events', [])
    print(f"⚽ Found {len(events)} fixtures on ESPN master board.")

    today_games = []
    teams_registry = {}
    leagues_registry = {}

    # 4. Process Each Game
    for event in events:
        game_id = event['id']
        comp = event['competitions'][0]
        game_time = event['date']
        status = event['status']['type']['state']
        clock = event['status']['type'].get('shortDetail', '')

        # Precision League Name Extraction using altGameNote
        league_name = (
            comp.get('altGameNote') or 
            event.get('league', {}).get('name') or 
            comp.get('league', {}).get('name') or 
            "Global Football"
        )

        league_obj = event.get('league') or comp.get('league') or {}
        league_logos = league_obj.get('logos', [])
        league_logo = league_logos[0]['href'] if league_logos else ""
        league_slug = slugify(league_name)

        home_comp = next((c for c in comp['competitors'] if c['homeAway'] == 'home'), None)
        away_comp = next((c for c in comp['competitors'] if c['homeAway'] == 'away'), None)

        if not home_comp or not away_comp:
            continue

        home_team = home_comp['team']['displayName']
        away_team = away_comp['team']['displayName']
        
        home_logo = home_comp['team'].get('logo', '') or (home_comp['team'].get('logos', [{}])[0].get('href', ''))
        away_logo = away_comp['team'].get('logo', '') or (away_comp['team'].get('logos', [{}])[0].get('href', ''))

        home_slug = slugify(home_team)
        away_slug = slugify(away_team)

        espn_venue = comp.get('venue', {})
        venue_id = str(espn_venue.get('id', slugify(espn_venue.get('fullName', 'default-stadium'))))
        stadium_info = get_or_update_stadium(stadiums_db, venue_id, espn_venue)

        if stadium_info['roof'] in ["Dome", "Retractable"]:
            weather = {"status": "ok", "temp": 70, "windSpeed": 0, "precip": 0.0, "hourly": []}
        else:
            weather = fetch_open_meteo_hourly(stadium_info['lat'], stadium_info['lon'], game_time) or {
                "status": "error", "temp": "--", "windSpeed": 0, "precip": 0.0, "hourly": []
            }

        game_obj = {
            "id": game_id,
            "game_time": game_time,
            "status": status,
            "clock": clock,
            "league_name": league_name,
            "league_slug": league_slug,
            "league_logo": league_logo,
            "home_team": home_team,
            "home_slug": home_slug,
            "home_logo": home_logo,
            "away_team": away_team,
            "away_slug": away_slug,
            "away_logo": away_logo,
            "stadium": stadium_info,
            "weather": weather
        }

        today_games.append(game_obj)

        if league_slug not in leagues_registry:
            leagues_registry[league_slug] = {"name": league_name, "slug": league_slug, "logo": league_logo, "games": []}
        leagues_registry[league_slug]["games"].append(game_obj)

        for team_name, team_slug, team_logo in [(home_team, home_slug, home_logo), (away_team, away_slug, away_logo)]:
            if team_slug not in teams_registry:
                teams_registry[team_slug] = {"name": team_name, "slug": team_slug, "logo": team_logo, "league": league_name, "games": []}
            teams_registry[team_slug]["games"].append(game_obj)

    save_stadiums_db(stadiums_db)

    # Chronological Sorting by Game Kickoff Time
    today_games.sort(key=lambda x: x['game_time'])

    # 5. Build Dual Datalist Options HTML (League vs Team)
    league_search_options_html = ""
    for l_slug, l_data in sorted(leagues_registry.items(), key=lambda x: x[1]['name']):
        if l_slug == "global-football":
            continue
        league_search_options_html += f'                    <option value="{l_data["name"]}" data-url="/leagues/{l_slug}/"></option>\n'

    team_search_options_html = ""
    for t_slug, t_data in sorted(teams_registry.items(), key=lambda x: x[1]['name']):
        team_search_options_html += f'                    <option value="{t_data["name"]}" data-url="/teams/{t_slug}/"></option>\n'

    toggle_row_html = """
        <div class="d-flex justify-content-end mb-3 px-1">
            <button id="expand-toggle-btn" class="btn btn-sm btn-white shadow-sm border fw-bold text-secondary" style="border-radius: 20px; font-size: 0.8rem;" onclick="toggleAllCards()">
                ▼ Expand All Cards
            </button>
        </div>"""

    # PAGE GENERATOR 1: MAIN HOMEPAGE (Compact Default = True)
    print("\n🌐 Generating Homepage (/index.html)...")
    home_cards_html = "".join([render_game_card_html(g, is_compact_default=True) for g in today_games]) if today_games else """
        <div class="col-12 text-center py-5">
            <div class="alert alert-light border shadow-sm d-inline-block px-4 py-3">
                <h5>⚽ No Matches Scheduled Today</h5>
                <p class="text-muted mb-0 small">Use the search bars above to view upcoming match schedules and stadium forecasts.</p>
            </div>
        </div>"""

    schema_json = json.dumps({"@context": "https://schema.org", "@type": "WebSite", "name": "Weather Football", "url": SITE_DOMAIN}, indent=2)

    home_content = MASTER_HTML_TEMPLATE
    home_content = home_content.replace("__PAGE_TITLE__", f"Live Soccer Weather & Pitch Forecasts | WeatherFootball")
    home_content = home_content.replace("__META_DESC__", f"Live matchday weather forecasts, wind speeds, rain risks, and pitch conditions for global soccer.")
    home_content = home_content.replace("__CANONICAL_URL__", f"{SITE_DOMAIN}/")
    home_content = home_content.replace("__OG_TITLE__", "Live Soccer Weather & Pitch Conditions")
    home_content = home_content.replace("__OG_DESC__", "Track pitch rain, wind speeds, and stadium conditions for all live soccer matches.")
    home_content = home_content.replace("__HERO_HEADING__", "Live Football Stadium Weather")
    home_content = home_content.replace("__HERO_SUBHEADING__", f"Matchday Slate for {date_str_display}")
    home_content = home_content.replace("__TOGGLE_CONTROLS_ROW__", toggle_row_html if today_games else "")
    home_content = home_content.replace("__LEAGUE_SEARCH_OPTIONS__", league_search_options_html)
    home_content = home_content.replace("__TEAM_SEARCH_OPTIONS__", team_search_options_html)
    home_content = home_content.replace("__MATCH_CARDS_GRID__", home_cards_html)
    home_content = home_content.replace("__SCHEMA_JSON__", schema_json)

    write_if_changed("index.html", home_content)

    # PAGE GENERATOR 2: LEAGUE PAGES (Compact Default = True, Skip generic 'global-football')
    print(f"\n🏆 Generating League Pages (/leagues/)...")
    for l_slug, l_data in leagues_registry.items():
        if l_slug == "global-football":
            print(f"  ⏭️  Skipping generic league page generation for: {l_slug}")
            continue

        l_data['games'].sort(key=lambda x: x['game_time'])
        cards_html = "".join([render_game_card_html(g, is_compact_default=True) for g in l_data['games']])
        schema_json = json.dumps({"@context": "https://schema.org", "@type": "SportsEvent", "name": f"{l_data['name']} Matches"}, indent=2)

        content = MASTER_HTML_TEMPLATE
        content = content.replace("__PAGE_TITLE__", f"{l_data['name']} Match Weather Forecasts | WeatherFootball")
        content = content.replace("__META_DESC__", f"Live stadium weather, rain delays, and pitch wind conditions for {l_data['name']}.")
        content = content.replace("__CANONICAL_URL__", f"{SITE_DOMAIN}/leagues/{l_slug}/")
        content = content.replace("__OG_TITLE__", f"{l_data['name']} Live Weather & Stadium Forecasts")
        content = content.replace("__OG_DESC__", f"Track real-time rain risks and wind metrics for {l_data['name']} fixtures.")
        content = content.replace("__HERO_HEADING__", f"{l_data['name']} Weather")
        content = content.replace("__HERO_SUBHEADING__", f"Active Slate & Stadium Forecasts")
        content = content.replace("__TOGGLE_CONTROLS_ROW__", toggle_row_html)
        content = content.replace("__LEAGUE_SEARCH_OPTIONS__", league_search_options_html)
        content = content.replace("__TEAM_SEARCH_OPTIONS__", team_search_options_html)
        content = content.replace("__MATCH_CARDS_GRID__", cards_html)
        content = content.replace("__SCHEMA_JSON__", schema_json)

        write_if_changed(os.path.join("leagues", l_slug, "index.html"), content)

    # PAGE GENERATOR 3: TEAM PAGES (Compact Default = False -> Fully Expanded)
    print(f"\n🛡️ Generating {len(teams_registry)} Team Pages (/teams/)...")
    for t_slug, t_data in teams_registry.items():
        t_data['games'].sort(key=lambda x: x['game_time'])
        cards_html = "".join([render_game_card_html(g, is_compact_default=False) for g in t_data['games']])
        schema_json = json.dumps({"@context": "https://schema.org", "@type": "SportsTeam", "name": t_data['name']}, indent=2)

        content = MASTER_HTML_TEMPLATE
        content = content.replace("__PAGE_TITLE__", f"{t_data['name']} Weather Forecast & Stadium Pitch Analytics")
        content = content.replace("__META_DESC__", f"View matchday weather forecasts, wind speeds, and rain risks for {t_data['name']}.")
        content = content.replace("__CANONICAL_URL__", f"{SITE_DOMAIN}/teams/{t_slug}/")
        content = content.replace("__OG_TITLE__", f"{t_data['name']} Game Weather")
        content = content.replace("__OG_DESC__", f"Live stadium weather analysis and pitch conditions for {t_data['name']}.")
        content = content.replace("__HERO_HEADING__", f"{t_data['name']} Forecast")
        content = content.replace("__HERO_SUBHEADING__", f"League: {t_data['league']}")
        content = content.replace("__TOGGLE_CONTROLS_ROW__", "")
        content = content.replace("__LEAGUE_SEARCH_OPTIONS__", league_search_options_html)
        content = content.replace("__TEAM_SEARCH_OPTIONS__", team_search_options_html)
        content = content.replace("__MATCH_CARDS_GRID__", cards_html)
        content = content.replace("__SCHEMA_JSON__", schema_json)

        write_if_changed(os.path.join("teams", t_slug, "index.html"), content)

    print("\n✅ All pages and stadium registries processed successfully!")

if __name__ == "__main__":
    main()
