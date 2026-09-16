%% compscale.m
%% compare two scales of MUR, visually.

cspdir='/nas/ftp/mur_sst/tmchin/cyc4out';

%% scales to be compared:
L1=11;
L2=10;

%% domain:
box=[140,144,36,40];  % Tohoku
box=[120,144,20,40];  % Tohoku2
box=[-65,-50,37,44];  % Gulf Stream
box=[-60,-30,20,30];  % Sargasso Sea
box=[45    85   -47   -38];  % Agulhas
%box=[150  180    30    45]; % Kuroshio1
%box=[-180  -150    30    45]; % Kuroshio2
%box=[-180  -120     0    10];  % Tropical Pacific
%box=[-160  -130    30    50];  % US WestCoast

%% images resolution [degrees]:
res=0.01;


whichdays={
2012,270
2013,1:90:180
};


lon=box(1):res:box(2);
lat=box(3):res:box(4);

for daycounter=1:size(whichdays,1),
  year=whichdays{daycounter,1};
for doy=whichdays{daycounter,2},


  
  [dy,mn,yr]=julian(doy,year);
  datelabel=sprintf('%04d%02d%02d09',yr,mn,dy);
  cspfile1=sprintf('%s/%04d/%s_MRVA4_Global.c%02d',cspdir,yr,datelabel,L1);
  cspfile2=sprintf('%s/%04d/%s_MRVA4_Global.c%02d',cspdir,yr,datelabel,L2);

  disp(datelabel);

  sst2=samplecsp(cspfile2,lon,lat)-273.15;
  sst1=samplecsp(cspfile1,lon,lat)-273.15;

  fig 1; imagesc(lon,lat,sst1'); axis xy; cax=caxis;
  fig 2; imagesc(lon,lat,sst2'); axis xy; caxis(cax);

  fig 3; imagesc(lon,lat,sst1'-sst2'); axis xy; caxis([-1,1]*0.3);

  pause;

end;
end;


