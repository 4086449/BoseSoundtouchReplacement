#!/usr/bin/env python3
"""Map Bose SoundTouch hardware preset buttons to UPnP radio streams.

The speaker still emits WebSocket events when hardware preset buttons are pressed,
but storing LOCAL_INTERNET_RADIO presets can fail with INVALID_SOURCE. This bridge
listens for those button events and immediately pushes a working UPnP AVTransport
URI to the speaker.

Display metadata is built with a future-proof subtitle priority:
  1. fresh live metadata, when available later
  2. active zone name, when configured
  3. speaker name
  4. station owner
"""

import asyncio
import html
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

import websockets

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import (  # noqa: E402
    ACTIVE_ZONE_NAME,
    BOSE_IP,
    DISPLAY_SUBTITLE_PRIORITY,
    LIVE_METADATA_MAX_AGE_SECONDS,
    PI_IP,
    PRESETS,
    PROXY_PORT,
    SPEAKER_NAME,
    STATIONS,
)

WS_URL = f"ws://{BOSE_IP}:8080"
AVTRANSPORT_URL = f"http://{BOSE_IP}:8091/AVTransport/Control"


def station_stream_url(station):
    return f"http://{PI_IP}:{PROXY_PORT}{station['path']}"


def station_logo_url(station):
    logo = station.get("logo") or ""
    if not logo:
        return ""
    if logo.startswith(("http://", "https://")):
        return logo
    return f"http://{PI_IP}:{PROXY_PORT}{logo}"


def soap_post(action, body):
    req = urllib.request.Request(
        AVTRANSPORT_URL,
        data=body.encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": 'text/xml; charset="utf-8"',
            "SOAPACTION": f'"urn:schemas-upnp-org:service:AVTransport:1#{action}"',
        },
    )

    with urllib.request.urlopen(req, timeout=8) as response:
        return response.read().decode("utf-8", errors="replace")


def fetch_live_metadata(station_key, station):
    """Fetch optional live metadata from the proxy.

    The current proxy ships with placeholder metadata endpoints so this function
    safely returns None until ICY parsing is added later.
    """
    meta = station.get("live_metadata") or {}
    if not meta.get("enabled"):
        return None
    endpoint = meta.get("endpoint")
    if not endpoint:
        return None

    url = f"http://{PI_IP}:{PROXY_PORT}{endpoint}"
    try:
        with urllib.request.urlopen(url, timeout=1.5) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
    except Exception:
        return None

    payload.setdefault("station", station_key)
    return payload


def format_live_metadata(metadata):
    if not metadata:
        return ""
    updated_at = metadata.get("updated_at") or 0
    try:
        age = time.time() - float(updated_at)
    except Exception:
        age = LIVE_METADATA_MAX_AGE_SECONDS + 1
    if age > LIVE_METADATA_MAX_AGE_SECONDS:
        return ""

    artist = str(metadata.get("artist") or "").strip()
    title = str(metadata.get("title") or "").strip()
    raw = str(metadata.get("raw") or "").strip()

    if artist and title:
        return f"{artist} - {title}"
    return raw


def choose_subtitle(station, live_metadata=None):
    candidates = {
        "live_metadata": format_live_metadata(live_metadata),
        "zone_name": ACTIVE_ZONE_NAME.strip(),
        "speaker_name": SPEAKER_NAME.strip(),
        "station_owner": str(station.get("owner") or "").strip(),
    }
    for source in DISPLAY_SUBTITLE_PRIORITY:
        value = candidates.get(source, "")
        if value:
            return value, source
    return "", "empty"


