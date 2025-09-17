

bin2bip.m:  make packaged bin (bip) file

-- collects single-sensor files within a given time window.
-- filters based on night/day/wind; reads wind data if needed.
-- handles quality flag (including FNMOC types).
-- handles bias data (including constant adjustment, e.g., AATSR).
-- re-computes time tag, in hours from a reference time.
-- filters based on domain box.
-- shifts the longitude domain from [-180,180] to [0,360], if needed.
-- filters based on std(rms)/PGE threshold.
-- subtracts an offset value from SST values.
-- converts rms error values to weights.
-- writes a single (temporally) sensor-specific data file:  *.bip

      -- inputs:
            bin and bip file directories,
            domain name, sensor name, reference date and hour,
            window size, domain size [optional],
            night/day/all flag, minimum daytime windspeed,
            sensor-dependent quality flag set,
            sensor-dependent bias flag and constant.

      -- outputs:
            *.nml partial (header) file for mrvacom.m etc: 
              lon-lat box
            *.bip file:
              integer*4: ndata,
              real*4:    lon, lat, hour, sst, std

            

mrvacom.m

-- runs mrva.
-- defines scale-specific correlation times (gaussian correlation function).
-- defines sensor-specific begin and end scales.
-- defines bin-correlation parameter (scale specific?).
-- writes spline coefficient file:  *.cXX, where XX is scale index.

      -- inputs:
            *.nml file:
              -- lon-lat box
              -- begin and end scales
              -- anomaly file production flag and its filename.
              -- lists of: 
                  *.bip files.
                  begin and end scales.
              -- scale table:
                  scale index, correlation time.
              -- output file name.

      -- output:
            *.cXX file (mrva format)
            *.aXX file (*.bip file format) -- anomaly file.

            []- uncertainty estimates?


spgridcom.m

-- runs spgrid.
-- defines the output grid (or lon/lat locations) and landmask.
-- writes binary product file:  *.map

      -- inputs:
            *.cXX file.
            output grid/landmask.
      -- output:
            *.map file.
            []- uncertainty data?



reference SST field:
-- can do with mrvacom.m using appropriate *.nml file.
-- save as a *.c03 file.

single-sensor lo-res field for bias correction and hi-res anomaly field:
-- can do with mrvacom.m using appropriate *.nml file,
   EXCEPT that the hi-res residual/anomaly must be written:  *.aXX
      -- output:
            *.aXX

combine the reference and sensor anomaly fields:
-- can do with mrva,
   EXCEPT that the background is a coefficient field
      and that the data files are anomaly field.



ultimate mrva:

-- can use a background data set (bip format)
      which participates in analysis only at the lowest resolution.

-- can use an initial coefficient field (*.cXX)
      without which the coefficient field is initialized to be zero.

-- can use the full data files (*.bip)
      which participate in the background (lowest resolution) analysis.

-- can use the anomaly data files (*.aXX, in bip format)
      which do not participate the background analysis.

-- can output a coefficient file at each specified scale.

-- can output an anomaly file at the highest resolution.

-- The "background analysis" consists of:
     produciton of the lowest resolution coefficient field
     using the background data and full data files.

-- The only distinction between a full and anomaly data file is
   whether or not it participates in background analysis.
   Both files have the bip format.

-- The initial coefficient field is mutually exclusive
   with the ingredients of the background analysis, i.e.,
   the background and full data files.
   mrva does NOT check this for an error.

-- The anomaly data can be combined with either background analysis
   or initialized coefficient field.  The only restriction is that
   it cannot participate in background analysis.



10.1.27

[x] include mean(sst) in residual statistic in mrva.f

[x] move bin2bip.m parameter "dayrange" to wrapper code (e.g., mrva0com.);
     then use mrva to print out matchup statistics --> matchup.m

[ ] speed-up?  write main part of bin2bip in Fortran.

[@] need speedup on spmData!
       -- How slow is spmRhoWeightScale?  --> not very much at all!
       -- What's aloc=0.;bloc=0.???  --> not needed.
       -- How about paralellizing at (i1,j1) -- 16 processors  --> bad idea!
    --> made some improvement by different indexing;
      but STILL SLOW.


10.2.8

[x] bug in mrva?com.m:  crashes when [L0,LF] doesn't contain [mapL0,mapLF].


11.9.28

written master script "nnrtMRVA.py"
now testing.

