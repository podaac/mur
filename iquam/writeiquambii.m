function writeiquambii(year,doy,lon,lat,sst,hour,pt)

  %% detination directory:
  ddir='/nas2/iquam';

  %% subdirectory:
  edir=sprintf('/nas2/iquam/%04d',year);
  if ~exist(edir,'dir'), eval(sprintf('! mkdir -p %s',edir)); end;
  
  %% filename:  
  filename=sprintf('%s/Global_IQUAM0_%04d_%03d.bii',edir,year,doy);
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

