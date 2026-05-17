# AirVision Project - Setup Guide

## ✅ Completed Fixes

### 1. Database Created ✓
- Database file: `backend/schema.db`
- Users table created with sample data
- Login credentials available:
  - `divyanshk337@gmail.com` / `1234` (hardcoded)
  - `test@example.com` / `password123` (database)

### 2. Google Generative AI Package Installed ✓
- Package: `google-generativeai` installed successfully
- Note: This package is deprecated; consider upgrading to `google.genai` in the future

### 3. Database Login Working ✓
- `/login` endpoint now properly authenticates users from the database

---

## 🆕 New Cached Data Architecture (v2.0)

### Overview
The server now uses a **cached data architecture** for improved performance:

- **Startup**: Fetches all Indian cities data from CPCB and major cities from OpenWeather
- **Storage**: Two separate CSV files (`cpcb_data.csv` and `openweather_data.csv`)
- **Caching**: In-memory cache with automatic refresh every 24 hours
- **Fallback**: CPCB → OpenWeather cache → Fresh OpenWeather API call

### Key Improvements
- ⚡ **Faster responses**: No API calls for cached cities
- 💾 **Persistent storage**: Data saved to CSV files
- 🔄 **Auto-refresh**: Cache updates every 24 hours
- 🎯 **Smart fallback**: Hierarchical data source priority
- 📊 **AQI calculation**: Real-time AQI from pollutant data

### New Endpoints
- `GET /data_status` - Check cache status and statistics
- `POST /refresh_data` - Manually refresh data cache

### Configuration
Set these environment variables to customize:

```bash
# Cache refresh interval (hours)
export DATA_CACHE_HOURS=24

# CSV file paths
export CPCB_CSV=cpcb_data.csv
export OPENWEATHER_CSV=openweather_data.csv
```

### Testing
Run the test script to verify the new architecture:
```bash
cd backend
python test_cached_architecture.py
```

---

## ⚙️ GEMINI_API_KEY Configuration (Required for AI Features)

The `/ask_ai` endpoint requires a Google Gemini API key to provide health recommendations.

### Steps to Configure:

#### Option 1: Set Environment Variable (Recommended)

**On Windows (PowerShell):**
```powershell
$env:GEMINI_API_KEY = "your-api-key-here"
python backend/app.py
```

**On Windows (Command Prompt):**
```cmd
set GEMINI_API_KEY=your-api-key-here
python backend/app.py
```

**On Linux/Mac (Bash):**
```bash
export GEMINI_API_KEY="your-api-key-here"
python backend/app.py
```

#### Option 2: Create a .env File

Create a file named `.env` in the project root:
```
GEMINI_API_KEY=your-api-key-here
OPENWEATHER_API_KEY=
```

Then load it before running the server:
```powershell
# On Windows (PowerShell)
Get-Content .env | ForEach-Object { $_ -match '(.+)=(.+)' | Out-Null; [Environment]::SetEnvironmentVariable($Matches[1], $Matches[2]) }
```

### How to Get Your API Key:

1. Visit: https://aistudio.google.com/apikey
2. Click "Create API Key" button
3. Copy the generated key
4. Set it as the `GEMINI_API_KEY` environment variable

---

## 🧪 Testing Your Setup

### 1. Test Prediction Endpoint
```powershell
Invoke-WebRequest -Uri "http://localhost:5000/predict_aqi?city=Delhi" -UseBasicParsing
```

### 2. Test Login Endpoint
```powershell
$body = @{email="test@example.com"; password="password123"} | ConvertTo-Json
Invoke-WebRequest -Uri "http://localhost:5000/login" -Method POST `
  -Headers @{"Content-Type"="application/json"} -Body $body -UseBasicParsing
```

### 3. Test AI Endpoint (after setting GEMINI_API_KEY)
```powershell
$body = @{city="Delhi"; aqi=150; pollutants=@{pm2_5=100; pm10=200; no2=50; o3=30}} | ConvertTo-Json
Invoke-WebRequest -Uri "http://localhost:5000/ask_ai" -Method POST `
  -Headers @{"Content-Type"="application/json"} -Body $body -UseBasicParsing
```

---

## 📝 Add More Users to Database

To add more test users:
```powershell
python -c "
import sqlite3
conn = sqlite3.connect('backend/schema.db')
cursor = conn.cursor()
cursor.execute('INSERT OR IGNORE INTO users (email, password) VALUES (?, ?)', ('user@example.com', 'password'))
conn.commit()
conn.close()
print('User added successfully')
"
```

---

## 🚀 Server Status

Your server is running on: **http://localhost:5000**

- Dashboard: http://localhost:5000/dashboard
- Login: http://localhost:5000/login
- Indoor: http://localhost:5000/indoor

---

## ⚠️ Important Notes

1. **Development Only**: This is a development server. Use a production WSGI server (like Gunicorn) for production deployment.
2. **API Keys**: Never commit API keys to version control. Use environment variables instead.
3. **Database**: The SQLite database is suitable for development. Use PostgreSQL for production.
4. **Debug Mode**: Debug mode is enabled for development. Disable it in production.

---

## 🐛 Troubleshooting

**Issue**: "Database not found" error
- **Solution**: Ensure `backend/schema.db` exists in the backend directory

**Issue**: "GEMINI_API_KEY not set" warning
- **Solution**: Set the `GEMINI_API_KEY` environment variable before starting the server

**Issue**: "google.generativeai not installed"
- **Solution**: Run `pip install google-generativeai --upgrade`

---

## 📦 Required Packages

All required packages should be installed. If you're missing any, run:
```
pip install -r requirements.txt
```

Current packages:
- Flask
- Flask-CORS
- requests
- scikit-learn
- pandas
- numpy
- joblib
- google-generativeai (newly added)

