function [mask,lon,lat,icemap]=readgdsgz(landicefile)
% [mask,lon,lat,icemap]=readgdsgz(landicefile)
% reads a landice file *.gds.gz
% Specify the "landicefile" WITHOUT the last ".gz".
%
% Fortran unformatted binary file with 3 records:
%   Record 1: nlon, nlat (dimensions)
%   Record 2: mask, lon, lat (grid data + coordinates)
%   Record 3: icemap (ice map data)

system(sprintf(' zcat %s.gz > /tmp/icemask.gds ', landicefile));

f=fopen('/tmp/icemask.gds','r');

% Record 1: dimensions
fread(f, 1, 'uint32');  % skip Fortran record marker
nlon = fread(f, 1, 'int32=>int32');
nlat = fread(f, 1, 'int32=>int32');
fread(f, 1, 'uint32');  % skip Fortran record marker

% Record 2: mask, lon, lat
fread(f, 1, 'uint32');  % skip Fortran record marker
mask = fread(f, [nlon, nlat], 'int8=>int8');
lon = fread(f, nlon, 'float32=>single');
lat = fread(f, nlat, 'float32=>single');
fread(f, 1, 'uint32');  % skip Fortran record marker

% Record 3: icemap
fread(f, 1, 'uint32');  % skip Fortran record marker
icemap = fread(f, [nlon, nlat], 'int8=>int8');
fread(f, 1, 'uint32');  % skip Fortran record marker

fclose(f);


