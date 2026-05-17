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
CPCB_URL     = "https://api.data.gov.in/resource/3b01bcb8-0b14-4abf-b6f2-c1bfd384ba69"

OWM_API_KEY  = ""

MODEL_PATH   = "models/model.pkl"

# ── Separate persistent CSV files ──────────────────────────────────────────────
CPCB_CSV       = "cpcb_data.csv"
OPENWEATHER_CSV = "openweather_data.csv"


# ================================
# DUPLICATE-SAFE CSV APPEND
# ================================
def _append_to_csv(new_rows: list, filepath: str, city: str, source: str) -> pd.DataFrame:
    """
    Append new_rows to filepath only if they are not already present.

    Duplicate logic
    ---------------
    A record is considered a duplicate when another row in the CSV
    shares the same:
        • city   (case-insensitive)
        • source (CPCB | OpenWeather | OpenWeather-History)
        • fetch_hour  — the current timestamp rounded DOWN to the hour
                        e.g.  2025-05-06 14:35  →  2025-05-06 14:00

    This means: if you restart the server within the same hour the data
    was last fetched, nothing new is written.  If an hour has passed, the
    new reading is treated as genuinely fresh and appended.

    For OpenWeather historical records the API already returns one record
    per hour with its own unix timestamp; we use THAT timestamp (rounded
    to the hour) as the dedup key instead of the fetch time.
    """

    now         = datetime.now()
    fetch_hour  = now.strftime("%Y-%m-%d %H:00:00")   # e.g. "2025-05-06 14:00:00"
    fetch_ts    = now.strftime("%Y-%m-%d %H:%M:%S")

    # ── Stamp every incoming row ──────────────────────────────────────────────
    stamped = []
    for row in new_rows:
        r = dict(row)
        r["city"]       = city
        r["source"]     = source
        r["fetch_hour"] = r.get("fetch_hour", fetch_hour)   # historical rows carry own
        r["fetched_at"] = r.get("fetched_at", fetch_ts)
        stamped.append(r)

    new_df = pd.DataFrame(stamped)

    # ── Load existing CSV (or start empty) ────────────────────────────────────
    if os.path.exists(filepath) and os.path.getsize(filepath) > 0:
        try:
            existing_df = pd.read_csv(filepath)
        except Exception:
            existing_df = pd.DataFrame()
    else:
        existing_df = pd.DataFrame()

    # ── Find which rows are genuinely new ─────────────────────────────────────
    if existing_df.empty:
        to_add = new_df
        skipped = 0
    else:
        # Build a set of (city_lower, source, fetch_hour) already on disk
        key_col = existing_df.apply(
            lambda r: (
                str(r.get("city",  "")).lower(),
                str(r.get("source", "")),
                str(r.get("fetch_hour", ""))
            ),
            axis=1
        )
        existing_keys = set(key_col)

        mask_new = new_df.apply(
            lambda r: (
                str(r.get("city",  "")).lower(),
                str(r.get("source", "")),
                str(r.get("fetch_hour", ""))
            ),
            axis=1
        ).apply(lambda k: k not in existing_keys)

        to_add  = new_df[mask_new]
        skipped = (~mask_new).sum()

    # ── Report & write ────────────────────────────────────────────────────────
    if to_add.empty:
        print(f"  ⏭️  [{source}] All {len(new_df)} record(s) already exist in "
              f"'{filepath}' for this hour — skipping.")
        return existing_df

    print(f"  ✅ [{source}] Appending {len(to_add)} new record(s) to '{filepath}'"
          + (f" ({skipped} duplicate(s) skipped)." if skipped else "."))

    combined = pd.concat([existing_df, to_add], ignore_index=True)

    # Keep columns in a stable, readable order
    priority_cols = ["city", "source", "fetch_hour", "fetched_at",
                     "pm2_5", "pm10", "no2", "so2", "co", "o3", "nh3", "aqi"]
    extra_cols    = [c for c in combined.columns if c not in priority_cols]
    ordered_cols  = [c for c in priority_cols if c in combined.columns] + extra_cols
    combined      = combined[ordered_cols]

    combined.to_csv(filepath, index=False)
    return combined


