function [sst,lon,lat,time,dt,bias,sigma,qual]=readL3UasL2P(ncfile);
%
% same as readL3U but converts the valid SST pixels into L2P (vector) output.


% default fill value:
vfv=NaN;


ncid=netcdf.open(ncfile,'nowrite');


% SST:
if nargout>=1,
  varid = netcdf.inqVarID(ncid,'sea_surface_temperature');
  sst = netcdf.getVar(ncid,varid);
  badpix = netcdf.getAtt(ncid,varid,'_FillValue');
  const = netcdf.getAtt(ncid,varid,'add_offset');
  scale = netcdf.getAtt(ncid,varid,'scale_factor');
  sst=single(sst);
  inx=find(sst(:)==badpix);
  sst=sst*single(scale)+single(const);
  if length(inx), sst(inx)=vfv*ones(size(inx)); end;
end;

% longitude:
if nargout>=2,
  varid = netcdf.inqVarID(ncid,'lon');
  lon = netcdf.getVar(ncid,varid);
end;

% latitude:
if nargout>=3,
  varid = netcdf.inqVarID(ncid,'lat');
  lat = netcdf.getVar(ncid,varid);
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
  inx=find(dt(:)==badpix);
  if length(inx), dt(inx)=vfv*ones(size(inx)); end;
end;

% SSES bias:
if nargout>=6,
  varid = netcdf.inqVarID(ncid,'sses_bias');
  bias = netcdf.getVar(ncid,varid);
  badpix = netcdf.getAtt(ncid,varid,'_FillValue');
  const = netcdf.getAtt(ncid,varid,'add_offset');
  scale = netcdf.getAtt(ncid,varid,'scale_factor');
  bias=single(bias);
  inx=find(bias(:)==badpix); 
  bias=bias*single(scale)+single(const);
  if length(inx), bias(inx)=vfv*ones(size(inx)); end;
end;

% SSES std:
if nargout>=7,
  varid = netcdf.inqVarID(ncid,'sses_standard_deviation');
  sigma = netcdf.getVar(ncid,varid);
  badpix = netcdf.getAtt(ncid,varid,'_FillValue');
  const = netcdf.getAtt(ncid,varid,'add_offset');
  scale = netcdf.getAtt(ncid,varid,'scale_factor');
  sigma=single(sigma);
  inx=find(sigma(:)==badpix); 
  sigma=sigma*single(scale)+single(const);
  if length(inx), sigma(inx)=vfv*ones(size(inx)); end;
end;

% quality flag (0-5):
if nargout>=8,
  varid = netcdf.inqVarID(ncid,'quality_level');
  qual = netcdf.getVar(ncid,varid);
  try,
    badpix = netcdf.getAtt(ncid,varid,'_FillValue');
    inx=find(qual(:)==badpix); 
    if length(inx), qual(inx)=vfv*ones(size(inx)); end;
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

