function [sst,lon,lat,dev]=readSeasonal(doy,vfv);
% [sst,lon,lat,dev]=readSeasonal(doy,vfv);
%
% Read MUR seasonal climatology for specified day of year.
%
% INPUTS:
%   doy - Day of year (1-366, 366 maps to 365)
%   vfv - Fill value for bad pixels (default: NaN)
%
% OUTPUTS:
%   sst - Sea surface temperature climatology [lon x lat]
%   lon - Longitude coordinates
%   lat - Latitude coordinates
%   dev - Standard deviation

% Container path for seasonal climatology data
seasonal_root = '/data/static-resources/seasonal';

if doy==366, doy=365; end;
ncfile = sprintf('%s/mur_%03d.nc', seasonal_root, doy);

% default fill value:
if nargin<2, vfv=NaN; end;

% Check file exists before attempting to open
if ~exist(ncfile, 'file')
    error('readSeasonal:FileNotFound', ...
          'Seasonal climatology file not found: %s\nVerify static_resources_dir mount contains seasonal/ directory with mur_###.nc files.', ...
          ncfile);
end

try
    ncid=netcdf.open(ncfile,'nowrite');
catch ME
    error('readSeasonal:OpenFailed', ...
          'Failed to open seasonal file: %s\nError: %s', ncfile, ME.message);
end




% latitude:
if nargout>=3,
  varid = netcdf.inqVarID(ncid,'lat');
  lat = netcdf.getVar(ncid,varid);
end;


% longitude:
if nargout>=2,
  varid = netcdf.inqVarID(ncid,'lon');
  lon = netcdf.getVar(ncid,varid);
end;




% SST:
if nargout>=1,
  varid = netcdf.inqVarID(ncid,'mean_sst');
  sst = netcdf.getVar(ncid,varid);
  badpix = netcdf.getAtt(ncid,varid,'_FillValue');
  const = netcdf.getAtt(ncid,varid,'add_offset');
  scale = netcdf.getAtt(ncid,varid,'scale_factor');
  inx=find(sst(:)==badpix);
  sst=single(sst);
  sst=sst*single(scale)+single(const);
  if length(inx), sst(inx)=vfv*ones(size(inx)); end;
end;


% Error:
if nargout>=4,
  varid = netcdf.inqVarID(ncid,'standard_deviation');
  dev = netcdf.getVar(ncid,varid);
  badpix = netcdf.getAtt(ncid,varid,'_FillValue');
  const = netcdf.getAtt(ncid,varid,'add_offset');
  scale = netcdf.getAtt(ncid,varid,'scale_factor');
  inx=find(dev(:)==badpix);
  dev=single(dev);
  dev=dev*single(scale)+single(const);
  if length(inx), dev(inx)=vfv*ones(size(inx)); end;
end;



netcdf.close(ncid);

