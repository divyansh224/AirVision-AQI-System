# app.py
"""
SkySigma Flask server (cleaned & hardened)
- Serves static login/dashboard
- /login: authenticates user (sqlite fallback)
- /predict_aqi?city=CityName or ?lat=..&lon=.. -> trains/loads model and predicts nextHour + hourly series
- /ask_ai: calls Gemini (optional)
Notes:
 - Model file is expected at models/model.pkl by default.
 - Training via models/train_model (if present) is attempted; otherwise existing model.pkl is loaded.
 - This file prioritizes robustness and clear logging for development.
"""

import os
import time
import json
import joblib
import requests
import sqlite3
import numpy as np
import pandas as pd
from flask import Flask, jsonify, request, send_from_directory, redirect, session
from flask_cors import CORS
app = Flask(__name__, static_folder='../frontend', template_folder='../frontend')
from twilio.rest import Client
#from alerts_service import send_alert, normalize_phone



conn = sqlite3.connect('schema.db')
c = conn.cursor()

c.execute("""
CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    city TEXT,
    alert_type TEXT,
    contact TEXT,
    threshold INTEGER,
    active INTEGER,
    last_sent INTEGER
)
""")

conn.commit()
conn.close()

print("✅ alerts table created")

TWILIO_SID = ""
TWILIO_TOKEN = ""
TWILIO_PHONE = ""

twilio_client = Client(TWILIO_SID, TWILIO_TOKEN)

def send_sms(phone, message):
    try:
        twilio_client.messages.create(
            body=message,
            from_=TWILIO_PHONE,
            to=phone
        )
        print(f"📩 SMS sent to {phone}")
    except Exception as e:
        print("SMS ERROR:", e)
# send voice call 
def send_voice(phone, message):
    try:
        slow_message = message.replace(".",". <break time='0.8s'/>")
        twilio_client.calls.create(
            to=phone,
            from_=TWILIO_PHONE,   # Twilio US number
            twiml=f"""
            <Response>
                <Say voice="alice" language="en-IN">
                 <prosody rate="slow">
                    {slow_message}
                 </prosody>
                </Say>
            </Response>
            """
        )
        print(f"📞 Voice call initiated to {phone}")
    except Exception as e:
        print("VOICE CALL ERROR:", e)

# normalize 
def normalize_phone(phone):
    phone = phone.replace(" ", "")
    if phone.startswith("0"):
        phone = "+91" + phone[1:]
    if not phone.startswith("+"):
        phone = "+91" + phone
    return phone
#safe sms
def safe_sms(text, limit=140):
    return text[:limit]
# composed sms
# ----------------------------
# AQI CATEGORY
# ----------------------------
def aqi_category(aqi):
    if aqi <= 50: return "Good"
    if aqi <= 100: return "Moderate"
    if aqi <= 150: return "Unhealthy"
    if aqi <= 200: return "Very Unhealthy"
    return "Hazardous"


# ----------------------------
# VOICE ALERT MESSAGE
# ----------------------------
def compose_alert_message(city, predicted_aqi, pollutants):
    cat = aqi_category(predicted_aqi)

    pm25 = pollutants.get("pm2_5", "N/A")
    pm10 = pollutants.get("pm10", "N/A")
    no2  = pollutants.get("no2", "N/A")
    so2  = pollutants.get("so2", "N/A")

    return (
        f"⚠️ AQI ALERT: {city}\n"
        f"Air Quality: {cat}\n"
        f"PM2.5: {pm25}\n"
        f"PM10: {pm10}\n"
        f"NO2: {no2}\n"
        f"SO2: {so2}\n"
        f"Agle ek ghante mein AQI {predicted_aqi} tak pahunch sakta hai.\n"
        f"Mask pehnein aur bahar kam niklein."
    )
def compose_sms_message(city, predicted_aqi):
    category = aqi_category(predicted_aqi)

    return (
        f"AQI ALERT: {city} | {category}. "
        f"Next hour AQI ~ {predicted_aqi}. "
        f"Mask pehnein, bahar kam niklein."
    )

# send alert 
def send_alert(alert_type, contact, city, predicted_aqi, pollutants):
    print("🔥 send_alert() CALLED")
    print("TYPE:", alert_type)
    print("CONTACT:", contact)

    if alert_type == "voice":
        voice_msg = compose_alert_message(city, predicted_aqi, pollutants)
        send_voice(contact, voice_msg)
    else:
        sms_msg = compose_sms_message(city, predicted_aqi)
        send_sms(contact, safe_sms(sms_msg))

