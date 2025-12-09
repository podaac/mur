function buoyDataProcessing(workDir, logDir, outputDir, cacheDir, sourceUrl, ...
                            enableREA, testing, nrtLatency, reaLatency, ...
                            scanLatency, buoyDayRange, buoyStabilityLatency, ...
                            reaAggregationWindow, reaOutputDir, simulatedToday)
% buoyDataProcessing - IQUAM In-Situ SST Observation Processing Pipeline
%
% USAGE:
%   buoyDataProcessing()  % Use all default parameters
%   buoyDataProcessing(workDir, logDir, ...)  % Override specific parameters
%
%   When compiled as executable:
%   ./IquamProcessor [workDir] [logDir] [outputDir] [cacheDir] [sourceUrl] ...
%
% DESCRIPTION:
%   Orchestrates processing of IQUAM in-situ SST observations for both
%   Near Real-Time (NRT) and Reanalysis (REA) modes. Manages date ranges,
%   determines which days need processing/reprocessing, and calls
%   makedailyiquam to download and convert IQUAM NetCDF data to binary format.
%
% PROCESSING MODES:
%   NRT Mode: Recent data with relaxed stability requirements (fast updates)
%   REA Mode: Historical data with full temporal aggregation (not yet implemented)
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
% TEMPORARY/CACHE DIRECTORIES (mount as read-write volumes):
%   cacheDir         - Cache directory for monthly .mat files
%                      Default: './cache/iquam'
%                      Format: iquam.YYYY.MM.mat
%                      Purpose: Avoid re-downloading NetCDF files
%                      Container mount: /data/cache/iquam
%
%   workDir          - Temporary working directory for processing
%                      Default: './tmp/makebic'
%                      Note: Cleaned at start of each run
%                      Container mount: /tmp/makebic (ephemeral)

% ========================================================================
% ARGUMENTS VALIDATION - Using Modern MATLAB Arguments Block
% ========================================================================
arguments
    % Directory Paths (all relative for container compatibility)
    workDir {mustBeTextScalar} = './tmp/makebic'
    logDir {mustBeTextScalar} = './logs'
    outputDir {mustBeTextScalar} = './output/iquam'
    cacheDir {mustBeTextScalar} = './cache/iquam'
    sourceUrl {mustBeTextScalar} = 'https://www.star.nesdis.noaa.gov/pub/socd/sst/iquam/v2.10/'

    % Processing Mode
    enableREA {mustBeTextScalar} = 'false'  % REA mode disabled by default
    testing {mustBeTextScalar} = '0'  % Set to '1' to test without executing

    % Latency and Date Range Parameters (in days)
    nrtLatency {mustBeTextScalar} = '1'   % [days] NRT end date offset
    reaLatency {mustBeTextScalar} = '4'   % [days] REA end date offset
    scanLatency {mustBeTextScalar} = '9'  % [days] Scan backward window

    % Buoy File Processing Parameters
    buoyDayRange {mustBeTextScalar} = '3'  % [days] Temporal window (±days)
    buoyStabilityLatency {mustBeTextScalar} = '2'  % [days] Stability threshold

    % REA-specific parameters (for future implementation)
    reaAggregationWindow {mustBeTextScalar} = '3'  % [days] ±3 days for refbii2biq
    reaOutputDir {mustBeTextScalar} = './output/iquam_rea'  % .biq files

    % Date simulation for historical reprocessing
    % Format: 'YYYY-MM-DD' or empty string to use current date
    % When set, uses this date instead of now() for all date calculations
    simulatedToday {mustBeTextScalar} = ''
end

% ========================================================================
% PARAMETERS - Convert string inputs to appropriate types
% ========================================================================

% Convert string arguments to numeric/logical types
enableREA = strcmpi(enableREA, 'true') || strcmpi(enableREA, '1');
testing = str2double(testing);
nrtLatency = str2double(nrtLatency);
reaLatency = str2double(reaLatency);
scanLatency = str2double(scanLatency);
buoyDayRange = str2double(buoyDayRange);
buoyStabilityLatency = str2double(buoyStabilityLatency);
reaAggregationWindow = str2double(reaAggregationWindow);

% Display input parameters
fprintf('=== DEBUG: buoyDataProcessing STARTED ===\n');
fprintf('buoyDataProcessing: workDir - %s\n', workDir);
fprintf('buoyDataProcessing: logDir - %s\n', logDir);
fprintf('buoyDataProcessing: outputDir - %s\n', outputDir);
fprintf('buoyDataProcessing: cacheDir - %s\n', cacheDir);
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

% Create cache directory if needed
fprintf('DEBUG: Checking cacheDir: %s\n', cacheDir);
if ~exist(cacheDir, 'dir')
    fprintf('DEBUG: Creating cacheDir...\n');
    mkdir(cacheDir);
end

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

% Get current date (or simulated date for historical reprocessing)
fprintf('DEBUG: Getting current date...\n');
if ~isempty(simulatedToday)
    % Use simulated date for historical reprocessing
    todayDatenum = datenum(simulatedToday, 'yyyy-mm-dd');
    fprintf('DEBUG: Using SIMULATED date: %s\n', simulatedToday);
