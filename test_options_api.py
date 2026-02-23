import requests

BASE_URL = "http://127.0.0.1:3000"

def test_endpoint(path):
    try:
        url = f"{BASE_URL}{path}"
        print(f"Testing {url}...")
        response = requests.get(url)
        if response.status_code == 200:
            print(f"SUCCESS: {path} returned 200")
            # print(response.json())
        else:
            print(f"FAILED: {path} returned {response.status_code}")
    except Exception as e:
        print(f"ERROR: {path} failed: {e}")

if __name__ == "__main__":
    test_endpoint("/api/options/oi-trend-detailed/NSE:NIFTY")
    test_endpoint("/api/options/oi-analysis/NSE:NIFTY")
    test_endpoint("/api/options/genie-insights/NSE:NIFTY")