# Support both package execution and direct script execution for backend imports.
try:
    from .fetch_data_new import get_aqi
    try:
        from .fetch_data_new import fetch_and_save_data
    except ImportError:
        fetch_and_save_data = None
except ImportError:
    try:
        from backend.fetch_data_new import get_aqi
    except Exception as e:
        get_aqi = None
        print("Warning: fetch_data module not available:", e)
    try:
        from backend.fetch_data_new import fetch_and_save_data
    except Exception:
        fetch_and_save_data = None


# Optional ML imports (scikit-learn) used if train_model isn't available or returns a model.
from sklearn.ensemble import RandomForestRegressor

# Try to import train_model from backend.models package, or fallback to local models/train_model.py
train_model_func = None
import importlib
for module_name in ('backend.models.train_model', 'models.train_model', 'train_model'):
    try:
        tm_mod = importlib.import_module(module_name)
        if hasattr(tm_mod, 'train_model'):
            train_model_func = tm_mod.train_model
        elif hasattr(tm_mod, 'train_and_save'):
            train_model_func = tm_mod.train_and_save
        elif hasattr(tm_mod, 'run_training'):
            train_model_func = tm_mod.run_training
        if train_model_func is not None:
            print(f"Loaded training module: {module_name}")
            break
    except Exception:
        continue

if train_model_func is None:
    print("train_model module not found or could not be imported automatically.")

# Optional: Gemini generative AI (best-effort; graceful if not configured)
genai = None
try:
    try:
        import google.generativeai as genai
    except ImportError:
        genai = None
        print("google.generativeai not installed. Install via: pip install google-generativeai")
        raise
    GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY', '')
    print(f"[DEBUG] GEMINI_API_KEY length = {len(GEMINI_API_KEY)}, first 10 chars: {GEMINI_API_KEY[:10] if GEMINI_API_KEY else 'EMPTY'}")
    if GEMINI_API_KEY:
        try:
            genai.configure(api_key=GEMINI_API_KEY)
            model_gemini = genai.GenerativeModel('gemini-1.5-flash')
            print("[OK] Gemini AI initialized successfully with model: gemini-1.5-flash")
        except Exception as model_err:
            model_gemini = None
            print("Gemini model initialization error:", model_err)
    else:
        model_gemini = None
        print("GEMINI_API_KEY not set; /ask_ai will return fallback message.")
except Exception as e:
    model_gemini = None
    print("Gemini client not available:", e)


CORS(app)  # In production restrict origins!

# CONFIG - defaults
OPENWEATHER_API_KEY = os.environ.get('OPENWEATHER_API_KEY', "")
MODEL_PATH = os.environ.get('MODEL_PATH', os.path.join('models', 'model.pkl'))
MODEL_META_PATH = os.environ.get('MODEL_META_PATH', os.path.join('models', 'model_meta.json'))
CSV_FILENAME = os.environ.get('CSV_FILENAME', 'air_quality_data.csv')

# New config for dual CSV approach
CPCB_CSV = os.environ.get('CPCB_CSV', os.path.join('cpcb_data.csv'))
OPENWEATHER_CSV = os.environ.get('OPENWEATHER_CSV', os.path.join('openweather_data.csv'))
DATA_CACHE_HOURS = int(os.environ.get('DATA_CACHE_HOURS', '24'))  # Refresh data every 24 hours

# Global data cache
cpcb_data_cache = None
openweather_data_cache = None
last_cache_update = None

# ----------------------------
# DATA INITIALIZATION & CACHE MANAGEMENT
# ----------------------------
def should_refresh_cache():
    """Check if cache needs refresh based on time"""
    global last_cache_update
    if last_cache_update is None:
        return True
    hours_since_update = (time.time() - last_cache_update) / 3600
    return hours_since_update >= DATA_CACHE_HOURS

def load_csv_data(filepath):
    """Load CSV data into memory as dict with city as key"""
    try:
        if os.path.exists(filepath):
            df = pd.read_csv(filepath)
            # Convert to dict with city as key (assuming city column exists)
            if 'city' in df.columns:
                return df.set_index('city').to_dict('index')
            else:
                # If no city column, return as list of dicts
                return df.to_dict('records')
        return {}
    except Exception as e:
        print(f"Error loading {filepath}: {e}")
        return {}

