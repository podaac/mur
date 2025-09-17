function makedailyiquam(year, doy, rewrite, outputDir, cacheDir, sourceUrl)
% makedailyiquam - Download and process IQUAM NetCDF data to daily binary files
%
% USAGE:
%   makedailyiquam(year, doy, rewrite, outputDir, cacheDir, sourceUrl)
%
% INPUTS:
%   year      - Year (e.g., 2024)
%   doy       - Day of year (1-366)
%   rewrite   - Force rewrite existing files (0=no, 1=yes) [optional, default: 0]
%   outputDir - Base directory for .bii output files [optional, default: './output/iquam']
%   cacheDir  - Directory for temporary .mat cache files [optional, default: pwd]
%   sourceUrl - URL for IQUAM NetCDF downloads [optional, default: NOAA STAR server]
%
% OUTPUTS:
%   Creates: <outputDir>/YYYY/Global_IQUAM0_YYYY_DDD.bii
%   Caches:  <cacheDir>/iquam.YYYY.MM.mat (monthly data for reuse)
%
% PROCESSING:
%   1. Downloads monthly IQUAM NetCDF file (if not cached)
%   2. Reads and quality-controls data (qual >= 5)
%   3. Extracts observations for specified day
%   4. Calls writeiquambii() to write binary output
%
% NOTE: This function now calls external writeiquambii() - no inline duplication

  %% Handle optional parameters
  if ~exist('rewrite','var'), rewrite = 0; end
  if ~exist('outputDir','var') || isempty(outputDir)
      outputDir = './output/iquam';
  end
  if ~exist('cacheDir','var') || isempty(cacheDir)
      cacheDir = pwd;
  end
  if ~exist('sourceUrl','var') || isempty(sourceUrl)
      sourceUrl = 'https://www.star.nesdis.noaa.gov/pub/socd/sst/iquam/v2.10/';
  end

  %% Output filename (check if exists and skip if not rewriting)
  edir = sprintf('%s/%04d', outputDir, year);
  if ~exist(edir,'dir')
      [status, msg] = mkdir(edir);
      if ~status, error('Failed to create output dir: %s', msg); end
  end

  %% Ensure cache directory exists
  if ~exist(cacheDir,'dir')
      [status, msg] = mkdir(cacheDir);
      if ~status, error('Failed to create cache dir: %s', msg); end
  end

  filename = sprintf('%s/Global_IQUAM0_%04d_%03d.bii', edir, year, doy);

  if (~rewrite) && exist(filename,'file')
      return
  end


    %% netCDF file:
    [day,month]=julian(doy,year);
    ifile=sprintf('%04d%02d-STAR-L2i_GHRSST-SST-iQuam-*.nc',year,month);
    localfile=sprintf('%s/iquam.%04d.%02d.mat',cacheDir,year,month);

    %% download, read HDF file, and quality control:
    if ~exist(localfile,'file')
      fprintf('Processing %04d/%03d: Downloading IQUAM data for %04d-%02d\n', year, doy, year, month);

      %% download:
      system(sprintf('wget -nH --cut-dirs 6 -r -l1 -np "%s" -A "%s"',sourceUrl,ifile),'-echo');

      %% read:
      ddir = dir( ifile );
      if length(ddir),
        ncfile = ddir(1).name;
      else,
        fprintf('ERROR: IQUAM download failed for %04d/%03d\n', year, doy);
        return;
      end;

      [dayf, hour, minute, lon, lat, sst, qual, pt] = readnc( ncfile );
      delete( ncfile );

      %f=hdfreadopen(ifile);
      %  dayf=hdfreadvariable(f,'Day');
      %  hour=hdfreadvariable(f,'Hour');
      %  minute=hdfreadvariable(f,'Minute');
      %  lon=hdfreadvariable(f,'Longitude');
      %  lat=hdfreadvariable(f,'Latitude');
      %  sst=hdfreadvariable(f,'Sea_Surface_Temperature');
      %  qual=hdfreadvariable(f,'Quality_Flag');
      %  pt=hdfreadvariable(f,'Type');
      %hdfreadclose(f);
      %delete(ifile);

      %% conversion:
      hour = hour+minute/60;
      %knx=find(lon>180);  if length(knx), lon(knx)=lon(knx)-360; end;
      sst = sst - 273.15;  % ncfile uses Kelvin.

      %% quality control:
      %% http://www.star.nesdis.noaa.gov/sod/sst/iquam/index.html
      %knx=find( mod(qual,4)==0 );
      knx=find( qual>=5 );
      fprintf('  QC: Retained %d of %d observations (qual>=5)\n', length(knx), length(dayf));
      dayf=dayf(knx); hour=hour(knx); pt=pt(knx);
      sst=sst(knx); lon=lon(knx); lat=lat(knx);

      %% save the contents:
      save(localfile,'dayf','hour','pt','sst','lon','lat');

    else  % read from mat file:
      fprintf('Processing %04d/%03d: Using cached data from %s\n', year, doy, localfile);
      load(localfile);

    end

    %% extract daily components:
    knx=find(dayf==day);
    fprintf('  Writing %d observations to %s\n', length(knx), filename);
    hour=hour(knx); pt=pt(knx);
    sst=sst(knx); lon=lon(knx); lat=lat(knx);

    %% write file: Call external writeiquambii function (no more code duplication!)
    writeiquambii(year, doy, lon, lat, sst, hour, pt, outputDir);



