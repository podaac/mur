function [sst,lon,lat,time,dt,bias,sigma,qual]=readL3UasL2Pviirso(ncfile);
%
% same as readL3U but converts the valid SST pixels into L2P (vector) output.
%
% specialized for OSPO VIIRS L3U product for speed up.


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
  %% find index sets for OpenDAP read:
    [ ii, jj ] = find( sst ~= badpix );
    ii = min(ii):max(ii); 
    jj = min(jj):max(jj); 
    sst = sst( ii, jj );  % trim SST field.
      %% OpenDAT ranges (initial indices and numbers to read)
      o0 = [ min(ii), min(jj), 1 ]-1;  
      oN = [ max(ii)-min(ii), max(jj)-min(jj), 0 ]+1;
      % use:  = netcdf.getVar(ncid,varid,o0,oN);
  inx=find(sst(:)==badpix);
  sst=sst*single(scale)+single(const);
  if length(inx), sst(inx)=vfv*ones(size(inx)); end;

    jnx = find( ~isnan( sst(:) ));
    sst = sst( jnx );

  if length(sst)==0,
      lon=[]; lat=[]; dt=[];bias=[];sigma=[];qual=[];
        varid = netcdf.inqVarID(ncid,'time');
        time = netcdf.getVar(ncid,varid);
      netcdf.close(ncid);
      return;
  end;

end;


% longitude and latitude:
if nargout>=2,
  varid = netcdf.inqVarID(ncid,'lon');
  lon = netcdf.getVar(ncid,varid);

  varid = netcdf.inqVarID(ncid,'lat');
  lat = netcdf.getVar(ncid,varid);

  lon = lon( ii );
  lat = lat( jj );

    %% make into L2P style:
    [ lon, lat ] = ndgrid( lon, lat );
    lon = lon(jnx);
    lat = lat(jnx);
end;

% reference time:
if nargout>=4,
  varid = netcdf.inqVarID(ncid,'time');
  time = netcdf.getVar(ncid,varid);
      % 'time' is a scalar.
end;

% time difference from the reference time:
if nargout>=5,
  varid = netcdf.inqVarID(ncid,'sst_dtime');
  dt = netcdf.getVar( ncid, varid, o0, oN);
  badpix = netcdf.getAtt(ncid,varid,'_FillValue');
  dt( find(dt(:)==badpix) )=vfv;
      dt = dt( jnx );
end;

% SSES bias:
if nargout>=6,
  varid = netcdf.inqVarID(ncid,'sses_bias');
  bias = netcdf.getVar( ncid, varid, o0, oN);
  badpix = netcdf.getAtt(ncid,varid,'_FillValue');
  const = netcdf.getAtt(ncid,varid,'add_offset');
  scale = netcdf.getAtt(ncid,varid,'scale_factor');
  bias=single(bias);
  inx=find(bias(:)==badpix); 
  bias=bias*single(scale)+single(const);
  if length(inx), bias(inx)=vfv*ones(size(inx)); end;
      bias = bias( jnx );
end;

% SSES std:
if nargout>=7,
  varid = netcdf.inqVarID(ncid,'sses_standard_deviation');
  sigma = netcdf.getVar( ncid, varid, o0, oN);
  badpix = netcdf.getAtt(ncid,varid,'_FillValue');
  const = netcdf.getAtt(ncid,varid,'add_offset');
  scale = netcdf.getAtt(ncid,varid,'scale_factor');
  sigma=single(sigma);
  inx=find(sigma(:)==badpix); 
  sigma=sigma*single(scale)+single(const);
  if length(inx), sigma(inx)=vfv*ones(size(inx)); end;
      sigma = sigma( jnx );
end;

% quality flag (0-5):
if nargout>=8,
  varid = netcdf.inqVarID(ncid,'quality_level');
  qual = netcdf.getVar( ncid, varid, o0, oN);
  try,
    badpix = netcdf.getAtt(ncid,varid,'_FillValue');
    inx=find(qual(:)==badpix); 
    if length(inx), qual(inx)=vfv*ones(size(inx)); end;
  catch,
  end;
      qual = qual( jnx );
end;


netcdf.close(ncid);

