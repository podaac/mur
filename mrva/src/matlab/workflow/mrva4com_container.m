function mrva4com_container(year, day, realtime, config_file)
% MRVA4COM_CONTAINER Containerized version of mrva4com.m
%
% Container entry point for MRVA processing.
%
% Usage: mrva4com_container(year, day, realtime, config_file)
%   year:        4-digit year (numeric or string)
%   day:         Day of year (numeric or string, 1-366)
%   realtime:    'nrt' or 'rea' or 0/1 (NRT=1, REA=0)
%   config_file: Path to a JSON config file (already localized -- see
%                common/bin/localize.sh -- containing every resolved input
%                this run needs: polar_cap_edge_file, mur25_grid_file
%                (optional), seasonal_file, landice_ice_p011_file,
%                landice_grid_p01_file, landice_icefiles_p011_file,
%                sensor_inputs_root (materialized from --sensor-inputs-manifest),
%                prior_csp_file (optional), l4_reference_root (optional),
%                sensors
%                (optional JSON array), debug (optional). This is purely an
%                internal handoff detail from entrypoint.sh -- the
%                container's own CLI is still all named flags; see
%                documentation/INPUT_CONTRACT.md.
%
% Container paths (mounted from host):
%   /data/output/csp/    - Coefficient files output (CSP format)
%   /data/output/netcdf/ - Final NetCDF4 products (GHRSST L4)
%   /data/cache/         - Temporary working files (BIQ, intermediate)
%   /data/logs/          - Execution logs
%
% This function adapts mrva4com.m for containerized execution by:
%   - Accepting command-line arguments instead of global variables
%   - Using explicit, already-resolved input paths (config_file) instead of
%     hardcoded /nas2, /nas4, or /data/static-resources conventions
%   - Simplifying directory structure for container environment

    %% Parse arguments
    if ischar(year), year = str2double(year); end
    if ischar(day), day = str2double(day); end

    % Parse realtime argument
    if ischar(realtime)
        if strcmpi(realtime, 'nrt')
            realtime = 1;
        elseif strcmpi(realtime, 'rea')
            realtime = 0;
        else
            error('Invalid mode: %s (must be "nrt" or "rea")', realtime);
        end
    end

    % Validate inputs
    if isnan(year) || year < 1900 || year > 2100
        error('Invalid year: %d', year);
    end
    if isnan(day) || day < 1 || day > 366
        error('Invalid day of year: %d', day);
    end

    config = jsondecode(fileread(config_file));

    % Parse debug flag (from config or environment variable)
    debugMode = false;
    if isfield(config, 'debug') && ~isempty(config.debug)
        debugMode = logical(config.debug);
    elseif ~isempty(getenv('MRVA_DEBUG'))
        debugMode = str2double(getenv('MRVA_DEBUG')) == 1;
    end

    fprintf('========================================\n');
    fprintf('MRVA Container Processing\n');
    fprintf('========================================\n');
    fprintf('Year:     %d\n', year);
    fprintf('DOY:      %d\n', day);
    fprintf('Mode:     %s\n', iif(realtime, 'NRT (Near Real-Time)', 'REA (Reanalysis)'));
    fprintf('Debug:    %s\n', iif(debugMode, 'ENABLED', 'disabled'));
    fprintf('========================================\n\n');

    %% Container path mapping
    % Binary paths
    fortran_bin = '/opt/mrva/bin';  % Fortran executables location

    % Sensor fan-in: materialized by entrypoint.sh's localize_manifest from
    % --sensor-inputs-manifest into <sensor>/<year>/<file> subdirectories --
    % reproduces exactly the layout the [bic_root, '/AMSR2R']-style
    % concatenation below already expects, so that code is unchanged.
    sensor_inputs_root = config.sensor_inputs_root;

    % Output paths
    csp_basedir = '/data/output/csp';
    netcdf_dir = '/data/output/netcdf';

    % Working paths
    bipdir = '/data/cache/bip';
    mapdir = '/data/cache/mrva4map';
    logdir = '/data/logs';

    % Create required directories
    if ~exist(bipdir, 'dir'), mkdir(bipdir); end
    if ~exist(mapdir, 'dir'), mkdir(mapdir); end
    if ~exist(logdir, 'dir'), mkdir(logdir); end
    if ~exist(csp_basedir, 'dir'), mkdir(csp_basedir); end
    if ~exist(netcdf_dir, 'dir'), mkdir(netcdf_dir); end

    %% Processing parameters (from original mrva4com.m)
    L0 = 2;
    LF = 11;
    outL = 10;
    outL4 = 11;

    % Temporal decay parameters (scale-dependent, in hours)
    decay = [48*ones(1,6), 42, 36, 30, 24, 18, 12];

    bgfile = '';
    coefile = '';

    hourAna = 9;  % UTC analysis time
    sstOffset = 273.15;  % Kelvin to Celsius conversion

    % Region and spatial domain
    region = 'Global';
    box = [-180., 180., -90., 90.];

    % Processing flags
    netcdfFlag = 1;
    trimbipFlag = 1;
    biasbipFlag = 1;
    prepbipFlag = 0;
    icecapFlag = 1;
    hiresgridFlag = 1;
    delbipFlag = 1;

    % Output file format
    cspfmt = '%04d%02d%02d%02d_MRVA4_%s';

    % Map/grid file (for spgrid)
    outgridfile = '/app/matlab/workflow/Global10km.out';

    % Map output parameters
    mapL0 = outL;
    mapLF = outL;
    mapbody = 'MUR_Global_1km';
    maptime0 = '000000Z';
    maptime1 = '180000Z';

    %% Sensor configuration
    % Reference data (for makeref.m - excludes real-time sensors)
    % Every sensor's input directory is sensor_inputs_root/<SENSOR> uniformly
    % -- IQUAM0 included, matching how build_mrva_sensor_manifest()
    % (run_mur_pipeline.py) and run_mur_maap.py materialize its manifest
    % entries under a per-sensor subdirectory, same as every satellite
    % sensor. (Previously IQUAM0 used sensor_inputs_root directly with no
    % subdirectory, which no longer matches the manifest's uniform layout.)
    refdata = {
        'IQUAM0', [sensor_inputs_root, '/IQUAM0'], 'Global', 0, 6, 3
    };

    % Main sensor configuration
    % Format: {sensor_name, input_directory, region, La, Lb, dayrange}
    all_sensors = {
        'IQUAM0', [sensor_inputs_root, '/IQUAM0'],   'Global', 0, 6, 3;
        'AMSR2R', [sensor_inputs_root, '/AMSR2R'],   'Global', 2, 8, 2;
        'MODISA', [sensor_inputs_root, '/MODISA'],   'Global', 2, 12, 2;
        'MODIST', [sensor_inputs_root, '/MODIST'],   'Global', 2, 12, 2;
        'AVMTAG', [sensor_inputs_root, '/AVMTAG'],   'Global', 2, 9, 2;
        'AVMTBG', [sensor_inputs_root, '/AVMTBG'],   'Global', 2, 9, 2;
    };

    if isfield(config, 'sensors') && ~isempty(config.sensors)
        % config.sensors is a JSON array of sensor names, e.g. ["IQUAM0","AMSR2R"]
        sensor_names = config.sensors;
        if ischar(sensor_names)
            sensor_names = {sensor_names};
        end

        sensors = {};
        for i = 1:length(sensor_names)
            name = strtrim(sensor_names{i});
            idx = find(strcmp(all_sensors(:,1), name));
            if ~isempty(idx)
                sensors = [sensors; all_sensors(idx,:)];
            else
                warning('Unknown sensor: %s (skipping)', name);
            end
        end

        if isempty(sensors)
            error('No valid sensors specified in config.sensors');
        end
    else
        % Default: all sensors
        sensors = all_sensors;
    end

    coedir = '';  % Wind data directory (optional)

    fprintf('Active sensors: %d\n', size(sensors, 1));
    for n = 1:size(sensors, 1)
        fprintf('  %d. %s (La=%d, Lb=%d, dayrange=%d)\n', ...
                n, sensors{n,1}, sensors{n,4}, sensors{n,5}, sensors{n,6});
    end
    fprintf('\n');

    %% Main output directory setup
    cspdir = sprintf('%s/%04d', csp_basedir, year);
    if ~exist(cspdir, 'dir')
        mkdir(cspdir);
    end

    [d, m, y] = julian(day, year);
    cspbody = sprintf(['%s/', cspfmt], cspdir, y, m, d, hourAna, region);

    %% Make *.bip/biq files
    fprintf('Stage 1: Creating BIQ files from sensor data...\n');

    % Main datasets
    logfile = makebiq(sensors, year, day, hourAna, box, bipdir, coedir);

    if exist(logfile, 'file')
        if realtime
            % Add realtime marker
            realtimemsg = 'RealTime 0 0 0 (realtime if this line exists)';
            system(sprintf('echo "%s" > /tmp/rtline.txt', realtimemsg));
            system(sprintf('cat %s >> /tmp/rtline.txt', logfile));
            system(sprintf('mv /tmp/rtline.txt %s', logfile));
        end
        name = sprintf('%s_inputs.txt', cspbody);
        system(sprintf('mv %s %s', logfile, name));
    end

    % Reference data (if different from main sensors)
    makebiq(refdata, year, day, hourAna, box, bipdir);

    fprintf('  ✓ BIQ files created\n\n');

    % Validate that we have actual data before proceeding
    fprintf('Validating BIQ files contain data...\n');
    total_data_points = 0;
    biq_files = dir(sprintf('%s/*.biq', bipdir));

    for i = 1:length(biq_files)
        biq_file = fullfile(bipdir, biq_files(i).name);
        try
            fid = fopen(biq_file, 'r');
            if fid > 0
                % Read first record (ndata count)
                rec_len1 = fread(fid, 1, 'int32');
                ndata = fread(fid, 1, 'int32');
                fclose(fid);

                fprintf('  %s: %d data points\n', biq_files(i).name, ndata);
                total_data_points = total_data_points + ndata;
            end
        catch
            % Ignore read errors for validation
            if fid > 0, fclose(fid); end
        end
    end

    fprintf('  Total data points across all BIQ files: %d\n\n', total_data_points);

    if total_data_points == 0
        error(['MRVA_VALIDATION:NO_DATA', newline, ...
               'ERROR: All BIQ files contain 0 data points!', newline, ...
               'This usually indicates:', newline, ...
               '  1. L2P processing failed or produced empty BIC files', newline, ...
               '  2. Downloaded L2P NetCDF files are corrupted or missing', newline, ...
               '  3. Date/time mismatch between requested analysis and available data', newline, ...
               newline, ...
               'MRVA cannot proceed without valid satellite data.', newline, ...
               'Please check preprocessing stages (landice, iquam, l2p) for errors.', newline, ...
               newline, ...
               'Exiting to avoid running solver with no data (which produces 500k+ lines of NaN output).']);
    end

    %% Set SST values under ice
    fprintf('Stage 2: Processing ice data...\n');

    if icecapFlag
        icesstfile = sprintf('%s/icesst_%04d_%03d.bip', bipdir, year, day);
        icefile = config.landice_ice_p011_file;

        % zcat -f passes uncompressed input through unchanged, so this works
        % whether icefile is gzip-compressed or not -- the caller resolves
        % the exact file (including any .gz suffix), no pattern-guessing here.
        if exist(icefile, 'file')
            system(sprintf('zcat -f %s > %s', icefile, icesstfile));
            iceconvert(icesstfile);
        else
            warning('Ice file not found: %s', icefile);
            icesstfile = '';
        end

        % Polar cap land mask (static reference file for polar latitudes)
        polarcap = sprintf('%s/cylindercap.bip', bipdir);
        polarcap_source = config.polar_cap_edge_file;
        if exist(polarcap_source, 'file')
            system(sprintf('ln -sf %s %s', polarcap_source, polarcap));
        else
            warning('Polar cap file not found: %s', polarcap_source);
            warning('This is a static reference file for polar latitudes (89-95 deg N/S).');
            warning('To generate it, run the makeedge.m script from mur-internal/icenew/p01/');
            warning('See MRVA README.md for detailed instructions.');
            warning('Processing will continue without polar cap observations.');
            polarcap = '';
        end
    else
        icesstfile = '';
        polarcap = '';
    end

    fprintf('  ✓ Ice data processed\n\n');

    %% Reference/background field
    fprintf('Stage 3: Generating reference field...\n');

    Lref = 7;
    Lref0 = L0;

    % For NRT run, update coefile and Lref0. Whether a prior-day
    % coefficient exists is decided by the caller (Python), not by scanning
    % csp_basedir here -- config.prior_csp_file is present only when one
    % genuinely exists (see design doc section 8: absent is a valid,
    % meaningful state, not an error).
    if realtime
        Lnrt0 = 6;  % Make sure to cover the buoys
        Lref0 = Lnrt0;

        if isfield(config, 'prior_csp_file') && ~isempty(config.prior_csp_file)
            coefile = config.prior_csp_file;
        else
            warning('No prior-day coefficient file provided; will create reference field from scratch (starting at L=%d)', Lref0);
            coefile = '';
            % Keep Lref0=Lnrt0=6 - do NOT fall back to L0=2
            % Fortran handles missing coefile gracefully
        end
    end

    % Exclude real-time sensors from reference field
    excludelist = {'AVH18G', 'MODISA', 'MODIST', 'PATH5D', 'PATH5N', 'VIIRSN'};
    [~, inx] = setdiff(sensors(:,1), excludelist);
    inx = sort(inx);

    % Debug: show sensors used for makeref vs excluded
    if debugMode
        fprintf('\n=== DEBUG: makeref sensor configuration ===\n');
        fprintf('Excluded from makeref: %s\n', strjoin(excludelist, ', '));
        fprintf('Sensors for makeref (%d):\n', length(inx));
        for i = 1:length(inx)
            fprintf('  %s (La=%d, Lb=%d)\n', sensors{inx(i),1}, sensors{inx(i),4}, sensors{inx(i),5});
        end
        fprintf('===========================================\n\n');
    end

    reffile = makeref(year, day, sensors(inx,:), Lref0, Lref, ...
                      bipdir, decay, icesstfile, polarcap, coefile);

    % For NRT, direct main MRVA run to use background coefile
    if realtime
        coefile = reffile;
        L0 = Lref;  % Initial scale must match coefile's
    end

    fprintf('  ✓ Reference field created: %s\n\n', reffile);

    %% Outlier and bias removal
    fprintf('Stage 4: Outlier detection and bias correction...\n');

    if trimbipFlag
        % Outlier removal using reference field
        % l4_reference_root is optional (entrypoint.sh): trimbip3a only reads
        % it on its no-MUR-reference bootstrap branch, which this call never
        % takes because reffile above is always a real coefficient file.
        l4_reference_root = '';
        if isfield(config, 'l4_reference_root') && ~isempty(config.l4_reference_root)
            l4_reference_root = config.l4_reference_root;
        end
        trimbip3a(sensors, year, day, bipdir, region, reffile, l4_reference_root);
        fprintf('  ✓ Outliers removed\n');

        if biasbipFlag
            % Inter-sensor bias removal
            biaslist = {'MODISA', 'MODIST', 'VIIRSN'};
            inx = find(ismember(sensors(:,1), biaslist));
            if ~isempty(inx)
                biasbip4(sensors(inx,:), year, day, bipdir, region);
                fprintf('  ✓ Sensor biases corrected\n');
            end
        end
    else
        if prepbipFlag
            prepbip(sensors, year, day, bipdir);
        end
    end

    fprintf('\n');

    %% Run MRVA (Fortran core)
    fprintf('Stage 5: MRVA multi-scale analysis (L=%d to %d)...\n', L0, LF);
    fprintf('  This may take 30-60 minutes...\n');

    % Debug: show all sensors for main MRVA run
    if debugMode
        fprintf('\n=== DEBUG: Main MRVA sensor configuration ===\n');
        fprintf('L0=%d, LF=%d, coefile=%s\n', L0, LF, coefile);
        fprintf('Sensors for main MRVA (%d total):\n', size(sensors, 1));
        for n = 1:size(sensors, 1)
            bipfile = sprintf('%s/%s_%s_%04d_%03d.biq', bipdir, region, sensors{n,1}, year, day);
            fileExists = exist(bipfile, 'file') > 0;
            fprintf('  %d. %s (La=%d, Lb=%d) -> %s [%s]\n', ...
                n, sensors{n,1}, sensors{n,4}, sensors{n,5}, bipfile, ...
                iif(fileExists, 'EXISTS', 'MISSING'));
        end
        fprintf('=============================================\n\n');
    end

    % Write MRVA namelist
    f = fopen('mrva.nml', 'w');
    fprintf(f, ' $input\n');
    fprintf(f, 'lonmin=%f\nlonmax=%f\n', box(1), box(2));
    fprintf(f, 'latmin=%f\nlatmax=%f\n', box(3), box(4));
    fprintf(f, 'L0=%d\nLF=%d\n', L0, LF);
    fprintf(f, 'decay=\n');
    fprintf(f, '  %f,%f,%f,%f,\n', decay(1:4));
    fprintf(f, '  %f,%f,%f,%f,\n', decay(5:8));
    fprintf(f, '  %f,%f,%f,%f,\n', decay(9:12));
    fprintf(f, 'bgfile=''%s''\n', bgfile);
    fprintf(f, 'coefile=''%s''\n', coefile);

    % Count actual BIP files (sensors + ice files)
    nbipfile = size(sensors, 1);
    file_count = nbipfile;

    % Add ice files if they exist
    if ~isempty(icesstfile) && exist(icesstfile, 'file')
        file_count = file_count + 1;
    end
    if ~isempty(polarcap) && exist(polarcap, 'file')
        file_count = file_count + 1;
    end

    fprintf(f, 'nbipfile=%d\nbipfile=\n', file_count);

    % Write ice files first if they exist
    if ~isempty(icesstfile) && exist(icesstfile, 'file')
        fprintf(f, '''%d'',''%d'',''%s'',\n', L0, 9, icesstfile);
    end
    if ~isempty(polarcap) && exist(polarcap, 'file')
        fprintf(f, '''%d'',''%d'',''%s'',\n', L0, 9, polarcap);
    end

    % Write sensor BIQ files
    for n = 1:nbipfile
        sensor = sensors{n,1};
        bipfile = sprintf('%s/%s_%s_%04d_%03d.biq', bipdir, region, sensor, year, day);
        fprintf(f, '''%d'',''%d'',''%s'',\n', sensors{n,4}, sensors{n,5}, bipfile);
    end
    fprintf(f, ' $end\n');
    fclose(f);

    % Debug: show namelist contents before running MRVA
    if debugMode
        fprintf('\n=== DEBUG: mrva.nml contents (main MRVA run) ===\n');
        type('mrva.nml');
        fprintf('=== END mrva.nml ===\n\n');
    end

    % Execute Fortran MRVA
    tic;
    [status, result] = system([fortran_bin, '/mrva']);
    elapsed = toc;

    % Debug: show Fortran output
    if debugMode
        fprintf('\n=== DEBUG: Fortran MRVA output ===\n');
        fprintf('%s\n', result);
        fprintf('=== END Fortran output ===\n\n');
    end

    if status == 99
        % NaN detected by Fortran code
        error(['MRVA_CONVERGENCE:NAN_DETECTED', newline, ...
               'ERROR: MRVA solver detected NaN values during PCG iteration!', newline, ...
               newline, ...
               'The Fortran solver detected numerical instability and stopped early.', newline, ...
               'Check the output above for details about which iteration failed.', newline, ...
               newline, ...
               'Common causes:', newline, ...
               '  1. Insufficient or invalid input data (check BIQ validation above)', newline, ...
               '  2. Poor conditioning in the covariance matrix', newline, ...
               '  3. Incompatible decay parameters for available data', newline, ...
               '  4. Problems with reference/background field', newline, ...
               '  5. Recent code changes affecting data preparation', newline, ...
               newline, ...
               'Recommended debugging steps:', newline, ...
               '  1. Check if recent code changes modified makebiq, makeref, or trimbip', newline, ...
               '  2. Verify BIQ files contain valid data ranges (not extreme outliers)', newline, ...
               '  3. Check reference field was created successfully', newline, ...
               '  4. Try running with different decay parameters', newline, ...
               '  5. Compare with reference implementation in mur-internal/cyc4/', newline, ...
               newline, ...
               'Full output:', newline, ...
               '%s'], result);
    elseif status ~= 0
        error('MRVA execution failed with exit code %d:\n%s', status, result);
    end

    fprintf('  ✓ MRVA completed in %.1f minutes\n\n', elapsed/60);

    %% Save coefficients (analysis and uncertainty)
    fprintf('Stage 6: Saving coefficient files...\n');

    for L = L0:LF
        % Analysis coefficients
        name = sprintf('%s.c%02d', cspbody, L);
        system(sprintf('mv ./mrva.c%02d %s', L, name));

        % Uncertainty estimates (only L=6,7,8 to save space)
        if ismember(L, 6:8)
            name = sprintf('%s.u%02d', cspbody, L);
            system(sprintf('mv ./mrva.u%02d %s', L, name));
        end
    end

    fprintf('  ✓ Coefficient files saved to: %s\n\n', cspdir);

    %% Create spgrid namelist (for map generation)
    f = fopen('spgrid.nml', 'w');
    fprintf(f, ' $input\n');
    fprintf(f, 'sstoffset=%f\n', 0);
    fprintf(f, 'nlist=%d\n', LF - L0 + 1);
    fprintf(f, 'coeffilelist=\n');
    for L = L0:LF
        name = sprintf('%s.u%02d', cspbody, L);
        fprintf(f, '''%d'',''%s'',\n', L, name);
    end
    fprintf(f, 'outgridfile=\n''%s''\n', outgridfile);
    fprintf(f, ' $end\n');
    fclose(f);

    %% Generate map files (optional diagnostic output)
    fprintf('Stage 7: Generating map files...\n');

    if exist(mapdir, 'dir') == 0
        mkdir(mapdir);
    end

    for L = mapL0:mapLF
        fortfile = sprintf('fort.%02d', 80 + L);
        if exist(fortfile, 'file')
            f = fopen(fortfile, 'r');
            % Read Fortran record with markers
            fread(f, 1, 'uint32');  % Skip record marker
            idm = fread(f, 1, 'int32');
            jdm = fread(f, 1, 'int32');
            fread(f, 1, 'uint32');  % Skip record marker
            fclose(f);

            [d_out, m_out, y_out] = julian(day, year);
            name = sprintf('%s/%d%02d%02dT%s', mapdir, y_out, m_out, d_out, maptime0);
            name = sprintf('%s-%d%02d%02dT%s', name, y_out, m_out, d_out, maptime1);
            name = sprintf('%s-%s-%dx%d.map', name, mapbody, idm, jdm);
            system(sprintf('mv %s %s', fortfile, name));
        end
    end

    fprintf('  ✓ Map files created\n\n');

    %% HiResGrid (dt_1km_data) for GDS2
    fprintf('Stage 8: Generating high-resolution distance grid...\n');

    if hiresgridFlag
        hiresgridfile = makehiresgrid(year, day, sensors(:,1));
        fprintf('  ✓ Distance grid created: %s\n\n', hiresgridfile);
    else
        hiresgridfile = '';
    end

    %% Make NetCDF file (GHRSST L4 output)
    fprintf('Stage 9: Generating NetCDF4 output...\n');
    fprintf('  This may take 15-20 minutes...\n');

    if netcdfFlag
        if ~exist(logdir, 'dir')
            mkdir(logdir);
        end

        % Call csp2nc4a as a function with config struct
        try
            % Build configuration struct for csp2nc4a
            nc_config = struct();
            nc_config.ncdir = netcdf_dir;
            nc_config.cspdir = cspdir;
            nc_config.cspfmt = cspfmt;
            nc_config.L = outL4;
            nc_config.region = region;
            nc_config.hourAna = hourAna;
            nc_config.whichdays = {year, day:day};
            nc_config.realtime = realtime;
            nc_config.landice_grid_p01_file = config.landice_grid_p01_file;
            nc_config.landice_icefiles_p011_file = config.landice_icefiles_p011_file;

            % Add optional high-res grid file if available
            if hiresgridFlag && ~isempty(hiresgridfile)
                nc_config.hiresgridfile = hiresgridfile;
            end

            % Execute NetCDF generation
            tic;
            status = csp2nc4a(nc_config);
            elapsed = toc;

            if status == 0
                fprintf('  ✓ NetCDF generation completed in %.1f minutes\n\n', elapsed/60);
            else
                warning('NetCDF generation returned non-zero status: %d', status);
            end

        catch ME
            warning('NetCDF generation failed: %s', ME.message);
            fprintf('  Error details:\n');
            for k = 1:length(ME.stack)
                fprintf('    %s (line %d)\n', ME.stack(k).name, ME.stack(k).line);
            end
        end
    end

    %% Generate MUR25 (0.25 degree) product
    fprintf('Stage 10: Generating MUR25 (0.25 degree) product...\n');

    mur25Flag = 1;  % Set to 0 to skip MUR25 generation

    % MUR25 grid file is optional (design doc section 8: absent -> skip
    % MUR25 generation, matching existing documented behavior) -- resolved
    % by the caller, not constructed from a root here.
    if isfield(config, 'mur25_grid_file') && ~isempty(config.mur25_grid_file)
        mur25_gridfile = config.mur25_grid_file;
    else
        mur25_gridfile = '';
    end
    if isempty(mur25_gridfile) || ~exist(mur25_gridfile, 'file')
        warning(['MUR25 grid file not provided or not found: %s\n', ...
                 'MUR25 product will not be generated.'], mur25_gridfile);
        mur25Flag = 0;
    end

    if mur25Flag
        try
            % Build configuration struct for makeMUR25_container
            mur25_config = struct();
            mur25_config.cspdir = cspdir;
            mur25_config.cspfmt = cspfmt;
            mur25_config.netcdf_dir = netcdf_dir;
            mur25_config.landice_grid_p01_file = config.landice_grid_p01_file;  % MUR25 uses p01 landiceP01_ files
            mur25_config.mur25_grid_file = mur25_gridfile;
            mur25_config.seasonal_file = config.seasonal_file;
            mur25_config.fortran_bin = fortran_bin;
            mur25_config.cache_dir = '/data/cache';
            mur25_config.region = region;
            mur25_config.hourAna = hourAna;

            % Execute MUR25 generation
            tic;
            makeMUR25_container(year, day, realtime, mur25_config);
            elapsed = toc;

            fprintf('  ✓ MUR25 generation completed in %.1f minutes\n\n', elapsed/60);

        catch ME
            warning('MUR25 generation failed: %s', ME.message);
            fprintf('  Error details:\n');
            for k = 1:length(ME.stack)
                fprintf('    %s (line %d)\n', ME.stack(k).name, ME.stack(k).line);
            end
            fprintf('  MUR25 product was not generated, but full MUR product is available.\n\n');
        end
    else
        fprintf('  Skipping MUR25 generation (grid file not available)\n\n');
    end

    %% Clean up temporary files
    fprintf('Stage 11: Cleaning up temporary files...\n');

    % Clean up per-run scratch directories. grd/ and ice25/ are intentional
    % same-day skip-if-exists caches and are left alone.
    if delbipFlag
        system(sprintf('rm -f %s/*.bip %s/*.biq', bipdir, bipdir));
        system(sprintf('rm -f %s/*.map', mapdir));
        fprintf('  ✓ BIP/BIQ scratch removed (%s)\n', bipdir);
        fprintf('  ✓ map scratch removed (%s)\n', mapdir);
    end

    % Clean up namelists
    system('rm -f mrva.nml spgrid.nml');

    fprintf('\n');
    fprintf('========================================\n');
    fprintf('MRVA Processing Complete!\n');
    fprintf('========================================\n');
    fprintf('Coefficient files: %s\n', cspdir);
    if netcdfFlag
        fprintf('NetCDF output:     %s\n', netcdf_dir);
        fprintf('  Full MUR (0.01 deg): GLOB/JPL/MUR/v4/%04d/%03d%s/\n', year, day, iif(realtime, 'nrt', ''));
        if mur25Flag
            fprintf('  MUR25 (0.25 deg):    GLOB/JPL/MUR/v4/%04d/%03d%s/\n', year, day, iif(realtime, 'nrt', ''));
        end
    end
    fprintf('========================================\n');

end

function out = iif(condition, true_val, false_val)
    % Inline if function
    if condition
        out = true_val;
    else
        out = false_val;
    end
end
