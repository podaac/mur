function writeiquambin(year,doy,lon,lat,sst,hour)

  %% detination directory:
  ddir='/nas2/iquam';

  %% subdirectory:
  edir=sprintf('/nas2/iquam/%04d',year);
  if ~exist(edir,'dir'), eval(sprintf('! mkdir -p %s',edir)); end;
  
  %% filename:  
  filename=sprintf('%s/Global_IQUAM0_%04d_%03d.bin',edir,year,doy);
  N=length(sst);
  f=fopen(filename,'w');
    if f==-1, error(['cannot write/open to ',filename]); end;
  fortwrite(f,'integer*4',year,'integer*4',doy,'integer*4',N);
  fortwrite(f,'real*4',lon,'real*4',lat,'real*4',sst,'real*4',hour);
  fclose(f);

