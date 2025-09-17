function [ice,lon,lat] = readosisafice( hem, year, doy, ...
                                        lastMJD_reprocessed, lastMJD_archive, ...
                                        out_dir)

    %hem='nh';
    %year=2015;
    %doy=200;

  if ~exist('lastMJD_reprocessed'), lastMJD_reprocessed=julian(1,1,2008,3); end;
  if ~exist('lastMJD_archive'), lastMJD_archive=inf; end;

  % Retrieve the date
  year = int32(str2double(year));
  doy = int32(str2double(doy));

  original_year = year;
  original_doy = doy;
  [day,month,year] = julian(doy,year);
  date   = sprintf('%04d%02d%02d',year,month,day);
  subdir = sprintf('/%04d/%02d',year,month);


  %% ftp source and file name(s):
  current_mjd = julian(doy,1,year,3);

  if current_mjd <= lastMJD_reprocessed

    ftpdir = getenv("OSISAF_FTP_REPROCESSED"); % 1978-2015.04
    filename = sprintf('ice_conc_%s_polstere-100_reproc_%s1200.nc',hem,date);
    fprintf(1, 'readOSISAF: Date %s (%s, MJD=%d) <= reprocessing cutoff (MJD=%d)\n', ...
        date, hem, current_mjd, lastMJD_reprocessed);
    fprintf(1, 'readOSISAF: Using REPROCESSED FTP source: %s\n', ftpdir);

  elseif current_mjd <= lastMJD_archive

    ftpdir = getenv("OSISAF_FTP_ARCHIVE");
    filename = sprintf('ice_conc_%s_polstere-100_multi_%s1200.nc',hem,date);
    fprintf(1, 'readOSISAF: Date %s (%s, MJD=%d) > reprocessing cutoff (MJD=%d), <= archive cutoff (MJD=%d)\n', ...
        date, hem, current_mjd, lastMJD_reprocessed, lastMJD_archive);
    fprintf(1, 'readOSISAF: Using ARCHIVE FTP source: %s\n', ftpdir);

  else

    ftpdir = getenv("OSISAF_FTP_PROD");
    subdir = '';
    filename = sprintf('ice_conc_%s_polstere-100_multi_%s1200.nc',hem,date);
    fprintf(1, 'readOSISAF: Date %s (%s, MJD=%d) > archive cutoff (MJD=%d)\n', ...
        date, hem, current_mjd, lastMJD_archive);
    fprintf(1, 'readOSISAF: Using PRODUCTION FTP source: %s\n', ftpdir);

  end

  % Attempt to retrieve the file
  pathname = sprintf('%s%s/%s',ftpdir,subdir,filename);
  original_pathname = pathname;
  download_file(pathname, filename);

  % Iterate through days to locate last available ice file - look 10 days back
  num_days = 10;
  current_day = 0;
  dt = datetime(year,month,day);
  while current_day < num_days & ~exist(filename,'file')

    % Decrease by 1 day and attempt to download
    dt = dt - days(1);
    [year,month,day] = ymd(dt);
    date = sprintf('%04d%02d%02d',year,month,day);
    
    % Set new paths and filenames based on date
    subdir = sprintf('/%04d/%02d',year,month);
    filename = sprintf('ice_conc_%s_polstere-100_multi_%s1200.nc',hem,date);
    pathname = sprintf('%s%s/%s',ftpdir,subdir,filename);
    download_file(pathname, filename);
    
    current_day = current_day + 1;

  end

  % Determine file existence
  if exist(filename,'file'),
    
    % Write out txt file to indicate the data file that will be used in processing
    write_file(out_dir, original_year, original_doy, filename);

    % Retrieve data from file that was downloaded
    ncid=netcdf.open(filename,'nowrite');
    varid = netcdf.inqVarID(ncid,'lat');
    lat = netcdf.getVar(ncid,varid);
    varid = netcdf.inqVarID(ncid,'lon');
    lon = netcdf.getVar(ncid,varid);
    varid = netcdf.inqVarID(ncid,'ice_conc');
    ice = netcdf.getVar(ncid,varid);
    %        badvalue = netcdf.getAtt(ncid,varid,'_FillValue');
    %        inx=find(ice==badvalue);
    %          if length(inx), ice(inx)=NaN*ones(size(inx)); end;
    scale = netcdf.getAtt(ncid,varid,'scale_factor');
    ice = double(ice)*scale;
    netcdf.close(ncid);

    if isfile(filename), delete(filename); end;

  % File does not exist, this is an error
  else,

    lon=[]; lat=[]; ice=[];
    fprintf(1, 'readOSISAF: OSISAF ice file does not exist: %s.\n', original_pathname);
    fprintf(1, 'readOSISAF: The past %d days of ice data could also not be located.\n', num_days);

  end;

  lon=fliplr(lon); lat=fliplr(lat); ice=fliplr(ice);

end

% Function to download file pathname from OSISAF
function download_file(pathname, filename)
  
  try
      uri = matlab.net.URI(pathname);
  catch
      fprintf(0, 'Error: malformed URL', pathname);
      return
  end

  fprintf(1,'readOSISAF: %s\n',pathname); 
  if isfile(filename), delete(filename); end

  try

    if strcmpi(uri.Scheme, 'ftp')
        % Use FTP commands, this failed on my version there may be some
        % configuration that varies
        ftpobj = ftp(uri.Host);
        download_file = uri.Path{end};
        cd(ftpobj, strjoin(uri.Path(1:end-1), "/"));
        % Previous code had logic to try adding ".gz" if after the first try
        % the file didn't download, we can check here first
        remote_files = dir(ftpobj);
        filenames = {remote_files.name};
        if ismember(filename, filenames)
            mget(ftpobj, download_file);
        elseif ismember([filename, '.gz'], filenames)
            %Add the .gz
            download_file(end+1:end+3) = '.gz';
            filename(end+1:end+3) = '.gz';
            if isfile(filename), delete(filename); end
            mget(ftpobj, download_file);
        else
            fprintf(0, 'Error: remote file %s/[.gz], not found', filename);
        end
        %Rename if desired
        if filename ~= download_file
            movefile(uri.Path(end), filename)
        end
    else
        % Non-FTP --------------------------------

        % Do lightweight read to see if file is present
        request = matlab.net.http.RequestMessage(matlab.net.http.RequestMethod.HEAD);

        % Send the request and get the response
        response = request.send(uri);

        % Check the HTTP status code
        options = weboptions('Timeout', 120);
        if response.StatusCode == matlab.net.http.StatusCode.OK
            websave(filename, pathname, options);
        else
            % Try it with .gz, if it fails nothing else to try
            pathname(end+1:end+3) = '.gz';
            filename(end+1:end+3) = '.gz';
            websave(filename, pathname, options);
        end
    end
  catch er
    % Ignore download errors, will be handled by file existence check
    disp(er)
  end

end

% Function to write the ice file that was located from OSISAF
function write_file(out_dir, year, day, filename)
  
  ice_filename = sprintf('icefiles_%04d_%03d.txt',year,day);
  ice_file = fullfile(out_dir,ice_filename);
  fid = fopen(ice_file, 'a+');
  fprintf(fid, '%s\n', filename);
  fclose(fid);
  fprintf(1, 'readOSISAF: Wrote %s to %s.\n',filename,ice_file);
  
end
