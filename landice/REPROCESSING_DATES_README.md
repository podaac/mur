# OSI-SAF Reprocessing Date Configuration

## Summary
Different grid resolutions (p01 and p11) have **different reprocessing cutoff dates**, which means they may pull ice concentration data from different FTP sources for the same calendar date.

## Critical Dates

### p11 Grid (1km resolution)
- **Cutoff Date**: 2006-12-31 (MJD = 54100)
- Dates ≤ 2006-12-31: Use **REPROCESSED** FTP source (`*_reproc_*.nc` files)
- Dates > 2006-12-31: Use **ARCHIVE/PROD** FTP source (`*_multi_*.nc` files)

### p01 Grid (0.1° resolution)
- **Cutoff Date**: 2008-12-31 (MJD = 54831)
- Dates ≤ 2008-12-31: Use **REPROCESSED** FTP source (`*_reproc_*.nc` files)
- Dates > 2008-12-31: Use **ARCHIVE/PROD** FTP source (`*_multi_*.nc` files)

## Date Range Analysis

### Range 1: Before 2006-12-31
- **p11**: REPROCESSED source
- **p01**: REPROCESSED source
- **Result**: ✅ **SAME files** - optimization possible

### Range 2: 2007-01-01 to 2008-12-31 ⚠️
- **p11**: ARCHIVE/PROD source
- **p01**: REPROCESSED source
- **Result**: ❌ **DIFFERENT files** - must download separately!

### Range 3: After 2008-12-31
- **p11**: ARCHIVE/PROD source
- **p01**: ARCHIVE/PROD source
- **Result**: ✅ **SAME files** - optimization possible

## Why This Matters

The attempted optimization in `landice.m` (downloading ice files once and reusing for both grids) **fails for dates in 2007-2008** because:

1. p11 needs `ice_conc_*_polstere-100_multi_YYYYMMDD1200.nc` (archive)
2. p01 needs `ice_conc_*_polstere-100_reproc_YYYYMMDD1200.nc` (reprocessed)
3. These are **different files** with potentially different data

## Solution: Enhanced makeicefiles.m

We've reverted to using `makeicefiles.m` with enhanced logging:

### Changes Made:

1. **Clear documentation in switch statement** ([makeicefiles.m:48-67](src/makeicefiles.m#L48-L67))
   - Added comments explaining cutoff dates
   - Shows which file type is used for each date range

2. **Logging of reprocessing cutoff** ([makeicefiles.m:85-88](src/makeicefiles.m#L85-L88))
   - Prints the cutoff date for the current resolution
   - Shows MJD value for debugging

3. **Enhanced FTP source logging** ([readosisafice.m:24-51](src/readosisafice.m#L24-L51))
   - Shows current date's MJD vs cutoff MJD
   - Explicitly states which FTP source is selected (REPROCESSED/ARCHIVE/PROD)
   - Logs hemisphere being processed

## Example Log Output

```
makeicefiles: resolution - p01
makeicefiles: OSI-SAF reprocessing cutoff for p01 grid: 2008-12-31 (MJD=54831)

readOSISAF: Date 20070701 (nh, MJD=54282) <= reprocessing cutoff (MJD=54831)
readOSISAF: Using REPROCESSED FTP source: https://thredds.met.no/thredds/fileServer/osisaf/met.no/reprocessed/ice/conc
```

vs

```
makeicefiles: resolution - p11
makeicefiles: OSI-SAF reprocessing cutoff for p11 grid: 2006-12-31 (MJD=54100)

readOSISAF: Date 20070701 (nh, MJD=54282) > reprocessing cutoff (MJD=54100), <= archive cutoff (MJD=Inf)
readOSISAF: Using ARCHIVE FTP source: https://thredds.met.no/thredds/fileServer/osisaf/met.no/ice/conc
```

Notice how **the same date (2007-07-01) triggers different FTP sources** for p01 vs p11!

## Files Modified

1. `src/makeicefiles.m` - Added comments and logging for cutoff dates
2. `src/readosisafice.m` - Enhanced FTP source selection logging

## Recommendation

**Continue using `makeicefiles.m` for each resolution separately.**

While there is theoretical efficiency to be gained for ~90% of dates (outside 2007-2008 range), the added complexity of a "smart" hybrid system is not worth the risk of incorrect results. The current approach is:
- ✅ Always correct
- ✅ Clear and maintainable
- ✅ Self-documenting via enhanced logs
- ✅ Easy to debug when issues arise
