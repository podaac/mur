function makeMUR25_container(year, day, realtime, config)
% MAKEMUR25_CONTAINER Generate 0.25-degree MUR25 SST product for container environment
%
% Usage: makeMUR25_container(year, day, realtime, config)
%
%   year:     4-digit year (numeric)
%   day:      Day of year (1-366)
%   realtime: 1 for NRT, 0 for REA
%   config:   Configuration struct with paths:
%             - cspdir:      Directory containing CSP coefficient files
%             - cspfmt:      CSP file name format
%             - netcdf_dir:  Output directory for NetCDF files
%             - landice_root: Land/ice input directory
%             - static_resources_root: Static resources directory
%             - fortran_bin: Fortran executables directory
%             - region:      Region name (default: 'Global')
%             - hourAna:     Analysis hour (default: 9)
%
% Container paths (mounted from host):
%   /data/output/csp/        - Input CSP coefficient files
%   /data/output/netcdf/     - Output MUR25 NetCDF files
%   /data/input/landice/     - Land/ice masks
%   /data/static-resources/  - Static resources (grids, seasonal)

    fprintf('\n========================================\n');
    fprintf('MUR25 Product Generation\n');
    fprintf('========================================\n');
    fprintf('Year:     %d\n', year);
    fprintf('DOY:      %d\n', day);
    fprintf('Mode:     %s\n', iif(realtime, 'NRT', 'REA'));
    fprintf('========================================\n\n');

    %% Extract configuration
    cspdir = config.cspdir;
    cspfmt = config.cspfmt;
    netcdf_dir = config.netcdf_dir;
    landice_root = config.landice_root;
    static_resources_root = config.static_resources_root;
    fortran_bin = config.fortran_bin;

    if isfield(config, 'region')
        region = config.region;
    else
        region = 'Global';
    end

    if isfield(config, 'hourAna')
        hourAna = config.hourAna;
    else
        hourAna = 9;
    end

    %% MUR25 grid parameters
    % Output grid: 0.25 degree (1440 x 720)
    L = 8;  % Scale level for MUR25 (~0.25 degree)

    box = [-180, 180, -90, 90];
    trimGrid = 0;

    %% Version and naming
    version = '04.2';
    namebody = sprintf('%02d0000-JPL-L4_GHRSST-SSTfnd-MUR25-GLOB-v02.0-fv%s', hourAna, version);
    entryID = ['MUR25-JPL-L4-GLOB-v', version];

    %% Scaling parameters
    sstoffset = 25 + 273.15;
    sstscale = 0.001;
    erroffset = 0.0;
    errscale = 0.01;
    iceoffset = 0.0;
    icescale = 0.01;

    badpixel = int16(-32768);
    minSSTvalue = -1.8 + 273.15;

    %% Processing flags
    errIncluded = 1;
    iceIncluded = 1;
    anomalyIncluded = 1;

    %% Error field parameters
    Lerr = 8;
    uave = 1.7;
    udev = 2.0;
    targetMean = 0.5;
    targetMin = 0.3;

    %% Static files
    % MUR25 grid file (0.25 degree landmask)
    landmaskfile = sprintf('%s/grids/MUR25grid.gds', static_resources_root);

    % Check if MUR25 grid exists, if not provide guidance
    if ~exist(landmaskfile, 'file')
        error(['MUR25_STATIC:GRID_NOT_FOUND\n', ...
               'MUR25 grid file not found: %s\n\n', ...
               'The MUR25grid.gds file is required for 0.25-degree product generation.\n', ...
               'This file defines the land/sea mask at 0.25-degree resolution (1440x720).\n\n', ...
               'To obtain this file:\n', ...
               '  1. Copy from production: /home/tmchin/grids/MUR25grid.gds\n', ...
               '  2. Or generate from the 0.01-degree mask using MURto25 function\n\n', ...
               'Place the file at: %s/grids/MUR25grid.gds'], ...
               landmaskfile, static_resources_root);
    end

    %% Creation date/time
    cdy = str2double(datestr(now, 'yyyy'));
    cdm = str2double(datestr(now, 'mm'));
    cdd = str2double(datestr(now, 'dd'));
    cnH = str2double(datestr(now, 'HH'));
    cnM = str2double(datestr(now, 'MM'));
    cnS = str2double(datestr(now, 'SS'));

    %% Source CSP file path
    [d, m, y] = julian(day, year);
    cspbody = sprintf(['%s/', cspfmt], cspdir, y, m, d, hourAna, region);

    % Verify source coefficient file exists
    cspfile = sprintf('%s.c%02d', cspbody, L);
    if ~exist(cspfile, 'file')
        error('MUR25:CSP_NOT_FOUND', ...
              'Source coefficient file not found: %s\n', cspfile);
    end

    fprintf('Source CSP file: %s\n', cspfile);

    %% Destination directory
    ncsubdir = 'GLOB/JPL/MUR/v4';
    ddir = sprintf('%s/%s/%04d/%03d', netcdf_dir, ncsubdir, year, day);
    if realtime
        ddir = [ddir, 'nrt'];
    end

    if ~exist(ddir, 'dir')
        mkdir(ddir);
    end

    fprintf('Output directory: %s\n\n', ddir);

    %% Process ice data
    fprintf('Processing ice data for MUR25...\n');

    if iceIncluded
        icemap = makeMUR25ice_container(year, day, landice_root, static_resources_root);
        fprintf('  Ice data loaded: %d x %d\n', size(icemap, 1), size(icemap, 2));
    end

    %% Load landmask
    fprintf('Loading MUR25 landmask...\n');

    f = fopen(landmaskfile, 'r');
    if f < 0
        error('Cannot open landmask file: %s', landmaskfile);
    end

    % Record 1: dimensions
    fread(f, 1, 'uint32');  % skip Fortran record marker
    ii = fread(f, 1, 'int32=>int32');
    jj = fread(f, 1, 'int32=>int32');
    fread(f, 1, 'uint32');  % skip Fortran record marker

    % Record 2: mask and coordinates
    fread(f, 1, 'uint32');  % skip Fortran record marker
    mask = fread(f, [ii, jj], 'int8=>int8');
    lon = fread(f, ii, 'float32=>single');
    lat = fread(f, jj, 'float32=>single');
    fread(f, 1, 'uint32');  % skip Fortran record marker
    fclose(f);

    mlon = lon;
    mlat = lat;
    clear lon lat;

    fprintf('  Landmask loaded: %d x %d\n', ii, jj);

    % Update landmask with ice data
    if iceIncluded
        knx = find(icemap > 0 & mask == 1);
        if ~isempty(knx)
            mask(knx) = int8(9);  % open-sea with ice
        end
        knx = find(icemap > 0 & mask == 5);
        if ~isempty(knx)
            mask(knx) = int8(13);  % open-lake with ice
        end
    end

    %% Interpolate SST from CSP file using spgrid
    fprintf('Interpolating SST to 0.25-degree grid...\n');

    % Write spgrid namelist
    f = fopen('spgrid.nml', 'w');
    fprintf(f, ' $input\n');
    fprintf(f, 'offset=%f\n', sstoffset);
    fprintf(f, 'sscale=%f\n', sstscale);
    fprintf(f, 'minsst=%f\n', minSSTvalue);
    fprintf(f, 'nlist=%d\n', 1);
    fprintf(f, 'coeffilelist=\n');
    fprintf(f, '''%d'',''%s'',\n', L, cspfile);
    fprintf(f, 'gridfile=\n''%s''\n', landmaskfile);
    fprintf(f, ' $end\n');
    fclose(f);

    % Execute spgrid
    spgrid_exe = sprintf('%s/spgrid', fortran_bin);
    [status, result] = system(spgrid_exe);
    if status ~= 0
        error('spgrid execution failed:\n%s', result);
    end

    % Read spgrid output
    fortfile = sprintf('./fort.%d', L + 180);
    f = fopen(fortfile, 'r');
    if f < 0
        error('Cannot open spgrid output: %s', fortfile);
    end

    % Record 1: dimensions
    fread(f, 1, 'uint32');
    ii_out = fread(f, 1, 'int32=>int32');
    jj_out = fread(f, 1, 'int32=>int32');
    fread(f, 1, 'uint32');

    % Record 2: scaling parameters
    fread(f, 1, 'uint32');
    offset = fread(f, 1, 'float32=>single');
    sscale_out = fread(f, 1, 'float32=>single');
    fread(f, 1, 'uint32');

    % Record 3: SST data and coordinates
    fread(f, 1, 'uint32');
    msst = fread(f, [ii_out, jj_out], 'int16=>int16');
    mlon = fread(f, ii_out, 'float32=>single');
    mlat = fread(f, jj_out, 'float32=>single');
    fread(f, 1, 'uint32');
    fclose(f);

    % Clean up fort file
    delete(fortfile);

    fprintf('  SST interpolated: %d x %d\n', ii_out, jj_out);

    %% Compute SST anomaly
    if anomalyIncluded
        fprintf('Computing SST anomaly...\n');

        ssta = double(msst) * sscale_out + offset;
        seasonal_sst = makeSeasonal_container(day, static_resources_root);
        ssta = ssta - seasonal_sst;

        fprintf('  Anomaly computed\n');
    end

    %% Process error field
    if errIncluded
        fprintf('Interpolating error field...\n');

        % Write spgrid namelist for error
        f = fopen('spgrid.nml', 'w');
        fprintf(f, ' $input\n');
        fprintf(f, 'offset=%f\n', uave*uave + 273.15);
        fprintf(f, 'sscale=%f\n', sstscale);
        fprintf(f, 'minsst=%f\n', 0.0 + 273.15);
        fprintf(f, 'nlist=%d\n', 1);
        fprintf(f, 'coeffilelist=\n');
        errfile = sprintf('%s.u%02d', cspbody, Lerr);
        fprintf(f, '''%d'',''%s'',\n', Lerr, errfile);
        fprintf(f, 'gridfile=\n''%s''\n', landmaskfile);
        fprintf(f, ' $end\n');
        fclose(f);

        if exist(errfile, 'file')
            [status, ~] = system(spgrid_exe);
            if status == 0
                % Read error output
                fortfile = sprintf('./fort.%d', Lerr + 180);
                f = fopen(fortfile, 'r');
                if f > 0
                    fread(f, 1, 'uint32');
                    fread(f, 2, 'int32');
                    fread(f, 1, 'uint32');

                    fread(f, 1, 'uint32');
                    fread(f, 2, 'float32');
                    fread(f, 1, 'uint32');

                    fread(f, 1, 'uint32');
                    err = fread(f, [ii_out, jj_out], 'int16=>int16');
                    fread(f, 1, 'uint32');
                    fclose(f);

                    delete(fortfile);

                    err(err == -32768) = NaN;
                    err = sqrt(double(err) * sscale_out + offset - 273.15);
                    err = (err - uave) / udev * (targetMean - targetMin) + targetMean;
                    err = single(err);

                    fprintf('  Error field interpolated\n');
                else
                    warning('Could not read error field output');
                    errIncluded = 0;
                end
            else
                warning('Error field interpolation failed');
                errIncluded = 0;
            end
        else
            warning('Error coefficient file not found: %s', errfile);
            errIncluded = 0;
        end
    end

    %% Get source data info
    inputsfile = sprintf('%s_inputs.txt', cspbody);
    if exist(inputsfile, 'file')
        [sourcedata, sensordata, platformdata] = txt2sourcedata(inputsfile, iceIncluded);
    else
        sourcedata = 'MUR SST data';
        sensordata = 'Multiple';
        platformdata = 'Multiple';
    end

    %% Revert shore-line flags to land
    mask(mask == 3 | mask == 7 | mask == 11 | mask == 15) = int8(2);

    %% Write NetCDF file
    fprintf('Writing MUR25 NetCDF file...\n');

    ncbasename = sprintf('%04d%02d%02d%s.nc', y, m, d, namebody);
    ncname = sprintf('%s/%s', ddir, ncbasename);

    % NetCDF parameters
    nc4d = 7;  % deflation level
    resolution = '0.25 degrees';
    resfloat = single(0.25);

    % Create NetCDF file
    mode = netcdf.getConstant('NETCDF4');
    ncid = netcdf.create(ncname, mode);

    % Define dimensions
    d0 = netcdf.defDim(ncid, 'time', 1);
    d1 = netcdf.defDim(ncid, 'lat', length(mlat));
    d2 = netcdf.defDim(ncid, 'lon', length(mlon));

    % Define variables and attributes
    % Time
    v0 = netcdf.defVar(ncid, 'time', 4, [d0]);
    netcdf.putAtt(ncid, v0, 'long_name', 'reference time of sst field');
    netcdf.putAtt(ncid, v0, 'standard_name', 'time');
    netcdf.putAtt(ncid, v0, 'coverage_content_type', 'coordinate');
    netcdf.putAtt(ncid, v0, 'axis', 'T');
    netcdf.putAtt(ncid, v0, 'units', 'seconds since 1981-01-01 00:00:00 UTC');
    netcdf.putAtt(ncid, v0, 'comment', 'Nominal time of analyzed fields');

    % Latitude
    v1 = netcdf.defVar(ncid, 'lat', 5, [d1]);
    netcdf.defVarDeflate(ncid, v1, true, true, nc4d);
    netcdf.putAtt(ncid, v1, 'long_name', 'latitude');
    netcdf.putAtt(ncid, v1, 'standard_name', 'latitude');
    netcdf.putAtt(ncid, v1, 'coverage_content_type', 'coordinate');
    netcdf.putAtt(ncid, v1, 'axis', 'Y');
    netcdf.putAtt(ncid, v1, 'units', 'degrees_north');
    netcdf.putAtt(ncid, v1, 'valid_min', single(box(3)));
    netcdf.putAtt(ncid, v1, 'valid_max', single(box(4)));

    % Longitude
    v2 = netcdf.defVar(ncid, 'lon', 5, [d2]);
    netcdf.defVarDeflate(ncid, v2, true, true, nc4d);
    netcdf.putAtt(ncid, v2, 'long_name', 'longitude');
    netcdf.putAtt(ncid, v2, 'standard_name', 'longitude');
    netcdf.putAtt(ncid, v2, 'coverage_content_type', 'coordinate');
    netcdf.putAtt(ncid, v2, 'axis', 'X');
    netcdf.putAtt(ncid, v2, 'units', 'degrees_east');
    netcdf.putAtt(ncid, v2, 'valid_min', single(box(1)));
    netcdf.putAtt(ncid, v2, 'valid_max', single(box(2)));

    % Analysed SST
    v3 = netcdf.defVar(ncid, 'analysed_sst', 3, [d2, d1, d0]);
    netcdf.defVarChunking(ncid, v3, 'CHUNKED', [1440, 720, 1]);
    netcdf.defVarDeflate(ncid, v3, true, true, nc4d);
    netcdf.putAtt(ncid, v3, 'long_name', 'analysed sea surface temperature');
    netcdf.putAtt(ncid, v3, 'standard_name', 'sea_surface_foundation_temperature');
    netcdf.putAtt(ncid, v3, 'coverage_content_type', 'physicalMeasurement');
    netcdf.putAtt(ncid, v3, 'units', 'kelvin');
    netcdf.defVarFill(ncid, v3, false, int16(-32768));
    netcdf.putAtt(ncid, v3, 'add_offset', sstoffset);
    netcdf.putAtt(ncid, v3, 'scale_factor', sstscale);
    netcdf.putAtt(ncid, v3, 'valid_min', int16(-32767));
    netcdf.putAtt(ncid, v3, 'valid_max', int16(32767));
    if realtime
        str = 'Interim near-real-time (nrt) version using Multi-Resolution Variational Analysis (MRVA) method for interpolation';
    else
        str = '"Final" version using Multi-Resolution Variational Analysis (MRVA) method for interpolation';
    end
    netcdf.putAtt(ncid, v3, 'comment', str);
    netcdf.putAtt(ncid, v3, 'coordinates', 'lon lat');
    netcdf.putAtt(ncid, v3, 'source', sourcedata);

    % Analysis error
    if errIncluded
        v4 = netcdf.defVar(ncid, 'analysis_error', 3, [d2, d1, d0]);
        netcdf.defVarChunking(ncid, v4, 'CHUNKED', [1440, 720, 1]);
        netcdf.defVarDeflate(ncid, v4, true, true, nc4d);
        netcdf.putAtt(ncid, v4, 'long_name', 'estimated error standard deviation of analysed_sst');
        netcdf.putAtt(ncid, v4, 'coverage_content_type', 'qualityInformation');
        netcdf.putAtt(ncid, v4, 'units', 'kelvin');
        netcdf.defVarFill(ncid, v4, false, int16(-32768));
        netcdf.putAtt(ncid, v4, 'add_offset', erroffset);
        netcdf.putAtt(ncid, v4, 'scale_factor', errscale);
        netcdf.putAtt(ncid, v4, 'valid_min', int16(0));
        netcdf.putAtt(ncid, v4, 'valid_max', int16(32767));
        netcdf.putAtt(ncid, v4, 'comment', 'uncertainty in "analysed_sst"');
        netcdf.putAtt(ncid, v4, 'coordinates', 'lon lat');
    end

    % Mask
    v5 = netcdf.defVar(ncid, 'mask', 1, [d2, d1, d0]);
    netcdf.defVarChunking(ncid, v5, 'CHUNKED', [1440, 720, 1]);
    netcdf.defVarDeflate(ncid, v5, true, true, nc4d);
    netcdf.putAtt(ncid, v5, 'long_name', 'sea/land field composite mask');
    netcdf.putAtt(ncid, v5, 'coverage_content_type', 'referenceInformation');
    netcdf.defVarFill(ncid, v5, false, int8(-128));
    netcdf.putAtt(ncid, v5, 'valid_min', int8(1));
    netcdf.putAtt(ncid, v5, 'valid_max', int8(31));
    netcdf.putAtt(ncid, v5, 'flag_masks', int8([1, 2, 4, 8, 16]));
    netcdf.putAtt(ncid, v5, 'flag_meanings', 'water land optional_lake_surface sea_ice optional_river_surface');
    netcdf.putAtt(ncid, v5, 'comment', 'flag interpretation as integer values: 1=water, 2=land, 5=lake, 9=water with ice, 13=lake with ice');
    netcdf.putAtt(ncid, v5, 'coordinates', 'lon lat');
    netcdf.putAtt(ncid, v5, 'source', 'GMT "grdlandmask", ice flag from sea_ice_fraction data');

    % Sea ice fraction
    if iceIncluded
        v6 = netcdf.defVar(ncid, 'sea_ice_fraction', 1, [d2, d1, d0]);
        netcdf.defVarChunking(ncid, v6, 'CHUNKED', [1440, 720, 1]);
        netcdf.defVarDeflate(ncid, v6, true, true, nc4d);
        netcdf.putAtt(ncid, v6, 'long_name', 'sea ice area fraction');
        netcdf.putAtt(ncid, v6, 'standard_name', 'sea_ice_area_fraction');
        netcdf.putAtt(ncid, v6, 'coverage_content_type', 'auxiliaryInformation');
        netcdf.defVarFill(ncid, v6, false, int8(-128));
        netcdf.putAtt(ncid, v6, 'add_offset', iceoffset);
        netcdf.putAtt(ncid, v6, 'scale_factor', icescale);
        netcdf.putAtt(ncid, v6, 'valid_min', int8(0));
        netcdf.putAtt(ncid, v6, 'valid_max', int8(100));
        netcdf.putAtt(ncid, v6, 'source', 'EUMETSAT OSI-SAF, copyright EUMETSAT');
        netcdf.putAtt(ncid, v6, 'comment', 'ice fraction is a dimensionless quantity between 0 and 1; interpolated by nearest neighbor approach');
        netcdf.putAtt(ncid, v6, 'coordinates', 'lon lat');
    end

    % SST anomaly
    if anomalyIncluded
        v8 = netcdf.defVar(ncid, 'sst_anomaly', 3, [d2, d1, d0]);
        netcdf.defVarChunking(ncid, v8, 'CHUNKED', [1440, 720, 1]);
        netcdf.defVarDeflate(ncid, v8, true, true, nc4d);
        netcdf.putAtt(ncid, v8, 'long_name', 'SST anomaly from a seasonal SST climatology based on the MUR data over 2003-2014 period');
        netcdf.putAtt(ncid, v8, 'coverage_content_type', 'auxiliaryInformation');
        netcdf.putAtt(ncid, v8, 'units', 'kelvin');
        netcdf.defVarFill(ncid, v8, false, int16(-32768));
        netcdf.putAtt(ncid, v8, 'add_offset', 0.0);
        netcdf.putAtt(ncid, v8, 'scale_factor', sstscale);
        netcdf.putAtt(ncid, v8, 'valid_min', int16(-32767));
        netcdf.putAtt(ncid, v8, 'valid_max', int16(32767));
        netcdf.putAtt(ncid, v8, 'comment', 'anomaly reference to the day-of-year average between 2003 and 2014');
        netcdf.putAtt(ncid, v8, 'coordinates', 'lon lat');
    end

    %% Global attributes
    varid = netcdf.getConstant('GLOBAL');
    if realtime
        version_str = [version, 'nrt'];
    else
        version_str = version;
    end

    netcdf.putAtt(ncid, varid, 'Conventions', 'CF-1.7, ACDD-1.3');
    if realtime
        str = 'Daily 0.25-degree MUR SST, Interim near-real-time (nrt) product';
    else
        str = 'Daily 0.25-degree MUR SST, Final product';
    end
    netcdf.putAtt(ncid, varid, 'title', str);
    netcdf.putAtt(ncid, varid, 'summary', 'A low-resolution version of the MUR SST analysis, a merged, multi-sensor L4 Foundation SST analysis product from JPL.');
    netcdf.putAtt(ncid, varid, 'keywords', 'Oceans > Ocean Temperature > Sea Surface Temperature');
    netcdf.putAtt(ncid, varid, 'keywords_vocabulary', 'NASA Global Change Master Directory (GCMD) Science Keywords');
    netcdf.putAtt(ncid, varid, 'standard_name_vocabulary', 'NetCDF Climate and Forecast (CF) Metadata Convention');
    netcdf.putAtt(ncid, varid, 'history', 'This is an intermediate analysis (called "sibling") resulted during production of the full-resolution (0.01 horizontal degrees) MUR SST analysis.');
    netcdf.putAtt(ncid, varid, 'source', sourcedata);
    netcdf.putAtt(ncid, varid, 'platform', platformdata);
    netcdf.putAtt(ncid, varid, 'instrument', sensordata);
    netcdf.putAtt(ncid, varid, 'sensor', sensordata);
    netcdf.putAtt(ncid, varid, 'processing_level', 'L4');
    netcdf.putAtt(ncid, varid, 'cdm_data_type', 'grid');
    netcdf.putAtt(ncid, varid, 'product_version', version_str);
    netcdf.putAtt(ncid, varid, 'references', 'Chin et al. (2017) "Remote Sensing of Environment", volume 200, pages 154-169. http://dx.doi.org/10.1016/j.rse.2017.07.029');
    netcdf.putAtt(ncid, varid, 'creator_name', 'JPL MUR SST project');
    netcdf.putAtt(ncid, varid, 'creator_email', 'ghrsst@podaac.jpl.nasa.gov');
    netcdf.putAtt(ncid, varid, 'creator_url', 'http://mur.jpl.nasa.gov');
    netcdf.putAtt(ncid, varid, 'creator_institution', 'Jet Propulsion Laboratory');
    netcdf.putAtt(ncid, varid, 'institution', 'Jet Propulsion Laboratory');
    netcdf.putAtt(ncid, varid, 'project', 'NASA MEaSUREs and COVERAGE');
    netcdf.putAtt(ncid, varid, 'program', 'NASA Earth Science Data and Information System (ESDIS)');

    % Geospatial bounds
    netcdf.putAtt(ncid, varid, 'geospatial_lat_min', single(box(3)));
    netcdf.putAtt(ncid, varid, 'geospatial_lat_max', single(box(4)));
    netcdf.putAtt(ncid, varid, 'geospatial_lon_min', single(box(1)));
    netcdf.putAtt(ncid, varid, 'geospatial_lon_max', single(box(2)));
    netcdf.putAtt(ncid, varid, 'geospatial_lat_units', 'degrees north');
    netcdf.putAtt(ncid, varid, 'geospatial_lat_resolution', resfloat);
    netcdf.putAtt(ncid, varid, 'geospatial_lon_units', 'degrees east');
    netcdf.putAtt(ncid, varid, 'geospatial_lon_resolution', resfloat);

    % Time metadata
    timestamp = sprintf('%04d%02d%02dT%02d%02d%02dZ', cdy, cdm, cdd, cnH, cnM, cnS);
    netcdf.putAtt(ncid, varid, 'date_created', timestamp);

    [d_t, m_t, y_t] = julian(day, year);
    hA = hourAna;
    mjd = julian(d_t, m_t, y_t, 3) + hA/24;
    timestamp = sprintf('%04d%02d%02dT%02d0000Z', y_t, m_t, d_t, hA);
    netcdf.putAtt(ncid, varid, 'start_time', timestamp);
    netcdf.putAtt(ncid, varid, 'stop_time', timestamp);

    [d_t, m_t, y_t] = julian(mjd - 12/24);
    hA_t = mod(hourAna - 12, 24);
    timestamp = sprintf('%04d%02d%02dT%02d0000Z', y_t, m_t, d_t, hA_t);
    netcdf.putAtt(ncid, varid, 'time_coverage_start', timestamp);

    [d_t, m_t, y_t] = julian(mjd + 12/24);
    timestamp = sprintf('%04d%02d%02dT%02d0000Z', y_t, m_t, d_t, hA_t);
    netcdf.putAtt(ncid, varid, 'time_coverage_end', timestamp);
    netcdf.putAtt(ncid, varid, 'time_coverage_resolution', 'P1D');

    netcdf.putAtt(ncid, varid, 'license', 'These data are available free of charge under data policy of JPL PO.DAAC.');
    netcdf.putAtt(ncid, varid, 'id', entryID);
    netcdf.putAtt(ncid, varid, 'uuid', '27665bc0-d5fc-11e1-9b23-0800200c9a66');

    if realtime
        str = 'near real time (nrt) version created at nominal 1-day latency.';
    else
        str = 'created at nominal 4-day latency; replaced nrt (1-day latency) version.';
    end
    netcdf.putAtt(ncid, varid, 'comment', str);

    netcdf.putAtt(ncid, varid, 'naming_authority', 'org.ghrsst');
    netcdf.putAtt(ncid, varid, 'gds_version_id', '2.0');
    netcdf.putAtt(ncid, varid, 'netcdf_version_id', version_str);
    netcdf.putAtt(ncid, varid, 'spatial_resolution', resolution);
    netcdf.putAtt(ncid, varid, 'publisher_name', 'GHRSST Project Office');
    netcdf.putAtt(ncid, varid, 'publisher_url', 'https://www.ghrsst.org');
    netcdf.putAtt(ncid, varid, 'publisher_email', 'gpc@ghrsst.org');
    netcdf.putAtt(ncid, varid, 'file_quality_level', int32(3));
    netcdf.putAtt(ncid, varid, 'metadata_link', ['http://podaac.jpl.nasa.gov/ws/metadata/dataset/?format=iso&shortName=', entryID]);
    netcdf.putAtt(ncid, varid, 'acknowledgment', 'Please acknowledge the use of these data with the following statement: These data were provided by JPL under support by NASA MEaSUREs and COVERAGE programs.');

    netcdf.endDef(ncid);

    %% Write data
    % Time
    [d_t, m_t, y_t] = julian(day, year);
    sec = (julian(d_t, m_t, y_t, 3) - julian(1, 1, 1981, 3) + hourAna/24) * 86400;
    netcdf.putVar(ncid, v0, int32(sec));

    % Coordinates
    netcdf.putVar(ncid, v1, single(mlat));
    netcdf.putVar(ncid, v2, single(mlon));

    % SST
    netcdf.putVar(ncid, v3, msst);

    inx = find(msst ~= badpixel);

    % Error
    if errIncluded
        data = ones(size(msst), 'int16') * int16(-32768);
        data(inx) = int16((err(inx) - erroffset) / errscale);
        netcdf.putVar(ncid, v4, data);
    end

    % Mask
    netcdf.putVar(ncid, v5, mask);

    % Ice fraction
    if iceIncluded
        data = ones(size(icemap), 'int8') * int8(-128);
        jnx = find(icemap >= 0 & icemap <= 100);
        data(jnx) = int8(icemap(jnx));
        netcdf.putVar(ncid, v6, data);
    end

    % Anomaly
    if anomalyIncluded
        inx = find(msst ~= badpixel);
        data = ones(size(ssta), 'int16') * int16(-32768);
        data(inx) = int16(ssta(inx) / sstscale);
        netcdf.putVar(ncid, v8, data);
    end

    netcdf.close(ncid);

    %% Generate MD5 checksum
    fprintf('Generating MD5 checksum...\n');

    olddir = pwd;
    cd(ddir);
    [~, ~] = system(sprintf('md5sum %s > %s.md5', ncbasename, ncbasename));
    cd(olddir);

    fprintf('  ✓ MUR25 NetCDF created: %s\n', ncname);
    fprintf('  ✓ MD5 checksum created: %s.md5\n\n', ncname);

    % Clean up
    if exist('spgrid.nml', 'file')
        delete('spgrid.nml');
    end

    fprintf('========================================\n');
    fprintf('MUR25 Generation Complete!\n');
    fprintf('========================================\n');

end

%% Helper function: inline if
function out = iif(condition, true_val, false_val)
    if condition
        out = true_val;
    else
        out = false_val;
    end
end

%% Helper function: makeMUR25ice for container
function icemap = makeMUR25ice_container(year, doy, landice_root, static_resources_root)
% Generate MUR25 ice map from landice data by downsampling
%
% Reads the full-resolution landice file and downsamples to 0.25 degree

    % Check for cached MUR25 ice file first
    icecachedir = sprintf('%s/ice25', landice_root);
    icefile = sprintf('%s/icemap%04d_%03d.ice', icecachedir, year, doy);

    if exist(icefile, 'file')
        % Read cached file
        f = fopen(icefile, 'r');
        fread(f, 1, 'uint32');  % record marker
        ii = fread(f, 1, 'int32');
        jj = fread(f, 1, 'int32');
        fread(f, 1, 'uint32');  % record marker
        fread(f, 1, 'uint32');  % record marker
        icemap = fread(f, [ii, jj], 'int8=>double');
        fread(f, 1, 'uint32');  % record marker
        fclose(f);
        return;
    end

    % Generate from full-resolution landice data
    gridfile = sprintf('%s/%04d/landiceP01_%04d_%03d.gds.gz', landice_root, year, year, doy);
    tmpgridfile = sprintf('/tmp/landice_%04d_%03d.gds', year, doy);

    if exist(gridfile, 'file')
        % Decompress
        system(sprintf('zcat -f %s > %s', gridfile, tmpgridfile));

        f = fopen(tmpgridfile, 'r');
        if f > 0
            % Read dimensions
            fread(f, 1, 'uint32');
            ii = fread(f, 1, 'int32');
            jj = fread(f, 1, 'int32');
            fread(f, 1, 'uint32');

            % Read mask and coordinates
            fread(f, 1, 'uint32');
            mask = fread(f, [ii, jj], 'int8');
            fread(f, ii, 'float32');  % lon
            fread(f, jj, 'float32');  % lat
            fread(f, 1, 'uint32');

            % Read ice map
            fread(f, 1, 'uint32');
            icemap_full = fread(f, [ii, jj], 'int8=>double');
            fread(f, 1, 'uint32');

            fclose(f);
            delete(tmpgridfile);

            % Downsample using MURto25
            icemap = MURto25(icemap_full);

            % Cache the result
            if ~exist(icecachedir, 'dir')
                mkdir(icecachedir);
            end

            f = fopen(icefile, 'w');
            if f > 0
                [ii25, jj25] = size(icemap);
                fwrite(f, 8, 'uint32');  % record marker (2 ints = 8 bytes)
                fwrite(f, ii25, 'int32');
                fwrite(f, jj25, 'int32');
                fwrite(f, 8, 'uint32');  % record marker
                fwrite(f, ii25*jj25, 'uint32');  % record marker
                fwrite(f, int8(icemap), 'int8');
                fwrite(f, ii25*jj25, 'uint32');  % record marker
                fclose(f);
            end
        else
            warning('Could not read landice file, returning empty ice map');
            icemap = zeros(1440, 720);
        end
    else
        % Try uncompressed version
        gridfile_unc = sprintf('%s/%04d/landiceP01_%04d_%03d.gds', landice_root, year, year, doy);
        if exist(gridfile_unc, 'file')
            f = fopen(gridfile_unc, 'r');
            % ... same reading logic ...
            warning('Reading uncompressed landice not fully implemented');
            icemap = zeros(1440, 720);
            if f > 0, fclose(f); end
        else
            warning('Landice file not found: %s', gridfile);
            icemap = zeros(1440, 720);
        end
    end
end

%% Helper function: makeSeasonal for container
function sst = makeSeasonal_container(doy, static_resources_root)
% Get MUR25 seasonal climatology for the specified day of year
%
% First tries to read pre-computed MUR25 seasonal file.
% If not found, reads full-resolution seasonal and downsamples.

    if doy == 366
        doy = 365;
    end

    % Check for pre-computed MUR25 seasonal file
    seasonaldir = sprintf('%s/seasonal25', static_resources_root);
    seasonalfile = sprintf('%s/mur_%03d.mat', seasonaldir, doy);

    if exist(seasonalfile, 'file')
        data = load(seasonalfile);
        sst = data.sst;
        return;
    end

    % Read full-resolution and downsample
    seasonal_full = readSeasonal(doy);
    sst = MURto25(seasonal_full);

    % Cache the result
    if ~exist(seasonaldir, 'dir')
        mkdir(seasonaldir);
    end

    save(seasonalfile, 'sst');
end
