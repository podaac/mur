function [sst,lon,lat,dev]=readSeasonal(doy,vfv);
% [sst,lon,lat,dev]=readNC(ncfile,vfv);

if doy==366, doy=365; end;
ncfile = sprintf('/home/tmchin/nas/seasonal/mur_%03d.nc',doy);


% default fill value:
if nargin<2, vfv=NaN; end;


ncid=netcdf.open(ncfile,'nowrite');




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

