"""Optional Battle.net full-body render for a real, locally recorded character."""
import base64
import json
import os
import re
import time
from urllib.error import HTTPError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import Request, urlopen

from settings import save_private


class Portraits:
    def __init__(self, folder):
        self.path = folder / ".battle-net.json"
        self.config = json.loads(self.path.read_text()) if self.path.exists() else {}
        self.token = None
        self.expiry = 0
        self.cache = {}

    def credentials(self):
        return (self.config.get("client_id") or os.getenv("BLIZZARD_CLIENT_ID"),
                self.config.get("secret") or os.getenv("BLIZZARD_CLIENT_SECRET"))

    def configure(self, client_id, secret):
        if not all(isinstance(v,str) and 0 < len(v.strip()) < 512 for v in (client_id, secret)):
            raise ValueError("Enter both Battle.net application credentials.")
        self.config.update(client_id=client_id.strip(), secret=secret.strip())
        save_private(self.path, json.dumps(self.config))
        self.token = None
        self.cache.clear()

    def fetch(self, header, full_name):
        region = header["region"]
        parts = full_name.strip().casefold().split()
        if region not in ("eu","us","kr","tw") or len(parts) != 2 or not all(
                all(c.isalpha() or c in "-’'" for c in p) and p[0].isalpha() and len(p) < 60 for p in parts):
            raise ValueError("Enter the character’s first name and surname in a supported region.")
        if parts[0] != header["character"].casefold().split()[0]:
            raise ValueError("The first name must match the selected character.")
        slug = "-".join(parts)
        client, secret = self.credentials()
        if not client or not secret:
            raise ValueError("Add Battle.net application credentials in Settings to look up a portrait.")
        if not self.token or self.expiry < time.monotonic():
            auth = base64.b64encode(f"{client}:{secret}".encode()).decode()
            req = Request("https://oauth.battle.net/token", data=b"grant_type=client_credentials",
                          headers={"Authorization":"Basic "+auth})
            with urlopen(req, timeout=8) as response:
                token = json.load(response)
            self.token = token["access_token"]
            self.expiry = time.monotonic() + max(0, int(token["expires_in"])-60)
        params = urlencode({"namespace":"profile-forever-"+region})
        req = Request(f"https://{region}.api.blizzard.com/profile/wow/character/{quote(slug, safe='')}/character-media?{params}",
                      headers={"Authorization":"Bearer "+self.token})
        with urlopen(req, timeout=8) as response:
            data = json.load(response)
        character = data.get("character", {})
        guid = re.fullmatch(r"Player-\d+-([0-9a-fA-F]+)", header["player_guid"])
        if not guid or character.get("id") != int(guid[1],16) or character.get("slug") != slug:
            raise ValueError("Blizzard returned a different character identity.")
        for kind in ("main-raw","main-sd-raw","avatar","avatar-sd"):
            for asset in data.get("assets", []):
                url = asset.get("value", "")
                parts = urlsplit(url)
                if asset.get("key")==kind and parts.scheme=="https" and parts.netloc=="render.worldofwarcraft.com" and parts.path.startswith("/forever-"+region+"/"):
                    return {"url":url,"kind":kind}
        raise ValueError("Blizzard has not published a portrait yet.")

    def lookup(self, header, key, name):
        if not name:
            return {"message":"Waiting for a real character save with a full name."}
        cached = self.cache.get((key, name))
        if cached and cached[0] > time.monotonic():
            return cached[1]
        try:
            result = self.fetch(header, name)
        except HTTPError as exc:
            if exc.code in (401,403):
                self.token = None
            result = {"message": "Blizzard has not published this portrait yet." if exc.code==404 else f"Battle.net returned HTTP {exc.code}."}
        except (OSError, KeyError, TypeError):
            result = {"message":"Battle.net is unavailable. Try again later."}
        except ValueError as exc:
            result = {"message":str(exc)}
        self.cache[key,name] = time.monotonic()+(3600 if result.get("url") else 60),result
        return result
