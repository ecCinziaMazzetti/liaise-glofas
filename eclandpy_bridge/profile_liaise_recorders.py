"""Where does eclandpy's per-step time go once the recorders are attached? (LIAISE, gt:cpu_kfirst)"""
import cProfile, pstats, time, io, os
from eclandpy.physics import ecland_porting_adapter as adapter

pr = adapter.build(plumber2_root="/perm/pad/liaise-ecland/eclandpy_bridge/data", site="LIAISE",
                   initial_date=19880101, final_date=19881231, group="LIAISE", forcing_type="2d")
from ecland_porting.offline.diag_writer import DiagRecorder
from ecland_porting.offline.writer import OutputRecorder
from ecland_porting.offline.diag_output import WAT_VARS, EVA_VARS

drv, run = pr.driver, pr.run
drv.run(24)  # warm-up
N = 240
t0 = time.time(); drv.run(N); t1 = time.time()
print(f"physics only:   {(t1-t0)/N*1000:.1f} ms/step", flush=True)

gg = OutputRecorder(run, nfrpos=1)
wat = DiagRecorder(run, WAT_VARS, nfrpos=1)
eva = DiagRecorder(run, EVA_VARS, nfrpos=1)
def on_diag(n, d):
    wat.accumulate(n, d); eva.accumulate(n, d)

prof = cProfile.Profile(); prof.enable()
t0 = time.time(); drv.run(N, on_step=gg.maybe_record, on_diag=on_diag); t1 = time.time()
prof.disable()
print(f"with recorders: {(t1-t0)/N*1000:.1f} ms/step", flush=True)
s = io.StringIO(); pstats.Stats(prof, stream=s).sort_stats("tottime").print_stats(22); print(s.getvalue()[-5500:])
s = io.StringIO(); st = pstats.Stats(prof, stream=s); st.sort_stats("cumulative").print_stats("maybe_record|accumulate|host|collect|to_host|step"); print(s.getvalue()[-3000:])

t0 = time.time(); gg.write("o_gg_test.nc"); wat.write("o_wat_test.nc"); eva.write("o_eva_test.nc"); t1 = time.time()
print(f"write 3 files ({N} records): {t1-t0:.2f}s", [os.path.getsize(f)//1024 for f in ("o_gg_test.nc","o_wat_test.nc","o_eva_test.nc")], "kB")
print("records in memory: gg", len(gg.records), "vars", len(gg.records[0]), "| wat", len(wat.records[0]), "| eva", len(eva.records[0]))