def set_av_transport_uri(name, stream_url, subtitle="", album="Live Radio", logo_url=""):
    creator_xml = f"<dc:creator>{html.escape(subtitle)}</dc:creator>" if subtitle else ""
    artist_xml = f"<upnp:artist>{html.escape(subtitle)}</upnp:artist>" if subtitle else ""
    album_xml = f"<upnp:album>{html.escape(album)}</upnp:album>" if album else ""
    art_xml = f"<upnp:albumArtURI>{html.escape(logo_url)}</upnp:albumArtURI>" if logo_url else ""

    didl = f"""<DIDL-Lite xmlns="urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/"
           xmlns:dc="http://purl.org/dc/elements/1.1/"
           xmlns:upnp="urn:schemas-upnp-org:metadata-1-0/upnp/"
           xmlns:dlna="urn:schemas-dlna-org:metadata-1-0/">
  <item id="{html.escape(name)}" parentID="0" restricted="1">
    <dc:title>{html.escape(name)}</dc:title>
    {creator_xml}
    {artist_xml}
    {album_xml}
    {art_xml}
    <upnp:class>object.item.audioItem.audioBroadcast</upnp:class>
    <res protocolInfo="http-get:*:audio/mpeg:DLNA.ORG_PN=MP3">{html.escape(stream_url)}</res>
  </item>
</DIDL-Lite>"""

    envelope = f"""<?xml version="1.0"?>
<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/"
            s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">
  <s:Body>
    <u:SetAVTransportURI xmlns:u="urn:schemas-upnp-org:service:AVTransport:1">
      <InstanceID>0</InstanceID>
      <CurrentURI>{html.escape(stream_url)}</CurrentURI>
      <CurrentURIMetaData>{html.escape(didl)}</CurrentURIMetaData>
    </u:SetAVTransportURI>
  </s:Body>
</s:Envelope>"""

    return soap_post("SetAVTransportURI", envelope)


def play():
    envelope = """<?xml version="1.0"?>
<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/"
            s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">
  <s:Body>
    <u:Play xmlns:u="urn:schemas-upnp-org:service:AVTransport:1">
      <InstanceID>0</InstanceID>
      <Speed>1</Speed>
    </u:Play>
  </s:Body>
</s:Envelope>"""

    return soap_post("Play", envelope)


def extract_preset_event(message):
    # Some firmware/events may include PRESET_1 directly.
    match = re.search(r"PRESET_[1-6]", message)
    if match:
        return match.group(0)

    # Observed event shape:
    # <nowSelectionUpdated><preset id="1">...</preset></nowSelectionUpdated>
    match = re.search(r'<preset\s+id=["\']([1-6])["\']', message, re.IGNORECASE)
    if match:
        return f"PRESET_{match.group(1)}"

    # Other possible variants: presetID="1", presetId="1", presetid="1".
    match = re.search(r'preset(?:ID|Id|id)=["\']([1-6])["\']', message, re.IGNORECASE)
    if match:
        return f"PRESET_{match.group(1)}"

    return None


async def play_station(preset_key, station_key, station):
    print(f"{preset_key}: playing {station['name']}", flush=True)

    # Let the Bose finish its own failed preset selection first.
    await asyncio.sleep(0.7)

    live_metadata = await asyncio.to_thread(fetch_live_metadata, station_key, station)
    subtitle, subtitle_source = choose_subtitle(station, live_metadata)
    stream_url = station_stream_url(station)
    logo_url = station_logo_url(station)

    print(f"Display title: {station['name']}", flush=True)
    print(f"Display subtitle: {subtitle or '(none)'} [{subtitle_source}]", flush=True)
    if logo_url:
        print(f"Display logo: {logo_url}", flush=True)

    await asyncio.to_thread(
        set_av_transport_uri,
        station["name"],
        stream_url,
        subtitle,
        "Live Radio",
        logo_url,
    )
    await asyncio.sleep(0.3)
    await asyncio.to_thread(play)

    print(f"Now playing {station['name']}", flush=True)


async def listen_forever():
    while True:
        try:
            print(f"Connecting to {WS_URL}", flush=True)

            async with websockets.connect(
                WS_URL,
                subprotocols=["gabbo"],
                ping_interval=20,
                ping_timeout=10,
            ) as ws:
                print("Connected. Press a Bose hardware preset button.", flush=True)

                async for message in ws:
                    print(f"Event: {message}", flush=True)

                    preset_key = extract_preset_event(message)
                    if not preset_key:
                        continue

                    station_key = PRESETS.get(preset_key)
                    station = STATIONS.get(station_key or "")
                    if not station:
                        print(f"No station configured for {preset_key}", flush=True)
                        continue

                    try:
                        await play_station(preset_key, station_key, station)
                    except Exception as e:
                        print(f"Playback error for {preset_key}: {e}", flush=True)

        except Exception as e:
            print(f"WebSocket error: {e}; reconnecting in 5 seconds", flush=True)
            await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(listen_forever())
