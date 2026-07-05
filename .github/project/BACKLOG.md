# BoseSoundtouchReplacement Project Backlog

> Last updated: 2026-06-09 | Current version: v1.0

## Status Legend
- `[ ]` — To do
- `[~]` — In progress  
- `[x]` — Done
- `[!]` — Blocked

---

## Bugs

### B01 —  button `Discover device ID's` should be `Discover devices`
- **File**: `nodered/data/flows.json` → `SoundTouch dashboard`
- **Issue**: Checks for known devices with missing device ID's. It should scan for unknown bose speaker devices on the same network instead.
- **Impact**: The IP address must be known before you can add a new speaker which requires access to the router or some extra tool on a separate device.
- **Priority**: High

### B02 —  drop or delete speakers
- **File**: `nodered/data/flows.json` → `SoundTouch dashboard`
- **Issue**: Checks for known devices with missing device ID's. It should scan for unknown bose speaker devices on the same network instead.
- **Impact**: The IP address must be known before you can add a new speaker which requires access to the router or some extra tool on a separate device.
- **Priority**: High

---

## Features

### F01 — Matter for Alexa voice command integration
- **Description**: Use `Matter`, `Node-Red` and `Home Assistant` to create virtual Matter devices. These devices will then be linked to HTTP requests sent to our `soundtouch-api`. That way we can convert for example socket on/off commands to speaker device commands. 
i.e. Create a virtual `on off socket` Matter device called `Portable preset 1`. When this device is called, it triggers a node-red flow and sends `{target: "speaker:portable", station: "radio1"}` to `/soundtouch/api/play`
- **Current state**: The matter-server docker container is added to docker-compose.yml file. There's a node-red flow for testing (below: `node-red Matter Bridge flow`), which is not yet in `flows.json`, in where a matter on/off socket node from `node-red-matter-bridge` package to play preset 1 on speaker Portable. The matter on/off socket node (Portable preset 1) says it’s connected but home assistant says it failed. The http request node isn’t setup well. First start by a
- **Priority**: Very High
- **Branch**: `feature/matter`

### F02 — enable Alexa to play upnp from soundtouch-radio
- **Description**: enable Amazon echo or `Alexa` to play upnp from `soundtouch-radio`. It should also be part of our speaker group in being able to be part of zones. If possible, control over the node-red dashboard.
- **Current state**: Not yet started
- **Priority**: Medium

---

## Tech Debt

## Notes

### node-red Matter Bridge flow

