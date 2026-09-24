function makedailyiquam(year, doy, rewrite, outputDir, sourceUrl)
% makedailyiquam - Download and process IQUAM NetCDF data to daily binary files
%
% USAGE:
%   makedailyiquam(year, doy, rewrite, outputDir, sourceUrl)
%
% INPUTS:
%   year      - Year (e.g., 2024)
%   doy       - Day of year (1-366)
%   rewrite   - Force rewrite existing files (0=no, 1=yes) [optional, default: 0]
%   outputDir - Base directory for .bii output files [optional, default: './output/iquam']
%   sourceUrl - URL for IQUAM NetCDF downloads [optional, default: NOAA STAR server]
%
% OUTPUTS:
%   Creates: <outputDir>/YYYY/Global_IQUAM0_YYYY_DDD.bii
%
% PROCESSING:
%   1. Downloads monthly IQUAM NetCDF file (fresh each time - no caching)
%   2. Reads and quality-controls data (qual >= 5)
%   3. Extracts observations for specified day
%   4. Calls writeiquambii() to write binary output
%
% NOTE: Downloads to ephemeral /tmp - no persistent cache needed.
%       This matches production behavior and avoids cache staleness issues.

  %% Handle optional parameters
  if ~exist('rewrite','var'), rewrite = 0; end
  if ~exist('outputDir','var') || isempty(outputDir)
      outputDir = './output/iquam';
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

  filename = sprintf('%s/Global_IQUAM0_%04d_%03d.bii', edir, year, doy);

  if (~rewrite) && exist(filename,'file')
      N_existing = read_bii_count(filename);
      if N_existing > 0
          fprintf('Processing %04d/%03d: Output exists with N=%d, skipping\n', ...
                  year, doy, N_existing);
          return
      end
      fprintf('Processing %04d/%03d: Existing file has N=0, re-fetching\n', ...
              year, doy);
  end

  %% Determine which monthly NetCDF file to download
  [day, month] = julian(doy, year);
  ifile = sprintf('%04d%02d-STAR-L2i_GHRSST-SST-iQuam-*.nc', year, month);

  fprintf('Processing %04d/%03d: Downloading IQUAM data for %04d-%02d\n', year, doy, year, month);

  %% Download fresh (no caching - simpler and matches production)
  system(sprintf('wget -nH --cut-dirs 6 -r -l1 -np "%s" -A "%s"', sourceUrl, ifile), '-echo');

  %% Find the downloaded file(s)
  ddir = dir(ifile);
  if isempty(ddir)
      fprintf('ERROR: IQUAM download failed for %04d/%03d\n', year, doy);
      return;
  end

  %% Read NetCDF data, best revision first, falling through unreadable ones
  ranked = rank_by_file_version(ddir);
  [dayf, hour, minute, lon, lat, sst, qual, pt, ncfile] = ...
      read_best_candidate(ranked);

  %% Clean up every downloaded file, not just the one that was read
  for ci = 1:numel(ranked)
      if exist(ranked(ci).name, 'file'), delete(ranked(ci).name); end
  end

  if isempty(ncfile)
      error('makedailyiquam:noReadableSource', ...
            ['No readable iQuam file for %04d-%02d (tried %d revision(s)).\n' ...
             'This is a bad upstream REVISION, not a bad download:\n' ...
             '  - fv00.0 for the CURRENT month is rewritten in place as days ' ...
             'accrue. Some of\n' ...
             '    those writes land corrupt and are then served unchanged ' ...
             'until the next one.\n' ...
             '  - Observed: the 2026-09-23 11:00Z revision was damaged ' ...
             '(14 of 32 variables,\n' ...
             '    including 7 of the 8 read here) and stayed byte-identical ' ...
             'and unreadable for\n' ...
             '    ~29 hours. The 2026-09-24 15:46Z rewrite of the same URL ' ...
             'was clean (32/32).\n' ...
             '  - So retrying NOW will fail identically. Re-run once the ' ...
             'file has been\n' ...
             '    rewritten -- compare Last-Modified with the failing run ' ...
             'before retrying.\n' ...
             'Check with: curl -sI %s'], ...
            year, month, numel(ranked), sourceUrl);
  end

  %% Data conversion
  hour = hour + minute/60;
  sst = sst - 273.15;  % NetCDF uses Kelvin

  %% Quality control (qual >= 5)
  %% http://www.star.nesdis.noaa.gov/sod/sst/iquam/index.html
  knx = find(qual >= 5);
  fprintf('  QC: Retained %d of %d observations (qual>=5)\n', length(knx), length(dayf));
  dayf = dayf(knx);
  hour = hour(knx);
  pt = pt(knx);
  sst = sst(knx);
  lon = lon(knx);
  lat = lat(knx);

  %% Extract this day's observations
  knx = find(dayf == day);

  if isempty(knx)
      fprintf('  WARNING: No observations found for day %d in monthly file\n', day);
      fprintf('  Writing 0 observations to %s\n', filename);
  else
      fprintf('  Writing %d observations to %s\n', length(knx), filename);
  end

  hour = hour(knx);
  pt = pt(knx);
  sst = sst(knx);
  lon = lon(knx);
  lat = lat(knx);

  %% Write output file
  writeiquambii(year, doy, lon, lat, sst, hour, pt, outputDir);


