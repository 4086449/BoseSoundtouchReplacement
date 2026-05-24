# Shared configuration for the Python services.
#
# Source of truth: soundtouch-radio/speakers.json (single JSON file with
# speakers, zones, stations and preset mappings). When that file is absent,
# we fall back to the legacy single-speaker mode driven by .env so existing
# deployments keep working.

import json
import logging
import os
import re
import tempfile
import urllib.request
from pathlib import Path

log = logging.getLogger(__name__)

# .env loading (unchanged from previous behavior).
_ROOT = Path(__file__).resolve().parents[1]
_env_path = _ROOT / ".env"
if _env_path.exists():
    with open(_env_path) as _f:
        for _line in _f:
            _line = _line.strip()
            if not _line or _line.startswith("#"):
                continue
            _key, _sep, _val = _line.partition("=")
            if _key and _sep == "=":
                os.environ.setdefault(_key.strip(), _val.strip())

# Legacy single-speaker env vars. With speakers.json these become fallbacks
# only; the shell scripts in soundtouch-api/ still rely on BOSE_IP/PI_IP.
BOSE_IP = os.environ.get("BOSE_IP", "10.0.0.199")
PI_IP = os.environ.get("PI_IP", "10.0.0.241")
SPEAKER_NAME = os.environ.get("SPEAKER_NAME", "Living Room")
ACTIVE_ZONE_NAME = os.environ.get("ACTIVE_ZONE_NAME", "")
PROXY_BIND_IP = os.environ.get("PROXY_BIND_IP", "0.0.0.0")
PROXY_PORT = int(os.environ.get("PROXY_PORT", "8091"))

DISPLAY_SUBTITLE_PRIORITY = [
    "live_metadata",
    "zone_name",
    "speaker_name",
    "station_owner",
]
LIVE_METADATA_MAX_AGE_SECONDS = 45

SCHEMA_VERSION = 1
SPEAKERS_FILE = Path(__file__).resolve().parent / "speakers.json"
SPEAKERS_BAK = SPEAKERS_FILE.with_suffix(".json.bak")
STATUS_FILE = Path(__file__).resolve().parent / "status.json"


# ---------------------------------------------------------------------------
# Legacy fallbacks (used only when speakers.json is missing).
# ---------------------------------------------------------------------------

