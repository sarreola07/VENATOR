# ground/ — what runs on a laptop

The ground station: the other end of the LoRa command link from
[`../drone/c2_server.py`](../drone/c2_server.py).

| File | What it is |
|---|---|
| `gcs_client.py` | Portable client (Windows, macOS, Linux). Fetches the mission menu over the radio, sends a choice, shows what the drone reports back. |

```bash
python3 ground/gcs_client.py              # auto-detects the stick
python3 ground/gcs_client.py --port COM5  # or name the port
```

It holds the stick's serial port exclusively, so close any serial monitor or
`radio/link_test.py` on that port first — otherwise one of the two silently eats
half the conversation. If the stick is unplugged mid-session it reconnects on its
own once the port returns, on whatever port it comes back on.

Every command is sent again until the drone answers, and the drone answers a
repeat from its cache, so a lost packet costs a couple of seconds, never a
session. If the handshake still fails it says why: the stick printed nothing,
the two machines have different keys, or the stick is alive and the drone is
not answering. In flight, Enter sends STOP (Mission 2) and Ctrl-C sends ABORT;
both are repeated until the drone's status shows they arrived, and the
heartbeat pings carry on so the landing is shown. `link quiet 5 s` means
nothing has come from the drone for five seconds.

It needs only Python and `pyserial`, so a laptop doesn't need the flight
software installed. It speaks [`../radio/protocol.py`](../radio/protocol.py),
and the link itself can be checked first with
[`../radio/link_test.py`](../radio/link_test.py).

## Prebuilt downloads

Pushing a change to this file or the protocol builds a Windows `.exe` and a
macOS binary through [GitHub Actions](../.github/workflows/build-gcs.yml).
Download them from the run's Artifacts, so a ground-station laptop needs no
Python at all.
