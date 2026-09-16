function buoyDataProcessing(year, doy, mode, referenceToday, ...
                            workDir, logDir, outputDir, ...
                            buoyDayRange, buoyStabilityLatency, ...
                            sourceUrl, enableREA, testing, ...
                            reaAggregationWindow, reaOutputDir)
% buoyDataProcessing - IQUAM In-Situ SST Observation Processing Pipeline
%
% USAGE:
%   buoyDataProcessing(year, doy, mode, referenceToday, workDir, logDir, outputDir, ...)
%
%   When compiled as executable:
%   ./IquamProcessor year doy mode referenceToday [workDir] [logDir] [outputDir] [buoyDayRange] [buoyStabilityLatency] ...
%
% DESCRIPTION:
%   Processes IQUAM in-situ SST observations for one explicit analysis day
%   (year/doy), downloading and converting IQUAM NetCDF data to binary
%   format for that day and its +/-buoyDayRange window via makedailyiquam.
%   The caller (run_mur_pipeline.py / run_mur_maap.py) is responsible for
%   iterating over the full processing window and invoking this function
%   once per day -- this function does not compute that window itself.
%
% PROCESSING MODES:
%   NRT Mode ('nrt'): Recent data with relaxed stability requirements (fast updates)
%   REA Mode ('rea'): Historical data with full temporal aggregation (not yet implemented)
%
% ========================================================================
% DIRECTORY STRUCTURE FOR CONTAINERIZATION
% ========================================================================
%
% EXTERNAL INPUTS (mount as read-only volumes):
%   sourceUrl        - URL for IQUAM NetCDF file downloads
%                      Default: 'https://www.star.nesdis.noaa.gov/pub/socd/sst/iquam/v2.10/'
%                      Note: No local files required - all data downloaded from URL
%
% EXTERNAL OUTPUTS (mount as read-write volumes):
%   outputDir        - Root directory for output .bii files
%                      Default: './output/iquam'
%                      Structure: <outputDir>/YYYY/Global_IQUAM0_YYYY_DDD.bii
%                      Container mount: /data/output/iquam
%
%   logDir           - Directory for log files
%                      Default: './logs'
%                      Output files: buoy.log
%                      Container mount: /data/logs
%
% TEMPORARY DIRECTORIES (mount as read-write volumes):
%   workDir          - Temporary working directory for processing
%                      Default: './tmp/makebic'
%                      Note: Cleaned at start of each run
%                      Container mount: /tmp/makebic (ephemeral)
%                      Downloads are deleted after processing (no cache)

% ========================================================================
% ARGUMENTS VALIDATION - Using Modern MATLAB Arguments Block
% ========================================================================
arguments
    % Target analysis day (explicit -- no internal window computation)
    year {mustBeTextScalar}
    doy {mustBeTextScalar}
    mode {mustBeTextScalar}          % 'nrt' or 'rea'
    referenceToday {mustBeTextScalar}  % 'YYYY-MM-DD', used for stability/future-date checks

    % Directory Paths (all relative for container compatibility)
    workDir {mustBeTextScalar} = './tmp/makebic'
    logDir {mustBeTextScalar} = './logs'
    outputDir {mustBeTextScalar} = './output/iquam'

    % Buoy File Processing Parameters
    buoyDayRange {mustBeTextScalar} = '3'  % [days] Temporal window (+/-days)
    buoyStabilityLatency {mustBeTextScalar} = '2'  % [days] Stability threshold

    sourceUrl {mustBeTextScalar} = 'https://www.star.nesdis.noaa.gov/pub/socd/sst/iquam/v2.10/'

    % Processing Mode
    enableREA {mustBeTextScalar} = 'false'  % REA mode disabled by default
    testing {mustBeTextScalar} = '0'  % Set to '1' to test without executing

    % REA-specific parameters (for future implementation)
    reaAggregationWindow {mustBeTextScalar} = '3'  % [days] +/-3 days for refbii2biq
    reaOutputDir {mustBeTextScalar} = './output/iquam_rea'  % .biq files
