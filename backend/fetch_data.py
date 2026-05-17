import requests
import pandas as pd
import joblib
import os
import time
from datetime import datetime, timedelta

# ================================
# CONFIG
# ================================
CPCB_API_KEY = ""
CPCB_URL = "https://api.data.gov.in/resource/3b01bcb8-0b14-4abf-b6f2-c1bfd384ba69"

OWM_API_KEY = ""

MODEL_PATH = "models/model.pkl"


# ================================
# FETCH CPCB
# ================================
def fetch_cpcb(city):
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

        return rows if rows else None

    except Exception as e:
        print("❌ CPCB Error:", e)
        return None


# ================================
# GET LAT/LON FROM CITY NAME
# ================================
def get_lat_lon(city):
    try:
        geo_url = f"http://api.openweathermap.org/data/2.5/weather?q={city}&appid={OWM_API_KEY}"
        geo = requests.get(geo_url).json()
        lat = geo["coord"]["lat"]
        lon = geo["coord"]["lon"]
        return lat, lon
    except Exception as e:
        print(f"❌ Geocoding Error: {e}")
        return None, None


# ================================
# FETCH OPENWEATHER (CURRENT)
# ================================
def fetch_openweather(city):
    try:
        lat, lon = get_lat_lon(city)
        if lat is None or lon is None:
            return None

        air_url = f"http://api.openweathermap.org/data/2.5/air_pollution?lat={lat}&lon={lon}&appid={OWM_API_KEY}"
        air = requests.get(air_url).json()

        comp = air["list"][0]["components"]

        return [{
            "pm2_5": comp.get("pm2_5", 0),
            "pm10": comp.get("pm10", 0),
            "no2": comp.get("no2", 0),
            "so2": comp.get("so2", 0),
            "co": comp.get("co", 0),
            "o3": comp.get("o3", 0),
            "aqi": 0
        }]

    except Exception as e:
        print("❌ OpenWeather Error:", e)
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

        print(f"📊 Fetching {days} days of historical data from {datetime.fromtimestamp(start_time)} to {datetime.fromtimestamp(end_time)}")

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
# SAVE CSV
# ================================
def save_csv(data, filename="air_data.csv"):
    df = pd.DataFrame(data)
    df.to_csv(filename, index=False)
    return df


# ================================
# TRAIN MODEL (SIMPLE INLINE)
# ================================
def train_and_predict(df):
    from sklearn.ensemble import RandomForestRegressor

    features = ['pm2_5', 'pm10', 'no2', 'o3', 'so2', 'co']

    for f in features:
        if f not in df.columns:
            df[f] = 0

    X = df[features]

    # target
    if "aqi" in df.columns and df["aqi"].sum() > 0:
        y = df["aqi"]
    else:
        y = df[["pm2_5", "pm10", "no2"]].max(axis=1) * 1.5

    model = RandomForestRegressor(n_estimators=50)
    model.fit(X, y)

    pred = model.predict(X.iloc[-1:])[0]

    # normalize
    pred = int(max(20, min(pred, 200)))

    return pred


# ================================
# MAIN PIPELINE
# ================================
def get_aqi(city):
    print(f"\n🔍 Processing city: {city}")

    # STEP 1: CPCB
    data = fetch_cpcb(city)

    if data:
        print("✅ CPCB data used")
    else:
        print("⚠️ Falling back to OpenWeather")
        data = fetch_openweather(city)

        if not data:
            return None

    # STEP 2: SAVE CSV
    df = save_csv(data)

    # STEP 3: TRAIN + PREDICT
    aqi = train_and_predict(df)

    return aqi


# ================================
# FETCH AND SAVE HISTORICAL DATA (5 DAYS)
# ================================
def fetch_and_save_data(city, api_key=None, filename="air_quality_data.csv"):
    """Fetch 5 days of historical OpenWeather data for a city and save to CSV"""
    try:
        if api_key:
            global OWM_API_KEY
            OWM_API_KEY = api_key

        print(f"📊 Fetching 5 days of historical data for {city}...")

        # Fetch historical data
        data = fetch_openweather_historical(city, days=5)

        if data:
            # Save to CSV
            df = save_csv(data, filename)
            print(f"✅ Saved {len(data)} records to {filename}")
            return True
        else:
            print("❌ No historical data available")
            return False

    except Exception as e:
        print(f"❌ Error in fetch_and_save_data: {e}")
        return False


# ================================
# TEST
# ================================
if __name__ == "__main__":
    city = input("Enter city: ")

    result = get_aqi(city)

    if result:
        print(f"\n🌫️ Predicted AQI: {result}")
    else:
        print("❌ No data available")