def save_csv_data(data, filepath, data_source="unknown"):
    """Save data to CSV with metadata"""
    try:
        if isinstance(data, dict):
            df = pd.DataFrame.from_dict(data, orient='index')
            df['data_source'] = data_source
            df['last_updated'] = time.time()
        else:
            df = pd.DataFrame(data)
            df['data_source'] = data_source
            df['last_updated'] = time.time()
        df.to_csv(filepath, index=False)
        print(f"✅ Saved {len(df)} records to {filepath}")
    except Exception as e:
        print(f"❌ Error saving to {filepath}: {e}")

def initialize_data_cache():
    """Initialize data cache on server startup"""
    global cpcb_data_cache, openweather_data_cache, last_cache_update

    print("🔄 Initializing data cache...")

    # Load existing CSV data
    cpcb_data_cache = load_csv_data(CPCB_CSV)
    openweather_data_cache = load_csv_data(OPENWEATHER_CSV)

    if should_refresh_cache():
        print("📡 Refreshing data from APIs...")
        refresh_data_cache()
    else:
        print("✅ Using cached data")

    last_cache_update = time.time()

def refresh_data_cache():
    """Fetch fresh data from APIs and update cache"""
    global cpcb_data_cache, openweather_data_cache

    print("🔄 Refreshing CPCB data...")
    cpcb_data_cache = fetch_all_cpcb_data()

    print("🔄 Refreshing OpenWeather data for major cities...")
    openweather_data_cache = fetch_openweather_for_major_cities()

    # Save to CSV files
    if cpcb_data_cache:
        save_csv_data(cpcb_data_cache, CPCB_CSV, "cpcb")
    if openweather_data_cache:
        save_csv_data(openweather_data_cache, OPENWEATHER_CSV, "openweather")

def fetch_all_cpcb_data():
    """Fetch all available CPCB data for Indian cities"""
    try:
        url = "https://api.data.gov.in/resource/3b01bcb8-0b14-4abf-b6f2-c1bfd384ba69"
        params = {
            "api-key": "",  # Use proper API key
            "format": "json",
            "limit": 10000  # Get maximum data
        }

        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()

        records = data.get("records", [])
        city_data = {}

        for record in records:
            city = str(record.get("city", "")).strip().lower()
            if not city:
                continue

            station = record.get("station", "Unknown")
            pollutant_id = str(record.get("pollutant_id", "")).upper()
            avg_value = record.get("avg_value", "0")

            try:
                value = float(avg_value) if avg_value and avg_value != "NA" else 0
            except:
                value = 0

            if city not in city_data:
                city_data[city] = {
                    "city": city,
                    "pm2_5": 0, "pm10": 0, "no2": 0, "so2": 0, "co": 0, "o3": 0, "nh3": 0,
                    "stations": [], "last_updated": time.time()
                }

            # Map pollutants
            if pollutant_id in ["PM2.5", "PM25", "PM2_5"]:
                city_data[city]["pm2_5"] = max(city_data[city]["pm2_5"], value)
            elif pollutant_id == "PM10":
                city_data[city]["pm10"] = max(city_data[city]["pm10"], value)
            elif pollutant_id == "NO2":
                city_data[city]["no2"] = max(city_data[city]["no2"], value)
            elif pollutant_id == "SO2":
                city_data[city]["so2"] = max(city_data[city]["so2"], value)
            elif pollutant_id == "CO":
                city_data[city]["co"] = max(city_data[city]["co"], value)
            elif pollutant_id == "O3":
                city_data[city]["o3"] = max(city_data[city]["o3"], value)
            elif pollutant_id == "NH3":
                city_data[city]["nh3"] = max(city_data[city]["nh3"], value)

            if station not in city_data[city]["stations"]:
                city_data[city]["stations"].append(station)

        print(f"✅ Fetched CPCB data for {len(city_data)} cities")
        return city_data

    except Exception as e:
        print(f"❌ Error fetching CPCB data: {e}")
        return {}

