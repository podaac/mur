function [icesstfile,landicefile]=makeicefiles(input_dir,output_dir,year,day,resolution)
%% makeicefile.m (modified from saf2bip.m)
%% -- reads OSI_SAF ice concentration data (both hemispheres).
%% -- produces daily *.bip file for ice sst, in "icesstfile".
%% -- produces/updates daily landmask and ice-con file, in "landicefile".
%%
%% LAND/ICE MASK ENCODING:
%% =======================
%% This function modifies the static land mask by adding ice flags where
%% OSI-SAF ice concentration > 0%. The mask uses bitwise flag encoding:
%%
%% BASE VALUES (from static mask file):
%%   1 (0001b) = Open sea (bit 0)
%%   2 (0010b) = Land (bit 1)
%%   3 (0011b) = Coast/shore (bits 0+1) - simplified to 2 in final NetCDF
%%   5 (0101b) = Open lake (bits 0+2)
%%   7 (0111b) = Lake shore (bits 0+1+2) - simplified to 2 in final NetCDF
%%
%% ICE MODIFICATION (when ice concentration > 0%):
%%   Adds bit 3 (value 8) to base mask:
%%   1 → 9  (1001b) = Open sea with ice
%%   3 → 11 (1011b) = Coast with ice - simplified to 2 in final NetCDF
%%   5 → 13 (1101b) = Open lake with ice
%%
%% FINAL NetCDF OUTPUT VALUES (after csp2nc4a.m simplification):
%%   1  = Open sea (no ice)
%%   2  = Land (including all coastal variants)
%%   5  = Open lake (no ice)
%%   9  = Open sea with ice
%%   13 = Open lake with ice
%%

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

% Ensure day is zero-padded to 3 digits for consistent file naming
day = sprintf('%03d', str2double(day));


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

  case 'p011',
    landmaskfile = append(input_dir, '/grids/maskGlob1km.gds');
    gridinxnorth = append(input_dir, '/mat/p011/saf2north');
    gridinxsouth = append(input_dir, '/mat/p011/saf2south');
    odir = append(output_dir, '/land/p011/', year);  % output dir.
    icefiles_odir = odir;  % icefiles.txt goes in same dir as GDS for container mapping
    landicefile = append(odir, '/landice_', year, '_', day, '.gds')
    icesstfile = append(odir, '/Global_ice_', year, '_', day, '.bip')

    % OSI-SAF reprocessing cutoff date for p011 grid (0.011 degrees)
    % Dates <= 2006-12-31 use reprocessed data (reproc files)
    % Dates >  2006-12-31 use archive/production data (multi files)
    lastMJD_reprocessed=julian(31,12,2006,3);  % for OSI-SAF data.
    lastMJD_archive=inf;    % for OSI_SAF data.

  case 'p01',

    landmaskfile = append(input_dir, '/grids/maskGLOBp01deg.gds');
    gridinxnorth = append(input_dir, '/mat/p01/saf2north');
    gridinxsouth = append(input_dir, '/mat/p01/saf2south');
    odir = append(output_dir, '/land/p01/', year);  % output dir.
    icefiles_odir = odir;  % icefiles.txt goes in same dir as GDS for container mapping
    landicefile = append(odir, '/landiceP01_', year, '_', day, '.gds')
    icesstfile = append(odir, '/Global_ice_', year, '_', day, '.bip')

    % OSI-SAF reprocessing cutoff date for p01 grid
    % Dates <= 2008-12-31 use reprocessed data (reproc files)
    % Dates >  2008-12-31 use archive/production data (multi files)
    lastMJD_reprocessed=julian(31,12,2008,3);  % for OSI-SAF data.
    lastMJD_archive=inf;    % for OSI_SAF data.

  otherwise,
    error('no such "resolution" (text) value.');

end;

% Print variables set by case
fprintf(1, 'makeicefiles: landmaskfile - %s\n', landmaskfile);
fprintf(1, 'makeicefiles: gridinxnorth - %s\n', gridinxnorth);
fprintf(1, 'makeicefiles: gridinxsouth - %s\n', gridinxsouth);
fprintf(1, 'makeicefiles: odir - %s\n', odir);
fprintf(1, 'makeicefiles: landicefile - %s\n', landicefile);
fprintf(1, 'makeicefiles: icesstfile - %s\n', icesstfile);
fprintf(1, 'makeicefiles: icefiles_odir - %s\n', icefiles_odir);