end

% ========================================================================
% PARAMETERS - Convert string inputs to appropriate types
% ========================================================================

year = str2double(year);
doy = str2double(doy);
realtime = strcmpi(mode, 'nrt');
todayDatenum = datenum(referenceToday, 'yyyy-mm-dd');

% Convert string arguments to numeric/logical types
enableREA = strcmpi(enableREA, 'true') || strcmpi(enableREA, '1');
testing = str2double(testing);
buoyDayRange = str2double(buoyDayRange);
buoyStabilityLatency = str2double(buoyStabilityLatency);
reaAggregationWindow = str2double(reaAggregationWindow);

% Display input parameters
fprintf('=== DEBUG: buoyDataProcessing STARTED ===\n');
fprintf('buoyDataProcessing: year - %d\n', year);
fprintf('buoyDataProcessing: doy - %d\n', doy);
fprintf('buoyDataProcessing: mode - %s\n', mode);
fprintf('buoyDataProcessing: referenceToday - %s\n', referenceToday);
fprintf('buoyDataProcessing: workDir - %s\n', workDir);
fprintf('buoyDataProcessing: logDir - %s\n', logDir);
fprintf('buoyDataProcessing: outputDir - %s\n', outputDir);
fprintf('buoyDataProcessing: sourceUrl - %s\n', sourceUrl);
fprintf('buoyDataProcessing: enableREA - %d\n', enableREA);
fprintf('buoyDataProcessing: testing - %d\n', testing);

% Testing overrides
if testing == 1
    logDir = './tmp/logs';
    fprintf('DEBUG: Testing mode enabled, logDir set to %s\n', logDir);
end

% ========================================================================
% INITIALIZATION
% ========================================================================

fprintf('DEBUG: Starting initialization...\n');

% Clean and create temporary directory
fprintf('DEBUG: Checking workDir: %s\n', workDir);
if exist(workDir, 'dir')
    fprintf('DEBUG: Removing existing workDir...\n');
    rmdir(workDir, 's');
end
fprintf('DEBUG: Creating workDir...\n');
mkdir(workDir);

% Create log directory if needed
fprintf('DEBUG: Checking logDir: %s\n', logDir);
if ~exist(logDir, 'dir')
    fprintf('DEBUG: Creating logDir...\n');
    mkdir(logDir);
end

% Open log file
logFile = fullfile(logDir, 'buoy.log');
fprintf('DEBUG: Opening log file: %s\n', logFile);
flog = fopen(logFile, 'a');
if flog == -1
    error(['Cannot open log file: ' logFile]);
end
fprintf('DEBUG: Log file opened successfully\n');

% Log the day being processed
fprintf(flog, '---------- Reference today = %s ----------\n', referenceToday);
if realtime
    fprintf(flog, '  ======== Interim run for Year %d Day %d ========\n', year, doy);
else
    fprintf(flog, '  ======== Final run for Year %d Day %d ========\n', year, doy);
end

% ========================================================================
% MAIN PROCESSING (single explicit analysis day)
% ========================================================================

fprintf('DEBUG: Starting processing for year=%d doy=%d mode=%s...\n', year, doy, mode);

% Save current directory and change to working directory
homeDir = pwd;
fprintf('DEBUG: Changing to workDir: %s\n', workDir);
cd(workDir);