```js
[
    {
        "id": "f06252a0f612ee1d",
        "type": "tab",
        "label": "Matter Bridge",
        "disabled": false,
        "info": "",
        "env": []
    },
    {
        "id": "2b5f0563d9d18a15",
        "type": "debug",
        "z": "f06252a0f612ee1d",
        "name": "Matter on/off",
        "active": true,
        "tosidebar": true,
        "console": false,
        "tostatus": true,
        "complete": "true",
        "targetType": "full",
        "statusVal": "payload",
        "statusType": "auto",
        "x": 555,
        "y": 120,
        "wires": [],
        "l": false
    },
    {
        "id": "11b5a12d04cc980f",
        "type": "http request",
        "z": "f06252a0f612ee1d",
        "name": "",
        "method": "POST",
        "ret": "txt",
        "paytoqs": "ignore",
        "url": "http://10.0.0.241:1880/soundtouch/api/play",
        "tls": "",
        "persist": false,
        "proxy": "",
        "insecureHTTPParser": false,
        "authType": "",
        "senderr": false,
        "headers": [
            {
                "keyType": "other",
                "keyValue": "Content-Type",
                "valueType": "other",
                "valueValue": "application/json"
            }
        ],
        "x": 750,
        "y": 140,
        "wires": [
            [
                "18b5b3e384a04c12"
            ]
        ]
    },
    {
        "id": "4525dc86e656fc9b",
        "type": "delay",
        "z": "f06252a0f612ee1d",
        "name": "Reset (momentary switch)",
        "pauseType": "delay",
        "timeout": "500",
        "timeoutUnits": "milliseconds",
        "rate": "1",
        "nbRateUnits": "1",
        "rateUnits": "second",
        "randomFirst": "1",
        "randomLast": "5",
        "randomUnits": "seconds",
        "drop": false,
        "allowrate": false,
        "outputs": 1,
        "x": 675,
        "y": 180,
        "wires": [
            [
                "dec60c945cf18720"
            ]
        ],
        "l": false
    },
    {
        "id": "c92531e4b2a66751",
        "type": "function",
        "z": "f06252a0f612ee1d",
        "name": "function 2",
        "func": "const state = msg.payload.state || false; \nconst msg1 = { payload: {\"target\":\"speaker:portable\",\"station\":\"radio1\" }};\nconst msg2 = { payload: false };\n\nif (state === true) {\n    return [msg1,msg2];\n} else if (String(state).toLowerCase() === 'true') {\n    return [msg1, msg2];\n}\nreturn [null,null];",
        "outputs": 2,
        "timeout": 0,
        "noerr": 0,
        "initialize": "",
        "finalize": "",
        "libs": [],
        "x": 595,
        "y": 180,
        "wires": [
            [
                "11b5a12d04cc980f",
                "b5c8f10c064a2239"
            ],
            [
                "4525dc86e656fc9b",
                "de242a5011a678b5"
            ]
        ],
        "l": false
    },
    {
        "id": "b5c8f10c064a2239",
        "type": "debug",
        "z": "f06252a0f612ee1d",
        "name": "Matter on",
        "active": true,
        "tosidebar": true,
        "console": false,
        "tostatus": true,
        "complete": "true",
        "targetType": "full",
        "statusVal": "payload",
        "statusType": "auto",
        "x": 655,
        "y": 120,
        "wires": [],
        "l": false
    },
    {
        "id": "604f611e5d98e608",
        "type": "inject",
        "z": "f06252a0f612ee1d",
        "name": "",
        "props": [
            {
                "p": "payload"
            }
        ],
        "repeat": "",
        "crontab": "",
        "once": false,
        "onceDelay": 0.1,
        "topic": "",
        "payload": "true",
        "payloadType": "bool",
        "x": 210,
        "y": 120,
        "wires": [
            [
                "dec60c945cf18720"
            ]
        ]
    },
    {
        "id": "dec60c945cf18720",
        "type": "matteronoffsocket",
        "z": "f06252a0f612ee1d",
        "name": "Portable preset 1",
        "bridge": "a31d73f16a73aae4",
        "passthrough": "true",
        "bat": "false",
        "topic": "",
        "x": 410,
        "y": 180,
        "wires": [
            [
                "2b5f0563d9d18a15",
                "c92531e4b2a66751"
            ]
        ]
    },
    {
        "id": "de242a5011a678b5",
        "type": "debug",
        "z": "f06252a0f612ee1d",
        "name": "Matter delay off",
        "active": true,
        "tosidebar": true,
        "console": false,
        "tostatus": true,
        "complete": "true",
        "targetType": "full",
        "statusVal": "payload",
        "statusType": "auto",
        "x": 655,
        "y": 240,
        "wires": [],
        "l": false
    },
    {
        "id": "18b5b3e384a04c12",
        "type": "debug",
        "z": "f06252a0f612ee1d",
        "name": "Matter on",
        "active": true,
        "tosidebar": true,
        "console": false,
        "tostatus": true,
        "complete": "true",
        "targetType": "full",
        "statusVal": "payload",
        "statusType": "auto",
        "x": 885,
        "y": 140,
        "wires": [],
        "l": false
    },
    {
        "id": "a31d73f16a73aae4",
        "type": "matterbridge",
        "name": "myBridge",
        "vendorId": "0xFFF1",
        "productId": "0x8000",
        "vendorName": "TestMatter",
        "productName": "myTestBridge",
        "storageLocation": "/data/.matter",
        "networkInterface": "wlan0",
        "logLevel": "ERROR"
    },
    {
        "id": "3bf4ef713332486c",
        "type": "global-config",
        "env": [],
        "modules": {
            "@sammachin/node-red-matter-bridge": "0.12.3"
        }
    }
]
```

