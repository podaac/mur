function [sstcsp,sstbip,lon,lat]=compCspL4(cspfile,nccfile,LL)
%% evaluate csp values at (lon,lat) points of L4 file.

% nccfile examples:
%/store/ghrsst/open/data/L4/GLOB/REMSS/mw_ir_OI/2010/011/20100111-REMSS-L4HRfnd-GLOB-v01-fv02-mw_ir_OI.nc.gz
%/store/ghrsst/open/data/L4/GLOB/UKMO/OSTIA/2010/011/20100111-UKMO-L4HRfnd-GLOB-v01-fv02-OSTIA.nc.bz2
%/store/ghrsst/open/data/L4/GLOB/NCDC/AVHRR_AMSR_OI/2010/011/20100111-NCDC-L4LRblend-GLOB-v01-fv02_0-AVHRR_AMSR_OI.nc.bz2

% cspfile examples:
%/home/tmchin/nas/cyc2out/2010011109_MRVA3_Global.c11

if ~exist('LL','var'), LL=0; end;

%% read bipfile:

  disp(['reading ',nccfile]);
  switch nccfile(end-2:end),
    case 'bz2', eval(sprintf('! bzcat %s > tmpL4file.nc',nccfile));
    case '.gz', eval(sprintf('! zcat %s > tmpL4file.nc',nccfile));
  end;

  [sstbip,x,y]=readL4core('tmpL4file.nc'); [lon,lat]=ndgrid(x,y);
  delete('tmpL4file.nc');
  sstbip=sstbip(:); lon=lon(:); lat=lat(:);
  inx=find(~isnan(sstbip));
  sstbip=sstbip(inx); lon=lon(inx); lat=lat(inx);

  sstbip=sstbip-273.15;


%% filter data:
  if 1,
    inx=1:length(sstbip);

    % avoid polar:
      if 1, 
        jnx=find(lat(:)>=-60&lat(:)<=60);
        inx=intersect(inx(:),jnx(:));
      end;

    % pacific box:
      if 0, 
        jnx=find(lon(:)>=-180&lon(:)<-140&lat(:)>=-45&lat(:)<=45);
        inx=intersect(inx(:),jnx(:));
      end;

    if length(inx),
      lon=lon(inx);lat=lat(inx);sstbip=sstbip(inx);
    else,
      lon=[]; lat=[]; sstbip=[];
    end;
  end;


sstcsp=[];

for L=LL,
  disp(sprintf('L=%d',L));
  if L, cspfile(end-1:end)=sprintf('%02d',L); end;

%% setup csp (e.g. MUR coefficient) file for the "cbscoeff":
          eval(sprintf('! ln -sf %s cbsdata.out',cspfile));

          f=fopen('cbspoints.dat','w');
          nx=length(sstbip);
          fortwrite(f,'integer*4',[nx,-1,0,0]);
          fortwrite(f,'real*4',lon,'real*4',lat);
          fclose(f);


%% run "cbscoeff"
          % Container: Use fixed path to Fortran executables
          fortran_bin='/opt/mrva/bin';
%          eval(sprintf('! %s/cbscoeff',fortran_bin)); % execute spline.
          eval(sprintf('! %s/cbscxcoeff',fortran_bin)); % execute spline.
          f=fopen('cbs.out','r');
          sst=fortread(f,nx);
          fclose(f);
          ! rm -f cbspoints.dat cbs.out cbsdata.out

  sstcsp=[sstcsp,sst(:)];
end;