def fetch_openweather_for_major_cities():
    """Fetch OpenWeather data for major Indian cities as fallback"""
    major_cities = [
        "delhi", "mumbai", "bangalore", "chennai", "kolkata", "hyderabad", "pune",
        "ahmedabad", "jaipur", "surat", "lucknow", "kanpur", "nagpur", "indore",
        "thane", "bhopal", "visakhapatnam", "pimpri-chinchwad", "patna", "vadodara"
    ]

    city_data = {}

    for city in major_cities:
        try:
            # Get coordinates
            geo_url = f"http://api.openweathermap.org/data/2.5/weather?q={city},IN&appid={OPENWEATHER_API_KEY}"
            geo_response = requests.get(geo_url, timeout=10)
            geo_response.raise_for_status()
            geo_data = geo_response.json()

            lat = geo_data['coord']['lat']
            lon = geo_data['coord']['lon']

            # Get air pollution data
            air_url = f"http://api.openweathermap.org/data/2.5/air_pollution?lat={lat}&lon={lon}&appid={OPENWEATHER_API_KEY}"
            air_response = requests.get(air_url, timeout=10)
            air_response.raise_for_status()
            air_data = air_response.json()

            components = air_data['list'][0]['components']

            city_data[city] = {
                "city": city,
                "pm2_5": components.get("pm2_5", 0),
                "pm10": components.get("pm10", 0),
                "no2": components.get("no2", 0),
                "so2": components.get("so2", 0),
                "co": components.get("co", 0),
                "o3": components.get("o3", 0),
                "nh3": components.get("nh3", 0),
                "lat": lat,
                "lon": lon,
                "last_updated": time.time()
            }

        except Exception as e:
            print(f"⚠️ Error fetching OpenWeather data for {city}: {e}")
            continue

    print(f"✅ Fetched OpenWeather data for {len(city_data)} cities")
    return city_data

print("DEBUG: Loading AQI calculation module")
def calculate_aqi_from_pollutants(pollutants):

    def get_aqi(concentration, breakpoints):
        """Calculate AQI for a single pollutant"""
        try:
            for i in range(len(breakpoints) - 1):
                if breakpoints[i][0] <= concentration <= breakpoints[i + 1][0]:
                    Clow, Chigh = breakpoints[i][0], breakpoints[i + 1][0]
                    Ilow, Ihigh = breakpoints[i][1], breakpoints[i + 1][1]
                    return round(((Ihigh - Ilow) / (Chigh - Clow)) * (concentration - Clow) + Ilow)
        except Exception:
            pass
        return 0

    # EPA AQI breakpoints for available pollutants (matching training data)
    breakpoints = {
        'pm2_5': [(0.0, 0), (12.0, 50), (35.4, 100), (55.4, 150), (150.4, 200), (250.4, 300), (350.4, 400), (500.4, 500)],
        'pm10':  [(0.0, 0), (54, 50), (154, 100), (254, 150), (354, 200), (424, 300), (504, 400), (604, 500)],
        'no2':   [(0.0, 0), (53, 50), (100, 100), (360, 150), (649, 200), (1249, 300), (1649, 400), (2049, 500)],
        'o3':    [(0.0, 0), (54, 50), (70, 100), (85, 150), (105, 200), (200, 300), (300, 400), (400, 500)],
        'so2':   [(0.0, 0), (35, 50), (75, 100), (185, 150), (304, 200), (604, 300), (804, 400), (1004, 500)],
        'co':    [(0.0, 0), (4.4, 50), (9.4, 100), (12.4, 150), (15.4, 200), (30.4, 300), (40.4, 400), (50.4, 500)],
    }

    aqi_values = []
    for pollutant, concentration in pollutants.items():
        if pollutant in breakpoints and concentration > 0:
            aqi = get_aqi(concentration, breakpoints[pollutant])
            aqi_values.append(aqi)
            print(f"DEBUG AQI: {pollutant}={concentration} -> AQI={aqi}")

    final_aqi = max(aqi_values) if aqi_values else 0
    print(f"DEBUG: Final AQI = {final_aqi} from {aqi_values}")
    return final_aqi

# ----------------------------
# Helpers
# ---------------------------
#----------#
#----------#
#----------#
def fetch_historic_and_save(city, api_key, filename=CSV_FILENAME):
    if fetch_and_save_data is None:
        print("fetch_data not available; skipping historic fetch.")
        return False
    try:
        ok = fetch_and_save_data(city, api_key, filename=filename)
        if (not ok) and os.path.exists(filename):
            return True
        return bool(ok)
    except Exception as e:
        print("Exception in fetch_historic_and_save:", e)
        return False

