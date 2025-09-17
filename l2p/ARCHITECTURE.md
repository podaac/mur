# L2P Container Architecture Decision

## Production vs Container Usage

### Production Architecture (nrtMRVA.py)

```
┌─────────────────┐
│ Cron Jobs       │
│ (hourly)        │
│ - amsr2r.sh     │  Downloads L2P files
│ - modis_a.sh    │  to /measures_mur/.../
│ - modis_t.sh    │  using podaac-data-subscriber
└────────┬────────┘
         │ Downloaded files
         ↓
┌─────────────────┐
│ nrtMRVA.py      │
│                 │  Creates makebiccmd_*.m script
│                 │  Calls: l2p2bic(sensor,region,
│                 │         indir,bicdir,year,day,rewrite)
└────────┬────────┘
         │
         ↓
┌─────────────────┐
│ l2p2bic.m       │  Reads NetCDF from indir
│                 │  Writes BIC to bicdir
│                 │  Uses SensorTable() for config
└─────────────────┘
```

### Container Options

#### Option A: Minimal (Production-Like)
```bash
# Container only does l2p2bic processing
# User must download separately

# 1. Download externally (host or separate container)
podaac-data-subscriber -c AMSR2-REMSS-L2P-v8.2 ...

# 2. Process with container
docker run --rm \
  -v /downloads:/data/input \
  -v /output:/data/output \
  mur-l2p:latest \
  AMSR2R Global /data/input /data/output 2025 220 0
```

**Arguments:** sensor region indir bicdir year day rewrite

#### Option B: Integrated (Current)
```bash
# Container does download + processing

docker run --rm \
  -v ~/.netrc:/root/.netrc:ro \
  -v /data/input:/data/input \
  -v /data/output:/data/output \
  mur-l2p:latest \
  AMSR2R 2025 220 1
```

**Arguments:** sensor year doy download_flag
**Paths:** Hardcoded to /data/input and /data/output

#### Option C: Dual-Mode (Recommended)
```bash
# Mode 1: Like production - pass all paths explicitly
docker run --rm \
  -v /downloads:/mnt/l2p \
  -v /output:/mnt/bic \
  mur-l2p:latest \
  --mode production \
  --sensor AMSR2R \
  --region Global \
  --indir /mnt/l2p/AMSR2R \
  --outdir /mnt/bic/AMSR2R \
  --year 2025 \
  --day 220 \
  --rewrite 0

# Mode 2: Integrated - download + process
docker run --rm \
  -v ~/.netrc:/root/.netrc:ro \
  mur-l2p:latest \
  --mode integrated \
  --sensor AMSR2R \
  --year 2025 \
  --day 220 \
  --download
```

## Decision: Go with Simplified Production-Like Interface

**Rationale:**
1. Production uses `l2p2bic(sensor,region,indir,bicdir,year,day,rewrite)` - 7 args
2. Downloads handled separately in production (cron jobs)
3. Container should match production calling pattern
4. Downloads can be separate concern (user's choice)

**Recommended Container Interface:**

```bash
docker run --rm \
  -v /downloads:/data/input \
  -v /output:/data/output \
  mur-l2p:latest \
  AMSR2R Global /data/input/AMSR2R /data/output/AMSR2R 2025 220 0
```

**Arguments (match l2p2bic exactly):**
1. sensor - AMSR2R, MODISA, MODIST, AVMTBG
2. region - Global
3. indir - Input directory with L2P NetCDF files
4. bicdir - Output directory for BIC files
5. year - 2025
6. day - 220
7. rewrite - 0 or 1

**For downloads:**
User can:
- Use host with podaac-data-subscriber
- Use our provided download function as optional preprocessing step
- Create separate download container
- Use cron jobs (like production)

## What About config.json?

**Analysis of config.json usage:**

```json
{
    "AMSR2R": {
        "collection_name": ["AMSR2-REMSS-L2P-v8.2", "AMSR2-REMSS-L2P_RT-v8.2"],
        "region": "Global",
        "La": 2,
        "Lb": 8,
        "day_range": [12, 1],
        "stable": 2
    }
}
```

**Fields:**
- `collection_name` - Used for downloads only
- `region` - Passed as argument to l2p2bic
- `La, Lb` - Used in MRVA (not l2p2bic)
- `day_range` - Used in MRVA (not l2p2bic)
- `stable` - Used for rewrite logic

**Conclusion:** config.json was only used by `execute_l2p.py` test wrapper, not by production!

**Recommendation:** Remove config.json dependency. If downloads needed, embed collection mappings in download function.

## Final Recommendation

**Primary interface - matches production:**
```bash
docker run mur-l2p:latest SENSOR REGION INDIR OUTDIR YEAR DAY REWRITE
```

**Optional convenience wrapper for downloads:**
```bash
# Separate download script/container if needed
docker run mur-l2p-download:latest SENSOR YEAR DAY /output
```

**Result:**
- Clean separation of concerns
- Matches production exactly
- Downloads are optional/separate
- No config.json needed
