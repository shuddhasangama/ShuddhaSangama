"""Twilio Verify email channel, delivered by its configured SendGrid integration."""
import os
import re
import requests


class ProviderUnavailable(Exception):
    pass


class TwilioEmail:
    def call(self, resource, data):
        account = os.getenv('TWILIO_ACCOUNT_SID', '')
        service = os.getenv('TWILIO_VERIFY_SERVICE_SID', '')
        token = os.getenv('TWILIO_AUTH_TOKEN', '')
        if not (re.fullmatch(r'AC[0-9a-fA-F]{32}', account) and
                re.fullmatch(r'VA[0-9a-fA-F]{32}', service) and token):
            raise ProviderUnavailable('Email verification is not configured')
        try:
            response = requests.post(
                f'https://verify.twilio.com/v2/Services/{service}/{resource}',
                data=data, auth=(account, token), timeout=(5, 12), allow_redirects=False)
            if resource == 'VerificationCheck' and response.status_code in (400, 404):
                return {}
            if response.status_code not in (200, 201):
                raise ProviderUnavailable('Email verification unavailable')
            result = response.json()
            if not isinstance(result, dict):
                raise ProviderUnavailable('Invalid verification response')
            return result
        except (requests.RequestException, ValueError):
            raise ProviderUnavailable('Email verification unavailable') from None

    def send(self, address):
        result = self.call('Verifications', {'To': address, 'Channel': 'email'})
        sid = result.get('sid', '')
        if result.get('status') != 'pending' or not re.fullmatch(r'VE[0-9a-fA-F]{32}', sid):
            raise ProviderUnavailable('Email request not accepted')
        return sid

    def verify(self, sid, code):
        if not sid:
            return False
        result = self.call('VerificationCheck', {'VerificationSid': sid, 'Code': code})
        return result.get('status') == 'approved' and result.get('sid') == sid
