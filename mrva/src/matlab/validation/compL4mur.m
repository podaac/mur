function [stat,sst,mur,lon,lat]=compL4mur(ncfile,murcoeffile,box)
% [stat,L4sst,MURsst]=compL4mur(ncfile,murcoeffile,box)
% compares L4 file against MUR coefficient file within the lon-lat "box".
% "stat" is difference statistics (mean,std,max,min).

% example:
%ncfile='/store/ghrsst/public/data/L4/GLOB/NCDC/AVHRR_AMSR_OI/2009/030/20090130-NCDC-L4LRblend-GLOB-v01-fv02_0-AVHRR_AMSR_OI.nc';
%ncfile='/store/ghrsst/public/data/L4/GLOB/REMSS/mw_ir_OI/2009/030/20090130-REMSS-L4HRfnd-GLOB-v01-fv02-mw_ir_OI.nc';
%ncfile='/store/ghrsst/public/data/L4/GLOB/UKMO/OSTIA/2009/030/20090130-UKMO-L4HRfnd-GLOB-v01-fv02-OSTIA.nc';

%murcoeffile='/nas2/mrva0out/2009013009-JPL-L4-SSTfnd-MUR_NCAMERICA-fv00.c10';

%box=[-165.,  -30., -20., 62.];

%badpixel=999.;  % see filemod.f/outgrid.
badpixel=2;  % see filemod.f/outscaledgds.


% read L4 file:
[sst,lon,lat]=readL4(ncfile);

% cut a box from L4 sst:

if exist('box','var'), if length(box)==4,
    inx=find(lon>=box(1) & lon<=box(2));
    jnx=find(lat>=box(3) & lat<=box(4));

    lon=lon(inx);
    lat=lat(jnx);
    sst=sst(inx,jnx);
end; end;


if 0,  % visualize the L4 box:
  imagesc(lon,lat,sst'); axis xy; axis image; colorbar horiz;
end;

% write into the filemod.f:outgrid format:
outgridfile='outgrid.out';
mask=ones(size(sst),'int8');
knx=find(isnan(sst)); if length(knx), mask(knx)=badpixel*ones(size(knx)); end;
f=fopen(outgridfile,'w');
  fortwrite(f,'integer',length(lon),'integer',length(lat));
  fortwrite(f,'int8',mask,'real*4',lon,'real*4',lat);
fclose(f);

% write spgrid.nml:
f=fopen('spgrid.nml','w');
  %fprintf(f,' $input\nsstoffset=273.150000\n');
  fprintf(f,' $input\noffset=298.15\nsscale=0.001\nminsst=271.35\n');
  fprintf(f,'nlist=1\ncoeffilelist=\n');
  fprintf(f,'''0'',''%s'',\n',murcoeffile);
  fprintf(f,'gridfile=\n''%s''\n $end\n',outgridfile);
  %fprintf(f,'outgridfile=\n''%s''\n $end\n',outgridfile);
fclose(f);

% run spgrid and get result:

! ./spgrid;

if 0,  % old spgrid style:
  f=fopen('fort.80','r');
    [ii,jj]=fortread(f,'int',1,'int',1);
    [mur,x,y]=fortread(f,[ii,jj],ii,jj);
  fclose(f);
else,
  f=fopen('fort.180','r');
    [ii,jj]=fortread(f,'int',1,'int',1);
    [offset,sscale]=fortread(f,'real*4',1,'real*4',1);
    [mur,x,y]=fortread(f,'integer*2',[ii,jj],'real*4',ii,'real*4',jj);
  fclose(f);
  mur=double(mur)*sscale+offset;
end;

% find stat:
if 0,  % visualize the difference field:
  imagesc(lon,lat,sst'-mur'); axis xy; axis image; colorbar horiz;
end;

knx=find(~isnan(sst));
d=sst(knx)-mur(knx);
stat=[mean(d),std(d),max(d),min(d)];

