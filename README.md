# Intex Spa for Home Assistant

Control an Intex PureSpa with a **Tuya** WiFi module from Home Assistant. You sign in
once with your Intex Link account; the device id, encryption key and network address are
found automatically. After setup all control is local, on your own network.

## Why this exists

Intex spas ship with two different WiFi modules and the difference is not advertised.
If the code on your control panel contains **TY**, the module is made by Tuya, and
integrations written for the original Intex protocol cannot talk to it at all - they
speak a proprietary protocol on TCP port 8990, while a Tuya module only answers on 6668.

The usual workaround is a generic Tuya integration, but those need a `local_key` that you
are expected to obtain through the Tuya IoT developer platform. That route is closed for
these spas: the pairing QR code is rejected as belonging to a "designated APP". The
remaining option is re-pairing the spa into the Smart Life app, which means giving up the
Intex Link app.

This integration takes the third path. It signs in to the same service the Intex Link app
uses, with the app's own credentials, and reads the key from there. The Intex Link app
keeps working - it talks to the spa through the cloud while this integration talks to it
over the LAN, so the two do not collide.

## What you get

| Entity | Notes |
|---|---|
| Water heater | Target and current temperature, heater on/off |
| Switches | Power, filtration, bubbles, jets, sanitizer |
| Water temperature | Separate sensor, so it can be graphed |
| Time remaining | Panel timer in minutes; zero means no timer |
| Heating | Diagnostic; on only while the element is actually drawing power |

That last one is worth explaining. Data point 117 is an enum, not a copy of the heater
switch: with heating enabled it reads `heat` while the water is below target and `warm`
once it has arrived. So it tells you whether the spa is heating *right now*, which is the
signal you want when correlating against an electricity meter.

## Live updates

The connection is held open and the spa announces changes as they happen, so turning the
bubbles on from the Intex Link app shows up in Home Assistant straight away rather than
whenever a poll next comes round. A read every thirty seconds remains, purely as a
liveness check.

## Self-repair

Re-pairing the spa in the Intex Link app **rotates the local key**. With a generic Tuya
integration that silently breaks the connection and you have to fetch a new key by hand.

Here, a decrypt failure triggers a fresh cloud lookup, the new key is written back to the
config entry and the connection is rebuilt, without you doing anything. The same applies
if the spa's IP address changes: it is looked up again from the beacons the device
broadcasts. Both are rate limited so a genuinely offline spa cannot turn into a flood of
cloud requests.

## Install

Add this repository to HACS as a custom repository of type *Integration*, install it,
restart Home Assistant, then add **Intex Spa** from *Settings → Devices & Services*.

You will be asked for your Intex Link email, password, and the dialling code of the
country the account was registered in - `40` for Romania, `49` for Germany, `44` for the
United Kingdom.

## Things you should know

**Credentials are kept, but not your actual password.** Renewing the key without you
means being able to sign in without you, so something has to be stored. The Tuya login
only ever receives `MD5(password)`, so that digest is what gets hashed at setup and
written to the config entry - the plaintext is discarded and never reaches disk.

Be clear about what that does and does not buy you. It means a leaked backup does not
hand someone a password to try against your email. It does **not** protect the Intex
account itself: the digest is enough to sign in there. And MD5 is unsalted, so a weak or
common password can be recovered from it in seconds. Use a password you do not use
anywhere else.

Home Assistant stores config entries as plain text under `.storage` and does not encrypt
them, which also means they travel inside backups. That is a
[long-standing complaint](https://community.home-assistant.io/t/wth-2025-a-secret-is-secret-why-are-passwords-in-plain-text-in-the-config-entries-file/809838)
about Home Assistant rather than anything specific to this integration, but it is worth
knowing.

If you would rather store nothing at all, do not use this integration - use
[tuya-local](https://github.com/make-all/tuya-local) with a key you fetch by hand. You
lose the automatic recovery, which is the whole point of this one.

**How much this talks to Intex's servers.** Once, at setup, to read the device id and
key. After that only when the local connection stops decrypting - which means the key
was rotated - and never more than once every ten minutes however badly the local side is
failing. Everything else happens on your own network. Requests identify themselves as
this integration in the `User-Agent` header rather than passing for the Intex Link app.

**The app credentials are extracted from the Intex Link APK.** They are the same for
every user and are already published elsewhere. If Intex or Tuya ever rotate them, sign-in
stops working for everyone until they are updated here.

**The spa accepts one local connection at a time.** Running another Tuya tool against it
in parallel will knock this integration off for a few seconds. The Intex Link app is not
affected, because it goes through the cloud.

**Only one model is verified.** The data point layout was confirmed on product id
`bksofco59ud7eovz` ("SPA PRODUCT WITH SALT & JET"). Other models are accepted, and
entities are created only for data points your spa actually reports - but if yours behaves
oddly, open an issue with its product id.

## Credits

The request signing, AES-GCM envelope and two-step RSA login are adapted from
[bpietroiu/homeassistant-intex-pool](https://github.com/bpietroiu/homeassistant-intex-pool)
(MIT), which does the same for the Intex WA510 water analyser.
[juliseisen/intex-purespa-local](https://github.com/juliseisen/intex-purespa-local) and
[make-all/tuya-local](https://github.com/make-all/tuya-local) were useful references for
the data point layout.

## Licence

MIT
