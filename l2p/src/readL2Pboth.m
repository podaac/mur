function [sst,lon,lat,time,dt,bias,sigma,rjct,conf,prox]=readL2Pboth(ncfile,vfv);
%
% [sst,lon,lat,time,dt,bias,sigma,rjct,conf,prox]=readL2Pboth(ncfile,fillvalue);
%
% extracts the most common (core) variables from a
% GHRSST L2P formatted netCDF file, given its filename "ncfile".
%
% This is an updated version of readL2Pcore.m that functions for GDS2.0
% as well as its previous GDS versions.
%
% The input "fillvalue" is optional, as described below.
% The outputs are the GHRSST L2P variables, where 
% "sst" is sea_surface_temperature, "dt" is sst_dtime,
% "bias" is SSES_bias_error, "sigma" is SSES_standard_deviation_error,
% (in GDS2.0 sses_bias and sses_standard_deviation, respectively),
% "rjct" is rejection_flag, "conf" is confidence_flag, and
% "prox" is proximity_confidence.
% (for GDS2.0 all three flags contain the same "quality-level" flag values).
%
% You can limit the data extraction process by reducing the
% number of output variables.  For example,
%   [sst, lon, lat] = readL2Pcore( ncfile )
% reads only the SST, longitude, latitude variables.
% The sequence of the output variables must remain the same, however.
% For example, "prox" cannot be read without reading all other variables first.
%
% By default, readL2core will fill each "_FillValue" pixel with
% a NaN ("not a number").  You can instead fill it with a given
% value by specifying the optional "fillvalue" input.  For example,
%   sst = readL2core( ncfile, -128 )
% will use -128 for the fill value.

% PLEASE CHANGE THE NAME OF THIS FILE IF YOU EDIT ITS CONTENTS.
%   2011.04.07, Mike Chin, readL2Pcore.m version 1.
%   2013.09.24, Mike Chin, first version


% default fill value:
if nargin<2, vfv=NaN; end;


ncid=netcdf.open(ncfile,'nowrite');

% determin if GDS2.0:
gds2=0;
[ndims,nvars,ngatts,uldid]=netcdf.inq(ncid);
for varid=0:nvars-1,
  if strcmp(netcdf.inqVar(ncid,varid),'quality_level'), gds2=1; end;
  %if strcmp(lower(netcdf.inqVar(ncid,varid)),'sses_bias'), gds2=1; end;
end;


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
  if gds2, nameBias='sses_bias'; else, nameBias='SSES_bias_error'; end;
  varid = netcdf.inqVarID(ncid,nameBias);
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
  if gds2,
    nameSTD='sses_standard_deviation';
  else,
    nameSTD='SSES_standard_deviation_error';
  end;
  varid = netcdf.inqVarID(ncid,nameSTD);
  sigma = netcdf.getVar(ncid,varid);
  badpix = netcdf.getAtt(ncid,varid,'_FillValue');
  const = netcdf.getAtt(ncid,varid,'add_offset');
  scale = netcdf.getAtt(ncid,varid,'scale_factor');
  sigma=single(sigma);
  inx=find(sigma(:)==badpix); 
  sigma=sigma*single(scale)+single(const);
  if length(inx), sigma(inx)=vfv*ones(size(inx)); end;
end;

% rejection flag:
if nargout>=8 & ~gds2,
  varid = netcdf.inqVarID(ncid,'rejection_flag');
  rjct = netcdf.getVar(ncid,varid);
end;

% confidence flag:
if nargout>=9 & ~gds2,
  varid = netcdf.inqVarID(ncid,'confidence_flag');
  conf = netcdf.getVar(ncid,varid);
end;

% proximity confidence:
if nargout>=10 & ~gds2,
  varid = netcdf.inqVarID(ncid,'proximity_confidence');
  prox = netcdf.getVar(ncid,varid);
end;

% quality flag:
if nargout>=8 & gds2,
  varid = netcdf.inqVarID(ncid,'quality_level');
  prox = netcdf.getVar(ncid,varid);
  rjct=prox; conf=prox;
end;


netcdf.close(ncid);