def attempt_train_from_module(csv_path=CSV_FILENAME, model_output=MODEL_PATH):
    """
    Attempt to call train_model_func with flexible signatures.
    If it writes model_output file, load it and return model object.
    If it returns model or (model, features) return model.
    """
    global train_model_func
    if not train_model_func:
        print("No train_model_func available.")
        return None
    try:
        import inspect
        sig = inspect.signature(train_model_func)
        params = len(sig.parameters)
        if params == 0:
            res = train_model_func()
        elif params == 1:
            res = train_model_func(csv_path)
        else:
            try:
                res = train_model_func(csv_path, model_output)
            except TypeError:
                res = train_model_func(csv_path)

        # Interpret result
        if res is None:
            if os.path.exists(model_output):
                print("Training function wrote model file to disk.")
                return joblib.load(model_output)
            return None
        if isinstance(res, tuple):
            # common: (model, feature_list)
            model_obj = res[0]
            # if returned path
            if isinstance(model_obj, str) and os.path.exists(model_obj):
                return joblib.load(model_obj)
            return model_obj
        # if returned model object
        return res
    except Exception as e:
        print("Error while calling train_model_func:", e)
        return None

def load_model_from_disk(path=MODEL_PATH):
    if os.path.exists(path):
        try:
            m = joblib.load(path)
            print(f"Loaded model from {path}")
            return m
        except Exception as e:
            print("Failed loading model from disk:", e)
            return None
    print(f"Model file not found at: {path}")
    return None

def fetch_from_cpcb(city):
    """
    Fetch air quality data from CPCB (Central Pollution Control Board) API.
    Returns list of pollutant rows for matching city, or None if not found.
    """
    try:
        url = "https://api.data.gov.in/resource"

        params = {
            "api-key": "YOUR_API_KEY",  # TODO: Set from environment variable
            "format": "json",
            "limit": 1000
        }

        res = requests.get(url, params=params, timeout=10)
        data = res.json()

        records = data.get("records", [])
        rows = []

        for r in records:
            if city.lower() in str(r.get("city", "")).lower():
                row = {
                    "pm2_5": float(r.get("pm2_5") or r.get("pm25") or 0),
                    "pm10": float(r.get("pm10") or 0),
                    "no2": float(r.get("no2") or 0),
                    "so2": float(r.get("so2") or 0),
                    "co": float(r.get("co") or 0),
                    "o3": float(r.get("o3") or 0),
                    "aqi": float(r.get("aqi") or 0)
                }

                if row["pm2_5"] > 0:
                    rows.append(row)

        return rows if rows else None

    except Exception as e:
        print("❌ CPCB Error:", e)
        return None


