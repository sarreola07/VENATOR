# tests/ — regression tests

```bash
python3 tests/test_missions.py
python3 tests/test_link_reconnect.py
```

Runs against a **mock flight controller**: no Pixhawk, no radio and no motors
are involved, so this is safe to run on any machine, including in CI. It prints
one line per check and exits non-zero if any fail.

`test_missions.py` covers the behaviour that is expensive to get wrong in the
air: a mission returning home on link loss, holding position instead of
drifting when the camera loses the person, and the ground client surviving
corrupted LoRa packets rather than crashing.

`test_link_reconnect.py` injects a fake serial module and yanks the stick
mid-session, pinning what happens next: the link reports itself down instead of
raising, retries on a timer rather than hammering the port, says so once instead
of once per read, refuses sends with an error the caller can show, and comes
back on its own when the port returns.

Add a case here whenever a bug reaches the aircraft — that is what keeps it
from coming back.
