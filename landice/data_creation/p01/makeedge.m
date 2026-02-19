%% makeedge.m
%% make cylinder edge data file (a bip format).

filepath='CylinderP01_edge.bip';

%% parameter:
%icesst=-1.8+273.15;  % SST value for the ice water.
icesst=-1.8;  % SST value for the ice water.
wgtmax=100.;  % max weight.



%% grid:
d=0.05;
lon=-180:d:180;
lat=[-95:d:(-89-d),(89+d):d:95];

[Lon,Lat]=ndgrid(lon,lat);
Lon=Lon(:); Lat=Lat(:);


%% write bip file:
  sst=icesst*ones(size(Lon));
  wgt=wgtmax*ones(size(Lon));
  dhr=zeros(size(Lon));
  N=length(Lon);

  fprintf(1,'makeedge: writing %s\n',filepath);
  f=fopen(filepath,'w');
  fortwrite(f,'integer*4',N);
  fortwrite(f,Lon,Lat,dhr,sst,wgt);
  fclose(f);

