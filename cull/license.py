"""The photographer's Cull license key, and the proxy that accepts it.

Typed instructions are the only part of Cull that costs money to run, so they are the only part
a license unlocks. The app never holds an Anthropic key: it sends the license key to the Cull
proxy (proxy/), which checks it, counts the call against the monthly cap and forwards it.
Opening, scoring and exporting a shoot need no license and no network.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

from cull import config, settings


class LicenseError(RuntimeError):
    """The key cannot be used. The message is written for the photographer."""


def normalize(key) -> str:
    """Keys are typed or pasted: drop spaces and line breaks, upper-case."""
    return "".join(str(key or "").split()).upper()


def check(key: str) -> dict:
    """Ask the proxy about a key. Returns {used, limit, month}."""
    if not config.PROXY_URL:
        raise LicenseError("This build of Cull has no license server set.")
    req = urllib.request.Request(config.PROXY_URL.rstrip("/") + "/v1/license",
                                 headers={"x-api-key": key, "user-agent": "Cull"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.load(resp)
    except urllib.error.HTTPError as exc:
        try:
            message = json.load(exc)["error"]["message"]
        except Exception:
            message = f"The license server answered with an error ({exc.code})."
        raise LicenseError(message) from exc
    except (OSError, ValueError) as exc:
        raise LicenseError("Cull could not reach the license server. "
                           "Check your internet connection.") from exc
    return {k: data.get(k) for k in ("used", "limit", "month")}


def public() -> dict:
    """What the page may know: whether a key is saved and its last characters, never the key."""
    key = settings.load()["license_key"]
    return {"set": bool(key), "hint": key[-5:] if key else None,
            "needed": config.LLM_PROVIDER == "license"}


def save(key) -> dict:
    """Check a key with the proxy and save it. An empty key removes the saved one."""
    key = normalize(key)
    if not key:
        settings.update({"license_key": None})
        return public()
    usage = check(key)
    settings.update({"license_key": key})
    return {**public(), **usage}
