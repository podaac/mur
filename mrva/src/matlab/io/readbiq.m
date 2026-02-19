function [sst,lon,lat,hour,wgt]=readbiq(biqfile)
% [sst,lon,lat,hour,wgt]=readbiq(biqfile)
%
% Fortran unformatted binary file with 6 records:
%   Record 1: n (count)
%   Record 2: lon (float32 array)
%   Record 3: lat (float32 array)
%   Record 4: hour (float32 array)
%   Record 5: sst (float32 array)
%   Record 6: wgt (float32 array)

f=fopen(biqfile,'r');

% Record 1: count
fread(f, 1, 'uint32');  % skip Fortran record marker
n = fread(f, 1, 'int32=>int32');
fread(f, 1, 'uint32');  % skip Fortran record marker

% Record 2: lon
fread(f, 1, 'uint32');  % skip Fortran record marker
lon = fread(f, n, 'float32=>single');
fread(f, 1, 'uint32');  % skip Fortran record marker

% Record 3: lat
fread(f, 1, 'uint32');  % skip Fortran record marker
lat = fread(f, n, 'float32=>single');
fread(f, 1, 'uint32');  % skip Fortran record marker

% Record 4: hour
fread(f, 1, 'uint32');  % skip Fortran record marker
hour = fread(f, n, 'float32=>single');
fread(f, 1, 'uint32');  % skip Fortran record marker

% Record 5: sst
fread(f, 1, 'uint32');  % skip Fortran record marker
sst = fread(f, n, 'float32=>single');
fread(f, 1, 'uint32');  % skip Fortran record marker

% Record 6: wgt
fread(f, 1, 'uint32');  % skip Fortran record marker
wgt = fread(f, n, 'float32=>single');
fread(f, 1, 'uint32');  % skip Fortran record marker

fclose(f);

