import requests
import json

CPCB_API_KEY = ''
CPCB_URL = 'https://api.data.gov.in/resource/3b01bcb8-0b14-4abf-b6f2-c1bfd384ba69'

params = {
    'api-key': CPCB_API_KEY,
    'format': 'json',
    'limit': 10
}

try:
    print('🔄 Testing CPCB API...')
    response = requests.get(CPCB_URL, params=params, timeout=10)
    print(f'Status Code: {response.status_code}')
    
    data = response.json()
    print(f'Response Keys: {list(data.keys())}')
    
    if 'records' in data:
        print(f'Total Records Available: {data.get("total", "Unknown")}')
        print(f'Sample Records Count: {len(data.get("records", []))}')
        
        if len(data.get('records', [])) > 0:
            sample = data['records'][0]
            print(f'Sample Record Keys: {list(sample.keys())}')
            print(f'\nSample Record:')
            print(json.dumps(sample, indent=2)[:500])
        else:
            print('No records in response')
    else:
        print(f'Full Response (first 500 chars):')
        print(json.dumps(data, indent=2)[:500])
        
except Exception as e:
    print(f'❌ Error: {type(e).__name__}: {e}')
