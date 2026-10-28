import asyncio
import json
import re
import threading
import time
import requests
import logging
from typing import Dict
from fastapi import HTTPException
import os

logger = logging.getLogger(__name__)


def normalize_phone(raw: str) -> str:
    """'+38 (050) 123-45-67' -> '380501234567' (smsc.ru wants bare digits)."""
    return re.sub(r"\D", "", raw or "")


class HLRService:
    def __init__(self):
        self.url = "https://smsc.ru"
        # Credentials load on first use: a missing assets/sms_logins.json must
        # not stop the whole app from starting
        self.credentials = None
        self.current_creds = {}
        self.login = None
        self.password = None
        # Active account is shared mutable state - one lookup at a time
        self._lock = threading.Lock()

    def _ensure_credentials(self):
        if self.credentials is not None:
            return
        self.credentials = self.load_credentials()
        if not self.credentials:
            raise HTTPException(status_code=503, detail="No HLR credentials configured (assets/sms_logins.json)")
        # Start with first RU credential by default
        self.current_creds = (self.credentials.get('ru') or [{}])[0]
        self.login = self.current_creds.get('login')
        self.password = self.current_creds.get('psw')

    def load_credentials(self) -> Dict:
        """Load credentials from JSON file"""
        try:
            json_path = os.path.join(os.path.dirname(__file__), '..', 'assets', 'sms_logins.json')
            logger.info(f"Loading credentials from: {json_path}")
            with open(json_path, 'r') as f:
                creds = json.load(f)
            logger.info(f"Loaded credentials for regions: {', '.join(creds.keys())}")
            return creds
        except Exception as e:
            logger.error(f"Failed to load credentials: {str(e)}")
            raise HTTPException(status_code=503, detail=f"HLR credentials could not be loaded: {e}")

    def switch_credentials(self, region: str = 'ru') -> bool:
        """Switch to next available credential for given region"""
        logger.info(f"Attempting to switch credentials for region: {region}")
        creds_list = self.credentials.get(region, [])
        if not creds_list:
            logger.warning(f"No credentials available for region: {region}")
            return False

        # Find current credential index
        current_index = -1
        for i, cred in enumerate(creds_list):
            if cred.get('login') == self.login:
                current_index = i
                break

        # Try next credential
        next_index = (current_index + 1) % len(creds_list)
        self.current_creds = creds_list[next_index]
        self.login = self.current_creds.get('login')
        self.password = self.current_creds.get('psw')
        logger.info(f"Switched to new credentials: {self.login}")
        return True

    def check_balance(self) -> str:
        """Check account balance"""
        logger.info(f"Checking balance for login: {self.login}")
        data = {
            'login': self.login,
            'psw': self.password
        }
        response = requests.get(f'{self.url}/sys/balance.php', params=data, timeout=30)
        if response.status_code != 200:
            logger.error(f"Balance check failed with status code: {response.status_code}")
            raise HTTPException(status_code=response.status_code, detail="Failed to check balance")
        logger.info(f"Balance check successful: {response.text}")
        return response.text

    def fetch_status(self, phone: str, sms_id: str) -> Dict:
        """Fetch HLR status for a specific phone number"""
        logger.info(f"Fetching status for phone: {phone} with SMS ID: {sms_id}")
        data = {
            'login': self.login,
            'psw': self.password,
            'phone': phone,
            'id': sms_id
        }
        response = requests.get(f'{self.url}/sys/status.php', params=data, timeout=30)
        if response.status_code != 200:
            logger.error(f"Status fetch failed with status code: {response.status_code}")
            raise HTTPException(status_code=response.status_code, detail="Failed to fetch status")

        # Initialize default result
        result = {
            'phone': phone,
            'status': 'Error',
            'operator': 'Unknown',
            'region': 'Unknown',
            'mcc': None,
            'mnc': None,
            'imsi': None,
            'error': None,
            'raw_response': response.text  # Store raw response immediately
        }

        try:
            # Parse the response
            logger.debug(f"Raw status response: {response.text}")

            # Split by comma and handle each parameter
            params = [param.strip() for param in response.text.split(',')]

            for param in params:
                # Split each parameter by '='
                parts = [p.strip() for p in param.split('=', 1)]
                if len(parts) != 2:
                    continue

                key, value = parts[0].lower(), parts[1]

                # Remove any trailing characters
                value = value.rstrip(', ')

                # Map the parameters to our result dictionary
                if 'status' in key:
                    result['status'] = 'OK' if value == '1' else 'Error'
                elif 'err' in key:
                    result['error'] = value
                elif 'imsi' in key:
                    result['imsi'] = value
                elif 'mcc' in key:
                    result['mcc'] = value
                elif 'mnc' in key:
                    result['mnc'] = value
                elif 'cn' in key:
                    result['region'] = value
                elif 'net' in key:
                    result['operator'] = value

            # Log the parsed result
            logger.info(f"Status parsed for {phone}:")
            logger.info(f"  Status: {result['status']}")
            logger.info(f"  Operator: {result['operator']}")
            logger.info(f"  Region: {result['region']}")
            logger.info(f"  MCC: {result['mcc']}")
            logger.info(f"  MNC: {result['mnc']}")
            logger.info(f"  IMSI: {result['imsi']}")
            if result['error']:
                logger.warning(f"  Error code: {result['error']}")

        except Exception as e:
            logger.error(f"Error parsing status response: {str(e)}")
            logger.error(f"Raw response was: {response.text}")

        return result

    async def lookup_numbers(self, phones: str) -> Dict:
        """Perform HLR lookup, running the blocking HTTP/sleep work off the event loop."""
        return await asyncio.to_thread(self._lookup_locked, phones)

    def _lookup_locked(self, phones: str) -> Dict:
        with self._lock:
            self._ensure_credentials()
            numbers = [normalize_phone(p) for p in re.split(r"[,;\n]+", phones or "")]
            numbers = [n for n in numbers if len(n) >= 7]
            if not numbers:
                raise HTTPException(status_code=400, detail="Enter at least one phone number")
            return self._lookup_numbers_sync(",".join(dict.fromkeys(numbers)))

    def _lookup_numbers_sync(self, phones: str) -> Dict:
        """Perform HLR lookup for multiple phone numbers"""
        logger.info(f"Starting HLR lookup for phones: {phones}")

        if not self.login or not self.password:
            logger.error("No valid credentials available")
            raise HTTPException(status_code=500, detail="No valid credentials available")

        # Determine region based on first phone number
        first_phone = phones.split(',')[0].strip()
        region = 'ua' if first_phone.startswith('380') else 'ru'
        logger.info(f"Detected region: {region} based on number: {first_phone}")

        retry_count = len(self.credentials.get(region, []))
        logger.info(f"Will attempt up to {retry_count} retries with different credentials")

        balance = None
        results = []
        phone_list = [p.strip() for p in phones.split(',')]

        for phone in phone_list:
            retry_count_for_phone = retry_count
            while retry_count_for_phone > 0:
                try:
                    # Check balance first
                    balance = self.check_balance()
                    logger.info(f"Current balance: {balance}")

                    # Prepare the HLR request for single number
                    data = {
                        'login': self.login,
                        'psw': self.password,
                        'phones': phone,
                        'hlr': '1'
                    }

                    logger.info(f"Sending HLR request for {phone}...")
                    response = requests.get(f'{self.url}/sys/send.php', params=data, timeout=30)
                    if response.status_code != 200:
                        logger.error(f"HLR request failed with status code: {response.status_code}")
                        raise HTTPException(status_code=response.status_code, detail="Failed to send HLR request")

                    if 'OK' in response.text:
                        try:
                            sms_id = response.text.split('ID - ')[1]
                            logger.info(f"HLR request successful for {phone}. SMS ID: {sms_id}")

                            logger.info("Waiting 10 seconds for results...")
                            time.sleep(10)

                            # Fetch result for this number
                            result = self.fetch_status(phone, sms_id)
                            results.append(result)
                            break  # Success, move to next number

                        except Exception as e:
                            logger.error(f"Error processing HLR response for {phone}: {str(e)}")
                            results.append({
                                'phone': phone,
                                'status': 'Error',
                                'error': str(e),
                                'raw_response': response.text
                            })
                            break  # Move to next number even if processing failed
                    else:
                        error_msg = response.text
                        logger.warning(f"HLR request failed for {phone} with response: {error_msg}")

                        # Only retry on balance-related errors (error codes 2 and 3)
                        if ("ERROR = 2" in error_msg or "ERROR = 3" in error_msg) and self.switch_credentials(region):
                            retry_count_for_phone -= 1
                            logger.info(f"Balance too low, retrying with new credentials. {retry_count_for_phone} attempts remaining")
                            continue

                        # For other errors, add to results and move to next number
                        results.append({
                            'phone': phone,
                            'status': 'Error',
                            'error': error_msg,
                            'raw_response': error_msg
                        })
                        break

                except Exception as e:
                    logger.error(f"Error during HLR lookup for {phone}: {str(e)}")
                    if self.switch_credentials(region):
                        retry_count_for_phone -= 1
                        continue
                    results.append({
                        'phone': phone,
                        'status': 'Error',
                        'error': str(e),
                        'raw_response': str(e)
                    })
                    break

        if not results:
            logger.error("All available credentials failed")
            raise HTTPException(status_code=500, detail="All available credentials failed")

        return {
            "balance": balance,
            "results": results,
            "used_login": self.login
        }