# ================================
# FETCH CPCB
# ================================
def fetch_cpcb(city):
    """Fetch CPCB data for a city and aggregate pollutants per station."""
    try:
        params = {
            "api-key": CPCB_API_KEY,
            "format":  "json",
            "limit":   5000
        }
        res    = requests.get(CPCB_URL, params=params, timeout=10)
        data   = res.json()
        records = data.get("records", [])

        station_data = {}

        for r in records:
            city_name = str(r.get("city", "")).lower()
            if city.lower() not in city_name:
                continue

            station_name = r.get("station", "Unknown")
            pollutant_id = str(r.get("pollutant_id", "")).upper()
            avg_val      = r.get("avg_value", "0")

            try:
                avg_value = float(avg_val) if avg_val and avg_val != "NA" else 0
            except Exception:
                avg_value = 0

            if station_name not in station_data:
                station_data[station_name] = {
                    "pm2_5": 0, "pm10": 0, "no2": 0,
                    "so2":   0, "co":   0, "o3":  0,
                    "nh3":   0, "aqi":  0
                }

            if   pollutant_id in ["PM2.5", "PM25", "PM2_5"]:
                station_data[station_name]["pm2_5"] = avg_value
            elif pollutant_id == "PM10": station_data[station_name]["pm10"] = avg_value
            elif pollutant_id == "NO2":  station_data[station_name]["no2"]  = avg_value
            elif pollutant_id == "SO2":  station_data[station_name]["so2"]  = avg_value
            elif pollutant_id == "CO":   station_data[station_name]["co"]   = avg_value
            elif pollutant_id == "O3":   station_data[station_name]["o3"]   = avg_value
            elif pollutant_id == "NH3":  station_data[station_name]["nh3"]  = avg_value

        rows = [p for p in station_data.values() if p["pm2_5"] > 0]
        return rows if rows else None

    except Exception as e:
        print("❌ CPCB Error:", e)
        return None


# ================================
# GET LAT/LON FROM CITY NAME
# ================================
def get_lat_lon(city):
    try:
        geo_url = (f"http://api.openweathermap.org/data/2.5/weather"
                   f"?q={city}&appid={OWM_API_KEY}")
        geo = requests.get(geo_url).json()
        return geo["coord"]["lat"], geo["coord"]["lon"]
    except Exception as e:
        print(f"❌ Geocoding Error: {e}")
        return None, None


# ================================
# FETCH OPENWEATHER (CURRENT)
# ================================
def fetch_openweather(city):
    try:
        lat, lon = get_lat_lon(city)
        if lat is None:
            return None

        air_url = (f"http://api.openweathermap.org/data/2.5/air_pollution"
                   f"?lat={lat}&lon={lon}&appid={OWM_API_KEY}")
        air  = requests.get(air_url).json()
        comp = air["list"][0]["components"]

        return [{
            "pm2_5": comp.get("pm2_5", 0),
            "pm10":  comp.get("pm10",  0),
            "no2":   comp.get("no2",   0),
            "so2":   comp.get("so2",   0),
            "co":    comp.get("co",    0),
            "o3":    comp.get("o3",    0),
            "aqi":   0
        }]

    except Exception as e:
        print("❌ OpenWeather Error:", e)
        return None


