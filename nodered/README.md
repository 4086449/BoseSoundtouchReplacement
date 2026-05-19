# Node-RED dashboard for SoundTouch Radio

This folder adds a Node-RED control plane and dashboard to the SoundTouch radio project.

Open the editor at:

```text
http://PI_IP:1880
```

Open the dashboard at:

```text
http://PI_IP:1880/ui
```

The dashboard lets you:

- edit the dynamic speakers map as JSON
- edit zones as JSON
- play one of the six preset stations on any speaker or zone
- play a custom audio stream URL
- proxy a custom stream through the Pi using `/proxy.mp3?url=...`
- send Bose key commands such as volume up/down, mute, play/pause, and power
- inspect now-playing status

The flow uses direct IP calls to the SoundTouch devices, not SSDP discovery. The Docker service therefore does not need host networking.

## Speaker map format

```json
{
  "living": {
    "name": "Living Room",
    "ip": "10.0.0.199",
    "device_id": "000C8AC19FAA"
  },
  "kitchen": {
    "name": "Kitchen",
    "ip": "10.0.0.200",
    "device_id": "000C8A..."
  }
}
```

`device_id` is only required for Bose zone creation. Get it from:

```bash
curl http://BOSE_IP:8090/info
```

## Zone format

```json
{
  "downstairs": {
    "name": "Downstairs",
    "master": "living",
    "members": ["kitchen"]
  },
  "all": {
    "name": "All Speakers",
    "master": "living",
    "members": ["kitchen", "bedroom"]
  }
}
```

When you play a station to a zone, Node-RED tries to create/update the Bose zone first, then sends UPnP playback to the zone master.

## Custom stream support

The dashboard can play arbitrary HTTP/HTTPS audio stream URLs. With "proxy custom URL via Pi" enabled, the Bose receives a local URL like:

```text
http://PI_IP:8091/proxy.mp3?url=https%3A%2F%2Fexample.com%2Fstream.mp3
```

The Pi follows redirects and passes the audio bytes to the Bose. This works best for MP3/AAC HTTP streams. Arbitrary files, DRM streams, web players, Spotify, YouTube, etc. are not expected to work without transcoding or a dedicated extractor.

## Display subtitle priority

The dashboard flow builds a display object for each playback request:

```json
{
  "title": "VRT Radio 1",
  "subtitle": "Downstairs",
  "subtitle_source": "zone_name",
  "fallback_subtitle": "Living Room",
  "logo": "http://PI_IP:8091/logos/radio1.png"
}
```

Subtitle priority is:

1. `live_metadata` - future ICY metadata, only if fresh
2. `zone_name` - when the target is a Node-RED zone
3. `speaker_name` - when the target is a standalone speaker
4. `station_owner` - final fallback, such as VRT or DPG Media

The radio proxy already exposes placeholder endpoints such as `/metadata/radio1.json`. When live ICY parsing is added later, update those endpoints or set `global.liveMetadata` in Node-RED with data like:

```json
{
  "radio1": {
    "artist": "The Cure",
    "title": "Friday I'm In Love",
    "raw": "The Cure - Friday I'm In Love",
    "updated_at": 1778985000
  }
}
```

Playback will then automatically use `Artist - Title` as the Bose subtitle until the metadata becomes stale.
