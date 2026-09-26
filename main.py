import requests
from decouple import config


def main():
    print("Testing PayVessel identity verification")

    base_url = config("PAYVESSEL_BASE_URL", default="https://sandbox.payvessel.com")
    api_key = config("PAYVESSEL_API_KEY")
    api_secret = config("PAYVESSEL_API_SECRET")

    url = base_url.rstrip("/") + "/kyc/api/v1/merchant/bvn/basic"

    payload = {
        "bvn": "22123456789",
        "first_name": "John",
        "middle_name": "Adebayo",
        "last_name": "Doe",
        "gender": "MALE",
        "birthday": "1992-08-14",
        "phone_number": "08012345678",
    }
    headers = {
        "Content-Type": "application/json",
        "api-key": api_key,
        "api-secret": api_secret,
    }

    print(f"URL: {url}")
    print(f"API key: {api_key[:20]}...")

    response = requests.post(url, json=payload, headers=headers, timeout=30)
    print(f"Status: {response.status_code}")
    print(response.text)


if __name__ == "__main__":
    main()
