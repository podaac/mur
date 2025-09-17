function [mask,lon,lat,icemap]=readgds(landicefile)
% reads a "landice" file *.gds

f=fopen(landicefile,'r');

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