%%%%%%%%%%
% Helper functions (kept for potential HDF4 compatibility)
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


function N = read_bii_count(filename)
% Read the observation count N from an existing .bii file header.
% Returns 0 if the file is missing, truncated, or unreadable. Used to
% detect empty 24-byte stubs so makedailyiquam can re-fetch them once
% NOAA back-fills the source month.
%
% Format from writeiquambii.m:46-49 — first Fortran record is
%   int32 N + int16 year + int16 doy (payload after 4-byte length prefix).
  N = 0;
  f = fopen(filename, 'r');
  if f == -1, return; end
  c = onCleanup(@() fclose(f));
  fread(f, 1, 'int32');       % Fortran record-length prefix
  raw = fread(f, 1, 'int32'); % N (observation count)
  if ~isempty(raw), N = raw; end


function ranked = rank_by_file_version(ddir)
% Order a month's downloaded files best-revision-first, by their fvNN.N suffix.
%
% NOAA publishes each month more than once. fv00.0 lands on the 1st of the
% following month as a near-real-time rollup; a reprocessed fv01.0 or higher
% follows weeks later carrying materially more observations:
%
%   202607  fv00.0  468,352,726 B (Aug 1)  ->  fv01.0  516,012,782 B (Sep 7)
%   202608  fv00.0  475,160,069 B (Sep 1)  ->  fv05.0  508,360,933 B (Sep 17)
%
% Every month since 2025-07 has had one. The download glob matches all of
% them and this used to take dir()'s first entry, which sorts alphabetically
% -- so fv00.0 always won and the reprocessed file was downloaded, ignored,
% and deleted. That is a silent ~7-10% loss of in-situ observations on any
% reprocessing run, quite apart from the robustness this ordering buys.
  n = numel(ddir);
  fv = zeros(n, 1);
  for k = 1:n
      tok = regexp(ddir(k).name, '-fv(\d+)\.(\d+)\.nc$', 'tokens', 'once');
      if isempty(tok)
          fv(k) = -1;   % unrecognised naming sorts last, but is still tried
      else
          fv(k) = str2double(tok{1}) + str2double(tok{2}) / 10;
      end
  end
  [~, order] = sort(fv, 'descend');
  ranked = ddir(order);


function [dayf, hour, minute, lon, lat, sst, qual, pt, used] = ...
        read_best_candidate(ranked)
% Try each revision in turn so that one unreadable file is not fatal.
%
% netcdf.open reports a damaged file as "HDF error (NC_EHDFERR)" and nothing
% else -- no filename, no variable, no hint that the cause is upstream. That
% one line cost two DPS runs before anyone looked at the file itself, so the
% catch below names the file and moves on instead.
%
% What it is actually recovering from: the current month's fv00.0 is rewritten
% in place as days accrue, and some of those writes land corrupt. The damage
% is a property of the published revision, not of our fetch -- the 2026-09-23
% 11:00Z revision was served byte-identical and unreadable for ~29 hours
% across two independent readers, then the 2026-09-24 15:46Z rewrite of the
% same URL read 32/32. So there is no point retrying inside one run; the
% fallback below is for the case where an older revision is still on disk.
%
% In the bad revision day, hour, minute, lat, lon, sst and platform_type were
% all unreadable -- 7 of the 8 variables readnc needs -- while quality_level
% survived. Every variable is gzip-9 + shuffle in ~1900 chunks, so a damaged
% chunk B-tree puts the data out of reach of any reader at any level.
  [dayf, hour, minute, lon, lat, sst, qual, pt] = deal([]);
  used = '';
  for k = 1:numel(ranked)
      name = ranked(k).name;
      try
          [dayf, hour, minute, lon, lat, sst, qual, pt] = readnc(name);
          used = name;
          if k > 1
              fprintf(['  NOTE: using %s after %d unreadable revision(s); ' ...
                       'this is the fallback working as intended\n'], ...
                      name, k - 1);
          end
          return
      catch err
          fprintf(['  WARNING: %s is unreadable (%s); ' ...
                   'trying the next revision\n'], name, err.identifier);
      end
  end
