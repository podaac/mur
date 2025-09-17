

mapdir0='/nas2/run4';  % where map files are
mapdir1='/nas2/run3';  % where map files are

pngflag=1;
if pngflag,
  pngdir='./out';
end;


mapbody='MUR_NCAMERICA_1km';  % main name for *.map file.
maptime0='000000Z'; maptime1='180000Z'; % [hhmmss] time range for buoy matchup.
idm=13501; jdm=8201;



whichdays={
%  2009,[10,30,70]
%  2008,[250,300,366]
%2008,92:366
2008,92:100
};


if pngflag,
  fig 1; set(gcf,'visible','off'); 
  if ~exist(pngdir,'dir'), mkdir(pngdir); end;
else,
  clf; 
end;



for daycounter=1:size(whichdays,1),
  year=whichdays{daycounter,1};
for day=whichdays{daycounter,2},




 [d,m,y]=julian(day,year);

        name=sprintf('%s/%d%02d%02dT%s',mapdir0,y,m,d,maptime0);
        name=sprintf('%s-%d%02d%02dT%s',name,y,m,d,maptime1);
        name=sprintf('%s-%s-%dx%d.map',name,mapbody,idm,jdm);
      name0=name;

        name=sprintf('%s/%d%02d%02dT%s',mapdir1,y,m,d,maptime0);
        name=sprintf('%s-%d%02d%02dT%s',name,y,m,d,maptime1);
        name=sprintf('%s-%s-%dx%d.map',name,mapbody,idm,jdm);
      name1=name;

  disp('reading .....');
  disp(name0);
    f=fopen(name0,'r');
    [ii,jj]=fortread(f,'int',1,'int',1);
    [t0,lon,lat]=fortread(f,[ii,jj],ii,jj);
    fclose(f);

  disp(name1);
    f=fopen(name1,'r');
    [ii,jj]=fortread(f,'int',1,'int',1);
    [t1,lon,lat]=fortread(f,[ii,jj],ii,jj);
    fclose(f);
  disp('..... done.');

  inx=find(t0>400); t0(inx)=NaN*ones(size(inx));
  seetmp(lon,lat,t1-t0,-1:0.25:1);

  if pngflag,
    [d,m,y]=julian(day,year);
        name=sprintf('%s/%d%02d%02dT%s',pngdir,y,m,d,maptime0);
        name=sprintf('%s-%d%02d%02dT%s',name,y,m,d,maptime1);
        name=sprintf('%s-%s-diff.png',name,mapbody);
    eval(sprintf('print -dpng -r150 %s',name));
  else,
    disp('ready: '); pause;
  end;

end;
end;
