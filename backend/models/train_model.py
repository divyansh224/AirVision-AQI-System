# models/train_model.py

import os
import json
import joblib
import pandas as pd
import numpy as np
import sys
import requests
from datetime import datetime, timedelta
import time

from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score


# ================================
# API CONFIG
# ================================
CPCB_API_KEY = "579b464db66ec23bdd0000011faffeb8609e489a794bababc54e3a20"
CPCB_URL = "https://api.data.gov.in/resource/3b01bcb8-0b14-4abf-b6f2-c1bfd384ba69"
OWM_API_KEY = "59f12ffb3e8557f8cb24c937ab96283e"


# ================================
# PATH SETUP
# ================================
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
csv_path = os.path.join(BASE_DIR, "..", "air_quality_data.csv")  # Go up one level to project root

MODEL_PATH = os.path.join(BASE_DIR, "models", "model.pkl")
META_PATH = os.path.join(BASE_DIR, "models", "model_meta.json")



# ================================
# AQI CALCULATION (EPA STYLE)
# ================================
def calculate_aqi(concentration, breakpoints):
    try:
        for i in range(len(breakpoints) - 1):
            if breakpoints[i][0] <= concentration <= breakpoints[i + 1][0]:
                Clow, Chigh = breakpoints[i][0], breakpoints[i + 1][0]
                Ilow, Ihigh = breakpoints[i][1], breakpoints[i + 1][1]
                return round(((Ihigh - Ilow) / (Chigh - Clow)) * (concentration - Clow) + Ilow)
    except:
        pass
    return 0


# ================================
# GET LAT/LON FROM CITY NAME
# ================================
def get_lat_lon(city):
    try:
        geo_url = f"http://api.openweathermap.org/data/2.5/weather?q={city}&appid={OWM_API_KEY}"
        geo = requests.get(geo_url, timeout=10).json()
        lat = geo["coord"]["lat"]
        lon = geo["coord"]["lon"]
        return lat, lon
    except Exception as e:
        print(f"❌ Geocoding Error: {e}")
        return None, None


# ================================
# FETCH CPCB DATA
# ================================
def fetch_cpcb_data(city):
    """Fetch CPCB data for a city and aggregate pollutants per station"""
    try:
        params = {
            "api-key": CPCB_API_KEY,
            "format": "json",
            "limit": 5000
        }

        res = requests.get(CPCB_URL, params=params, timeout=10)
        data = res.json()

        records = data.get("records", [])
        
        # Group by city and station
        station_data = {}

        for r in records:
            city_name = str(r.get("city", "")).lower()
            if city.lower() not in city_name:
                continue

            station_name = r.get("station", "Unknown")
            pollutant_id = str(r.get("pollutant_id", "")).upper()
            avg_val = r.get("avg_value", "0")
            
            # Handle 'NA' values
            try:
                avg_value = float(avg_val) if avg_val and avg_val != "NA" else 0
            except:
                avg_value = 0

            # Initialize station record if not exists
            if station_name not in station_data:
                station_data[station_name] = {
                    "pm2_5": 0,
                    "pm10": 0,
                    "no2": 0,
                    "so2": 0,
                    "co": 0,
                    "o3": 0,
                    "nh3": 0,
                    "aqi": 0
                }

            # Map pollutant IDs to our field names
            if pollutant_id in ["PM2.5", "PM25", "PM2_5"]:
                station_data[station_name]["pm2_5"] = avg_value
            elif pollutant_id == "PM10":
                station_data[station_name]["pm10"] = avg_value
            elif pollutant_id == "NO2":
                station_data[station_name]["no2"] = avg_value
            elif pollutant_id == "SO2":
                station_data[station_name]["so2"] = avg_value
            elif pollutant_id == "CO":
                station_data[station_name]["co"] = avg_value
            elif pollutant_id == "O3":
                station_data[station_name]["o3"] = avg_value
            elif pollutant_id == "NH3":
                station_data[station_name]["nh3"] = avg_value

        # Convert to list and filter by pm2_5 > 0
        rows = []
        for station, pollutants in station_data.items():
            if pollutants["pm2_5"] > 0:
                rows.append(pollutants)

        print(f"✅ CPCB API: Found {len(rows)} stations with valid PM2.5 data")
        return rows if rows else None

    except Exception as e:
        print(f"❌ CPCB Error: {e}")
        return None


