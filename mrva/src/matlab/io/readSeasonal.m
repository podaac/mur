function [sst,lon,lat,dev]=readSeasonal(seasonal_file,vfv);
% [sst,lon,lat,dev]=readSeasonal(seasonal_file,vfv);
%
% Read MUR seasonal climatology from an already-resolved file.
%
% INPUTS:
%   seasonal_file - Path to the seasonal climatology NetCDF file for the
%                   day of year this run needs (resolved by the caller --
%                   mrva_static_files.py's seasonal_relative_path() handles
%                   the day-366-maps-to-365 convention on the Python side,
%                   so this function no longer needs a doy argument at all)
%   vfv           - Fill value for bad pixels (default: NaN)
%
% OUTPUTS:
%   sst - Sea surface temperature climatology [lon x lat]
%   lon - Longitude coordinates
%   lat - Latitude coordinates
%   dev - Standard deviation

ncfile = seasonal_file;

% default fill value:
if nargin<2, vfv=NaN; end;

% Check file exists before attempting to open
if ~exist(ncfile, 'file')
    error('readSeasonal:FileNotFound', ...
          'Seasonal climatology file not found: %s\nVerify the --seasonal-file flag was localized correctly.', ...
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

