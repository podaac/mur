function [sst,lon,lat,hour,wgt]=readbiq(biqfile)
% [sst,lon,lat,hour,wgt]=readbiq(biqfile)


f=fopen(biqfile,'r');

% Read count with type preservation
n = fread(f, 1, 'int32=>int32');

% Read data arrays with type preservation
lon = fread(f, n, 'float32=>single');
lat = fread(f, n, 'float32=>single');
hour = fread(f, n, 'float32=>single');
sst = fread(f, n, 'float32=>single');
wgt = fread(f, n, 'float32=>single');

fclose(f);