# ================================
# FETCH OPENWEATHER HISTORICAL (5 DAYS)
# ================================
def fetch_openweather_historical(city, days=5):
    """Fetch 5 days of historical air pollution data from OpenWeather"""
    try:
        lat, lon = get_lat_lon(city)
        if lat is None or lon is None:
            return None

        # Calculate start and end timestamps (unix)
        end_time = int(time.time())
        start_time = end_time - (days * 24 * 3600)  # 5 days back

        print(f"📊 Fetching {days} days of historical data...")
        print(f"   From: {datetime.fromtimestamp(start_time).strftime('%Y-%m-%d')} To: {datetime.fromtimestamp(end_time).strftime('%Y-%m-%d')}")

        hist_url = f"http://api.openweathermap.org/data/2.5/air_pollution/history?lat={lat}&lon={lon}&start={start_time}&end={end_time}&appid={OWM_API_KEY}"
        response = requests.get(hist_url, timeout=30).json()

        records = response.get("list", [])
        rows = []

        for record in records:
            comp = record.get("components", {})
            row = {
                "pm2_5": comp.get("pm2_5", 0),
                "pm10": comp.get("pm10", 0),
                "no2": comp.get("no2", 0),
                "so2": comp.get("so2", 0),
                "co": comp.get("co", 0),
                "o3": comp.get("o3", 0),
                "aqi": record.get("main", {}).get("aqi", 0)
            }
            if row["pm2_5"] > 0:
                rows.append(row)

        print(f"✅ Fetched {len(rows)} historical records")
        return rows if rows else None

    except Exception as e:
        print(f"❌ OpenWeather Historical Error: {e}")
        return None


# ================================
# FETCH DATA BASED ON CITY
# ================================
def fetch_data_for_city(city):
    """
    Fetch data for a city. Priority:
    1. CPCB (requires at least 2 rows)
    2. OpenWeather Historical (5 days)
    """
    print(f"\n🔍 Processing city: {city}")
    
    # Try CPCB first
    print("🔄 Checking CPCB API...")
    cpcb_data = fetch_cpcb_data(city)
    
    if cpcb_data and len(cpcb_data) >= 2:
        print(f"✅ Using CPCB data ({len(cpcb_data)} rows)")
        return cpcb_data
    elif cpcb_data and len(cpcb_data) == 1:
        print(f"⚠️ CPCB has only 1 row, need at least 2. Falling back to OpenWeather...")
    else:
        print(f"⚠️ CPCB data not found. Falling back to OpenWeather Historical...")
    
    # Fall back to OpenWeather Historical
    owm_data = fetch_openweather_historical(city, days=5)
    
    if owm_data and len(owm_data) >= 2:
        print(f"✅ Using OpenWeather Historical data ({len(owm_data)} rows)")
        return owm_data
    
    print("❌ No sufficient data available from both sources")
    return None


