#!/bin/bash
#
R_IN="/projsu/igcmg/IGCM"
lon="-6.75,6.25"
lat="38.25,47.75"

\rm -rf PFTmap_2000_01.nc PFTmap_2000_005.nc
ncks -d lon,${lon} -d lat,${lat} ${R_IN}/SRF/PFTMAPS/CMIP6/ESACCI-LC/15PFT.v2023.1/0.1/PFTmap_2000.nc PFTmap_2000_01.nc
ncks -d lon,${lon} -d lat,${lat} ${R_IN}/SRF/PFTMAPS/CMIP6/ESACCI-LC/15PFT.v2023.1/0.05/PFTmap_2000.nc PFTmap_2000_005.nc
