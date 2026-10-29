# Field mode

The drone hosts its own Wi-Fi and serves the camera, with nobody at the
keyboard. A phone that joins `VenatorDrone` is taken to the camera feed
automatically.

```bash
./deploy/field_mode.sh install     # once — install and enable the boot services
./deploy/field_mode.sh on          # bring it up now
./deploy/field_mode.sh status      # what is running, and the phone URL
./deploy/field_mode.sh off         # stop the camera, rejoin the normal Wi-Fi
```

There is also a **Field Mode (toggle)** desktop icon, with right-click actions
for status, on, off, the phone URL, and install. That icon is the escape hatch:
it is how an operator gets back onto the lab network without a terminal.

---

## What happens at boot

Two units, installed by `field_mode.sh install`:

| Unit | Does |
|---|---|
| `venator-net-fallback.service` | Waits up to 45 s for NetworkManager to join a Wi-Fi network it already knows. If one appears, it leaves it alone. If none does — a field — it brings up the `VenatorDrone` access point. |
| `venator-gui.service` | Runs the camera server either way, so the feed exists whether the drone is hosting or joined to the lab. |

**Why wait rather than always host.** Giving the hotspot a high autoconnect
priority would be simpler, but it would take the Jetson off the lab Wi-Fi on
every reboot — and with no Ethernet carrier that is its only route, so `apt`,
`git` and `pip` would all stop working until someone switched it back. This way
the bench keeps its internet and the field still self-hosts.

**Why it does not switch back by itself.** NetworkManager keeps scanning while
the access point is up. A rule like "a known network appeared, go back to it"
would drop the hotspot — and the operator's video link — the moment the aircraft
drifted within range of the lab. The decision is made once per boot, on purpose.

> **Saved networks matter here.** Any Wi-Fi profile with `autoconnect=yes` that
> is in range will win, and the drone will join it instead of self-hosting. A
> saved phone hotspot is the dangerous case: the drone gets a `172.20.10.x`
> address, becomes unreachable, and nothing visibly fails. Check with
> `nmcli -t -f NAME,AUTOCONNECT connection show` and set anything that is not
> the lab network to `autoconnect no`.

---

## How the popup works

When a phone joins a network it immediately fetches a URL its vendor controls
to find out whether there is real internet. Answer that with anything other
than the expected response and the phone concludes there is a login page and
opens it. That is the popup.

Two mechanisms, belt and braces:

**1. DHCP option 114 — the modern path.** `deploy/dnsmasq/venator-portal.conf`
advertises a Captive Portal API URL (RFC 8908). iOS 14+ and Android 11+ fetch
`/captive-portal-api`, read `{"captive": true, "user-portal-url": ...}` and open
that URL themselves. No request interception, no certificate warning, nothing
for the operator to type. **This is the one that actually delivers the popup.**

**2. Probe interception — the fallback for older devices.** The same dnsmasq
fragment resolves the vendors' probe hostnames to the drone, and
`gui_server.py` answers ten probe paths with a `302` to the portal:

| Probe | Used by |
|---|---|
| `/hotspot-detect.html`, `/library/test/success.html` | iOS, macOS |
| `/generate_204`, `/gen_204` | Android, Chrome |
| `/connecttest.txt`, `/ncsi.txt`, `/redirect` | Windows |
| `/success.txt` | Firefox |
| `/canonical.html`, `/nm-check.txt` | Ubuntu, GNOME |

`/favicon.ico` deliberately answers `204` rather than redirecting, because some
captive browsers follow a redirect there and loop.

### It will not fire every single time

Behaviour varies by OS and version, and that is not something this code can fix:

- **iOS 14+** usually opens the sheet within seconds. Sometimes it shows only a
  "Sign in to Wi-Fi Network" *notification* instead, especially if the screen
  was locked when the phone joined.
- **Android** shows a "Sign in to network" notification; whether it auto-opens
  depends on the manufacturer's software.
- **Windows** shows a taskbar balloon, inconsistently.
- **A device that has joined before** may skip the probe entirely.

**So the documented primary instruction is "open your browser and go to
`venator.com`", with the popup as a convenience.** The portal page says
exactly that, in case it is the popup the operator is looking at.

