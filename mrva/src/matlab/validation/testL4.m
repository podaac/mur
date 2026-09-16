% testL4.m
%function [sst,lon,lat]=readL4(ncfile);

year=2010;
day=3;
day=127;

ddir=sprintf('/nas/ftp/mur_sst/tmchin/L4/GLOB/JPL/MUR/%04d/%03d',year,day);
[d,m,y]=julian(day,year);
filename=sprintf('%04d%02d%02d-JPL-L4UHfnd-GLOB-v01-fv02-MUR.nc',y,m,d);

ncfile='testL4tmp.nc';

eval(sprintf('!bzcat %s/%s.bz2 > %s',ddir,filename,ncfile));

ncid=netcdf.open(ncfile,'nowrite');

% latitude:
%dimid = netcdf.inqDimID(ncid,'lat'),
%[dimname, nlat] = netcdf.inqDim(ncid,dimid);
varid = netcdf.inqVarID(ncid,'lat');
lat = netcdf.getVar(ncid,varid);

% longitude:
varid = netcdf.inqVarID(ncid,'lon');
lon = netcdf.getVar(ncid,varid);

% SST:
varid = netcdf.inqVarID(ncid,'analysed_sst');
sst = netcdf.getVar(ncid,varid);
badpix = netcdf.getAtt(ncid,varid,'_FillValue');
const = netcdf.getAtt(ncid,varid,'add_offset');
scale = netcdf.getAtt(ncid,varid,'scale_factor');
sst=double(sst);
inx=find(sst(:)==badpix); if length(inx), sst(inx)=NaN*ones(size(inx)); end;
sst=sst*double(scale)+double(const);

% Error:
varid = netcdf.inqVarID(ncid,'analysis_error');
err = netcdf.getVar(ncid,varid);
badpix = netcdf.getAtt(ncid,varid,'_FillValue');
const = netcdf.getAtt(ncid,varid,'add_offset');
scale = netcdf.getAtt(ncid,varid,'scale_factor');
err=double(err);
inx=find(err(:)==badpix); if length(inx), err(inx)=NaN*ones(size(inx)); end;
err=err*double(scale)+double(const);

% Mask:
varid = netcdf.inqVarID(ncid,'mask');
mask = netcdf.getVar(ncid,varid);
badpix = netcdf.getAtt(ncid,varid,'_FillValue');
inx=find(mask(:)==badpix); if length(inx), mask(inx)=NaN*ones(size(inx)); end;

% Ice:
varid = netcdf.inqVarID(ncid,'sea_ice_fraction');
ice = netcdf.getVar(ncid,varid);
badpix = netcdf.getAtt(ncid,varid,'_FillValue');
const = netcdf.getAtt(ncid,varid,'add_offset');
scale = netcdf.getAtt(ncid,varid,'scale_factor');
ice=double(ice);
inx=find(ice(:)==badpix); if length(inx), ice(inx)=NaN*ones(size(inx)); end;
ice=ice*double(scale)+double(const);


netcdf.close(ncid);