% Process buoy files for temporal window (+/-buoyDayRange)
for dt = -buoyDayRange:buoyDayRange

    % Adjust day with offset
    [d, y] = adjustDoy(doy + dt, year);

    % Skip future dates (relative to reference day)
    % This matches production behavior where data wasn't available yet
    dataDatenum = datenum(y, 1, 0) + d;
    if dataDatenum > todayDatenum
        continue;
    end

    % Determine if source file is stable (old enough to not change)
    daysOld = todayDatenum - dataDatenum;
    if daysOld < buoyStabilityLatency
        rewrite = 1;
    else
        rewrite = 0;
    end

    % In realtime mode, never rewrite existing files
    if realtime
        rewrite = 0;
    end

    % Define output filename for checking
    buoyFile = fullfile(outputDir, sprintf('%04d', y), ...
        sprintf('Global_IQUAM0_%04d_%03d.bii', y, d));

    % Check if file exists and should be kept
    if exist(buoyFile, 'file') && (rewrite == 0)
        fprintf(flog, 'keeping old %s\n', buoyFile);
        fprintf('DEBUG: Keeping existing file: %s\n', buoyFile);
    else
        % Process this day using makedailyiquam
        fprintf(flog, 'Processing year=%d day=%d rewrite=%d\n', y, d, rewrite);
        fprintf('DEBUG: CALLING makedailyiquam(y=%d, d=%d, rewrite=%d)\n', y, d, rewrite);

        if testing == 0
            % Call makedailyiquam with all path parameters
            fprintf('DEBUG: About to call makedailyiquam...\n');
            makedailyiquam(y, d, rewrite, outputDir, sourceUrl);
            fprintf('DEBUG: makedailyiquam returned successfully\n');
        else
            % Testing mode - just log the command
            fprintf(flog, '[TESTING] Would call: makedailyiquam(%d, %d, %d, %s, %s)\n', ...
                y, d, rewrite, outputDir, sourceUrl);
            fprintf('DEBUG: [TESTING] Skipped makedailyiquam call\n');
        end
    end

end  % end dt loop (temporal window)

% ========================================================================
% REA MODE: Temporal Aggregation (STUB - Not Yet Implemented)
% ========================================================================
% After processing all +/-buoyDayRange .bii files for this analysis day,
% aggregate them into a single .biq file for the final analysis.
%
% This would call refbii2biq.m to:
%   1. Read all .bii files from [day-reaAggregationWindow : day+reaAggregationWindow]
%   2. Apply platform-specific error weighting
%   3. Apply temporal weighting based on distance from analysis day
%   4. Write aggregated .biq file to reaOutputDir
%
if enableREA && ~realtime
    % Only run REA aggregation for "Final run" days (not interim/NRT)
    fprintf(flog, '[REA STUB] Would aggregate temporal window for analysis day %04d/%03d\n', ...
        year, doy);

    % Future implementation:
    % refbii2biq(year, doy, outputDir, reaOutputDir, reaAggregationWindow);
    %
    % Where refbii2biq.m would be refactored to accept:
    %   - year, day: Analysis date
    %   - biiInputDir: Directory containing .bii files (outputDir)
    %   - biqOutputDir: Directory for .biq output (reaOutputDir)
    %   - dayrange: Temporal window (reaAggregationWindow)
end

% ========================================================================
% CLEANUP
% ========================================================================

% Return to original directory
cd(homeDir);

% Close log file
fclose(flog);

fprintf('Processing complete. Log written to: %s\n', logFile);

end  % end function buoyDataProcessing


% ========================================================================
% HELPER FUNCTIONS
% ========================================================================

function leap = isLeapYear(year)
% Returns 1 if year is a leap year, 0 otherwise
    leap = (mod(year, 4) == 0) && ...
           ((mod(year, 100) ~= 0) || (mod(year, 400) == 0));
end

function [doy, year] = adjustDoy(doy, year)
% Adjusts day-of-year and year values to neighboring year if necessary
    daysInYear = 365 + isLeapYear(year);

    % Handle underflow (negative day)
    while doy < 1
        year = year - 1;
        doy = doy + 365 + isLeapYear(year);
    end

    % Handle overflow (day exceeds year length)
    while doy > daysInYear
        doy = doy - daysInYear;
        year = year + 1;
        daysInYear = 365 + isLeapYear(year);
    end
end
