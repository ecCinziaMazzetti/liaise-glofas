#!/usr/bin/env python3
"""Merge estimate_dam_q100.py's per-dam Qn/Q100 into a runtime-ready dam_param.csv
for CaMa-Flood's LDAMOUT reservoir module (cmf_ctrl_damout_mod.F90).

Step 3's p03+p04 in the "Ebro Reservoir Operation" activation pipeline
(https://claude.ai/artifact/V5ZZxE3K4jFS6tsds5JiP3), reimplementing the official
CaMa-Flood package's `map/src/src_dam/script/p04_complete_damcsv.py` merge rules
exactly (checked against that script line-for-line, not approximated):

  Qn  = annual mean discharge (already in the input CSV)
  Qf  = 0.3 * Q100, THEN if Qf < Qn (flood discharge smaller than the mean, which
        cannot be right): Qf = 0.4*Q100 if that's >= Qn, else Qf = 1.1*Qn
  FldVol = GRSAD/ReGeom-derived normal-volume estimate; without it (our case --
        GRSAD's TDL Dataverse API returns 403 from this HPC, see PLAN.md),
        FldVol = 0.37 * total capacity, the package's own documented fallback
  ConVol = total capacity - FldVol
  One dam per grid cell: where two+ dams share a 0.25deg cell (real at this
        resolution -- e.g. Canelles/SantaAna both land on the same cell), keep
        only the LARGEST by capacity and drop the rest, exactly as p04 does --
        the runtime module operates per-cell, not per-individual-dam, so only
        one physical reservoir per cell can actually be represented.

Output matches the exact 13-column, LDAMYBY=.TRUE. format
`cmf_ctrl_damout_mod.F90` reads (DamID, DamName, DamLat, DamLon, upreal, DamIX,
DamIY, FldVol_mcm, ConVol_mcm, TotVol_mcm, Qn, Qf, DamYear), with the NDAM count
on line 1 and a header on line 2, as `CMF_DAMOUT_INIT` expects.

Usage
-----
    python3 build_dam_param_csv.py --in /perm/pad/liaise_discharge_compare/ebro_dam_q100.csv \\
        --q-source fortran --fldvol-fraction 0.37 --out dam_param.csv
"""

import argparse
import csv

ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument("--in", dest="in_csv", required=True, help="output of estimate_dam_q100.py")
ap.add_argument("--q-source", choices=["fortran", "gpu"], default="fortran",
                 help="which Qn/Q100 columns to use (fortran = the recommended, full naturalised run)")
ap.add_argument("--fldvol-fraction", type=float, default=0.37,
                 help="fallback FldVol = this fraction of total capacity (no GRSAD data)")
ap.add_argument("--min-uparea-km2", type=float, default=0.0,
                 help="drop dams below this CaMa-Flood drainage area; 0 = keep all "
                      "(the 45-dam Ebro set is already the artifact's validated list, "
                      "not blindly reusing whichever MINUPAREA CaMa's own test scripts use elsewhere)")
ap.add_argument("--out", required=True)
args = ap.parse_args()

with open(args.in_csv, newline="") as fh:
    rows = list(csv.DictReader(fh))

qn_key, q100_key = f"{args.q_source}_q_mean", f"{args.q_source}_q100"

dams = []
skipped_no_q = []
for r in rows:
    if not r.get(qn_key) or not r.get(q100_key):
        skipped_no_q.append(r["name"])
        continue
    qn = float(r[qn_key])
    q100 = float(r[q100_key])
    cap = float(r["cap_mcm"])
    uparea = float(r["uparea_km2"])
    if uparea < args.min_uparea_km2:
        continue

    fldvol = cap * args.fldvol_fraction
    convol = cap - fldvol

    qf = 0.3 * q100
    if qf < qn:
        qf = 0.4 * q100 if 0.4 * q100 >= qn else 1.1 * qn

    year = r["year"]
    year = 2009 if year in ("-99", "", None) else year  # La Loteta: artifact notes this by hand (built 2009)

    dams.append({
        "id": r["ix"] + "_" + r["iy"],  # stand-in GRanD ID (not preserved by estimate_dam_q100.py); unique per cell pre-dedup
        "name": r["name"], "lat": r["lat"], "lon": r["lon"], "uparea_km2": uparea,
        "ix": int(r["ix"]), "iy": int(r["iy"]),
        "fldvol_mcm": round(fldvol, 2), "convol_mcm": round(convol, 2), "totvol_mcm": cap,
        "qn": round(qn, 3), "qf": round(qf, 3), "year": year, "cap_mcm": cap,
    })

if skipped_no_q:
    print(f"Skipped {len(skipped_no_q)} dam(s) with no {args.q_source} Q100 (insufficient years): {skipped_no_q}")

# One dam per grid cell: keep the largest by capacity (matches p04_complete_damcsv.py)
by_cell = {}
for d in dams:
    cell = (d["ix"], d["iy"])
    if cell not in by_cell or d["cap_mcm"] > by_cell[cell]["cap_mcm"]:
        by_cell[cell] = d
dropped = [d["name"] for d in dams if by_cell[(d["ix"], d["iy"])] is not d]
final = sorted(by_cell.values(), key=lambda d: -d["cap_mcm"])

if dropped:
    print(f"Dropped {len(dropped)} smaller dam(s) sharing a grid cell with a bigger one: {dropped}")
print(f"Final dam count: {len(final)} (from {len(dams)} before grid-cell dedup)")

with open(args.out, "w") as fh:
    fh.write(f"{len(final)}\n")
    fh.write("DamID DamName DamLat DamLon UpArea DamIX DamIY FldVol_mcm ConVol_mcm TotVol_mcm Qn Qf DamYear\n")
    for i, d in enumerate(final, start=1):
        fh.write(f'{i} "{d["name"]}" {d["lat"]} {d["lon"]} {d["uparea_km2"]} {d["ix"]} {d["iy"]} '
                  f'{d["fldvol_mcm"]} {d["convol_mcm"]} {d["totvol_mcm"]} {d["qn"]} {d["qf"]} {d["year"]}\n')

print(f"wrote {args.out}")
print(f"\n{'Dam':22s} {'Qn':>8s} {'Qf':>8s} {'FldVol':>9s} {'ConVol':>9s} {'TotVol':>9s} {'Year':>6s}")
for d in final:
    print(f"{d['name']:22s} {d['qn']:8.1f} {d['qf']:8.1f} {d['fldvol_mcm']:9.1f} {d['convol_mcm']:9.1f} "
          f"{d['totvol_mcm']:9.1f} {str(d['year']):>6s}")