# ================================
# TRAIN MODEL
# ================================
def train_model(csv_path=None):
    """
    Train model on data from the specified CSV file.
    If csv_path is None, prompt for city and fetch data.
    Returns: (model, features_used, metrics_dict)
    """
    print("\n" + "="*60)
    print("🤖 MODEL TRAINING PIPELINE")
    print("="*60)

    # STEP 1: LOAD DATA
    if csv_path and os.path.exists(csv_path):
        # Load from CSV file
        df = pd.read_csv(csv_path)
        print(f"📊 Loaded data from CSV: {csv_path} ({len(df)} rows)")
        city = "CSV data"
    else:
        # Fallback: fetch data for city
        if csv_path:
            city = csv_path  # treat csv_path as city name
        else:
            city = input("Enter city name: ")
        
        data_list = fetch_data_for_city(city)
        
        if not data_list:
            print("❌ No data available for training")
            return None, None, None

        df = pd.DataFrame(data_list)
        print(f"📊 Dataset fetched: {len(df)} rows")

    # STEP 2: CLEAN DATA
    df = df.fillna(0)

    # STEP 3: AQI BREAKPOINTS
    breakpoints_dict = {
        'pm2_5': [(0.0, 0), (12.0, 50), (35.4, 100), (55.4, 150), (150.4, 200), (250.4, 300), (350.4, 400), (500.4, 500)],
        'pm10':  [(0.0, 0), (54, 50), (154, 100), (254, 150), (354, 200), (424, 300), (504, 400), (604, 500)],
        'no2':   [(0.0, 0), (53, 50), (100, 100), (360, 150), (649, 200), (1249, 300), (1649, 400), (2049, 500)],
        'o3':    [(0.0, 0), (54, 50), (70, 100), (85, 150), (105, 200), (200, 300), (300, 400), (400, 500)],
        'so2':   [(0.0, 0), (35, 50), (75, 100), (185, 150), (304, 200), (604, 300), (804, 400), (1004, 500)],
        'co':    [(0.0, 0), (4.4, 50), (9.4, 100), (12.4, 150), (15.4, 200), (30.4, 300), (40.4, 400), (50.4, 500)],
    }

    FEATURE_ORDER = ['pm2_5', 'pm10', 'no2', 'o3', 'so2', 'co']

    print("⚙️ Calculating AQI sub-indices...")

    aqi_columns = []
    features_used = []

    for pollutant in FEATURE_ORDER:
        if pollutant in df.columns:
            df[pollutant] = df[pollutant].fillna(0)

            # Convert units for gases before AQI calculation (EPA standard)
            if pollutant == 'co':
                converted_values = df[pollutant] / 1145  # µg/m³ → ppm
            elif pollutant == 'no2':
                converted_values = df[pollutant] / 1.88  # µg/m³ → ppb
            elif pollutant == 'so2':
                converted_values = df[pollutant] / 2.62  # µg/m³ → ppb
            elif pollutant == 'o3':
                converted_values = df[pollutant] / 2.0   # µg/m³ → ppb
            else:
                converted_values = df[pollutant]  # PM2.5, PM10 stay in µg/m³

            aqi_col = f"{pollutant}_AQI"
            df[aqi_col] = converted_values.apply(
                lambda x: calculate_aqi(x, breakpoints_dict[pollutant])
            )

            aqi_columns.append(aqi_col)
            features_used.append(pollutant)

    if not aqi_columns:
        print("❌ No pollutant columns found")
        return None, None, None

    # STEP 4: FINAL AQI (TARGET)
    df["final_aqi"] = df[aqi_columns].max(axis=1)

    # STEP 5: REMOVE OUTLIERS
    df_filtered = df[(df["final_aqi"] > 0) & (df["final_aqi"] < 500)]
    removed = len(df) - len(df_filtered)
    print(f"🧹 Removed {removed} outlier(s), {len(df_filtered)} rows remaining")
    
    if len(df_filtered) < 2:
        print("❌ Not enough data after filtering (need at least 2 rows)")
        return None, None, None

    df = df_filtered

    # STEP 6: FEATURES & TARGET
    X = df[features_used]
    y = df["final_aqi"]

    print(f"📌 Using features: {features_used}")
    print(f"📈 Final dataset size: {len(df)} rows")

    # STEP 7: SPLIT DATA
    test_size = 0.2 if len(df) >= 5 else 0.3  # Adjust split ratio for small datasets
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=test_size, random_state=42
    )

    print(f"✂️ Train/Test split: {len(X_train)} / {len(X_test)}")

    # STEP 8: TRAIN MODEL
    print("🤖 Training Random Forest model...")

    model = RandomForestRegressor(
        n_estimators=200,
        max_depth=12,
        min_samples_split=5,
        random_state=42,
        n_jobs=-1
    )

    model.fit(X_train, y_train)

    # STEP 9: EVALUATION
    y_pred = model.predict(X_test)

    mae = mean_absolute_error(y_test, y_pred)
    mse = mean_squared_error(y_test, y_pred)
    rmse = np.sqrt(mse)
    r2 = r2_score(y_test, y_pred)

    metrics = {
        "mae": float(mae),
        "mse": float(mse),
        "rmse": float(rmse),
        "r2": float(r2),
        "train_samples": len(X_train),
        "test_samples": len(X_test),
        "total_samples": len(df),
        "city": city
    }

    print("\n📊 MODEL PERFORMANCE")
    print(f"MAE  : {mae:.2f}")
    print(f"RMSE : {rmse:.2f}")
    print(f"R²   : {r2:.3f}")

    # STEP 10: SAVE MODEL
    os.makedirs(os.path.dirname(MODEL_PATH), exist_ok=True)

    joblib.dump(model, MODEL_PATH)

    meta = {
        "features": features_used,
        "city": city,
        "metrics": metrics,
        "trained_at": datetime.now().isoformat(),
        "data_source": "csv" if csv_path and os.path.exists(csv_path) else "api"
    }

    with open(META_PATH, "w") as f:
        json.dump(meta, f, indent=2)

    print(f"\n💾 Model saved → {MODEL_PATH}")
    print(f"📄 Meta saved → {META_PATH}")
    print("="*60 + "\n")

    return model, features_used, metrics


# ================================
# RUN
# ================================
if __name__ == "__main__":
    if len(sys.argv) > 1:
        city = sys.argv[1]
    else:
        city = input("Enter city name: ")
    
    model, features, metrics = train_model(city)
    
    if metrics:
        print(f"\n✅ Training completed for {city}")
        print(json.dumps(metrics, indent=2))
    else:
        print(f"\n❌ Training failed for {city}")