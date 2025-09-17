function [mask,lon,lat,icemap]=readgdsgz(landicefile)
% [mask,lon,lat,icemap]=readgdsgz(landicefile)
% reads a landice file *.gds.gz
% Specify the "landicefile" WITHOUT the last ".gz".

system(sprintf(' zcat %s.gz > /tmp/icemask.gds ', landicefile));

f=fopen('/tmp/icemask.gds','r');

% Read dimensions with type preservation
nlon = fread(f, 1, 'int32=>int32');
nlat = fread(f, 1, 'int32=>int32');

% Read mask grid data
mask = fread(f, [nlon, nlat], 'int8=>int8');

% Read coordinate information
lon = fread(f, nlon, 'float32=>single');
lat = fread(f, nlat, 'float32=>single');

% Read ice map data
icemap = fread(f, [nlon, nlat], 'int8=>int8');

fclose(f);


