function [icesstfile,landicefile]=makeicefiles(input_dir,output_dir,year,day,resolution)
%% makeicefile.m (modified from saf2bip.m)
%% -- reads OSI_SAF ice concentration data (both hemispheres).
%% -- produces daily *.bip file for ice sst, in "icesstfile".
%% -- produces/updates daily landmask and ice-con file, in "landicefile".

% % Cast dates to integers
% year = int32(str2double(year))
% day = int32(str2double(day))

% Print arugments
fprintf(1, 'makeicefiles: input_dir - %s\n', input_dir);
fprintf(1, 'makeicefiles: output_dir - %s\n', output_dir);
fprintf(1, 'makeicefiles: year - %s\n', year);
fprintf(1, 'makeicefiles: day - %s\n', day);
fprintf(1, 'makeicefiles: resolution - %s\n', resolution);


if ~exist('resolution','var'), resolution='p01'; end;


%% parameter:

minice = 30;    % [%] minimum ice conc value below which samples are ignored.
icesst = -1.8;  % [C] SST value for the ice water.
wgtmax = 5.0;   % max weight (given for 100% ice concentration).


% landmaskfile: landmask file that requires addition of ice flags.
% gridinxnorth, gridinxsouth: map particular ice data sets to landmask grid.
% odir: output file directory.
% landicefile: updated landmaskfile (output #1)
% icesstfile: SST data file based on ice conc data (output #2)

% NOTE: (lon,lat)'s of landmask must match gridinxnorth/south indeces,
% e.g., see saf2north.m and saf2south.m

switch resolution,

  case 'p11',
    landmaskfile = append(input_dir, '/grids/maskGlob1km.gds');
    gridinxnorth = append(input_dir, '/mat/p11/saf2north');
    gridinxsouth = append(input_dir, '/mat/p11/saf2south');
    odir = append(output_dir, '/land/p11/', year);  % output dir.
    landicefile = append(odir, '/landice_', year, '_', day, '.gds')
    icesstfile = append(odir, '/Global_ice_', year, '_', day, '.bip')

    lastMJD_reprocessed=julian(31,12,2006,3);  % for OSI-SAF data.
    lastMJD_archive=inf;    % for OSI_SAF data.

  case 'p01',

    landmaskfile = append(input_dir, '/grids/maskGLOBp01deg.gds');
    gridinxnorth = append(input_dir, '/mat/p01/saf2north');
    gridinxsouth = append(input_dir, '/mat/p01/saf2south');
    odir = append(output_dir, '/land/p01/', year);  % output dir.
    landicefile = append(odir, '/landiceP01_', year, '_', day, '.gds')
    icesstfile = append(odir, '/Global_ice_', year, '_', day, '.bip')

    lastMJD_reprocessed=julian(31,12,2008,3);  % for OSI-SAF data.
    lastMJD_archive=inf;    % for OSI_SAF data.

  otherwise,
    error('no such "resolution" (text) value.');

end;

icefiles_odir = append(output_dir, '/ice/', year);  % output dir.

% Print variables set by case
fprintf(1, 'makeicefiles: landmaskfile - %s\n', landmaskfile);
fprintf(1, 'makeicefiles: gridinxnorth - %s\n', gridinxnorth);
fprintf(1, 'makeicefiles: gridinxsouth - %s\n', gridinxsouth);
fprintf(1, 'makeicefiles: odir - %s\n', odir);
fprintf(1, 'makeicefiles: landicefile - %s\n', landicefile);
fprintf(1, 'makeicefiles: icesstfile - %s\n', icesstfile);
fprintf(1, 'makeicefiles: icefiles_odir - %s\n', icefiles_odir);


%%% only for testing:
if 0,
  switch resolution,
  case 'p11',
    gridinxnorth = append(input_dir, '/ice/saf2north');
    gridinxsouth = append(input_dir, '/ice/saf2south');
    odir = append(output_dir, '/land/p11/', year);  % output dir.
    landicefile=sprintf('%s/landice_%04d_%03d.gds',odir,year,day);
    icesstfile=sprintf('%s/Global_ice_%04d_%03d.bip',odir,year,day);
  case 'p01',
    odir = append(output_dir, '/land/p01/', year);  % output dir.
    landicefile = sprintf('%s/landiceP01_%04d_%03d.gds',odir,year,day);
    icesstfile = sprintf('%s/Global_ice_%04d_%03d.bip',odir,year,day);
  end;
end;
%%% only for testing [end]


%% check target(output) directory:

if ~exist(odir,'dir'), eval(sprintf('!mkdir -p %s',odir)); end;
if ~exist(icefiles_odir,'dir'), eval(sprintf('!mkdir -p %s',icefiles_odir)); end;

if 0,  % if set, no rewrite
  %% check to see if output files exist:
  landicefilegz=[landicefile,'.gz'];
  icesstfilegz=[icesstfile,'.gz'];
  if exist(landicefilegz,'file')&exist(icesstfilegz,'file'),
    fprintf(1,'LAND/ICE FILES EXIST ALREADY:\n');
    fprintf(1,'  %s\n  %s\n',landicefilegz,icesstfilegz);
    fprintf(1,'... NOT WRITING.\n');
    landicefile=[]; icesstfile=[]; return;
  end;
end;


%%%%%%%%%%

%% landmask data:
fprintf(1,'makeicefiles: loading %s\n',landmaskfile);
f=fopen(landmaskfile,'r');
[ii,jj]=fortread(f,'int',1,'int',1);
[mask,mlon,mlat]=fortread(f,'integer*1',[ii,jj],'real*4',ii,'real*4',jj);
fclose(f);

%% initialize icemap:
icemap=ones(size(mask),'int8')*(-1);  % integer [0,100]; badvalue = -1.

%% read ice concentration data [in %]:

% desired outputs -> icelon, icelat, icecon
icelon=[]; icelat=[]; icecon=[];

% north hemisphere:
[ice,lon,lat] = readosisafice('nh',year,day,lastMJD_reprocessed,lastMJD_archive,icefiles_odir);

if length(ice(:))==0,
  fprintf(1,'makeicefiles: bad/no north data on %04d/%03d\n',year,day);
  fprintf(1,'..... aborting\n');  quit;
end;

inx=find(ice<minice | ice>100);
if length(inx), ice(inx)=ones(size(inx))*(-1); end;

if 1,  % fix "no data" at the pole:
  inx=find(lat>=87.7 & ice==-1);
  if length(inx), ice(inx)=ones(size(inx))*100; end;
end;

fprintf(1,'makeicefiles: loading %s\n',gridinxnorth);
load( gridinxnorth );  % --> gridinx, iceinx.
icemap(gridinx) = ice(iceinx);

inx=find(ice>0);
if length(inx), 
  icelon=[icelon;lon(inx)]; 
  icelat=[icelat;lat(inx)]; 
  icecon=[icecon;ice(inx)];
end;

% south hemisphere:
[ice,lon,lat] = readosisafice('sh',year,day,lastMJD_reprocessed,lastMJD_archive,icefiles_odir);

if length(ice(:))==0,
  fprintf(1,'makeicefiles: bad/no south data on %04d/%03d\n',year,day);
  fprintf(1,'..... aborting\n');  quit;
end;

inx=find(ice<minice | ice>100);
if length(inx), ice(inx)=ones(size(inx))*(-1); end;

fprintf(1,'makeicefiles: loading %s\n',gridinxsouth);
load( gridinxsouth );  % --> gridinx, iceinx.
icemap(gridinx) = ice(iceinx);

inx=find(ice>0);
if length(inx), 
  icelon=[icelon;lon(inx)]; 
  icelat=[icelat;lat(inx)]; 
  icecon=[icecon;ice(inx)];
end;


%% update and write landmask:

knx=find(icemap>0 & mask==1);
  if length(knx), mask(knx)=9*ones(size(knx),'int8'); end;
knx=find(icemap>0 & mask==3);
  if length(knx), mask(knx)=11*ones(size(knx),'int8'); end;
knx=find(icemap>0 & mask==5);
  if length(knx), mask(knx)=13*ones(size(knx),'int8'); end;


fprintf(1,'makeicefiles: writing %s\n',landicefile);
f=fopen(landicefile,'w');
fortwrite(f,'int',length(mlon),'int',length(mlat));
fortwrite(f,'integer*1',mask,'real*4',mlon,'real*4',mlat);
fortwrite(f,'integer*1',icemap);
fclose(f);

%  eval(sprintf('! gzip -f %s',landicefile));
%  landicefile=[landicefile,'.gz'];


%% write bip file:

sst = icesst*ones(size(icecon));  % set SST to a given constant.
wgt = wgtmax*icecon/100;  % weight is a mapping of icecon.
dhr = zeros(size(icecon));
N = length(icecon);

fprintf(1,'makeicefiles: writing %s\n',icesstfile);
f=fopen(icesstfile,'w');
fortwrite(f,'integer*4',N);
fortwrite(f,icelon,icelat,dhr,sst,wgt);
fclose(f);
