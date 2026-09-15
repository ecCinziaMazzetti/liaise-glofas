"""Per-step cost of eclandpy on the LIAISE grid, in 250-step blocks (CPU or GPU backend; run with cwd = the eclandpy tree and the environment of submit_eclandpy_liaise_control{,_gpu}.sh). Sept-2026 numbers: 24 ms/step on one EPYC-7742 core, 32 ms/step on one A100 (35 with the three recorders).

per step than a 240-step benchmark). Blocks of 250 steps, with the LIAISE recorders attached;
second pass with the cyclic GC frozen after warm-up."""
import gc, sys, time
from eclandpy.physics import ecland_porting_adapter as adapter

BLOCK, NBLOCKS = 250, int(sys.argv[1]) if len(sys.argv) > 1 else 8

def make():
    pr = adapter.build(plumber2_root="/perm/pad/liaise-ecland/eclandpy_bridge/data", site="LIAISE",
                       initial_date=19880101, final_date=19881231, group="LIAISE", forcing_type="2d")
    from ecland_porting.offline.diag_writer import DiagRecorder
    from ecland_porting.offline.writer import OutputRecorder
    from ecland_porting.offline.diag_output import WAT_VARS, EVA_VARS
    gg = OutputRecorder(pr.run, nfrpos=1)
    wat = DiagRecorder(pr.run, WAT_VARS, nfrpos=1)
    eva = DiagRecorder(pr.run, EVA_VARS, nfrpos=1)
    def on_diag(n, d):
        wat.accumulate(n, d); eva.accumulate(n, d)
    return pr.driver, gg, on_diag

for mode in ("default-gc", "gc-frozen", "no-recorders"):
    drv, gg, on_diag = make()
    drv.run(24)
    if mode == "gc-frozen":
        gc.collect(); gc.freeze()
    line = []
    for b in range(NBLOCKS):
        t0 = time.time()
        if mode == "no-recorders":
            drv.run(BLOCK)
        else:
            drv.run(BLOCK, on_step=gg.maybe_record, on_diag=on_diag)
        line.append(f"{(time.time()-t0)/BLOCK*1000:.0f}")
    print(f"{mode:14s} ms/step per {BLOCK}-step block: {' '.join(line)}  (gc counts {gc.get_count()}, tracked objs {len(gc.get_objects())})", flush=True)
    del drv, gg