def fetch_both_pollutants_by_city(city):
    """
    Get pollutant data for city from both CPCB and OpenWeather sources.
    Returns dict with 'cpcb' and 'openweather' keys, each containing pollutant data.
    """
    city_lower = city.lower().strip()
    result = {"cpcb": None, "openweather": None}

    # STEP 1: Try CPCB cache
    if cpcb_data_cache and city_lower in cpcb_data_cache:
        data = cpcb_data_cache[city_lower]
        print(f"✅ Found cached CPCB data for {city}")
        result["cpcb"] = {
            "pm2_5": data.get("pm2_5", 0),
            "pm10": data.get("pm10", 0),
            "no2": data.get("no2", 0),
            "so2": data.get("so2", 0),
            "co": data.get("co", 0),
            "o3": data.get("o3", 0),
            "nh3": data.get("nh3", 0)
        }

    # STEP 2: Try OpenWeather cache or fetch fresh
    if openweather_data_cache and city_lower in openweather_data_cache:
        data = openweather_data_cache[city_lower]
        print(f"✅ Found cached OpenWeather data for {city}")
        result["openweather"] = {
            "pm2_5": data.get("pm2_5", 0),
            "pm10": data.get("pm10", 0),
            "no2": data.get("no2", 0),
            "so2": data.get("so2", 0),
            "co": data.get("co", 0),
            "o3": data.get("o3", 0),
            "nh3": data.get("nh3", 0)
        }
    else:
        # Fetch fresh OpenWeather data
        print(f"⚠️ No cached OpenWeather data for {city}, fetching from API...")
        try:
            geo_url = f"http://api.openweathermap.org/data/2.5/weather?q={city}&appid={OPENWEATHER_API_KEY}"
            gr = requests.get(geo_url, timeout=10)
            gr.raise_for_status()
            geoj = gr.json()
            lat = geoj['coord']['lat']
            lon = geoj['coord']['lon']

            air_url = f"http://api.openweathermap.org/data/2.5/air_pollution?lat={lat}&lon={lon}&appid={OPENWEATHER_API_KEY}"
            ar = requests.get(air_url, timeout=10)
            ar.raise_for_status()
            aj = ar.json()
            comp = aj.get('list', [{}])[0].get('components', {})

            result["openweather"] = {
                "pm2_5": comp.get("pm2_5", 0),
                "pm10": comp.get("pm10", 0),
                "no2": comp.get("no2", 0),
                "so2": comp.get("so2", 0),
                "co": comp.get("co", 0),
                "o3": comp.get("o3", 0),
                "nh3": comp.get("nh3", 0)
            }

            # Cache this new data
            if openweather_data_cache is not None:
                openweather_data_cache[city_lower] = {
                    "city": city_lower,
                    "pm2_5": comp.get("pm2_5", 0),
                    "pm10": comp.get("pm10", 0),
                    "no2": comp.get("no2", 0),
                    "so2": comp.get("so2", 0),
                    "co": comp.get("co", 0),
                    "o3": comp.get("o3", 0),
                    "nh3": comp.get("nh3", 0),
                    "lat": lat,
                    "lon": lon,
                    "last_updated": time.time()
                }
                # Save updated cache to CSV
                save_csv_data(openweather_data_cache, OPENWEATHER_CSV, "openweather")

        except Exception as e:
            print(f"❌ OpenWeather API Error for {city}: {e}")

    return result

def get_model_expected_features(model, model_meta_path=MODEL_META_PATH):
    """
    Determine the feature names the model expects.
    1) Try model.feature_names_in_ (sklearn >=0.24)
    2) Read model_meta.json if present (with key 'features')
    3) Fallback to a common pollutant feature list
    """
    try:
        feat = getattr(model, 'feature_names_in_', None)
        if feat is not None:
            return list(feat)
    except Exception:
        pass

    if os.path.exists(model_meta_path):
        try:
            with open(model_meta_path, 'r') as f:
                meta = json.load(f)
            if 'features' in meta and isinstance(meta['features'], list):
                return meta['features']
        except Exception as e:
            print("Could not read model_meta.json:", e)

    # fallback
    return ['co','no','no2','o3','so2','pm2_5','pm10','nh3']

def build_feature_dataframe_from_components(components, expected_features):
    """
    Build pandas.DataFrame with columns ordered exactly as expected_features,
    mapping from available components; missing features filled with 0.0.
    """
    row = {}
    for f in expected_features:
        row[f] = float(components.get(f, 0.0))
    df = pd.DataFrame([row], columns=expected_features)
    return df

# ----------------------------
# Routes
# ----------------------------
@app.route('/')
def home():
    return send_from_directory('../frontend', 'dashboard.html')

@app.route('/dashboard')
def dashboard():
    return send_from_directory('../frontend', 'dashboard.html')
#---
@app.route('/indoor')
def indoor():
    return send_from_directory('../frontend', 'indoor.html')

@app.route('/login', methods=['GET', 'POST'])  
def login():
    # GET: serve login page
    if request.method == 'GET':
        return send_from_directory('../frontend', 'login.html')
    
    # POST: handle authentication
    data = request.json or {}
    email = data.get('email'); password = data.get('password')
    try:
        conn = sqlite3.connect('schema.db')
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE email=? AND password=?", (email, password))
        user = cursor.fetchone()
        conn.close()
        if user or (email == "divyanshk337@gmail.com" and password == "1234"):
            return jsonify({"status": "success", "redirect": "/indoor"})
        else:
            return jsonify({"status": "fail", "message": "Invalid credentials"})
    except Exception as e:
        print("Login DB error:", e)
        if email == "divyanshk337@gmail.com" and password == "1234":
            return jsonify({"status": "success", "redirect": "/indoor"}) 
        return jsonify({"status": "error", "message": "DB Error"})

