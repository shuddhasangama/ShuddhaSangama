"""SMS one-time codes for the Investor Room.

Numbers whose country code is listed in MSG91_COUNTRY_CODES (default: 91, India) are sent through MSG91.
Every other number is sent through Twilio Verify's SMS channel. Add more codes, for example "91,1",
to move US/Canada to MSG91 later without any code change.
"""
import os
import re
import requests


class ProviderUnavailable(Exception):
    pass


MSG91_BASE = 'https://control.msg91.com/api/v5/otp'


class TwilioSms:
    """Twilio Verify, SMS channel. Approval is bound to the exact verification SID."""

    def call(self, resource, data):
        account = os.getenv('TWILIO_ACCOUNT_SID', '')
        service = os.getenv('TWILIO_VERIFY_SERVICE_SID', '')
        token = os.getenv('TWILIO_AUTH_TOKEN', '')
        if not (re.fullmatch(r'AC[0-9a-fA-F]{32}', account) and
                re.fullmatch(r'VA[0-9a-fA-F]{32}', service) and token):
            raise ProviderUnavailable('SMS verification is not configured')
        try:
            response = requests.post(
                f'https://verify.twilio.com/v2/Services/{service}/{resource}',
                data=data, auth=(account, token), timeout=(5, 12), allow_redirects=False)
            if resource == 'VerificationCheck' and response.status_code in (400, 404):
                return {}
            if response.status_code not in (200, 201):
                raise ProviderUnavailable('SMS verification unavailable')
            result = response.json()
            if not isinstance(result, dict):
                raise ProviderUnavailable('Invalid verification response')
            return result
        except (requests.RequestException, ValueError):
            raise ProviderUnavailable('SMS verification unavailable') from None

    def send(self, number):
        result = self.call('Verifications', {'To': number, 'Channel': 'sms'})
        sid = result.get('sid', '')
        if result.get('status') != 'pending' or not re.fullmatch(r'VE[0-9a-fA-F]{32}', sid):
            raise ProviderUnavailable('SMS request not accepted')
        return sid

    def verify(self, sid, code, number=None):
        if not sid or not re.fullmatch(r'VE[0-9a-fA-F]{32}', sid):
            return False
        result = self.call('VerificationCheck', {'VerificationSid': sid, 'Code': code})
        return result.get('status') == 'approved' and result.get('sid') == sid


class Msg91Sms:
    """MSG91 SendOTP. The code is generated and checked by MSG91 for the exact mobile number."""

    def _config(self):
        key = os.getenv('MSG91_AUTH_KEY', '')
        template = os.getenv('MSG91_TEMPLATE_ID', '')
        if not (key and re.fullmatch(r'[0-9A-Za-z]{10,64}', template)):
            raise ProviderUnavailable('SMS verification is not configured')
        return key, template

    def _get_json(self, method, url, **kw):
        key, _ = self._config()
        try:
            response = requests.request(method, url, headers={'authkey': key, 'accept': 'application/json'},
                                        timeout=(5, 12), allow_redirects=False, **kw)
            if response.status_code != 200:
                raise ProviderUnavailable('SMS verification unavailable')
            result = response.json()
            if not isinstance(result, dict):
                raise ProviderUnavailable('Invalid verification response')
            return result
        except (requests.RequestException, ValueError):
            raise ProviderUnavailable('SMS verification unavailable') from None

    @staticmethod
    def _mobile(number):
        return number.lstrip('+')

    def send(self, number):
        _, template = self._config()
        result = self._get_json('POST', MSG91_BASE, params={
            'template_id': template, 'mobile': self._mobile(number), 'otp_length': 6, 'otp_expiry': 5})
        if result.get('type') != 'success':
            raise ProviderUnavailable('SMS request not accepted')
        request_id = re.sub(r'[^0-9A-Za-z]', '', str(result.get('request_id') or result.get('message') or ''))[:30]
        return 'M91-' + (request_id or 'ok')

    def verify(self, sid, code, number=None):
        if not sid or not str(sid).startswith('M91-') or not number:
            return False
        result = self._get_json('GET', MSG91_BASE + '/verify', params={
            'mobile': self._mobile(number), 'otp': code})
        return result.get('type') == 'success'


class SmsRouter:
    """Chooses MSG91 or Twilio Verify from the number's country code."""

    def __init__(self, msg91=None, twilio=None):
        self.msg91 = msg91 or Msg91Sms()
        self.twilio = twilio or TwilioSms()

    @staticmethod
    def msg91_codes():
        raw = os.getenv('MSG91_COUNTRY_CODES', '91')
        return [c for c in (part.strip() for part in raw.split(',')) if re.fullmatch(r'[1-9]\d{0,2}', c)]

    def route(self, number):
        digits = number.lstrip('+')
        return self.msg91 if any(digits.startswith(c) for c in self.msg91_codes()) else self.twilio

    def send(self, number):
        return self.route(number).send(number)

    def verify(self, sid, code, number):
        return self.route(number).verify(sid, code, number)
