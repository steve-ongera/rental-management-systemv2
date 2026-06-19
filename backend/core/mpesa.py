"""
M-Pesa Daraja API integration (Safaricom).
Implements OAuth token fetch + STK Push (Lipa Na M-Pesa Online) for the
tenant portal's online rent/water payments.

Sandbox docs: https://developer.safaricom.co.ke/
Set the following in your environment / .env:
    MPESA_ENV=sandbox            # or "production"
    MPESA_CONSUMER_KEY=...
    MPESA_CONSUMER_SECRET=...
    MPESA_SHORTCODE=174379       # sandbox till/paybill
    MPESA_PASSKEY=...
    MPESA_CALLBACK_URL=https://yourdomain.com/api/payments/mpesa/callback/
"""

import base64
import datetime

import requests
from django.conf import settings

BASE_URLS = {
    "sandbox": "https://sandbox.safaricom.co.ke",
    "production": "https://api.safaricom.co.ke",
}


class MpesaClient:
    def __init__(self):
        self.env = getattr(settings, "MPESA_ENV", "sandbox")
        self.base_url = BASE_URLS.get(self.env, BASE_URLS["sandbox"])
        self.consumer_key = settings.MPESA_CONSUMER_KEY
        self.consumer_secret = settings.MPESA_CONSUMER_SECRET
        self.shortcode = settings.MPESA_SHORTCODE
        self.passkey = settings.MPESA_PASSKEY
        self.callback_url = settings.MPESA_CALLBACK_URL

    def get_access_token(self):
        url = f"{self.base_url}/oauth/v1/generate?grant_type=client_credentials"
        response = requests.get(url, auth=(self.consumer_key, self.consumer_secret), timeout=30)
        response.raise_for_status()
        return response.json()["access_token"]

    def _password_and_timestamp(self):
        timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
        raw = f"{self.shortcode}{self.passkey}{timestamp}"
        password = base64.b64encode(raw.encode()).decode()
        return password, timestamp

    def stk_push(self, phone_number, amount, account_reference, transaction_desc):
        """
        Initiates an STK push (Lipa Na M-Pesa Online) prompt on the
        tenant's phone. phone_number must be in 2547XXXXXXXX format.
        """
        token = self.get_access_token()
        password, timestamp = self._password_and_timestamp()

        payload = {
            "BusinessShortCode": self.shortcode,
            "Password": password,
            "Timestamp": timestamp,
            "TransactionType": "CustomerPayBillOnline",
            "Amount": int(amount),
            "PartyA": phone_number,
            "PartyB": self.shortcode,
            "PhoneNumber": phone_number,
            "CallBackURL": self.callback_url,
            "AccountReference": account_reference[:12],
            "TransactionDesc": transaction_desc[:13],
        }
        headers = {"Authorization": f"Bearer {token}"}
        url = f"{self.base_url}/mpesa/stkpush/v1/processrequest"
        response = requests.post(url, json=payload, headers=headers, timeout=30)
        response.raise_for_status()
        return response.json()

    def query_stk_status(self, checkout_request_id):
        token = self.get_access_token()
        password, timestamp = self._password_and_timestamp()
        payload = {
            "BusinessShortCode": self.shortcode,
            "Password": password,
            "Timestamp": timestamp,
            "CheckoutRequestID": checkout_request_id,
        }
        headers = {"Authorization": f"Bearer {token}"}
        url = f"{self.base_url}/mpesa/stkpushquery/v1/query"
        response = requests.post(url, json=payload, headers=headers, timeout=30)
        response.raise_for_status()
        return response.json()


def normalize_phone_number(raw_number):
    """
    Normalizes Kenyan phone numbers to the 2547XXXXXXXX / 2541XXXXXXXX
    format required by Daraja, accepting 07XX, +2547XX, 2547XX inputs.
    """
    number = raw_number.strip().replace(" ", "").replace("-", "")
    if number.startswith("+"):
        number = number[1:]
    if number.startswith("0"):
        number = "254" + number[1:]
    if number.startswith("7") or number.startswith("1"):
        number = "254" + number
    return number