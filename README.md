# Intex Spa for Home Assistant

Control an Intex PureSpa with a **Tuya** WiFi module from Home Assistant, **using your
Intex Link account** — the one already on your phone. No Tuya account, no Smart Life
account, no developer portal, no re-pairing the spa away from the app you use.

You sign in once. The device id, its encryption key and its address on your network are
found for you. After that everything is local, and **nothing from that sign-in is kept**.

> An independent project, [not affiliated with Intex or Tuya](#not-affiliated-with-intex-or-tuya).

## Is this the right integration for your spa?

**Look at the code printed on the control panel. If it contains `TY`, this is the one.**

Intex ships two different WiFi modules and does not advertise the difference. `TY` means
a **Tuya** module. If yours does not have it, use
[mathieu-mp/homeassistant-intex-spa](https://github.com/mathieu-mp/homeassistant-intex-spa)
instead - and nothing here will work for you, because the two speak entirely different
protocols on different ports: the original Intex one on TCP 8990, Tuya on 6668.

Two further checks that do not need the panel. A Tuya module answers on port 6668 and
nothing on 8990. And if your spa appears at all when you sign in during setup, it is a
Tuya module - the Intex Link account *is* a Tuya account under a different name, so a
non-Tuya spa is simply not in it.

Setup will also tell you if your particular model is one this has been tested against.
An untested model is not refused - entities are built from whatever the spa reports - but
you get a notice naming the product id and the data points it sent, which is exactly what
is needed to add proper support.

## Why this exists

The usual workaround is a generic Tuya integration, but those need a `local_key` that you
are expected to obtain through the Tuya IoT developer platform. **That platform does not
support these devices**: it rejects the pairing QR code as belonging to a "designated
APP", so the information needed to interoperate is not available by that route. The
remaining documented option is re-pairing the spa into the Smart Life app, which means
giving up the Intex Link app.

This integration signs in to the same service the Intex Link app uses, as you, with the
account you already have, and reads your own device's key. That is the whole point of it:
the account you use is the one on your phone, not a second one you have to create.

The Intex Link app keeps working - it talks to the spa through the cloud while this
integration talks to it over the LAN, so the two do not collide.

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

## When the key changes

Re-pairing the spa in the Intex Link app **rotates its key**. With a generic Tuya
integration that silently breaks the connection and you have to go and fetch a new key by
hand, through a developer portal that does not support these spas.

Here, Home Assistant notices and asks you to sign in again. One dialog, the same email and
password as before, and the new key is fetched for you. That is deliberately not automatic:
doing it unattended would mean keeping your password on disk, and it is not worth it for
something that only happens when you were standing at the spa re-pairing it anyway.

A changed IP address **is** handled without you - the spa is simply looked up again on the
network.

## Install

Add this repository to HACS as a custom repository of type *Integration*, install it,
restart Home Assistant, then add **Intex Spa** from *Settings → Devices & Services*.

You will be asked for your Intex Link email, password, and the dialling code of the
country the account was registered in - `40` for Romania, `49` for Germany, `44` for the
United Kingdom.

## Things you should know

**Your Intex credentials are never stored.** They are used once, in the setup dialog, to
read your spa's key, and then discarded. Not the password, not a hash of it, not the
email, not the session. Nothing.

What **is** stored is the spa's device id, its local key, and its address - the three
things local control needs. The local key is a device secret: it lets something already on
your network talk to your spa. It is not an account credential and cannot be used to sign
in anywhere.

That matters because Home Assistant keeps config entries as plain text under `.storage`
and does not encrypt them, so they travel inside every backup. That is a
[long-standing complaint](https://community.home-assistant.io/t/wth-2025-a-secret-is-secret-why-are-passwords-in-plain-text-in-the-config-entries-file/809838)
about Home Assistant rather than anything specific to this integration - but it is exactly
why there is nothing here worth taking.

**How much this talks to Intex's servers.** Once, at setup, to read the device id and
key. After that only when the local connection stops decrypting - which means the key
was rotated - and never more than once every ten minutes however badly the local side is
failing. Everything else happens on your own network. Requests identify themselves as
this integration in the `User-Agent` header rather than passing for the Intex Link app.

**The app constants are a client identity, not a key to anything.** They identify the
software making the request; signing in still requires your own email and password, and
the integration only ever reads your own account. They are the same for every user of the
Intex Link app. They were **copied from a public MIT-licensed repository** that published
them (see THIRD_PARTY_NOTICES.md); nothing was decompiled for this project. If Intex or
Tuya ever change them, sign-in stops working for everyone until they are updated here.

**Using this may not sit well with Intex's or Tuya's terms.** Neither publishes terms
covering this endpoint, and no action has ever been taken against a project of this kind -
but automated access to your account is not something either has authorised, and in
principle it could result in action against your account. You are choosing that; the
software cannot choose it for you.

**The spa accepts one local connection at a time.** Running another Tuya tool against it
in parallel will knock this integration off for a few seconds. The Intex Link app is not
affected, because it goes through the cloud.

**Only one model is verified.** The data point layout was confirmed on product id
`bksofco59ud7eovz` ("SPA PRODUCT WITH SALT & JET"). Other models are accepted and you are
told during setup that yours is untested; entities are built from whatever data points
your spa reports, and appear later if it starts reporting more. If something is missing,
open an issue with the product id and data point list from that notice.

**Protocol version and address can be corrected.** Setup asks the spa which protocol it
speaks rather than assuming, but if it cannot be reached at that moment, *Configure* on
the integration lets you set the address, the protocol version and the local key by hand.

**Both temperature units are handled.** The spa transports whichever unit its own panel is
set to. Which one is in use is worked out from the target temperature, whose two valid
ranges - 20-40 and 68-104 - cannot be confused with each other.

## Not affiliated with Intex or Tuya

This is an independent project, not affiliated with, authorised by, or endorsed by Intex
Recreation Corp. or Tuya Inc. INTEX and INTEX LINK are trademarks of Intex Recreation
Corp.; TUYA is a trademark of Tuya Inc. They are used here only to identify the devices
and services this software works with.

## Credits

The request signing, AES-GCM envelope and two-step RSA login are adapted from
[bpietroiu/homeassistant-intex-pool](https://github.com/bpietroiu/homeassistant-intex-pool)
(MIT), which does the same for the Intex WA510 water analyser.
[juliseisen/intex-purespa-local](https://github.com/juliseisen/intex-purespa-local) and
[make-all/tuya-local](https://github.com/make-all/tuya-local) were useful references for
the data point layout.

## Licence

MIT