% Log reprocessing date threshold for this resolution
[reprocess_day, reprocess_month, reprocess_year] = julian(lastMJD_reprocessed);
fprintf(1, 'makeicefiles: OSI-SAF reprocessing cutoff for %s grid: %04d-%02d-%02d (MJD=%d)\n', ...
    resolution, reprocess_year, reprocess_month, reprocess_day, lastMJD_reprocessed);


%% check target(output) directory:

if ~exist(odir,'dir'), mkdir(odir); end;
if ~exist(icefiles_odir,'dir'), mkdir(icefiles_odir); end;

%%%%%%%%%%

%% landmask data:
fprintf(1,'makeicefiles: loading %s\n',landmaskfile);
f=fopen(landmaskfile,'r');
if f == -1
    error('makeicefiles: Cannot open landmask file: %s', landmaskfile);
end
fprintf(1,'makeicefiles: file opened successfully\n');
% Read Fortran record with dimensions
record_header = fread(f, 1, 'uint32=>uint32');
ii = fread(f, 1, 'int32=>int32');
jj = fread(f, 1, 'int32=>int32');
record_trailer = fread(f, 1, 'uint32=>uint32');
fprintf(1,'makeicefiles: grid dimensions read: ii=%d, jj=%d\n', ii, jj);
% Read Fortran record with mask and coordinates
record_header = fread(f, 1, 'uint32=>uint32');
mask = fread(f, [ii,jj], 'int8=>int8');
mlon = fread(f, ii, 'single=>single');
mlat = fread(f, jj, 'single=>single');
record_trailer = fread(f, 1, 'uint32=>uint32');
fprintf(1,'makeicefiles: mask data loaded successfully\n');
fclose(f);

%% initialize icemap:
icemap=ones(size(mask),'int8')*(-1);  % integer [0,100]; badvalue = -1.

%% read ice concentration data [in %]:

% desired outputs -> icelon, icelat, icecon
icelon=[]; icelat=[]; icecon=[];

% north hemisphere:
[ice,lon,lat] = readosisafice('nh',year,day,lastMJD_reprocessed,lastMJD_archive,icefiles_odir);

if length(ice(:))==0,
  error('makeicefiles: bad/no north data on %04d/%03d - aborting', year, day);
end;

% TODO: investigate why "ice" is a single, but the legacy code tried to
% insert a int8

% Label all "non-ice" data with -1 in the ice data matrix
% Assuming above 100% indicates an error
ice(ice<minice | ice>100) = -1;

% Now correct the mask at the poles for "non data"
ice(lat>=87.7 & ice==-1) = 100;

% % Legacy Code
% inx=find(ice<minice | ice>100);
% if length(inx), ice(inx)=int8(ones(size(inx))*(-1)); end;
% 
% if 1,  % fix "no data" at the pole:
%   inx=find(lat>=87.7 & ice==-1);
%   if length(inx), ice(inx)=int8(ones(size(inx))*100); end;
% end;

fprintf(1,'makeicefiles: loading %s\n',gridinxnorth);
load( gridinxnorth, 'gridinx', 'iceinx' );  % --> gridinx, iceinx.
icemap(gridinx) = ice(iceinx);


% Generate nx1 vectors the lat,lon,concentration where ice is found
ice_msk = ice>0;
icelon = reshape(lon(ice_msk), [], 1);
icelat = reshape(lat(ice_msk), [], 1);
icecon = reshape(ice(ice_msk), [], 1);

% % Legacy Code
% inx=find(ice>0);
% % TODO: Don't loop this to grow the matrix
% if length(inx), 
%   icelon=[icelon;lon(inx)]; 
%   icelat=[icelat;lat(inx)]; 
%   icecon=[icecon;ice(inx)];
% end;

% south hemisphere:
[ice,lon,lat] = readosisafice('sh',year,day,lastMJD_reprocessed,lastMJD_archive,icefiles_odir);

%if length(ice(:))==0,
if isempty(ice)
  error('makeicefiles: bad/no south data on %04d/%03d - aborting', year, day);
