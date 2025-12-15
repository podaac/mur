function l2p_wrapper(sensor, region, indir, bicdir, year_str, day_str, rewrite_str)
%L2P_WRAPPER Wrapper function matching production nrtMRVA.py calling pattern
%
%   This wrapper matches the exact interface used in production nrtMRVA.py,
%   which calls l2p2bic() directly with explicit paths.
%
%   USAGE:
%       l2p_wrapper('AMSR2R', 'Global', '/data/input/AMSR2R',
%                   '/data/output/AMSR2R', '2025', '220', '0')
%
%   When compiled as executable:
%       ./L2pProcessor AMSR2R Global /data/input/AMSR2R /data/output/AMSR2R 2025 220 0
%
%   ARGUMENTS (matches l2p2bic signature):
%       sensor    - Sensor name: 'AMSR2R', 'AVMTBG', 'MODISA', or 'MODIST'
%       region    - Region name: 'Global' (typically always Global)
%       indir     - Input directory containing L2P NetCDF files
%       bicdir    - Output directory for BIC files
%       year_str  - Year as string (e.g., '2025')
%       day_str   - Day of year as string (e.g., '220')
%       rewrite_str - Rewrite flag: '0' = skip existing, '1' = overwrite
%
%   PRODUCTION USAGE (how nrtMRVA.py calls it):
%       In production, nrtMRVA.py creates a temporary MATLAB script:
%         l2p2bic(sensor, region, indir, bicdir, year, day, rewrite);
%
%       Our container provides the same interface but compiled.
%
%   DATA FLOW:
%       1. Expects L2P NetCDF files already in indir (from cron downloads)
%       2. Calls l2p2bic(sensor, region, indir, bicdir, year, day, rewrite)
%       3. Writes BIC files to bicdir
%       4. No download logic - matches production separation of concerns

% ========================================================================
% STARTUP AND VALIDATION
% ========================================================================

start_time = datetime('now');

% Display input parameters
fprintf('=== L2P_WRAPPER: Processing Started ===\n');
fprintf('Sensor:     %s\n', sensor);
fprintf('Region:     %s\n', region);
fprintf('Input Dir:  %s\n', indir);
fprintf('Output Dir: %s\n', bicdir);
fprintf('Year:       %s\n', year_str);
fprintf('Day:        %s\n', day_str);
fprintf('Rewrite:    %s\n', rewrite_str);

% Convert string arguments to appropriate types for validation
% BUT keep original strings to pass to l2p2bic (which does its own conversion)
year_num = str2double(year_str);
day_num = str2double(day_str);
rewrite = str2double(rewrite_str);

% Validate sensor
valid_sensors = {'AMSR2R', 'AVMTBG', 'MODISA', 'MODIST', 'AVMTAG'};
sensor_upper = upper(sensor);
if ~ismember(sensor_upper, valid_sensors)
    error('Invalid sensor: %s. Must be one of: %s', sensor, strjoin(valid_sensors, ', '));
end

% Validate year and day
if isnan(year_num) || year_num < 1900 || year_num > 2100
    error('Invalid year: %s. Must be between 1900 and 2100', year_str);
end
if isnan(day_num) || day_num < 1 || day_num > 366
    error('Invalid day: %s. Must be between 1 and 366', day_str);
end

% Validate rewrite flag
if rewrite ~= 0 && rewrite ~= 1
    error('Invalid rewrite flag: %d. Must be 0 or 1', rewrite);
end

% Check input directory exists
if ~exist(indir, 'dir')
    fprintf('WARNING: Input directory does not exist: %s\n', indir);
    fprintf('Creating directory...\n');
    mkdir(indir);
end

% Create output directory if it doesn't exist
if ~exist(bicdir, 'dir')
    fprintf('Creating output directory: %s\n', bicdir);
    mkdir(bicdir);
end

% ========================================================================
% CHECK FOR INPUT FILES
% ========================================================================

fprintf('\n=== CHECKING FOR INPUT FILES ===\n');

% Look for NetCDF files in input directory
nc_files = dir(fullfile(indir, '*.nc'));
nc_bz2_files = dir(fullfile(indir, '*.nc.bz2'));
nc_gz_files = dir(fullfile(indir, '*.nc.gz'));

total_files = length(nc_files) + length(nc_bz2_files) + length(nc_gz_files);

if total_files == 0
    fprintf('WARNING: No L2P files found in: %s\n', indir);
    fprintf('Expected file patterns: *.nc, *.nc.bz2, *.nc.gz\n');
    fprintf('\n');
    fprintf('IMPORTANT: This container expects L2P files to be pre-downloaded.\n');
    fprintf('In production, cron jobs download files hourly using podaac-data-subscriber.\n');
    fprintf('\n');
    fprintf('To download files manually:\n');
    fprintf('  podaac-data-subscriber -c <COLLECTION> -d %s -sd YYYY-MM-DDT00:00:00Z\n', indir);
    fprintf('\n');
    fprintf('Will attempt processing anyway (l2p2bic may produce empty output).\n');
else
    fprintf('Found %d L2P NetCDF files:\n', total_files);
    fprintf('  .nc files:     %d\n', length(nc_files));
    fprintf('  .nc.bz2 files: %d\n', length(nc_bz2_files));
    fprintf('  .nc.gz files:  %d\n', length(nc_gz_files));
end

% ========================================================================
% CALL L2P2BIC - CORE PROCESSING
% ========================================================================

fprintf('\n=== CALLING L2P2BIC ===\n');
try
    % Call the core L2P to BIC conversion function
    % This is the same function called by production nrtMRVA.py
    % NOTE: l2p2bic expects year and day as STRINGS (it does str2double internally)
    l2p2bic(sensor_upper, region, indir, bicdir, year_str, day_str, rewrite);

    fprintf('L2P2BIC completed successfully\n');

catch ME
    fprintf('ERROR in l2p2bic: %s\n', ME.message);
    fprintf('Stack trace:\n');
    for k = 1:length(ME.stack)
        fprintf('  File: %s\n', ME.stack(k).file);
        fprintf('  Name: %s\n', ME.stack(k).name);
        fprintf('  Line: %d\n', ME.stack(k).line);
    end
    rethrow(ME);
end

% ========================================================================
% VERIFY OUTPUT
% ========================================================================

fprintf('\n=== VERIFYING OUTPUT ===\n');

% Check for output BIC file (uncompressed - makebiq handles either format)
expected_bic = fullfile(bicdir, ...
    sprintf('%s_%s_%04d_%03d.bic', region, sensor_upper, year_num, day_num));

if exist(expected_bic, 'file')
    file_info = dir(expected_bic);
    fprintf('SUCCESS: Output file created\n');
    fprintf('  File: %s\n', expected_bic);
    fprintf('  Size: %.2f MB\n', file_info.bytes / 1024^2);
else
    fprintf('WARNING: Expected output file not found:\n');
    fprintf('  %s\n', expected_bic);
    fprintf('  No output file created - check logs above for errors\n');
end

% ========================================================================
% COMPLETION
% ========================================================================

end_time = datetime('now');
execution_time = end_time - start_time;

fprintf('\n=== L2P_WRAPPER: Processing Completed ===\n');
fprintf('Total execution time: %s\n', string(execution_time));
fprintf('==========================================\n');

end