_LEGACY_STATIONS = {
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

_LEGACY_PRESETS = {
    "PRESET_1": "radio1",
    "PRESET_2": "radio2-limburg",
    "PRESET_3": "stubru",
    "PRESET_4": "joe",
    "PRESET_5": "nostalgie",
    "PRESET_6": "joe-gold",
}


def _legacy_config():
    return {
        "version": SCHEMA_VERSION,
        "speakers": {
            "living": {
                "name": SPEAKER_NAME or "Living Room",
                "ip": BOSE_IP,
                "device_id": "",
                "default_zone": "",
                "enabled": True,
            }
        },
        "zones": {},
        "stations": dict(_LEGACY_STATIONS),
        "presets": dict(_LEGACY_PRESETS),
    }


# ---------------------------------------------------------------------------
# Loader / saver / validator.
# ---------------------------------------------------------------------------

def load_speakers():
    """Return the parsed speakers.json, or the .env-derived fallback."""
    if not SPEAKERS_FILE.exists():
        return _legacy_config()
    try:
        with SPEAKERS_FILE.open() as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        log.error("Failed to read %s: %s; using legacy fallback", SPEAKERS_FILE, e)
        return _legacy_config()
    if not isinstance(data, dict):
        log.error("%s is not a JSON object; using legacy fallback", SPEAKERS_FILE)
        return _legacy_config()
    data.setdefault("version", SCHEMA_VERSION)
    data.setdefault("speakers", {})
    data.setdefault("zones", {})
    data.setdefault("stations", {})
    data.setdefault("presets", {})
    return data


_BAK_WRITTEN = False


def _atomic_write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def save_speakers(data):
    """Atomic write of speakers.json. On the first call per process, also
    snapshot the previous file as speakers.json.bak."""
    global _BAK_WRITTEN
    if not _BAK_WRITTEN and SPEAKERS_FILE.exists():
        try:
            SPEAKERS_BAK.write_bytes(SPEAKERS_FILE.read_bytes())
            log.info("Wrote backup %s", SPEAKERS_BAK)
        except OSError as e:
            log.warning("Could not write backup %s: %s", SPEAKERS_BAK, e)
        _BAK_WRITTEN = True
    _atomic_write_json(SPEAKERS_FILE, data)


def save_status(data):
    """Atomic write of status.json (used by the bridge)."""
    _atomic_write_json(STATUS_FILE, data)


_ID_RE = re.compile(r"^[A-Za-z0-9_.\-]+$")


def validate_speakers(data):
    """Return a list of human-readable error strings. Empty list = valid."""
    errors = []
    if not isinstance(data, dict):
        return ["payload must be a JSON object"]
    version = data.get("version", SCHEMA_VERSION)
    if version != SCHEMA_VERSION:
        errors.append(f"version must be {SCHEMA_VERSION}, got {version!r}")

    speakers = data.get("speakers") or {}
    zones = data.get("zones") or {}
    stations = data.get("stations") or {}
    presets = data.get("presets") or {}

    for section_name, section in (
        ("speakers", speakers),
        ("zones", zones),
        ("stations", stations),
        ("presets", presets),
    ):
        if not isinstance(section, dict):
            errors.append(f"{section_name} must be a JSON object")
            return errors

    for sid, sp in speakers.items():
        if not _ID_RE.match(sid):
            errors.append(f"speaker id {sid!r} must match [A-Za-z0-9_.-]+")
        if not isinstance(sp, dict):
            errors.append(f"speaker {sid!r} must be an object")
            continue
        if not str(sp.get("name") or "").strip():
            errors.append(f"speaker {sid!r} missing name")
        if not str(sp.get("ip") or "").strip():
            errors.append(f"speaker {sid!r} missing ip")
        dz = sp.get("default_zone") or ""
        if dz and dz not in zones:
            errors.append(f"speaker {sid!r} default_zone {dz!r} not in zones")
        elif dz and zones.get(dz, {}).get("master") != sid:
            errors.append(
                f"speaker {sid!r} default_zone {dz!r} but speaker is not the zone master"
            )

    for zid, z in zones.items():
        if not _ID_RE.match(zid):
            errors.append(f"zone id {zid!r} must match [A-Za-z0-9_.-]+")
        if not isinstance(z, dict):
            errors.append(f"zone {zid!r} must be an object")
            continue
        master = z.get("master") or ""
        if not master:
            errors.append(f"zone {zid!r} missing master")
        elif master not in speakers:
            errors.append(f"zone {zid!r} master {master!r} not in speakers")
        members = z.get("members") or []
        if not isinstance(members, list):
            errors.append(f"zone {zid!r} members must be a list")
            continue
        for m in members:
            if m not in speakers:
                errors.append(f"zone {zid!r} member {m!r} not in speakers")
            if m == master:
                errors.append(f"zone {zid!r} master {master!r} also listed as member")

    for stid, st in stations.items():
        if not _ID_RE.match(stid):
            errors.append(f"station id {stid!r} must match [A-Za-z0-9_.-]+")
        if not isinstance(st, dict):
            errors.append(f"station {stid!r} must be an object")
            continue
        if not str(st.get("name") or "").strip():
            errors.append(f"station {stid!r} missing name")
        if not str(st.get("path") or "").strip().startswith("/"):
            errors.append(f"station {stid!r} path must start with /")
        if not str(st.get("upstream") or "").startswith(("http://", "https://")):
            errors.append(f"station {stid!r} upstream must be http(s) URL")

    for pkey, stid in presets.items():
        if not re.match(r"^PRESET_[1-6]$", str(pkey)):
            errors.append(f"preset key {pkey!r} must match PRESET_[1-6]")
        if stid not in stations:
            errors.append(f"preset {pkey!r} references unknown station {stid!r}")

    return errors


# ---------------------------------------------------------------------------
# Device-id discovery.
# ---------------------------------------------------------------------------

def discover_device_id(ip, timeout=3.0):
    """Fetch http://IP:8090/info and parse the deviceID attribute.
    Returns the device id string, or None on any error."""
    url = f"http://{ip}:8090/info"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            body = r.read().decode("utf-8", errors="replace")
    except Exception as e:
        log.warning("discover_device_id(%s) failed: %s", ip, e)
        return None
    m = re.search(r'deviceID\s*=\s*"([^"]+)"', body) or re.search(
        r"deviceID\s*=\s*'([^']+)'", body
    )
    if not m:
        log.warning("discover_device_id(%s): no deviceID in /info response", ip)
        return None
    return m.group(1)


def reconcile_device_ids(data):
    """For every enabled speaker without a device_id, run discovery and fill
    it in. Mutates `data` in place. Returns True iff anything changed."""
    changed = False
    for sid, sp in (data.get("speakers") or {}).items():
        if not isinstance(sp, dict) or not sp.get("enabled", True):
            continue
        if sp.get("device_id"):
            continue
        ip = sp.get("ip") or ""
        if not ip:
            continue
        did = discover_device_id(ip)
        if did:
            sp["device_id"] = did
            changed = True
            log.info("Discovered device_id for %s=%s", sid, did)
    return changed


# ---------------------------------------------------------------------------
# Module-level convenience exports (computed once at import time).
# Long-running services should re-load via load_speakers() on file changes.
# ---------------------------------------------------------------------------

_initial = load_speakers()
SPEAKERS = _initial.get("speakers", {})
ZONES = _initial.get("zones", {})
STATIONS = _initial.get("stations", {})
PRESETS = _initial.get("presets", {})
