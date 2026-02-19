
function outname=makehiresgrid(year,day,sensorlist, ...
                               bipdir,outname,hiressensorlist, ...
                               lon0,lat0,dlon,dlat,nlon,nlat)

% Container path mapping
grddir = '/data/cache/grd';  % result destination (container path)
fortran_bin = '/opt/mrva/bin';  % Fortran executables location

% Ensure grddir exists
if ~exist(grddir, 'dir'), mkdir(grddir); end

if ~exist('bipdir','var'), bipdir='/data/cache/bip'; end;

if ~exist('outname','var'), 
  %outname=sprintf('hiresdt_%04d_%03d.grd',year,day); 
  outname=sprintf('%s/hiresdt_%04d_%03d.grd',grddir,year,day); 
end;

if exist( outname, 'file' ), return; end;

%%disp(['creating: ',hiresgridfile]);
disp(['creating: ',outname]);

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



%% find hires sensor list:
snx = find( ismember( sensorlist, hiressensorlist ) );

%% write namelist file:
f=fopen('makehiresgrid.nml','w');
fprintf(f,' $input\n');
fprintf(f,'lon0=%.7f\nlat0=%.7f\n',lon0,lat0);
fprintf(f,'dlon=%.7f\ndlat=%.7f\n',dlon,dlat);
fprintf(f,'nlon=%d\nnlat=%d\n',nlon,nlat);
fprintf(f,'nbiqfile=%d\n',length(snx));
fprintf(f,'biqfiles=\n');
for s=snx(:)',
  biqfile=sprintf('%s/Global_%s_%04d_%03d.biq',bipdir,sensorlist{s},year,day);
  fprintf(f,'''%s'',\n',biqfile);
end;
fprintf(f,'outfile=\n');
fprintf(f,'''%s'',\n',outname);
fprintf(f,' $end\n');
fclose(f);

%% run the fortran code (faster than makehiresgrid_matlab.m):
system([fortran_bin, '/makehiresgrid']);


