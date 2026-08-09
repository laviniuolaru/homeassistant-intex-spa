# Third-party notices

This project is MIT licensed (see LICENSE). It contains, and depends on, code from
the projects below, each of which is also MIT licensed. Their copyright and
permission notices are reproduced here as their licences require.
## bpietroiu/homeassistant-intex-pool

`custom_components/intex_spa/cloud.py` contains code adapted from, and in places
copied unchanged from, this project: the request signature scheme (`SIGN_KEYS`,
`_swap`, `_sign`), the AES-GCM request and response envelope with its key
derivation (`_envelope_key`), the client id generation (`new_client_id`), the
request parameter block, and the two-step RSA login and device-listing calls
(`login`, `_homes`, `devices`).

`custom_components/intex_spa/const.py` — the Intex Link app constants (`PACKAGE`,
`APP_KEY`, `CH_KEY`, `_CERT`, `_SECRET1`, `_SECRET2`, `SECRET`, `TTID`, `BASE_URL`,
`APP_VERSION`) are copied from that project's `const.py`.

  Copyright (c) 2026 bpietroiu

  Permission is hereby granted, free of charge, to any person obtaining a copy
  of this software and associated documentation files (the "Software"), to deal
  in the Software without restriction, including without limitation the rights
  to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
  copies of the Software, and to permit persons to whom the Software is
  furnished to do so, subject to the following conditions:

  The above copyright notice and this permission notice shall be included in all
  copies or substantial portions of the Software.

  THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
  IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
  FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
  AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
  LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
  OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
  SOFTWARE.

## juliseisen/intex-purespa-local

The single-owner socket thread in `custom_components/intex_spa/link.py` follows the
design of that project's `IntexPureSpaMonitor`: one thread owning the spa's only
permitted connection, a command queue drained by that same thread, interval
heartbeats and a delayed reconnect. The data point constant names and the
Fahrenheit temperature limits in `const.py` follow its `const.py`.

  Copyright (c) 2026 Julian Seisenberger

  Permission is hereby granted, free of charge, to any person obtaining a copy
  of this software and associated documentation files (the "Software"), to deal
  in the Software without restriction, including without limitation the rights
  to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
  copies of the Software, and to permit persons to whom the Software is
  furnished to do so, subject to the following conditions:

  The above copyright notice and this permission notice shall be included in all
  copies or substantial portions of the Software.

  THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
  IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
  FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
  AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
  LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
  OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
  SOFTWARE.

## make-all/tuya-local

The entity layout in `const.py`, `switch.py`, `sensor.py` and `water_heater.py` was
informed by that project's `devices/intex_purespa_spa.yaml`: the data point to
entity assignment, the water heater off/electric operation pair, the 68-104 F
range, the `mdi:air-filter` and `mdi:chart-bubble` icons, and the `time_remaining`
sensor definition.

  Copyright 2018 Nik Rolls, 2026 Jason Rumney, 2022-2026 other contributors as
  listed in that project's ACKNOWLEDGEMENTS.md

  Permission is hereby granted, free of charge, to any person obtaining a copy
  of this software and associated documentation files (the "Software"), to deal
  in the Software without restriction, including without limitation the rights
  to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
  copies of the Software, and to permit persons to whom the Software is
  furnished to do so, subject to the following conditions:

  The above copyright notice and this permission notice shall be included in all
  copies or substantial portions of the Software.

  THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
  IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
  FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
  AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
  LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
  OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
  SOFTWARE.

## jasonacox/tinytuya

Installed at runtime (declared in `manifest.json`) and used for the local protocol
and for active device discovery. The Tuya UDP beacon frame parser in `discovery.py`
is an independent implementation, but the frame layouts and the fixed UDP key it
uses are documented by this project; tinytuya in turn credits **tuya-convert** for
that key.

  Copyright (c) 2024 Jason Cox

  Permission is hereby granted, free of charge, to any person obtaining a copy
  of this software and associated documentation files (the "Software"), to deal
  in the Software without restriction, including without limitation the rights
  to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
  copies of the Software, and to permit persons to whom the Software is
  furnished to do so, subject to the following conditions:

  The above copyright notice and this permission notice shall be included in all
  copies or substantial portions of the Software.

  THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
  IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
  FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
  AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
  LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
  OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
  SOFTWARE.