---

## The address is `http://venator.com` — not `https`

This is not a shortcut, and it cannot be changed:

1. **Captive-portal probes are plain HTTP by design.** There is no HTTPS
   request to intercept.
2. **No certificate authority will issue a certificate for `venator.com`** —
   it is an unregistered domain. Every validation method proves *control* of a
   domain, which is unprovable for one nobody owns.
3. **A self-signed certificate breaks the feature.** The captive sheet has no
   "proceed anyway" button — deliberately, so portals cannot intercept
   traffic. You would trade the automatic popup for a warning that cannot be
   dismissed.
4. **Intercepting HTTPS is impossible regardless.** Redirect a request for
   `https://www.apple.com` and the certificate cannot match that name; the
   client aborts.
5. **Certificates expire every 90 days** and renewal needs internet, which a
   field drone does not have.

The capital `V` in `Venatordrone.com` is fine — DNS is case-insensitive.

The GUI is also reachable at `http://10.42.0.1:8080` and, on any network,
`http://jetson.local:8080`.

---

## Port 80

Captive-portal probes go to port 80, but an unprivileged process cannot bind it
on this Jetson (`ip_unprivileged_port_start` is 1024, there are no file
capabilities, and `authbind` is not installed).

Rather than loosen that kernel-wide or put a capability on the interpreter —
which would apply to every script it runs and vanish on any venv rebuild — a
single nftables rule redirects port 80 to 8080 on the access-point interface
only. A NetworkManager dispatcher script loads it when the hotspot comes up and
removes it when the hotspot goes away, so it is present after a manual toggle,
a NetworkManager restart or a reconnect — none of which a boot-time rule would
survive.

The camera server keeps running unprivileged on 8080, which also stays directly
reachable for laptops.

---

## Security posture — read this before a demo

**Once the portal hands the token to anything that joins the network, the Wi-Fi
password is the entire access control.** Anyone with the password can see the
live feed, every saved evidence frame, and can change detection thresholds.

That is the correct trade for an aircraft that must work with nobody at the
keyboard — it is what "the camera opens automatically" means — but it is a
deliberate change and it is recorded in `docs/SECURITY.md`.

What it is **not**: an escalation path. The GUI token is a one-way derivation of
the command-and-control key, so it cannot be worked backwards to sign flight
commands, and `tests/test_gui_auth.py` pins that in both directions. The blast
radius is a camera feed, not the aircraft.

Use a password worth having:

```bash
sudo nmcli connection modify venator-hotspot wifi-sec.psk '<something good>'
```

---

## Troubleshooting

**The phone joins but gets no IP address.** `dnsmasq-base` is not configured.
`sudo dpkg --configure -a`, then `field_mode.sh preflight`.

**Changes to `venator-portal.conf` appear to do nothing.** dnsmasq reads that
directory **once, at startup**. Cycle the connection:

```bash
sudo nmcli connection down venator-hotspot && sudo nmcli connection up venator-hotspot
```

`field_mode.sh status` warns when the installed config is newer than the
running dnsmasq.

**No popup, and `venator.com` does not resolve.** Confirm the fragment is
installed and in effect:

```bash
dig +short venator.com @10.42.0.1          # -> 10.42.0.1
ps -o args= -C dnsmasq | tr ' ' '\n' | grep conf-dir
```

**The popup opens but shows an error.** Check the redirect and the port-80 rule:

```bash
curl -s -o /dev/null -w '%{http_code} %{redirect_url}\n' \
  -H 'Host: captive.apple.com' http://10.42.0.1/hotspot-detect.html
sudo nft list table ip venator-portal
```

**A camera launcher refuses to start.** The GUI boot service owns the OAK — the
device allows exactly one process.

```bash
./drone/wildlife/oak_camera.sh status     # says who has it
sudo systemctl stop venator-gui           # release it
```

**The drone joined the wrong network.** See the saved-networks warning above.

**Everything, after a reboot:**

```bash
journalctl -u venator-net-fallback -u venator-gui -b
cat ~/.local/state/venator/net-mode       # why it chose client or AP
```
