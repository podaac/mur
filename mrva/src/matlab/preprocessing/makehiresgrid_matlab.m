
function outname=makehiresgrid(year,day,sensorlist, ...
                               bipdir,outname,hiressensorlist, ...
                               lon0,lat0,dlon,dlat,nlon,nlat)

if ~exist('bipdir','dir'), bipdir='./bip'; end;

if ~exist('outname','var'), 
  outname=sprintf('hiresdt_%04d_%03d.grd',year,day); 
end;

if ~exist('hiressensorlist','var'), 
  hiressensorlist={'MODISA','MODIST','VIIRSN','VIIRSO'};
end;

%% default values for lon0, lat0, dlon, dlat for GDS2 grid:
%%   from /home/tmchin/grids/maskGLOBp01deg.gds

if ~exist('lon0','var'), lon0=-179.99; end;
if ~exist('lat0','var'), lat0= -89.99; end;
if ~exist('dlon','var'), dlon=0.01; end;
if ~exist('dlat','var'), dlat=0.01; end;
if ~exist('nlon','var'), nlon=36000; end;
if ~exist('nlat','var'), nlat=17999; end;


%% initialize the grid as NaN:
none=-128;
grid = ones(nlon,nlat,'int8')*none;

%% find hires sensor list:
snx = find( ismember( sensorlist, hiressensorlist ) );

for s=snx(:)',

  biqfile=sprintf('%s/Global_%s_%04d_%03d.biq',bipdir,sensorlist{s},year,day);

  disp(sprintf('makehiresgrid reading %s',biqfile));
  [sst,lon,lat,hour]=readbiq(biqfile);
  
  %% find grid coordinates:
  inx=round((lon-lon0)/dlon)+1;
  knx=find(inx==0); inx(knx)=nlon;

  jnx=round((lat-lat0)/dlat)+1;

  %% QC the coordinate indices:
  knx=find(inx>=1&inx<=nlon&jnx>=1&jnx<=nlat);
  inx=inx(knx); jnx=jnx(knx);
  hour=hour(knx);

  %% gridding:
  for k=1:length(knx),

    if abs(grid(inx(k),jnx(k)))>abs(round(hour(k))),
      grid(inx(k),jnx(k))=round(hour(k)); 
    end;

  end;

end;

%% write file:
f=fopen(outname,'w');
fortwrite(f,'integer*4',nlon,'integer*4',nlat);
fortwrite(f,'integer*1',grid);
fclose(f);
