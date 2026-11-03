import asyncio
import json
import re
import threading
import time
import httpx
import logging
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

    def load_credentials(self) -> dict:
        """Load credentials from JSON file"""
        try:
            json_path = os.path.join(os.path.dirname(__file__), '..', 'assets', 'sms_logins.json')
            logger.info('Loading credentials from: %s', json_path)
            with open(json_path, 'r') as f:
                creds = json.load(f)
            logger.info('Loaded credentials for regions: %s', ', '.join(creds.keys()))
            return creds
        except Exception as e:
            logger.error('Failed to load credentials: %s', str(e))
            raise HTTPException(status_code=503, detail=f"HLR credentials could not be loaded: {e}")

    def switch_credentials(self, region: str = 'ru') -> bool:
        """Switch to next available credential for given region"""
        logger.info('Attempting to switch credentials for region: %s', region)
        creds_list = self.credentials.get(region, [])
        if not creds_list:
            logger.warning('No credentials available for region: %s', region)
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
        logger.info('Switched to new credentials: %s', self.login)
        return True

    def check_balance(self) -> str:
        """Check account balance"""
        logger.info('Checking balance for login: %s', self.login)
        data = {
            'login': self.login,
            'psw': self.password
        }
        response = httpx.get(f'{self.url}/sys/balance.php', params=data, timeout=30, follow_redirects=True)
        if response.status_code != 200:
            logger.error('Balance check failed with status code: %s', response.status_code)
            raise HTTPException(status_code=response.status_code, detail="Failed to check balance")
        logger.info('Balance check successful: %s', response.text)
        return response.text

    def fetch_status(self, phone: str, sms_id: str) -> dict:
        """Fetch HLR status for a specific phone number"""
        logger.info('Fetching status for phone: %s with SMS ID: %s', phone, sms_id)
        data = {
            'login': self.login,
            'psw': self.password,
            'phone': phone,
            'id': sms_id
        }
        response = httpx.get(f'{self.url}/sys/status.php', params=data, timeout=30, follow_redirects=True)
        if response.status_code != 200:
            logger.error('Status fetch failed with status code: %s', response.status_code)
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
            logger.debug('Raw status response: %s', response.text)

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
            logger.info('Status parsed for %s:', phone)
            logger.info('  Status: %s', result['status'])
            logger.info('  Operator: %s', result['operator'])
            logger.info('  Region: %s', result['region'])
            logger.info('  MCC: %s', result['mcc'])
            logger.info('  MNC: %s', result['mnc'])
            logger.info('  IMSI: %s', result['imsi'])
            if result['error']:
                logger.warning('  Error code: %s', result['error'])

        except Exception as e:
            logger.error('Error parsing status response: %s', str(e))
            logger.error('Raw response was: %s', response.text)

        return result

    async def lookup_numbers(self, phones: str) -> dict:
        """Perform HLR lookup, running the blocking HTTP/sleep work off the event loop."""
        return await asyncio.to_thread(self._lookup_locked, phones)

    def _lookup_locked(self, phones: str) -> dict:
        with self._lock:
            self._ensure_credentials()
            numbers = [normalize_phone(p) for p in re.split(r"[,;\n]+", phones or "")]
            numbers = [n for n in numbers if len(n) >= 7]
            if not numbers:
                raise HTTPException(status_code=400, detail="Enter at least one phone number")
            return self._lookup_numbers_sync(",".join(dict.fromkeys(numbers)))

    def _lookup_numbers_sync(self, phones: str) -> dict:
        """Perform HLR lookup for multiple phone numbers"""
        logger.info('Starting HLR lookup for phones: %s', phones)

        if not self.login or not self.password:
            logger.error("No valid credentials available")
            raise HTTPException(status_code=500, detail="No valid credentials available")

        # Determine region based on first phone number
        first_phone = phones.split(',')[0].strip()
        region = 'ua' if first_phone.startswith('380') else 'ru'
        logger.info('Detected region: %s based on number: %s', region, first_phone)

        retry_count = len(self.credentials.get(region, []))
        logger.info('Will attempt up to %s retries with different credentials', retry_count)

        balance = None
        results = []
        phone_list = [p.strip() for p in phones.split(',')]

        for phone in phone_list:
            retry_count_for_phone = retry_count
            while retry_count_for_phone > 0:
                try:
                    # Check balance first
                    balance = self.check_balance()
                    logger.info('Current balance: %s', balance)

                    # Prepare the HLR request for single number
                    data = {
                        'login': self.login,
                        'psw': self.password,
                        'phones': phone,
                        'hlr': '1'
                    }

                    logger.info('Sending HLR request for %s...', phone)
                    response = httpx.get(f'{self.url}/sys/send.php', params=data, timeout=30, follow_redirects=True)
                    if response.status_code != 200:
                        logger.error('HLR request failed with status code: %s', response.status_code)
                        raise HTTPException(status_code=response.status_code, detail="Failed to send HLR request")

                    if 'OK' in response.text:
                        try:
                            sms_id = response.text.split('ID - ')[1]
                            logger.info('HLR request successful for %s. SMS ID: %s', phone, sms_id)

                            logger.info("Waiting 10 seconds for results...")
                            time.sleep(10)

                            # Fetch result for this number
                            result = self.fetch_status(phone, sms_id)
                            results.append(result)
                            break  # Success, move to next number

                        except Exception as e:
                            logger.error('Error processing HLR response for %s: %s', phone, str(e))
                            results.append({
                                'phone': phone,
                                'status': 'Error',
                                'error': str(e),
                                'raw_response': response.text
                            })
                            break  # Move to next number even if processing failed
                    else:
                        error_msg = response.text
                        logger.warning('HLR request failed for %s with response: %s', phone, error_msg)

                        # Only retry on balance-related errors (error codes 2 and 3)
                        if ("ERROR = 2" in error_msg or "ERROR = 3" in error_msg) and self.switch_credentials(region):
                            retry_count_for_phone -= 1
                            logger.info('Balance too low, retrying with new credentials. %s attempts remaining', retry_count_for_phone)
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
                    logger.error('Error during HLR lookup for %s: %s', phone, str(e))
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