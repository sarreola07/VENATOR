# blender/ — the aircraft model

`x500_cad.blend` is the master model every render in `assets/renders/` and every
frame of the hero and mission animations comes from. 1069 objects, 2.31 M polys,
13 materials, four hand-placed lights and two cameras. It holds **no animation**:
the hero sequence is generated onto a copy at build time, never saved back here.

Stored with **[Git LFS](https://git-lfs.com)** — it is 49 MB. `git clone` on a
machine without LFS gives you a pointer file instead of the model:

```bash
git lfs install
git lfs pull
```

## What is in it

| | |
|---|---|
| Airframe | Holybro X500 V2 — plates, arms, 2216 motors, GPS mast, PM06, fasteners |
| Flight controller | Pixhawk 6X on the top plate |
| Companion | NVIDIA Jetson Orin Nano under the payload shelf |
| Camera | Luxonis OAK-D Pro on the nose bracket |
| Radio | Heltec Wireless Stick — modelled for this project |
| Propellers | modelled for this project; handedness is the sign of `scale.x`, never the Z rotation |

Frame of reference: origin at the centre of the bottom plate, metres,
**−X is the nose**, +X the tail, +Y starboard, −Y port, +Z up.

## Licence — read this before reusing the file

The repository is MIT. **This file is not.**

[`docs/BRAND.md`](../docs/BRAND.md) sets the rule that vendor CAD is not
committed here, because the Holybro, NVIDIA, Pixhawk and Luxonis geometry
belongs to those manufacturers and an MIT repo "would imply a licence we cannot
grant." That rule was set aside deliberately for this one file, so that the
model is backed up and publicly inspectable rather than existing in a single
unversioned folder on one machine.

The consequence is that **the MIT licence in this repository does not extend to
the manufacturers' geometry inside this `.blend`.** The propeller and the radio
were modelled for this project and are ours outright; the airframe, flight
controller, companion computer and camera are vendor CAD, reproduced here for
rendering this aircraft. Do not treat them as MIT-licensed assets, and settle
the terms with the manufacturer before using them in anything else. The Pixhawk
CAD's exact source is still not written down — `BRAND.md` has that as an open
item and it applies here too.

Renders made from this model are a different matter: a picture of hardware we
own is our own picture, and those are MIT like the rest of the repo.

## Not committed

`x500_cinematic.blend` is generated from this file by `build_cinematic.py` and
is reproducible, so it is not kept here. Neither are the render scripts, the
shot table or the source CAD — those still live only in `_localai/`, which has
no version control and no backup.
