#!/usr/bin/env python3
"""Plot a geographic diff of two Global_ice .bip.gz files.

Reads each file's (icelon, icelat) arrays, classifies each cell as
shared / prod-only / container-only, and renders three plots:
  1. Global PlateCarree showing only the divergent cells (red=prod-only,
     blue=cont-only) with shared cells in faint gray for context.
  2. North polar projection (the Arctic ice edge).
  3. South polar projection (the Antarctic ice edge).
"""
import gzip
import struct
import sys
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

PROD = 'prod_data/Global_ice_2026_134.bip.gz'
CONT = 'container_data/Global_ice_2026_134.bip.gz'
OUT  = 'utils/global_ice_diff_134.png'


def parse_bip(path):
    with gzip.open(path, 'rb') as f:
        data = f.read()
    N = struct.unpack('<i', data[4:8])[0]
    off = 16
    lon = np.frombuffer(data[off:off+4*N], dtype='<f4'); off += 4*N
    lat = np.frombuffer(data[off:off+4*N], dtype='<f4'); off += 4*N
    return N, lon, lat


def main():
    Np, plon, plat = parse_bip(PROD)
    Nc, clon, clat = parse_bip(CONT)
    print(f'prod N={Np:,}  cont N={Nc:,}  delta={Nc-Np:+,}')

    # Use rounded (lon,lat) keys so float-precision noise doesn't bucket
    # near-duplicates as differences.  OSI-SAF polar-stereo grid cells are at
    # discrete coordinates, so equality after rounding to 0.001 deg is safe.
    pset = set(zip(np.round(plon, 3).tolist(), np.round(plat, 3).tolist()))
    cset = set(zip(np.round(clon, 3).tolist(), np.round(clat, 3).tolist()))
    shared = pset & cset
    only_p = pset - cset
    only_c = cset - pset
    print(f'shared={len(shared):,}  prod-only={len(only_p):,}  cont-only={len(only_c):,}')

    shared_arr = np.array(list(shared)) if shared else np.empty((0,2))
    p_only_arr = np.array(list(only_p)) if only_p else np.empty((0,2))
    c_only_arr = np.array(list(only_c)) if only_c else np.empty((0,2))

    fig = plt.figure(figsize=(16, 12))

    # --- Global PlateCarree ---
    ax = fig.add_subplot(2, 1, 1)
    if shared_arr.size:
        ax.scatter(shared_arr[:,0], shared_arr[:,1], s=0.15,
                   color='#c8c8c8', alpha=0.5, label=f'shared ({len(shared):,})')
    if p_only_arr.size:
        ax.scatter(p_only_arr[:,0], p_only_arr[:,1], s=1.4,
                   color='red', alpha=0.85, label=f'prod-only ({len(only_p):,})')
    if c_only_arr.size:
        ax.scatter(c_only_arr[:,0], c_only_arr[:,1], s=1.4,
                   color='blue', alpha=0.85, label=f'cont-only ({len(only_c):,})')
    ax.set_xlim(-180, 180); ax.set_ylim(-90, 90)
    ax.set_xlabel('Longitude'); ax.set_ylabel('Latitude')
    ax.set_aspect('equal')
    ax.set_title('Global_ice DOY 134 — ice-cell diff (prod vs container)\n'
                 'red = ice in prod but not container; blue = ice in container but not prod')
    ax.grid(True, alpha=0.3)
    ax.legend(loc='lower left', fontsize=9, markerscale=4)

    # --- North polar (lambert-like via subset) ---
    axN = fig.add_subplot(2, 2, 3)
    axN.set_title(f'Arctic (lat ≥ 55°N)')
    for arr, c, s, lbl in [(shared_arr, '#cccccc', 0.2, None),
                            (p_only_arr, 'red', 2.0, 'prod-only'),
                            (c_only_arr, 'blue', 2.0, 'cont-only')]:
        if arr.size:
            m = arr[:,1] >= 55
            if m.any():
                axN.scatter(arr[m,0], arr[m,1], s=s, color=c, alpha=0.85, label=lbl)
    axN.set_xlim(-180, 180); axN.set_ylim(55, 90)
    axN.set_xlabel('Longitude'); axN.set_ylabel('Latitude')
    axN.grid(True, alpha=0.3)
    axN.legend(loc='lower left', fontsize=8)

    # --- South polar ---
    axS = fig.add_subplot(2, 2, 4)
    axS.set_title(f'Antarctic (lat ≤ -55°S)')
    for arr, c, s, lbl in [(shared_arr, '#cccccc', 0.2, None),
                            (p_only_arr, 'red', 2.0, 'prod-only'),
                            (c_only_arr, 'blue', 2.0, 'cont-only')]:
        if arr.size:
            m = arr[:,1] <= -55
            if m.any():
                axS.scatter(arr[m,0], arr[m,1], s=s, color=c, alpha=0.85, label=lbl)
    axS.set_xlim(-180, 180); axS.set_ylim(-90, -55)
    axS.set_xlabel('Longitude'); axS.set_ylabel('Latitude')
    axS.grid(True, alpha=0.3)
    axS.legend(loc='upper left', fontsize=8)

    plt.tight_layout()
    plt.savefig(OUT, dpi=140, bbox_inches='tight')
    print(f'wrote {OUT}')

    # Print latitude-band breakdown for structural hints
    print()
    print('Latitude-band breakdown of divergent cells:')
    bands = [(-90,-70),(-70,-55),(-55,-30),(-30,30),(30,55),(55,70),(70,90)]
    print(f'  {"lat band":>14}  {"prod-only":>10}  {"cont-only":>10}')
    for lo, hi in bands:
        pcount = ((p_only_arr[:,1] > lo) & (p_only_arr[:,1] <= hi)).sum() if p_only_arr.size else 0
        ccount = ((c_only_arr[:,1] > lo) & (c_only_arr[:,1] <= hi)).sum() if c_only_arr.size else 0
        print(f'  [{lo:>4}, {hi:>4}]    {pcount:>10,}  {ccount:>10,}')


if __name__ == '__main__':
    main()