else
    % Check environment variable MUR_SIMULATED_DATE
    envSimDate = getenv('MUR_SIMULATED_DATE');
    if ~isempty(envSimDate)
        todayDatenum = datenum(envSimDate, 'yyyy-mm-dd');
        fprintf('DEBUG: Using MUR_SIMULATED_DATE env var: %s\n', envSimDate);
    else
        todayDatenum = now;
        fprintf('DEBUG: Using actual current date\n');
    end
end
todayVec = datevec(todayDatenum);
todayYear = todayVec(1);
todayDoy = floor(todayDatenum - datenum(todayYear, 1, 0));  % Day of year
fprintf('DEBUG: Today is year=%d, doy=%d\n', todayYear, todayDoy);

% ========================================================================
% CALCULATE DATE RANGES
% ========================================================================

% End of NRT run
nrtEndDatenum = todayDatenum - nrtLatency;
nrtEndVec = datevec(nrtEndDatenum);
year2 = nrtEndVec(1);
day2 = floor(nrtEndDatenum - datenum(year2, 1, 0));

% End of REA run / pre-start of NRT run
reaEndDatenum = todayDatenum - reaLatency;
reaEndVec = datevec(reaEndDatenum);
year1 = reaEndVec(1);
day1 = floor(reaEndDatenum - datenum(year1, 1, 0));

% Start of REA run (scan backward window)
scanStartDatenum = todayDatenum - scanLatency;
scanStartVec = datevec(scanStartDatenum);
year0 = scanStartVec(1);
day0 = floor(scanStartDatenum - datenum(year0, 1, 0));

% Log the processing window
fprintf(flog, '---------- Today = Year %d Day %d ----------\n', todayYear, todayDoy);
fprintf(flog, '           from (%d,%d) to (%d,%d) \n', year0, day0, year2, day2);

% ========================================================================
% MAIN PROCESSING LOOP
% ========================================================================

fprintf('DEBUG: Starting main processing loop...\n');
fprintf('DEBUG: Processing date range: year0=%d day0=%d to year2=%d day2=%d\n', year0, day0, year2, day2);

% Save current directory and change to working directory
homeDir = pwd;
fprintf('DEBUG: Changing to workDir: %s\n', workDir);
cd(workDir);

% Process each year in the date range
fprintf('DEBUG: Entering year loop (year0=%d to year2=%d)\n', year0, year2);
for year = year0:year2
    fprintf('DEBUG: Processing year=%d\n', year);

    % Determine day range for this year
    d0 = 1;
    d2 = 365 + isLeapYear(year);  % 366 for leap years, 365 otherwise

    if year == year0
        d0 = day0;
    end
    if year == year2
        d2 = day2;
    end

    % Process each day in the year
    for day = d0:d2

        % Calculate ordinal day for comparison
        dayOrdinal = ordinalDay(day, year);
        day1Ordinal = ordinalDay(day1, year1);

        % Determine if this is NRT or REA mode
        if dayOrdinal > day1Ordinal
            realtime = 1;
            fprintf(flog, '  ======== Interim run for Year %d Day %d ========\n', year, day);
        else
            realtime = 0;
            fprintf(flog, '  ======== Final run for Year %d Day %d ========\n', year, day);
        end

        % Process buoy files for temporal window (±buoyDayRange)
        for dt = -buoyDayRange:buoyDayRange

            % Adjust day with offset
            [d, y] = adjustDoy(day + dt, year);

            % Skip future dates
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
            if realtime == 1
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
                    makedailyiquam(y, d, rewrite, outputDir, cacheDir, sourceUrl);
                    fprintf('DEBUG: makedailyiquam returned successfully\n');
                else
                    % Testing mode - just log the command
                    fprintf(flog, '[TESTING] Would call: makedailyiquam(%d, %d, %d, %s, %s, %s)\n', ...
                        y, d, rewrite, outputDir, cacheDir, sourceUrl);
                    fprintf('DEBUG: [TESTING] Skipped makedailyiquam call\n');
                end
            end

        end  % end dt loop (temporal window)

        % ================================================================
        % REA MODE: Temporal Aggregation (STUB - Not Yet Implemented)
        % ================================================================
        % After processing all ±buoyDayRange .bii files for this analysis day,
        % aggregate them into a single .biq file for the final analysis.
        %
        % This would call refbii2biq.m to:
        %   1. Read all .bii files from [day-reaAggregationWindow : day+reaAggregationWindow]
        %   2. Apply platform-specific error weighting
        %   3. Apply temporal weighting based on distance from analysis day
        %   4. Write aggregated .biq file to reaOutputDir
        %
        if enableREA && (realtime == 0)
            % Only run REA aggregation for "Final run" days (not interim/NRT)
            fprintf(flog, '[REA STUB] Would aggregate temporal window for analysis day %04d/%03d\n', ...
                year, day);

            % Future implementation:
            % refbii2biq(year, day, outputDir, reaOutputDir, reaAggregationWindow);
            %
            % Where refbii2biq.m would be refactored to accept:
            %   - year, day: Analysis date
            %   - biiInputDir: Directory containing .bii files (outputDir)
            %   - biqOutputDir: Directory for .biq output (reaOutputDir)
            %   - dayrange: Temporal window (reaAggregationWindow)
        end

    end  % end day loop

end  % end year loop

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

function ordDay = ordinalDay(doy, year)
% Returns cumulative days since a reference point (Jan 0, year 1)
% Used for comparing dates across year boundaries
    ordDay = datenum(year, 1, 0) + doy;
end
