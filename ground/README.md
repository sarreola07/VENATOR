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

It needs only Python and `pyserial`, so a laptop doesn't need the flight
software installed. It speaks [`../radio/protocol.py`](../radio/protocol.py),
and the link itself can be checked first with
[`../radio/link_test.py`](../radio/link_test.py).

## Prebuilt downloads

Pushing a change to this file or the protocol builds a Windows `.exe` and a
macOS binary through [GitHub Actions](../.github/workflows/build-gcs.yml).
Download them from the run's Artifacts, so a ground-station laptop needs no
Python at all.
