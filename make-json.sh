#!/bin/sh
# Optional diagnostic files for the old LOCAL_INTERNET_RADIO path.
# The working setup uses UPnP via bose-preset-bridge.py; these JSON files are not required.

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
. "$SCRIPT_DIR/config.sh"

make_station() {
  file="$1"
  name="$2"
  url="$3"

  cat > "$SCRIPT_DIR/radio-stations/$file" <<JSON
{
  "audio": {
    "hasPlaylist": false,
    "isRealtime": true,
    "streamUrl": "$url"
  },
  "imageUrl": "",
  "name": "$name",
  "streamType": "liveRadio"
}
JSON
}

make_station "radio1.json" "VRT Radio 1" "http://$PI_IP:$PROXY_PORT/radio1.mp3"
make_station "radio2-limburg.json" "VRT Radio 2 Limburg" "http://$PI_IP:$PROXY_PORT/radio2-limburg.mp3"
make_station "stubru.json" "VRT Studio Brussel" "http://$PI_IP:$PROXY_PORT/stubru.mp3"
make_station "joe.json" "Joe" "http://$PI_IP:$PROXY_PORT/joe.mp3"
make_station "nostalgie.json" "Nostalgie Vlaanderen" "http://$PI_IP:$PROXY_PORT/nostalgie.mp3"
make_station "joe-gold.json" "JOE Gold" "http://$PI_IP:$PROXY_PORT/joe-gold.mp3"
