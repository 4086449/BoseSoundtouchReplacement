# Shared configuration for the Python services.
# All network settings are loaded from .env (or environment variables).

import os
from pathlib import Path

_env_path = Path(__file__).resolve().parent / ".env"
if _env_path.exists():
    with open(_env_path) as _f:
        for _line in _f:
            _line = _line.strip()
            if not _line or _line.startswith("#"):
                continue
            _key, _, _val = _line.partition("=")
            if _key and _ == "=":
                os.environ.setdefault(_key.strip(), _val.strip())

BOSE_IP = os.environ.get("BOSE_IP", "10.0.0.199")
PI_IP = os.environ.get("PI_IP", "10.0.0.241")
SPEAKER_NAME = os.environ.get("SPEAKER_NAME", "Living Room")

# Optional static zone display name for the single-speaker bridge.
# Node-RED supports dynamic zones; this is only used by bose-preset-bridge.py.
ACTIVE_ZONE_NAME = os.environ.get("ACTIVE_ZONE_NAME", "")

# Bind proxy to all interfaces by default, which is Docker-friendly.
# The Bose must still receive PI_IP in stream/logo URLs.
PROXY_BIND_IP = os.environ.get("PROXY_BIND_IP", "0.0.0.0")
PROXY_PORT = int(os.environ.get("PROXY_PORT", "8091"))

# Subtitle priority used by the bridge when building Bose UPnP metadata.
# Live metadata is a future extension: the proxy currently exposes placeholder
# metadata endpoints, so this will gracefully fall back to zone/device/owner.
DISPLAY_SUBTITLE_PRIORITY = [
    "live_metadata",
    "zone_name",
    "speaker_name",
    "station_owner",
]
LIVE_METADATA_MAX_AGE_SECONDS = 45

STATIONS = {
    "radio1": {
        "name": "VRT Radio 1",
        "owner": "VRT",
        "path": "/radio1.mp3",
        "upstream": "http://icecast.vrtcdn.be/radio1-high.mp3",
        "logo": "/logos/radio1.png",
        "live_metadata": {"enabled": True, "source": "icy", "endpoint": "/metadata/radio1.json"},
    },
    "radio2-limburg": {
        "name": "VRT Radio 2 Limburg",
        "owner": "VRT",
        "path": "/radio2-limburg.mp3",
        "upstream": "http://icecast.vrtcdn.be/ra2lim-high.mp3",
        "logo": "/logos/radio2-limburg.png",
        "live_metadata": {"enabled": True, "source": "icy", "endpoint": "/metadata/radio2-limburg.json"},
    },
    "stubru": {
        "name": "VRT Studio Brussel",
        "owner": "VRT",
        "path": "/stubru.mp3",
        "upstream": "http://icecast.vrtcdn.be/stubru-high.mp3",
        "logo": "/logos/stubru.png",
        "live_metadata": {"enabled": True, "source": "icy", "endpoint": "/metadata/stubru.json"},
    },
    "joe": {
        "name": "Joe",
        "owner": "DPG Media",
        "path": "/joe.mp3",
        "upstream": "https://streams.radio.dpgmedia.cloud/redirect/joe_fm/mp3",
        "logo": "/logos/joe.png",
        "live_metadata": {"enabled": True, "source": "icy", "endpoint": "/metadata/joe.json"},
    },
    "nostalgie": {
        "name": "Nostalgie Vlaanderen",
        "owner": "Nostalgie",
        "path": "/nostalgie.mp3",
        "upstream": "https://playerservices.streamtheworld.com/api/livestream-redirect/NOSTALGIEWHATAFEELING.mp3",
        "logo": "/logos/nostalgie.png",
        "live_metadata": {"enabled": True, "source": "icy", "endpoint": "/metadata/nostalgie.json"},
    },
    "joe-gold": {
        "name": "JOE Gold",
        "owner": "DPG Media",
        "path": "/joe-gold.mp3",
        "upstream": "https://streams.radio.dpgmedia.cloud/redirect/joe_gold/mp3",
        "logo": "/logos/joe-gold.png",
        "live_metadata": {"enabled": True, "source": "icy", "endpoint": "/metadata/joe-gold.json"},
    },
}

PRESETS = {
    "PRESET_1": "radio1",
    "PRESET_2": "radio2-limburg",
    "PRESET_3": "stubru",
    "PRESET_4": "joe",
    "PRESET_5": "nostalgie",
    "PRESET_6": "joe-gold",
}
