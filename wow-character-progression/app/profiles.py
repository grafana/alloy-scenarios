"""Read the same character progression measures from the Battle.net Profile API."""

import os
import time
from urllib.parse import quote, urlsplit

import requests
from opentelemetry import trace

tracer = trace.get_tracer(__name__)
REGIONS = {"eu": "en_GB", "us": "en_US", "kr": "ko_KR", "tw": "zh_TW"}


class ProfileError(Exception):
    """An actionable, credential-free message for the roster and telemetry."""


def whole(value, field):
    if type(value) is not int or value < 0:
        raise ValueError(f"Invalid {field}")
    return value


def item_level(value):
    # Blizzard omits this field for some profiles, including fully equipped characters.
    return None if value is None else whole(value, "item level")


class Profiles:
    def __init__(self):
        self.client_id = os.getenv("BLIZZARD_CLIENT_ID")
        self.secret = os.getenv("BLIZZARD_CLIENT_SECRET")
        if bool(self.client_id) != bool(self.secret):
            raise ValueError("Set both Battle.net client credentials or leave both empty.")
        self.enabled = bool(self.client_id)
        self.http = requests.Session()
        self.token = None
        self.expires = 0

    def request(self, method, url, operation, **kwargs):
        with tracer.start_as_current_span(operation, kind=trace.SpanKind.CLIENT) as span:
            span.set_attribute("server.address", urlsplit(url).hostname)
            try:
                response = self.http.request(method, url, timeout=(5, 15), **kwargs)
            except requests.RequestException:
                raise ProfileError("Connection to Blizzard failed. Will retry.") from None
            span.set_attribute("http.response.status_code", response.status_code)
            if response.status_code == 404:
                raise ProfileError(
                    "Profile unavailable. Check the name and region, or log out after reaching level 10."
                )
            if response.status_code in (401, 403):
                self.expires = 0
                raise ProfileError(
                    f"Blizzard denied access ({response.status_code}). Check the Battle.net API credentials."
                )
            if not response.ok:
                raise ProfileError(f"Blizzard returned HTTP {response.status_code}. Will retry.")
            return response

    def fetch(self, region, slug):
        if not self.enabled:
            raise ProfileError("Configure Battle.net API credentials to enable profile tracking.")
        try:
            return self.api_profile(region, quote(slug, safe=""))
        except (KeyError, IndexError, ValueError, TypeError, AttributeError):
            raise ProfileError("Blizzard returned an incomplete profile. Will retry.") from None

    def api_profile(self, region, slug):
        if time.monotonic() >= self.expires:
            auth = self.request(
                "POST",
                "https://oauth.battle.net/token",
                "battle.net.authorize",
                auth=(self.client_id, self.secret),
                data={"grant_type": "client_credentials"},
            ).json()
            self.token = auth["access_token"]
            self.expires = time.monotonic() + max(0, int(auth["expires_in"]) - 60)
        base = f"https://{region}.api.blizzard.com/profile/wow/character/{slug}"
        params = {"namespace": f"profile-forever-{region}", "locale": REGIONS[region]}
        headers = {"Authorization": f"Bearer {self.token}"}
        profile = self.request("GET", base, "battle.net.profile", params=params, headers=headers).json()
        achievements = self.request(
            "GET", base + "/achievements", "battle.net.achievements", params=params, headers=headers
        ).json()
        return {
            "level": whole(profile["level"], "level"),
            "item_level": item_level(profile.get("average_item_level")),
            "achievements": whole(achievements["total_quantity"], "achievement count"),
            "class_name": profile["character_class"]["name"],
        }