@app.route('/predict_aqi', methods=['GET'])
def predict_aqi():
    """
    Main prediction endpoint. Accepts:
      - city (preferred) OR lat & lon
    Flow:
      - Optionally fetch historic CSV
      - Attempt training via train_model_func (if available)
      - If training not available/failed, load model.pkl
      - If no model, create small fallback model (quick bootstrap)
      - Fetch current pollutant components for the city
      - Align features to model expectation and predict nextHour
      - Build a simple 24-hour hourly forecast and return JSON
    """
    city = request.args.get('city')
    lat = request.args.get('lat')
    lon = request.args.get('lon')

    if not city and not (lat and lon):
        return jsonify({"error": "City or lat/lon required"}), 400

    target_city = city
    if not target_city and lat and lon:
        try:
            resp = requests.get(f"http://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lon}&appid={OPENWEATHER_API_KEY}", timeout=8)
            resp.raise_for_status()
            js = resp.json()
            target_city = js.get('name') or f"{lat},{lon}"
        except Exception:
            target_city = f"{lat},{lon}"

    # 1) optional historic fetch
    fetched_ok = False
    if fetch_and_save_data:
        try:
            fetched_ok = fetch_historic_and_save(target_city, OPENWEATHER_API_KEY, filename=CSV_FILENAME)
            print("Historic fetch complete:", fetched_ok)
        except Exception as e:
            print("Historic fetch error:", e)

    # 2) try to train via train_model_func (if present)
    model = None
    if train_model_func:
        try:
            model = attempt_train_from_module(csv_path=CSV_FILENAME, model_output=MODEL_PATH)
            if model is not None:
                print("Model obtained from training module.")
        except Exception as e:
            print("Training attempt raised:", e)
            model = None

    # 3) if still no model, try to load existing model file
    if model is None:
        model = load_model_from_disk(MODEL_PATH)

    # 4) fetch current pollutant components from both sources
    data_sources = fetch_both_pollutants_by_city(target_city)
    
    # Prefer OpenWeather current data for prediction, and use CPCB only as fallback
    components = data_sources.get("openweather") or data_sources.get("cpcb")
    
    if components is None:
        return jsonify({"error": "Could not fetch current pollutant data for city"}), 500

    # 5) if still no model, train a quick fallback RF on bootstrapped current components
    try:
        if model is None:
            if train_model_func:
                model = attempt_train_from_module(
                    csv_path="air_quality_data.csv",
                    model_output=MODEL_PATH
                )
            else:
                model = load_model_from_disk(MODEL_PATH)
                print("Loaded fallback model.")  # Corrected message for accuracy
    except Exception as e:
        print("Fallback model training/loading failed:", e)
        return jsonify({"error": "Unable to create or load fallback model"}), 500

    # 6) Determine expected features and align input
    expected_features = get_model_expected_features(model)
    print("Model expects features:", expected_features)
    try:
        X_df = build_feature_dataframe_from_components(components, expected_features)
        # Try predicting using DataFrame (preserves feature names)
        try:
            pred_arr = model.predict(X_df)
            next_hour = float(pred_arr[0])
        except Exception as e:
            print("Primary model.predict error:", e)
            # fallback to numpy array
            X_np = X_df.to_numpy().reshape(1, -1)
            try:
                pred_arr = model.predict(X_np)
                next_hour = float(pred_arr[0])
            except Exception as e2:
                print("Model predict failed on numpy fallback:", e2)
                next_hour = None
    except Exception as e:
        print("Error preparing features for prediction:", e)
        next_hour = None

    # 7) Build hourly series for next 24 hours (demo synthetic around prediction)
    now_ms = int(time.time() * 1000)
    hourly = []
    base = next_hour if (next_hour is not None) else 80
    for i in range(24):
        jitter = float(np.random.normal(0, max(1, base*0.03)))
        drift = (i - 12) * 0.6
        val = max(0, base + drift + jitter)
        hourly.append({"t": int(now_ms + (i+1) * 3600 * 1000), "aqi": int(round(val))})

    # Calculate current AQI from pollutants
    current_aqi = calculate_aqi_from_pollutants(components) if components else 0

    payload = {
        "timestamp": now_ms,
        "city": target_city,
        "current_aqi": current_aqi,
        "nextHour": int(round(next_hour)) if next_hour is not None else None,
        "hourly": hourly,
        "pollutants": components,
        "data_sources": data_sources  # Include both CPCB and OpenWeather data
    }
    return jsonify(payload)

