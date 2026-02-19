function [sst,lon,lat,time,dt,bias,sigma,qual]=readL3UasL2P(ncfile);
%
% same as readL3U but converts the valid SST pixels into L2P (vector) output.


% default fill value:
vfv=NaN;


ncid=netcdf.open(ncfile,'nowrite');


% SST:
if nargout>=1,
  varid = netcdf.inqVarID(ncid,'sea_surface_temperature');
  sst = netcdf.getVar(ncid,varid);  % Read as native type (int16)
  badpix = netcdf.getAtt(ncid,varid,'_FillValue');  % Keep native type for exact comparison
  mask = (sst == badpix);  % Compare in native type (exact integer match)
  % Now convert to single for scaling
  sst = single(sst);
  const = single(netcdf.getAtt(ncid,varid,'add_offset'));
  scale = single(netcdf.getAtt(ncid,varid,'scale_factor'));
  sst = sst * scale + const;
  if any(mask(:)), sst(mask) = single(vfv); end;
end;

% longitude:
if nargout>=2,
  varid = netcdf.inqVarID(ncid,'lon');
  lon = netcdf.getVar(ncid,varid);
  % Handle fill values (e.g., -999.0) in lon
  try
    badpix = netcdf.getAtt(ncid,varid,'_FillValue');
    mask = (lon == badpix);
    if any(mask(:)), lon(mask) = vfv; end;
  catch
    % No _FillValue attribute for lon, skip
  end;
end;

% latitude:
if nargout>=3,
  varid = netcdf.inqVarID(ncid,'lat');
  lat = netcdf.getVar(ncid,varid);
  % Handle fill values (e.g., -999.0) in lat
  try
    badpix = netcdf.getAtt(ncid,varid,'_FillValue');
    mask = (lat == badpix);
    if any(mask(:)), lat(mask) = vfv; end;
  catch
    % No _FillValue attribute for lat, skip
  end;
end;

% reference time:
if nargout>=4,
  varid = netcdf.inqVarID(ncid,'time');
  time = netcdf.getVar(ncid,varid);
end;

% time difference from the reference time:
if nargout>=5,
  varid = netcdf.inqVarID(ncid,'sst_dtime');
  dt = netcdf.getVar(ncid,varid);
  badpix = netcdf.getAtt(ncid,varid,'_FillValue');
  mask = (dt == badpix);
  if any(mask(:)), dt(mask) = vfv; end;
end;

% SSES bias:
if nargout>=6,
  varid = netcdf.inqVarID(ncid,'sses_bias');
  bias = netcdf.getVar(ncid,varid);  % Read as native type (int8)
  badpix = netcdf.getAtt(ncid,varid,'_FillValue');  % Keep native type for exact comparison
  mask = (bias == badpix);  % Compare in native type (exact integer match)
  % Now convert to single for scaling
  bias = single(bias);
  const = single(netcdf.getAtt(ncid,varid,'add_offset'));
  scale = single(netcdf.getAtt(ncid,varid,'scale_factor'));
  bias = bias * scale + const;
  if any(mask(:)), bias(mask) = single(vfv); end;
end;

% SSES std:
if nargout>=7,
  varid = netcdf.inqVarID(ncid,'sses_standard_deviation');
  sigma = netcdf.getVar(ncid,varid);  % Read as native type (int8)
  badpix = netcdf.getAtt(ncid,varid,'_FillValue');  % Keep native type for exact comparison
  mask = (sigma == badpix);  % Compare in native type (exact integer match)
  % Now convert to single for scaling
  sigma = single(sigma);
  const = single(netcdf.getAtt(ncid,varid,'add_offset'));
  scale = single(netcdf.getAtt(ncid,varid,'scale_factor'));
  sigma = sigma * scale + const;
  if any(mask(:)), sigma(mask) = single(vfv); end;
end;

% quality flag (0-5):
if nargout>=8,
  varid = netcdf.inqVarID(ncid,'quality_level');
  qual = netcdf.getVar(ncid,varid);
  try,
    badpix = netcdf.getAtt(ncid,varid,'_FillValue');
    mask = (qual == badpix);
    if any(mask(:)), qual(mask) = vfv; end;
  catch,
  end;
end;


netcdf.close(ncid);


% make L2P (vector) output:
  inx = find( ~isnan( sst(:) ) );

  sst = sst(inx);
  if exist('lon','var')&exist('lat','var'),
    [ lon, lat ] = ndgrid( lon, lat );
    lon = lon(inx);
    lat = lat(inx);
  end;
  if exist('dt','var'),    dt    = dt(inx);    end;
  if exist('bias','var'),  bias  = bias(inx);  end;
  if exist('sigma','var'), sigma = sigma(inx); end;
  if exist('qual','var'),  qual  = qual(inx);  end;
  % --> only "time" (scalar) is kept the same.

