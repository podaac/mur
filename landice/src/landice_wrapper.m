function landice_wrapper(landmask_p01, gridindex_north_p01, gridindex_south_p01, ...
                          landmask_p011, gridindex_north_p011, gridindex_south_p011, ...
                          output_dir_p011, output_dir_p01, year_str, doy_str)
%LANDICE_WRAPPER Wrapper function for compiled MATLAB executable
%   This wrapper accepts all string inputs from command line and calls
%   makeicefiles for both p01 and p011 resolutions, each with its own
%   explicit static input files and output directory (matching production's
%   separate NAS paths).
%
%   Usage:
%   landice_wrapper('/path/to/landmask-p01.gds', '/path/to/gridindex-north-p01.mat', ...
%                    '/path/to/gridindex-south-p01.mat', '/path/to/landmask-p011.gds', ...
%                    '/path/to/gridindex-north-p011.mat', '/path/to/gridindex-south-p011.mat', ...
%                    '/path/to/output-p011', '/path/to/output-p01', '2024', '100')
%
%   When compiled as executable:
%   ./LandiceProcessor landmask-p01.gds gridindex-north-p01.mat gridindex-south-p01.mat \
%       landmask-p011.gds gridindex-north-p011.mat gridindex-south-p011.mat \
%       /path/to/output-p011 /path/to/output-p01 2024 100

start_time = datetime('now');

% Display input parameters
fprintf('landice_wrapper: landmask_p01 - %s\n', landmask_p01);
fprintf('landice_wrapper: gridindex_north_p01 - %s\n', gridindex_north_p01);
fprintf('landice_wrapper: gridindex_south_p01 - %s\n', gridindex_south_p01);
fprintf('landice_wrapper: landmask_p011 - %s\n', landmask_p011);
fprintf('landice_wrapper: gridindex_north_p011 - %s\n', gridindex_north_p011);
fprintf('landice_wrapper: gridindex_south_p011 - %s\n', gridindex_south_p011);
fprintf('landice_wrapper: output_dir_p011 - %s\n', output_dir_p011);
fprintf('landice_wrapper: output_dir_p01 - %s\n', output_dir_p01);
fprintf('landice_wrapper: year - %s\n', year_str);
fprintf('landice_wrapper: doy - %s\n', doy_str);

% Set up environment variables
setup_environment();

fprintf('landice_wrapper: Running land ice operations for %s/%s\n', year_str, doy_str);

% Process both resolutions with their respective explicit input files and output directory
resolutions = {'p01', 'p011'};
output_dirs = {output_dir_p01, output_dir_p011};
landmask_files = {landmask_p01, landmask_p011};
gridindex_north_files = {gridindex_north_p01, gridindex_north_p011};
gridindex_south_files = {gridindex_south_p01, gridindex_south_p011};
for i = 1:length(resolutions)
    res = resolutions{i};
    odir = output_dirs{i};
    fprintf('\nlandice_wrapper: ===== Processing %s resolution =====\n', res);

    % Call makeicefiles for this resolution with its explicit static files and output directory
    [icesstfile, landicefile] = makeicefiles(landmask_files{i}, gridindex_north_files{i}, ...
                                              gridindex_south_files{i}, odir, ...
                                              year_str, doy_str, res);

    % Compress output files
    if ~isempty(landicefile) && isfile(landicefile)
        fprintf('landice_wrapper: Compressing %s\n', landicefile);
        gzip(landicefile);
        delete(landicefile);
    end

    if ~isempty(icesstfile) && isfile(icesstfile)
        fprintf('landice_wrapper: Compressing %s\n', icesstfile);
        gzip(icesstfile);
        delete(icesstfile);
    end
end

% Report completion
end_time = datetime('now');
execution_time = end_time - start_time;
fprintf('\nlandice_wrapper: Execution completed successfully\n');
fprintf('landice_wrapper: Total execution time: %s\n', string(execution_time));

end