# ================================
# FETCH OPENWEATHER HISTORICAL (5 DAYS)
# ================================
def fetch_openweather_historical(city, days=5):
    """Fetch up to `days` days of historical air-pollution data from OpenWeather."""
    try:
        lat, lon = get_lat_lon(city)
        if lat is None:
            return None

        end_time   = int(time.time())
        start_time = end_time - (days * 24 * 3600)

        print(f"  📡 Fetching {days}d history: "
              f"{datetime.fromtimestamp(start_time)} → "
              f"{datetime.fromtimestamp(end_time)}")

        hist_url = (
            f"http://api.openweathermap.org/data/2.5/air_pollution/history"
            f"?lat={lat}&lon={lon}&start={start_time}&end={end_time}"
            f"&appid={OWM_API_KEY}"
        )
        response = requests.get(hist_url, timeout=30).json()
        records  = response.get("list", [])

        rows = []
        for record in records:
            comp = record.get("components", {})
            # Use the API's own unix timestamp as the authoritative dedup key
            api_unix = record.get("dt", end_time)
            api_hour = datetime.utcfromtimestamp(api_unix).strftime("%Y-%m-%d %H:00:00")

            row = {
                "pm2_5":      comp.get("pm2_5", 0),
                "pm10":       comp.get("pm10",  0),
                "no2":        comp.get("no2",   0),
                "so2":        comp.get("so2",   0),
                "co":         comp.get("co",    0),
                "o3":         comp.get("o3",    0),
                "aqi":        record.get("main", {}).get("aqi", 0),
                # Pre-stamp so _append_to_csv uses the API hour, not fetch time
                "fetch_hour": api_hour,
                "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
            if row["pm2_5"] > 0:
                rows.append(row)

        print(f"  ✅ {len(rows)} historical records fetched")
        return rows if rows else None

    except Exception as e:
        print(f"❌ OpenWeather Historical Error: {e}")
        return None


# ================================
# TRAIN MODEL (SIMPLE INLINE)
# ================================
def train_and_predict(df):
    from sklearn.ensemble import RandomForestRegressor

    features = ["pm2_5", "pm10", "no2", "o3", "so2", "co"]
    for f in features:
        if f not in df.columns:
            df[f] = 0

    X = df[features]
    if "aqi" in df.columns and df["aqi"].sum() > 0:
        y = df["aqi"]
    else:
        y = df[["pm2_5", "pm10", "no2"]].max(axis=1) * 1.5

    model = RandomForestRegressor(n_estimators=50)
    model.fit(X, y)

    pred = model.predict(X.iloc[-1:])[0]
    return int(max(20, min(pred, 200)))


# ================================
# MAIN PIPELINE  (get_aqi)
# ================================
def get_aqi(city):
    """
    Fetch live data for `city`, persist it to CSV (dedup-safe), and
    return a predicted AQI value.
    """
    print(f"\n🔍 Processing city: {city}")

    # ── STEP 1: fetch ─────────────────────────────────────────────────────────
    cpcb_data = fetch_cpcb(city)

    if cpcb_data:
        print("  ✅ CPCB data fetched")
        combined_df = _append_to_csv(cpcb_data, CPCB_CSV, city, source="CPCB")
    else:
        print("  ⚠️  CPCB unavailable — falling back to OpenWeather")
        owm_data = fetch_openweather(city)
        if not owm_data:
            print("  ❌ No data available")
            return None
        combined_df = _append_to_csv(owm_data, OPENWEATHER_CSV, city, source="OpenWeather")

    # ── STEP 2: predict ───────────────────────────────────────────────────────
    # Use the full history for the requested city so the model sees context
    city_df = combined_df[
        combined_df["city"].str.lower() == city.lower()
    ].copy()

    aqi = train_and_predict(city_df)
    return aqi


# ================================
# FETCH AND SAVE HISTORICAL DATA
# ================================
def fetch_and_save_data(city, api_key=None, filename=None):
    """
    Fetch 5 days of OpenWeather historical data for `city` and
    append (dedup-safe) to OPENWEATHER_CSV.

    `filename` is accepted for backward-compatibility but ignored;
    data always goes to OPENWEATHER_CSV so history is never lost.
    """
    try:
        if api_key:
            global OWM_API_KEY
            OWM_API_KEY = api_key

        if filename and filename != OPENWEATHER_CSV:
            print(f"  ℹ️  Note: data will be saved to '{OPENWEATHER_CSV}' "
                  f"(not '{filename}') to preserve history.")

        print(f"\n📊 Fetching 5-day history for '{city}' …")
        data = fetch_openweather_historical(city, days=5)

        if data:
            _append_to_csv(data, OPENWEATHER_CSV, city, source="OpenWeather-History")
            return True
        else:
            print("  ❌ No historical data returned")
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
        print(f"\n🌫️  Predicted AQI for {city}: {result}")
        print(f"📁  CPCB history    → {CPCB_CSV}")
        print(f"📁  OWM history     → {OPENWEATHER_CSV}")
    else:
        print("❌ No data available")
