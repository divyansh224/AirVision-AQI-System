#!/usr/bin/env python3
"""
Test script for the new cached data architecture
"""

import requests
import json
import time
import os

# Adjust BASE_URL if running from backend folder
BASE_URL = "http://localhost:5000"

def test_data_status():
    """Test data status endpoint"""
    print("🔍 Testing data status...")
    try:
        response = requests.get(f"{BASE_URL}/data_status")
        if response.status_code == 200:
            data = response.json()
            print("✅ Data status:")
            print(json.dumps(data, indent=2))
            return True
        else:
            print(f"❌ Status check failed: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ Connection error: {e}")
        return False

def test_prediction(city):
    """Test AQI prediction for a city"""
    print(f"\n🔍 Testing prediction for {city}...")
    try:
        response = requests.get(f"{BASE_URL}/predict_aqi?city={city}")
        if response.status_code == 200:
            data = response.json()
            print("✅ Prediction successful:")
            print(f"   City: {data.get('city')}")
            print(f"   Current AQI: {data.get('current_aqi')}")
            print(f"   Next Hour AQI: {data.get('nextHour')}")
            print(f"   Data Source: {data.get('data_source')}")
            print(f"   Pollutants: {data.get('pollutants')}")
            return True
        else:
            print(f"❌ Prediction failed: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        print(f"❌ Connection error: {e}")
        return False

def test_refresh_data():
    """Test manual data refresh"""
    print("\n🔄 Testing data refresh...")
    try:
        response = requests.post(f"{BASE_URL}/refresh_data")
        if response.status_code == 200:
            data = response.json()
            print("✅ Data refresh successful:")
            print(json.dumps(data, indent=2))
            return True
        else:
            print(f"❌ Refresh failed: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        print(f"❌ Connection error: {e}")
        return False

if __name__ == "__main__":
    print("🧪 Testing new cached data architecture...")
    print("=" * 50)

    # Test data status
    if not test_data_status():
        print("❌ Server not running or data status check failed")
        exit(1)

    # Test predictions for different cities
    cities = ["delhi", "mumbai", "bangalore", "chennai"]
    for city in cities:
        test_prediction(city)
        time.sleep(1)  # Small delay between requests

    # Test data refresh
    test_refresh_data()

    print("\n" + "=" * 50)
    print("✅ Testing completed!")