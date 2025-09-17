function sst=samplecsp(cspfile,lon,lat)
% sst=samplecsp(cspfile,lon,lat)
% uses $home/util/spgrid to sample the given "cspfile"
% over the grid given by the vectors "lon" and "lat".
% "lon" can be given over [-180,180] or [0,360]



nlon=length(lon); nlat=length(lat);

outgridfile='outgrid.out';

badpixel=2;  % see filemod.f/outscaledgds (NOT USED).


% longitude adjustments:
inx=find(lon>180);
if length(inx), lon(inx)=lon(inx)-360; end;
  


% write into the filemod.f:outgrid format:
mask=ones(nlon,nlat,'int8');
%knx=find(isnan(sst)); if length(knx), mask(knx)=badpixel*ones(size(knx)); end;
f=fopen(outgridfile,'w');
  fortwrite(f,'integer',nlon,'integer',nlat);
  fortwrite(f,'int8',mask,'real*4',lon,'real*4',lat);
fclose(f);

% write spgrid.nml:
f=fopen('spgrid.nml','w');
  %fprintf(f,' $input\nsstoffset=273.150000\n');
  fprintf(f,' $input\noffset=298.15\nsscale=0.001\nminsst=271.35\n');
  fprintf(f,'nlist=1\ncoeffilelist=\n');
  fprintf(f,'''0'',''%s'',\n',cspfile);
  fprintf(f,'gridfile=\n''%s''\n $end\n',outgridfile);
  %fprintf(f,'outgridfile=\n''%s''\n $end\n',outgridfile);
fclose(f);

% run spgrid and get result:

%! ./spgrid;
! /home/tmchin/util/spgrid;


if 0,  % old spgrid style:
  f=fopen('fort.80','r');
    [ii,jj]=fortread(f,'int',1,'int',1);
    [sst,x,y]=fortread(f,[ii,jj],ii,jj);
  fclose(f);
else,
  f=fopen('fort.180','r');
    [ii,jj]=fortread(f,'int',1,'int',1);
    [offset,sscale]=fortread(f,'real*4',1,'real*4',1);
    [sst,x,y]=fortread(f,'integer*2',[ii,jj],'real*4',ii,'real*4',jj);
  fclose(f);
  sst=double(sst)*sscale+offset;
end;

% clean up:
delete(outgridfile);
delete('fort.180');
delete('spgrid.nml');