end

% Label non-ice
%inx=find(ice<minice | ice>100);
%if length(inx), ice(inx)=int8(ones(size(inx))*(-1)); end;
ice(ice<minice | ice>100) = -1;

fprintf(1,'makeicefiles: loading %s\n',gridinxsouth);
load( gridinxsouth, 'gridinx', 'iceinx');  % --> gridinx, iceinx.
icemap(gridinx) = ice(iceinx);

%Add to existing vectors
ice_msk = ice>0;
num_ice = nnz(ice_msk);

% inx first time is [70504 x 1]
% inx second time is [143464x1]
if num_ice>0
    icelon(end+1:end+num_ice, 1) = lon(ice_msk);
    icelat(end+1:end+num_ice, 1) = lat(ice_msk);
    icecon(end+1:end+num_ice, 1) = ice(ice_msk);
end

% inx=find(ice>0);
% if length(inx), 
%   icelon=[icelon;lon(inx)]; 
%   icelat=[icelat;lat(inx)]; 
%   icecon=[icecon;ice(inx)];
% end;


%% update and write landmask:

% Label, the mask (int8) with new values based on ice labels
% knx=find(icemap>0 & mask==1);
%   if length(knx), mask(knx)=9*ones(size(knx),'int8'); end;
% knx=find(icemap>0 & mask==3);
%   if length(knx), mask(knx)=11*ones(size(knx),'int8'); end;
% knx=find(icemap>0 & mask==5);
%   if length(knx), mask(knx)=13*ones(size(knx),'int8'); end;

% Not sure what these values mean, but the old code basically increased the
% value of mask by 8 anywhere there was ice
icemap_msk = icemap>0;
% mask(icemap_msk) = mask(icemap_msk)+8;
% Turns out there were values of mask where icemap was >0 that should 
% not have been increased (e.g. a value of 7)
mask(icemap_msk & mask==1) = 9;
mask(icemap_msk & mask==3) = 11;
mask(icemap_msk & mask==5) = 13;


fprintf(1,'makeicefiles: writing %s\n',landicefile);
f=fopen(landicefile,'w');
% Write Fortran record with dimensions
record_size = 4 + 4;  % 2 int32s
fwrite(f, record_size, 'uint32');
fwrite(f, int32(length(mlon)), 'int32');
fwrite(f, int32(length(mlat)), 'int32');
fwrite(f, record_size, 'uint32');
% Write Fortran record with mask and coordinates
record_size = numel(mask)*1 + numel(mlon)*4 + numel(mlat)*4;
fwrite(f, record_size, 'uint32');
fwrite(f, mask, 'int8');
fwrite(f, mlon, 'single');
fwrite(f, mlat, 'single');
fwrite(f, record_size, 'uint32');
% Write Fortran record with icemap
record_size = numel(icemap)*1;
fwrite(f, record_size, 'uint32');
fwrite(f, icemap, 'int8');
fwrite(f, record_size, 'uint32');
fclose(f);

%  eval(sprintf('! gzip -f %s',landicefile));
%  landicefile=[landicefile,'.gz'];


%% write bip file:

sst = single(icesst*ones(size(icecon)));  % set SST to a given constant.
wgt = single(wgtmax*icecon/100);  % weight is a mapping of icecon.
dhr = single(zeros(size(icecon)));
N = length(icecon);

fprintf(1,'makeicefiles: writing %s\n',icesstfile);
f=fopen(icesstfile,'w');
% Write Fortran record with N
record_size = 4;  % 1 int32
fwrite(f, record_size, 'uint32');
fwrite(f, int32(N), 'int32');
fwrite(f, record_size, 'uint32');
% Write Fortran record with data arrays
record_size = numel(icelon)*4 + numel(icelat)*4 + numel(dhr)*4 + numel(sst)*4 + numel(wgt)*4;
fwrite(f, record_size, 'uint32');
fwrite(f, single(icelon), 'single');
fwrite(f, single(icelat), 'single');
fwrite(f, dhr, 'single');
fwrite(f, sst, 'single');
fwrite(f, wgt, 'single');
fwrite(f, record_size, 'uint32');
fclose(f);
