from datetime import datetime, timedelta
from typing import Optional
import jwt
from fastapi import HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from passlib.context import CryptContext
from dotenv import load_dotenv
import os
from telethon import TelegramClient
from telethon.errors import (
    SessionPasswordNeededError,
    PhoneNumberInvalidError,
    PhoneCodeInvalidError,
    PhoneCodeExpiredError,
    PhoneCodeEmptyError
)


class AuthHandler:
    security = HTTPBearer()
    pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

    def __init__(self):
        load_dotenv()
        self.secret = os.getenv('JWT_SECRET')

    def get_password_hash(self, password):
        return self.pwd_context.hash(password)

    def verify_password(self, plain_password, hashed_password):
        return self.pwd_context.verify(plain_password, hashed_password)

    def encode_token(self, user_id):
        payload = {
            'exp': datetime.utcnow() + timedelta(days=0, hours=24),
            'iat': datetime.utcnow(),
            'sub': user_id
        }
        return jwt.encode(
            payload,
            self.secret,
            algorithm='HS256'
        )

    def decode_token(self, token):
        try:
            payload = jwt.decode(token, self.secret, algorithms=['HS256'])
            return payload['sub']
        except jwt.ExpiredSignatureError:
            raise HTTPException(status_code=401, detail='Signature has expired')
        except jwt.InvalidTokenError:
            raise HTTPException(status_code=401, detail='Invalid token')

    def auth_wrapper(self, auth: HTTPAuthorizationCredentials = Security(security)):
        return self.decode_token(auth.credentials)


class TelegramAuthHandler:
    def __init__(self):
        load_dotenv()
        self.api_id = int(os.getenv("TELEGRAM_API_ID", 123))
        self.api_hash = os.getenv("TELEGRAM_API_HASH", "invalid")
        self.session_name = "telegram_session"
        self.client = TelegramClient(self.session_name, self.api_id, self.api_hash)
        self.phone_code_hash = None

    async def connect(self):
        await self.client.connect()
        return await self.client.is_user_authorized()

    async def send_verification_code(self, phone_number: str):
        try:
            sent_code = await self.client.send_code_request(phone_number)
            self.phone_code_hash = sent_code.phone_code_hash
            return {"status": "success", "message": "Verification code sent"}
        except PhoneNumberInvalidError:
            return {"status": "error", "message": "Invalid phone number"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def verify_code(self, phone_number: str, code: str):
        if not self.phone_code_hash:
            return {"status": "error", "message": "No active verification session"}

        try:
            await self.client.sign_in(
                phone=phone_number,
                code=code,
                phone_code_hash=self.phone_code_hash
            )
            return {"status": "success", "message": "Telegram authentication successful"}
        except SessionPasswordNeededError:
            return {"status": "error", "message": "2FA password required"}
        except (PhoneCodeInvalidError, PhoneCodeExpiredError, PhoneCodeEmptyError):
            return {"status": "error", "message": "Invalid verification code"}
        except Exception as e:
            return {"status": "error", "message": str(e)}