%%%%%%%%%%

function fileID=hdfreadopen(filename,contents)
% fileID=hdfreadopen(filename,contents)
% open an HDF file using matlab.io.hdf4.sd and returns its file ID.
%
% If "contents" flag is set, a list of its variable contents is printed.
%
% The file is closed if the "contents" flag is set (default: contents=0).
%
% Updated to use matlab.io.hdf4.sd interface (replaces deprecated hdfsd)


if ~exist('contents','var'), contents=0; end;

fileID = matlab.io.hdf4.sd.start(filename, 'read');

if fileID==-1,
  disp(sprintf('hdfreadopen: %s not found.',filename)); return;
end;

if contents,
  [ndatasets, nglobattr] = matlab.io.hdf4.sd.fileInfo(fileID);

  fprintf(1,'ndatasets=%d, nglobattr=%d\n',ndatasets,nglobattr);

  disp(sprintf('### %s, CONTENTS: ###',filename));
  for n=0:ndatasets-1,
    dataID = matlab.io.hdf4.sd.select(fileID, n);
    [name, ndim, dimvector, type, nattr] = matlab.io.hdf4.sd.getInfo(dataID);
    fprintf(1,'  %s: %s(%d) +%d\n',name,type,ndim,nattr);
    matlab.io.hdf4.sd.endAccess(dataID);
  end;

  matlab.io.hdf4.sd.close(fileID);
end;


function val=hdfreadvariable(fileID,varname)
% val=hdfreadvariable(fileID,'varname')
% returns value "val" of the HDF file variable named "varname".
%
% Updated to use matlab.io.hdf4.sd interface (replaces deprecated hdfsd)

varIndex = matlab.io.hdf4.sd.nameToIndex(fileID, varname);
dataID = matlab.io.hdf4.sd.select(fileID, varIndex);

if dataID==-1,
  disp(sprintf('"%s" not found in fileID %d',varname,fileID));
  val=[];
  return;
end;

[name, ndim, dims, type, nattr] = matlab.io.hdf4.sd.getInfo(dataID);
startvector = zeros(size(dims));
stridevector = [];
endvector = dims;
val = matlab.io.hdf4.sd.readData(dataID, startvector, stridevector, endvector);
matlab.io.hdf4.sd.endAccess(dataID);


function status=hdfreadclose(fileID)
% closes the opened HDF file.
%
% Updated to use matlab.io.hdf4.sd interface (replaces deprecated hdfsd)
status = matlab.io.hdf4.sd.close(fileID);


function [dayf,hour,minute,lon,lat,sst,qual,pt] = readnc( ncfile )

ncid=netcdf.open(ncfile,'nowrite');

  dayf = netcdf.getVar( ncid, netcdf.inqVarID( ncid, 'day' ) );
  bad = netcdf.getAtt( ncid, netcdf.inqVarID( ncid, 'day' ), '_FillValue' );
  dayf( find( dayf==bad ) ) = NaN;

  hour = netcdf.getVar( ncid, netcdf.inqVarID( ncid, 'hour' ) );
  bad = netcdf.getAtt( ncid, netcdf.inqVarID( ncid, 'hour' ), '_FillValue' );
  hour( find( hour==bad ) ) = NaN;

  minute = netcdf.getVar( ncid, netcdf.inqVarID( ncid, 'minute' ) );
  bad = netcdf.getAtt( ncid, netcdf.inqVarID( ncid, 'minute' ), '_FillValue' );
  minute( find( minute==bad ) ) = NaN;

  lon = netcdf.getVar( ncid, netcdf.inqVarID( ncid, 'lon' ) );

  lat = netcdf.getVar( ncid, netcdf.inqVarID( ncid, 'lat' ) );

  sst = netcdf.getVar( ncid, netcdf.inqVarID( ncid, 'sst' ) );
  bad = netcdf.getAtt( ncid, netcdf.inqVarID( ncid, 'sst' ), '_FillValue' );
  sst( find( sst==bad ) ) = NaN;

  qual = netcdf.getVar( ncid, netcdf.inqVarID( ncid, 'quality_level' ) );
  bad = netcdf.getAtt(ncid,netcdf.inqVarID(ncid,'quality_level'),'_FillValue');
  qual( find( qual==bad ) ) = NaN;

  pt = netcdf.getVar( ncid, netcdf.inqVarID( ncid, 'platform_type' ) );
  bad = netcdf.getAtt(ncid,netcdf.inqVarID(ncid,'platform_type'),'_FillValue');
  pt( find( pt==bad ) ) = NaN;


netcdf.close(ncid);

