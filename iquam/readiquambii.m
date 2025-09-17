function [lon,lat,sst,hour,pt]=readbii(biifile)
% readbii - Read IQUAM binary .bii file with optimized direct fread
%
% Replaces fortread with direct fread calls using type specifications
% to avoid unnecessary double conversion and reduce memory usage.

      f=fopen(biifile,'r');

      % Read Fortran record header (byte count)
      m = fread(f, 1, 'uint32');

      % Read header: N (int32), nyear (int16), nday (int16)
      N = fread(f, 1, 'int32');
      nyear = fread(f, 1, 'int16');
      nday = fread(f, 1, 'int16');

      % Read Fortran record trailer and verify
      n = fread(f, 1, 'uint32');
      if m ~= n
          error('readbii: Fortran record size mismatch in header');
      end

      % Read Fortran record header for data arrays
      m = fread(f, 1, 'uint32');

      % Read data arrays directly as single precision with scaling
      % Using int16=>single to read as int16 and output as single in one step
      sst = fread(f, N, 'int16=>single') / 100;  % Celsius
      lon = fread(f, N, 'int16=>single') / 100;  % Degrees
      lat = fread(f, N, 'int16=>single') / 100;  % Degrees
      hour = fread(f, N, 'int16=>single') / 100;  % Hours
      pt = fread(f, N, 'int8=>int8');  % Platform type (keep as int8)

      % Read Fortran record trailer and verify
      n = fread(f, 1, 'uint32');
      if m ~= n
          error('readbii: Fortran record size mismatch in data arrays');
      end

      fclose(f);


%%%%% pt (Platform Type) %%%%%

%% for iQuam (v.2.10):
% 1: Ship; 
% 2: Drifting Buoy;
% 3: Tropical Moored Buoy;
% 4: Coastal Moored Buoy;
% 5: Argo Float;
% 6: High Resolution Drifter;
% 7: IMOS;
% 8: CRW Buoy;
% 9+: Reserved.
% Note: only type 1,2,3,4,5,6,7,8 are QCed." ;

%% for iQuam (v.2.00):
% 0: Unknown;
% 1: Ship;
% 2: Drifting Buoy;
% 3: Tropical Moored Buoy;
% 4: Coastal Moored Buoy;
% 5: Argo Float;
% 6: High Resolution Drifter;
% 7: IMOS;
% 8: CRW Buoy;
% 9+: Reserved.
% Note: only type 1,2,3,4,5,6,7,8 are QCed." ;

%% for IQUAM (old):
%  0: Unknown;
%  1: Ship;
%  2: Drifting Buoy;
%  3: Open-sea Moored Buoy;
%  4: Coastal Moored Buoy;
%  5: Station.

%% for ICOADS:
%    0 ­ US Navy or "deck" log, or unknown
%    1 ­ merchant ship or foreign military
%    2 ­ ocean station vessel--off station or station proximity unknown
%    3 ­ ocean station vessel--on station
%    4 ­ lightship
%    5 ­ ship
%    6 ­ moored buoy
%    7 ­ drifting buoy
%    8 ­ ice buoy [note: currently unused]
%    9 ­ ice station (manned, including ships overwintering in ice)
%   10 ­ oceanographic station data (bottle and low-resolution CTD/XCTD data)
%   11 ­ mechanical/digital/micro bathythermograph (MBT)
%   12 ­ expendable bathythermograph (XBT)
%   13 ­ Coastal-Marine Automated Network (C-MAN) (NDBC operated)
%   14 ­ other coastal/island station
%   15 ­ fixed ocean platform (plat, rig)
%   16 ­ tide gauge
%   17 ­ high-resolution Conductivity-Temp.-Depth (CTD)/Expendable CTD (XCTD)
%   18 ­ profiling float
%   19 ­ undulating oceanographic recorder
%   20 ­ autonomous pinneped bathythermograph
%   21 ­ glider
%        Background: PT settings 0-4 are derived from the
%        "OSV or Ship Indicator" in NCDC (1968);
%        PT settings 0-1 are very poorly documented and probably should
%        be regarded as equivalent to ship data (PT=5).


