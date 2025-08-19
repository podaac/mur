function [lon,lat,sst,hour,pt]=readbii(biifile)


      f=fopen(biifile,'r');
      [N,nyear,nday]=fortread(f,'int32',1,'int16',1,'int16',1);
      [sst,lon,lat,hour,pt]=fortread(f,'int16',N,'int16',N,'int16',N,...
                                     'int16',N,'int8',N);
      fclose(f);

      sst=single(sst)/100;  % Celcius.
      lon=single(lon)/100;
      lat=single(lat)/100;
      hour=single(hour)/100;


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


