"""
Thin PayVessel API client.

Endpoint confidence, as of this build:

  - Reserved (virtual) account creation — CONFIRMED against
    docs.payvessel.com/api-reference/virtual-accounts/create-virtual-account:
        POST /pms/api/external/request/customerReservedAccount/

  - NIN Basic Verification — CONFIRMED against
    docs.payvessel.com/api-reference/verification/basic-nin-verification:
        POST /kyc/api/v1/merchant/nin/basic
    Response shape uses per-field match verdicts (name_match_rlt,
    birthday_match_rlt, gender_match_rlt, phone_number_match_rlt) plus
    names_match_percentage — NOT a raw name/DOB return to compare
    yourself. tasks.py relies on this exact shape.

  - BVN Basic Verification — NOT independently confirmed in the docs
    fetched for this build. Inferred by symmetry with the NIN endpoint as:
        POST /kyc/api/v1/merchant/bvn/basic
    CONFIRM this against docs.payvessel.com/api-reference/verification/
    before relying on it in production. If the real path differs, only
    BVN_VERIFY_PATH below needs to change — nothing else in this client.

Base URLs:
  production: https://api.payvessel.com
  sandbox:    https://sandbox.payvessel.com
(set via PAYVESSEL_BASE_URL in settings/.env — use sandbox until PayVessel's
business verification is complete, per the design doc's Phase 2 build note.)
"""

import requests
from django.conf import settings


class PayVesselError(Exception):
    pass


class PayVesselClient:
    RESERVED_ACCOUNT_PATH = "/pms/api/external/request/customerReservedAccount/"
    NIN_VERIFY_PATH = "/kyc/api/v1/merchant/nin/basic"
    BVN_VERIFY_PATH = "/kyc/api/v1/merchant/bvn/basic"  # inferred — confirm before production use

    def __init__(self):
        self.base_url = settings.PAYVESSEL_BASE_URL.rstrip("/")
        self.api_key = settings.PAYVESSEL_API_KEY
        self.api_secret = settings.PAYVESSEL_API_SECRET
        self.business_id = settings.PAYVESSEL_BUSINESS_ID

    def _headers(self):
        return {
            "Content-Type": "application/json",
            "api-key": self.api_key,
            "api-secret": self.api_secret,
        }

    def _post(self, path, payload):
        try:
            response = requests.post(
                f"{self.base_url}{path}", json=payload, headers=self._headers(), timeout=15
            )
        except requests.RequestException as exc:
            raise PayVesselError(f"Network error calling PayVessel: {exc}") from exc

        try:
            data = response.json()
        except ValueError:
            raise PayVesselError(
                f"PayVessel returned a non-JSON response (status {response.status_code})."
            )

        if response.status_code >= 400:
            message = data.get("message", "Unknown error")
            raise PayVesselError(f"PayVessel API error ({response.status_code}): {message}")

        return data

    # Bank codes supported by PayVessel's reserved account API.
    BANK_PALMPAY = "999991"
    BANK_9PSB = "120001"

    def create_reserved_account(self, *, member, bvn=None, nin=None, first_name, last_name, phone_number, email):
        """
        Creates a STATIC reserved virtual account for a member.

        PayVessel's API (docs.payvessel.com/api-reference/virtual-accounts/
        create-virtual-account) expects:
          - name: full name (not split first/last)
          - phoneNumber: camelCase
          - bankcode: array of bank codes (e.g. ["120001", "999991"])
          - businessid: merchant business ID (required)
          - bvn or nin: for KYC (PalmPay requires one; 9PSB is optional)
          - account_type: "STATIC" or "DYNAMIC"

        Previously this method sent the wrong field names
        (first_name, last_name, phone_number, merchant_reference) and omitted
        bankcode + businessid, causing a 400 that was silently swallowed.

        Strategy: always request 9PSB (KYC optional, works for everyone) and
        add PalmPay only if the member has a BVN or NIN. This way NIN-only
        members still get a static account (9PSB, 30k daily limit) rather
        than being silently skipped.
        """
        full_name = f"{first_name} {last_name}".strip()
        bankcode = [self.BANK_9PSB]
        if bvn:
            bankcode.append(self.BANK_PALMPAY)
        elif nin:
            bankcode.append(self.BANK_PALMPAY)

        payload = {
            "email": email or f"member-{member.pk}@coop.local",
            "name": full_name,
            "phoneNumber": phone_number,
            "bankcode": bankcode,
            "account_type": "STATIC",
            "businessid": self.business_id,
        }
        if bvn:
            payload["bvn"] = bvn
        elif nin:
            payload["nin"] = nin

        return self._post(self.RESERVED_ACCOUNT_PATH, payload)

    def verify_nin(self, *, nin, first_name, last_name, middle_name, gender, birthday, phone_number):
        payload = {
            "nin": nin,
            "first_name": first_name,
            "last_name": last_name,
            "middle_name": middle_name or "",
            "gender": gender,
            "birthday": birthday,  # "YYYY-MM-DD"
            "phone_number": phone_number,
        }
        return self._post(self.NIN_VERIFY_PATH, payload)

    def verify_bvn(self, *, bvn, first_name, last_name, middle_name, gender, birthday, phone_number):
        # See BVN_VERIFY_PATH docstring note above — path unconfirmed.
        payload = {
            "bvn": bvn,
            "first_name": first_name,
            "last_name": last_name,
            "middle_name": middle_name or "",
            "gender": gender,
            "birthday": birthday,
            "phone_number": phone_number,
        }
        return self._post(self.BVN_VERIFY_PATH, payload)