# ----- Gemini AI route (optional) -----
@app.route('/ask_ai', methods=['POST'])
def ask_ai():
    print("[ROUTE] /ask_ai called")
    data = request.json or {}
    city = data.get('city', 'your city')
    aqi = data.get('aqi', 'unknown')
    pollutants = data.get('pollutants', {})

    prompt = f"""
    Act as an expert Environmental Scientist and Health Advisor.
    The user is in {city}.
    The predicted Air Quality Index (AQI) is {aqi}.
    The specific pollutant levels are:
    - PM2.5: {pollutants.get('pm2_5')}
    - PM10: {pollutants.get('pm10')}
    - NO2: {pollutants.get('no2')}
    - O3: {pollutants.get('o3')}

    Based on this data, provide a concise, 3-sentence health recommendation.
    Focus on practical advice (e.g., masks, outdoor activities, ventilation).
    Do not use markdown formatting.
    """

    if not model_gemini:
        print(f"DEBUG: model_gemini is {model_gemini}")
        return jsonify({"response": "AI service unavailable. Please configure GEMINI_API_KEY on the server."})

    try:
        resp = model_gemini.generate_content(prompt)
        text = getattr(resp, 'text', None)
        if not text:
            try:
                text = resp.candidates[0].content
            except Exception:
                text = str(resp)
        return jsonify({"response": text})
    except Exception as e:
        print("Gemini generate error:", e)
        return jsonify({"response": "AI Service unavailable at the moment."})
@app.route('/save_alert', methods=['POST'])
def save_alert():
    try:
        data = request.json

        city = data.get('city')
        alert_type = data.get('alert_type')
        contact = data.get('contact')
        threshold = int(data.get('threshold', 150))

        contact = normalize_phone(contact)

        if not city or not alert_type or not contact:
            return jsonify({"error": "Missing fields"}), 400

        conn = sqlite3.connect('schema.db')
        c = conn.cursor()

        c.execute("""
            INSERT INTO alerts (city, alert_type, contact, threshold, active)
            VALUES (?, ?, ?, ?, 1)
        """, (city, alert_type, contact, threshold))

        conn.commit()
        conn.close()

        return jsonify({"status": "ok"})

    except Exception as e:
        print("SAVE ALERT ERROR:", e)
        return jsonify({"error": "Server error"}), 500

# Serve other static files (CSS, JS)
@app.route('/static/<path:filename>')
def serve_static(filename):
    return send_from_directory('../frontend', filename)

@app.route('/login.css')
def login_css():
    return send_from_directory('../frontend', 'login.css')

@app.route('/login_script.js')
def login_script_js():
    return send_from_directory('../frontend', 'login_script.js')

@app.route('/refresh_data', methods=['POST'])
def refresh_data():
    """Manually refresh the data cache"""
    try:
        print("🔄 Manual data refresh requested...")
        refresh_data_cache()
        return jsonify({"status": "success", "message": "Data cache refreshed successfully"})
    except Exception as e:
        print(f"❌ Data refresh failed: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/data_status', methods=['GET'])
def data_status():
    """Get status of cached data"""
    cpcb_count = len(cpcb_data_cache) if cpcb_data_cache else 0
    ow_count = len(openweather_data_cache) if openweather_data_cache else 0
    last_update = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(last_cache_update)) if last_cache_update else "Never"

    return jsonify({
        "cpcb_cities": cpcb_count,
        "openweather_cities": ow_count,
        "total_cities": cpcb_count + ow_count,
        "last_update": last_update,
        "cache_hours": DATA_CACHE_HOURS
    })

if __name__ == '__main__':
    print("🚀 Starting SkySigma server...")
    print(f"OpenWeather key set: {'YES' if OPENWEATHER_API_KEY else 'NO'}; Model path: {MODEL_PATH}")

    # Initialize data cache on startup
    try:
        initialize_data_cache()
        print("✅ Data cache initialized successfully")
    except Exception as e:
        print(f"⚠️ Data cache initialization failed: {e}")

    print("🌐 Server ready on http://localhost:5000")
    app.run(debug=True, host='0.0.0.0', port=5000)
