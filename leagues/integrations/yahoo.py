import base64
import json
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from django.conf import settings
from datetime import timedelta

from django.utils import timezone

from leagues.models import YahooAccount


class YahooLeagueService:
    AUTH_URL = "https://api.login.yahoo.com/oauth2/request_auth"
    TOKEN_URL = "https://api.login.yahoo.com/oauth2/get_token"

    def __init__(self, yahoo_account=None):
        self.yahoo_account = yahoo_account

    # ---------------------------------------------------------
    # OAuth
    # ---------------------------------------------------------

    @staticmethod
    def build_authorization_url(state):
        params = {
            "client_id": settings.YAHOO_CLIENT_ID,
            "redirect_uri": settings.YAHOO_REDIRECT_URI,
            "response_type": "code",
            "state": state,
        }

        return (
            f"{YahooLeagueService.AUTH_URL}?"
            f"{urlencode(params)}"
        )

    @staticmethod
    def _build_basic_auth_header():
        credentials = (
            f"{settings.YAHOO_CLIENT_ID}:"
            f"{settings.YAHOO_CLIENT_SECRET}"
        )

        encoded_credentials = base64.b64encode(
            credentials.encode("utf-8")
        ).decode("utf-8")

        return f"Basic {encoded_credentials}"

    @staticmethod
    def exchange_code(code):
        data = urlencode({
            "grant_type": "authorization_code",
            "redirect_uri": settings.YAHOO_REDIRECT_URI,
            "code": code,
        }).encode("utf-8")

        request = Request(
            YahooLeagueService.TOKEN_URL,
            data=data,
            method="POST",
            headers={
                "Authorization": (
                    YahooLeagueService._build_basic_auth_header()
                ),
                "Content-Type": (
                    "application/x-www-form-urlencoded"
                ),
            },
        )

        with urlopen(request) as response:
            return json.load(response)

    # ---------------------------------------------------------
    # Token Refresh
    # ---------------------------------------------------------

    @staticmethod
    def refresh_account(yahoo_account):
        data = urlencode({
            "grant_type": "refresh_token",
            "redirect_uri": settings.YAHOO_REDIRECT_URI,
            "refresh_token": yahoo_account.refresh_token,
        }).encode("utf-8")

        request = Request(
            YahooLeagueService.TOKEN_URL,
            data=data,
            method="POST",
            headers={
                "Authorization": (
                    YahooLeagueService._build_basic_auth_header()
                ),
                "Content-Type": (
                    "application/x-www-form-urlencoded"
                ),
            },
        )

        try:
            with urlopen(request) as response:
                token_data = json.load(response)

        except HTTPError as error:
            if error.code in (400, 401):
                raise ValueError(
                    "Yahoo authorization has expired or "
                    "has been revoked. Please reconnect your Yahoo account."
                ) from error

            raise

        access_token = token_data.get("access_token")
        expires_in = token_data.get("expires_in")

        if not access_token or not expires_in:
            raise ValueError(
                "Yahoo returned an invalid token refresh response."
            )

        yahoo_account.access_token = access_token
        yahoo_account.expires_at = (
                timezone.now()
                + timedelta(seconds=int(expires_in))
        )

        # Yahoo may issue a new refresh token.
        # If it does, the old one must be replaced.
        new_refresh_token = token_data.get("refresh_token")

        if new_refresh_token:
            yahoo_account.refresh_token = new_refresh_token

        yahoo_account.save(
            update_fields=[
                "access_token",
                "refresh_token",
                "expires_at",
                "updated_at",
            ]
        )

        return yahoo_account

    def get_valid_access_token(self):
        if self.yahoo_account is None:
            raise ValueError(
                "A Yahoo account is required."
            )

        # Refresh slightly early so we don't start an API request
        # with a token that is about to expire.
        refresh_buffer = timedelta(minutes=5)

        if (
            not self.yahoo_account.expires_at
            or timezone.now()
            >= self.yahoo_account.expires_at - refresh_buffer
        ):
            self.yahoo_account = self.refresh_account(
                self.yahoo_account
            )

        return self.yahoo_account.access_token

    # ---------------------------------------------------------
    # Yahoo API Requests
    # ---------------------------------------------------------

    def _get(self, endpoint):
        access_token = self.get_valid_access_token()

        request = Request(
            endpoint,
            method="GET",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json",
            },
        )

        try:
            with urlopen(request) as response:
                return json.load(response)

        except HTTPError as error:
            if error.code == 401:
                # The token may have expired between our
                # validity check and the actual API request.
                self.yahoo_account = self.refresh_account(
                    self.yahoo_account
                )

                access_token = self.yahoo_account.access_token

                retry_request = Request(
                    endpoint,
                    method="GET",
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Accept": "application/json",
                    },
                )

                with urlopen(retry_request) as response:
                    return json.load(response)

            raise

    # ---------------------------------------------------------
    # Helpers
    # ---------------------------------------------------------

    @staticmethod
    def get_api_error(error):
        try:
            body = error.read().decode("utf-8")
            return body
        except Exception:
            return str(error)