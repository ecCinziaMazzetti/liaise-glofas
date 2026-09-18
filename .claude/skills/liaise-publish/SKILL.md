---
name: liaise-publish
description: Build the LIAISE dashboards from a finished run's diagnostics or gauge scores and publish them to ECMWF Sites with sitesctl. Use when asked to build, rebuild, update or publish a LIAISE dashboard or results page, or to put results on sites.ecmwf.int.
---

# Building and publishing LIAISE dashboards

Two different pages, three builders. Pick by what you have:

| You have | Builder | Page |
|---|---|---|
| `extract_control_diagnostics.py` JSON | `run/build_land_control_dashboard.py` | land-surface control: water balance, T2m, soil moisture, seasonal cycle |
| `skill_benchmark_chains.py` JSON | `cama_flood/build_chain_dashboard.py` | two-chain discharge skill vs GRDC |
| `skill_benchmark_control.py` JSON | `cama_flood/build_control_dashboard.py` | single-model river-gauge skill map |

The last two are easy to confuse with each other, and
`cama_flood/build_control_dashboard.py` is **not** the land-surface page despite
the name — that's `run/build_land_control_dashboard.py`.

## 1. Build

```bash
module load python3/3.11.10-01     # REQUIRED: default python3 is 3.6 and fails
                                   # on `from __future__ import annotations`

python3 run/build_land_control_dashboard.py \
  --diagnostics $PERM/liaise_diagnostics/control.json \
  --out $PERM/liaise_dashboard_control/index.html \
  --note "Independently reproduced by <user>: own build, restart-chained."

python3 cama_flood/build_chain_dashboard.py \
  --results $PERM/liaise_diagnostics/skill.json \
  --out $PERM/liaise_dashboard_discharge/index.html \
  --fortran-label "Fortran ecLand-CaMa-Flood chain (<user>, restart-chained)" \
  --gpu-label "eclandpy to CaMa-Flood-GPU chain (pad reference)"
```

Each writes one self-contained `index.html` (no external assets beyond a
webfont), so it can be moved or mailed as a single file.

**Label the provenance of every series you didn't produce.** The chain dashboard
draws a Fortran chain and a GPU chain, and the GPU rows are usually upstream's
eclandpy output, not yours. Its "GPU wins N/133" headline is only a model
comparison when both sides were driven by equivalently chained ecLand runoff —
say so in the labels rather than letting the page imply otherwise.

## 2. Check before publishing

```bash
grep -o "<figure class=\"chart\"" index.html | wc -l    # charts rendered
grep -oE "https://[a-z.]+" index.html | sort -u         # external hosts
```

Then confirm a couple of headline numbers appear in the HTML and match the
source JSON. The builder can't tell you the *data* is right.

## 3. Publish

```bash
module load sites
sitesctl auth status                                    # must not say "Anonymous"
sitesctl site --space <space> --name <site> content upload \
  --source $PERM/liaise_dashboard_control/index.html --destination / --force
sitesctl site --space <space> --name <site> content list --match "*" --recursive
```

- `--force` is needed in any non-interactive shell; without it `sitesctl`
  prompts and the upload is cancelled.
- **A silent upload with no output means it failed** — usually an expired token
  giving HTTP 403. Always confirm with `content list`, never assume success from
  a zero exit code.
- `Could not upgrade the CLI binary ... permission denied` is harmless noise:
  the CLI tries to self-update inside `/usr/local/apps`.
- Log in with `sitesctl auth login --username <user>` (interactive: it needs a
  one-time code entered at `github.com/login/device`-style device flow, so a
  user has to run it — an agent cannot).

## 4. Conventions worth keeping

- **Publish tests to a subpath, not the root.** `/test_<year>/` keeps the root
  free for the real multi-year page and makes it obvious what's provisional.
- **Look at what's there before overwriting** (`content list --recursive`).
- **Never publish cold-start numbers as a result.** Verify the run first with
  the `liaise-verify` skill; a page is much harder to retract than a file.

## Reading the pages

The land dashboard states two conventions on the page itself because they're
easy to get wrong: evapotranspiration and runoff are plotted **positive**
although `o_wat.nc` stores `Evap` and `Qs+Qsb` negative, and annual depths come
from rates times the output interval, not from pre-accumulated fields.

Trends are least-squares per decade and only appear with >=10 years. They are
sensitive to the restart chain in a way the means partly hide: chaining changed
the root-zone moisture trend from −6.1 to −22.7 kg/m²/decade and the runoff
trend from −8.3 to −18.8 mm/decade on this domain, while precipitation
(−5.75 mm/decade) and T2m (+0.34 °C/decade) stayed put, being forcing-driven.
