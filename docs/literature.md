# Literature relevant to this project

Scientific context for the LIAISE ecLand / CaMa-Flood work. One entry per paper:
citation, what it does, and — the reason this file exists — **which of its
diagnostics are worth replicating here and what we already have to do it with.**

Status labels are load-bearing, same convention as `PLAN.md`: a diagnostic is
only "replicated" once it has actually been computed on our own output.

---

## Polcher et al. (2026) — km-scale LSM evaluation over the Pyrenean catchments

**A framework to evaluate and identify development requirements for land-surface
models at km-scale resolution: Application to a semi-arid and mountainous
region.** Jan Polcher, Julie Collignan, Juan Pablo Sierra Perez, Gabriele
Arduini, Sophie Bastin, Martin Best, Aaron Boone, Manel Bravo, Francesca Covella,
Jasper M. C. Denissen, Cenlin He, Simon Munier, Marc Prange, Elena Shevliakova.
*Quarterly Journal of the Royal Meteorological Society*, published 2026-06-04.
DOI [10.1002/qj.70229](https://doi.org/10.1002/qj.70229). CC-BY 4.0.
Open-archive copy: `hal-05662176`.

**Reading status: ABSTRACT AND METADATA ONLY — full text not yet read.**
Wiley, HAL and Europe PMC all refuse automated fetching (403 / anti-bot), so
everything below is derived from the Crossref abstract, not from the methods
section. Every "diagnostic" listed under *Replication candidates* is therefore an
**inference about what the paper probably did**, not a description of its actual
method. Get the PDF and rewrite this section before treating any of it as the
paper's own approach.

### What it does

Six land-surface models are driven by **3-km resolution atmospheric forcing** and
compared against their own **50-km reference simulation**, over a domain covering
**all catchments flowing off the Pyrenees** — which includes the Ebro, i.e. our
domain. The forcing dataset itself is a contribution: it is shown to capture
mountain/valley contrasts in atmospheric conditions that are absent at coarser
resolution.

### Headline findings (as stated in the abstract)

- At finer resolution the LSMs show **reduced evaporation over semi-arid
  catchments**, and this is **not explained by differences in the atmospheric
  forcing** — so it is a model response, not a forcing artefact. The authors
  attribute it to the **lack of spatial redistribution of water within
  catchments**.
- Observed **diurnal amplitude of land-surface temperature** shows local minima
  along rivers and in irrigated areas, caused by increased evaporation there.
  **The models do not reproduce these minima.**
- Conclusion: at km-scale, **lateral water transfers organise the landscape and
  matter for getting evaporation right**. At deca-kilometre resolution grid-cell
  lateral flows can be neglected; at higher resolution **groundwater, riparian
  recharge and human water management for irrigation** need to be simulated. The
  paper is an explicit call for the community to develop these processes in LSMs.

### Why this matters here, specifically

This project is unusually well placed to speak to that conclusion, because the
missing process the paper identifies — lateral water redistribution — is exactly
what our CaMa-Flood coupling adds, and we have **already measured its effect on
evaporation**:

> 2-way coupling (`NCMF2LAKEC=2` + CaMa-Flood `LWEVAP=true`) raised ecLand's own
> open-water evaporation (`EWater`) by **~19.5%** domain/year mean, with the other
> evaporation components moving <0.06% — a clean, isolated signal from the added
> floodplain/lake fraction. See "2-way coupling" in `CLAUDE.md`.

That is a direct, quantitative data point for the paper's central claim, obtained
independently and before reading it.

### Replication candidates

Ordered by how much we already have in place. **None of these have been done.**

| # | Diagnostic | What we already have | Gap |
|---|---|---|---|
| 1 | **Coarse-vs-km forcing, same model** — run ecLand on 0.5deg WFDE5 and on ~3-km forcing over the same domain/period and compare evaporation | `forcing/get_liaise_forcing_05_cds.sh` (WFDE5, 0.5deg) and `forcing/get_liaise_forcing_km.sh` (ETHZ_Avg / IPSL_Alt / IPSL_Avg, ~3 km) — both already implemented | Never run as a paired comparison; km-scale forcing has not been used for a documented run at all |
| 2 | **Is the evaporation difference a forcing effect or a model response?** The paper separates these — we would need the same separation | Both forcings; `o_eva.nc` components (`EWater`, `ECanop`, `TVeg`, `ESoil`, `SubSnow`); `run/check_water_budget.py` | Needs a decomposition design. NB `check_water_budget.py` does not mask sea/missing points (known bug, `CLAUDE.md`) — fix before using |
| 3 | **Diurnal amplitude of land-surface temperature**, and whether local minima appear along rivers and over irrigated areas | `AvgSurfT` in `o_gg.nc`, hourly; the Ebro domain includes the LIAISE irrigated area (Ivars d'Urgell / Els Plans de Sio) | No LST observations pulled in yet — the paper compares against observed amplitude. Would need a satellite LST product (e.g. MSG/SEVIRI or MODIS) |
| 4 | **Effect of lateral transfer on evaporation** — our strongest angle | Already measured once: +19.5% `EWater` under 2-way coupling (above) | Single year, glb_15min, not repeated at 6/3 arcmin; not expressed as a spatial pattern (the paper's point is about *contrasts along rivers*, not domain means) |
| 5 | **Irrigation** | Nothing — ecLand here has no irrigation scheme | Out of scope for now; noted because the paper treats it as a required process at km-scale |

### Open question worth settling from the full text

The paper says finer resolution *reduces* evaporation in semi-arid catchments
because water is not redistributed. Our 2-way coupling *increases* evaporation by
adding floodplain water. These are consistent in sign (both say "missing lateral
water suppresses evaporation"), but whether our +19.5% is the same magnitude and
mechanism the paper is pointing at cannot be judged from the abstract. Check
against the paper's own numbers before claiming agreement.
