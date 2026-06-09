#!/bin/sh
# Directly play one station on the Bose via UPnP AVTransport.
#
# Usage: bose-radio.sh <preset> [<speaker-id>]
#   <preset>     1|radio1, 2|radio2-limburg, ... (see -h)
#   <speaker-id> optional id from speakers.json; resolved via the proxy at
#                http://$PI_IP:$PROXY_PORT/config. Defaults to $BOSE_IP.

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
ENV_FILE="$SCRIPT_DIR/../../.env"
if [ -f "$ENV_FILE" ]; then set -a; . "$ENV_FILE"; set +a; fi
BOSE_IP="${BOSE_IP:-10.0.0.216}"
PI_IP="${PI_IP:-10.0.0.241}"
PROXY_PORT="${PROXY_PORT:-8091}"
SPEAKER_NAME="${SPEAKER_NAME:-Portable}"
ACTIVE_ZONE_NAME="${ACTIVE_ZONE_NAME:-}"

resolve_speaker_ip() {
  sid="$1"
  if [ -z "$sid" ]; then echo "$BOSE_IP"; return 0; fi
  if ! command -v jq >/dev/null 2>&1; then
    echo "warn: jq not installed; using \$BOSE_IP=$BOSE_IP" >&2
    echo "$BOSE_IP"; return 0
  fi
  ip=$(curl -sS --max-time 2 "http://$PI_IP:$PROXY_PORT/config" 2>/dev/null \
         | jq -r --arg s "$sid" '.speakers[$s].ip // empty' 2>/dev/null)
  if [ -n "$ip" ]; then echo "$ip"; return 0; fi
  echo "warn: speaker '$sid' not in proxy /config; using \$BOSE_IP=$BOSE_IP" >&2
  echo "$BOSE_IP"
}

case "$1" in
  1|radio1)
    NAME="VRT Radio 1"
    OWNER="VRT"
    LOGO="http://$PI_IP:$PROXY_PORT/logos/radio1.png"
    STREAM="http://$PI_IP:$PROXY_PORT/radio1.mp3"
    ;;
  2|radio2|radio2-limburg)
    NAME="VRT Radio 2 Limburg"
    OWNER="VRT"
    LOGO="http://$PI_IP:$PROXY_PORT/logos/radio2-limburg.png"
    STREAM="http://$PI_IP:$PROXY_PORT/radio2-limburg.mp3"
    ;;
  3|stubru|studio-brussel)
    NAME="VRT Studio Brussel"
    OWNER="VRT"
    LOGO="http://$PI_IP:$PROXY_PORT/logos/stubru.png"
    STREAM="http://$PI_IP:$PROXY_PORT/stubru.mp3"
    ;;
  4|joe)
    NAME="Joe"
    OWNER="DPG Media"
    LOGO="http://$PI_IP:$PROXY_PORT/logos/joe.png"
    STREAM="http://$PI_IP:$PROXY_PORT/joe.mp3"
    ;;
  5|nostalgie)
    NAME="Nostalgie Vlaanderen"
    OWNER="Nostalgie"
    LOGO="http://$PI_IP:$PROXY_PORT/logos/nostalgie.png"
    STREAM="http://$PI_IP:$PROXY_PORT/nostalgie.mp3"
    ;;
  6|joe-gold|joegold)
    NAME="JOE Gold"
    OWNER="DPG Media"
    LOGO="http://$PI_IP:$PROXY_PORT/logos/joe-gold.png"
    STREAM="http://$PI_IP:$PROXY_PORT/joe-gold.mp3"
    ;;
  *)
    echo "Usage: $0 <preset> [<speaker-id>]"
    echo
    echo "Presets:"
    echo "  1  radio1            VRT Radio 1"
    echo "  2  radio2-limburg    VRT Radio 2 Limburg"
    echo "  3  stubru            VRT Studio Brussel"
    echo "  4  joe               Joe"
    echo "  5  nostalgie         Nostalgie Vlaanderen"
    echo "  6  joe-gold          JOE Gold"
    echo
    echo "<speaker-id> is optional. When given, it is looked up in the proxy's"
    echo "/config endpoint (http://$PI_IP:$PROXY_PORT/config) and that IP is"
    echo "used instead of \$BOSE_IP. Requires jq."
    exit 1
    ;;
esac

TARGET_IP=$(resolve_speaker_ip "$2")

SUBTITLE="$ACTIVE_ZONE_NAME"
if [ -z "$SUBTITLE" ]; then SUBTITLE="$SPEAKER_NAME"; fi
if [ -z "$SUBTITLE" ]; then SUBTITLE="$OWNER"; fi

META=$(cat <<XML
<DIDL-Lite xmlns="urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/"
           xmlns:dc="http://purl.org/dc/elements/1.1/"
           xmlns:upnp="urn:schemas-upnp-org:metadata-1-0/upnp/"
           xmlns:dlna="urn:schemas-dlna-org:metadata-1-0/">
  <item id="$1" parentID="0" restricted="1">
    <dc:title>$NAME</dc:title>
    <dc:creator>$SUBTITLE</dc:creator>
    <upnp:artist>$SUBTITLE</upnp:artist>
    <upnp:album>Live Radio</upnp:album>
    <upnp:albumArtURI>$LOGO</upnp:albumArtURI>
    <upnp:class>object.item.audioItem.audioBroadcast</upnp:class>
    <res protocolInfo="http-get:*:audio/mpeg:DLNA.ORG_PN=MP3">$STREAM</res>
  </item>
</DIDL-Lite>
XML
)

ESCAPED_META=$(printf '%s' "$META" | sed 's/&/\&amp;/g; s/</\&lt;/g; s/>/\&gt;/g; s/"/\&quot;/g')

echo "Playing: $NAME"
echo "Stream:  $STREAM"
echo "Subtitle: $SUBTITLE"
echo "Target:  $TARGET_IP"

curl -s -X POST "http://$TARGET_IP:8091/AVTransport/Control" \
  -H 'Content-Type: text/xml; charset="utf-8"' \
  -H 'SOAPACTION: "urn:schemas-upnp-org:service:AVTransport:1#SetAVTransportURI"' \
  --data-binary @- <<XML
<?xml version="1.0"?>
<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/"
            s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">
  <s:Body>
    <u:SetAVTransportURI xmlns:u="urn:schemas-upnp-org:service:AVTransport:1">
      <InstanceID>0</InstanceID>
      <CurrentURI>$STREAM</CurrentURI>
      <CurrentURIMetaData>$ESCAPED_META</CurrentURIMetaData>
    </u:SetAVTransportURI>
  </s:Body>
</s:Envelope>
XML

echo
sleep 0.3

curl -s -X POST "http://$TARGET_IP:8091/AVTransport/Control" \
  -H 'Content-Type: text/xml; charset="utf-8"' \
  -H 'SOAPACTION: "urn:schemas-upnp-org:service:AVTransport:1#Play"' \
  --data-binary @- <<XML
<?xml version="1.0"?>
<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/"
            s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">
  <s:Body>
    <u:Play xmlns:u="urn:schemas-upnp-org:service:AVTransport:1">
      <InstanceID>0</InstanceID>
      <Speed>1</Speed>
    </u:Play>
  </s:Body>
</s:Envelope>
XML

echo
echo "Now playing $NAME"
