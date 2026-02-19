function writeiquambii(year,doy,lon,lat,sst,hour,pt,basedir)
% writeiquambii - Write IQUAM buoy data to binary .bii format
%
% USAGE:
%   writeiquambii(year, doy, lon, lat, sst, hour, pt, basedir)
%
% INPUTS:
%   year    - Year (e.g., 2024)
%   doy     - Day of year (1-366)
%   lon     - Longitude array (decimal degrees)
%   lat     - Latitude array (decimal degrees)
%   sst     - Sea surface temperature (Celsius)
%   hour    - Hour of day (decimal, 0-24)
%   pt      - Platform type (integer code)
%   basedir - Base output directory (optional, default: './output/iquam')
%
% OUTPUT FILE:
%   <basedir>/YYYY/Global_IQUAM0_YYYY_DDD.bii
%
% FILE FORMAT:
%   Binary file with Fortran-style record markers
%   Header: N (int32), year (int16), doy (int16)
%   Data: sst, lon, lat, hour (all int16, scaled ×100), pt (int8)

  %% destination directory:
  if ~exist('basedir','var') || isempty(basedir)
      basedir = './output/iquam';
  end

  %% subdirectory:
  edir = sprintf('%s/%04d', basedir, year);
  if ~exist(edir,'dir'), mkdir(edir); end;

  %% filename:
  filename = sprintf('%s/Global_IQUAM0_%04d_%03d.bii', edir, year, doy);
  f=fopen(filename,'w');
    if f==-1, error(['cannot write/open to ',filename]); end;

  %% data conversion:
  N=length(sst(:));
  sst=int16(sst*100);
  lon=int16(lon*100);
  lat=int16(lat*100);
  hour=int16(hour*100);
  pt=int8(pt);

  %% write
  fortwrite(f,'int32',N,'int16',year,'int16',doy);
  fortwrite(f,'int16',sst,'int16',lon,'int16',lat,'int16',hour,'int8',pt);
  fclose(f);

%%% pt (platform type) =
%  0: Unknown;
%  1: Ship;
%  2: Drifting Buoy;
%  3: Open-sea Moored Buoy;
%  4: Coastal Moored Buoy;
%  5: Station.

