function landice_wrapper(input_dir, output_dir, year_str, doy_str)
%LANDICE_WRAPPER Wrapper function for compiled MATLAB executable
%   This wrapper accepts all string inputs from command line and calls
%   makeicefiles for both p01 and p011 resolutions
%
%   Usage:
%   landice_wrapper('/path/to/input', '/path/to/output', '2024', '100')
%
%   When compiled as executable:
%   ./LandIce /path/to/input /path/to/output 2024 100

start_time = datetime('now');

% Display input parameters
fprintf('landice_wrapper: input_dir - %s\n', input_dir);
fprintf('landice_wrapper: output_dir - %s\n', output_dir);
fprintf('landice_wrapper: year - %s\n', year_str);
fprintf('landice_wrapper: doy - %s\n', doy_str);

% Set up environment variables
setup_environment();

fprintf('landice_wrapper: Running land ice operations for %s/%s\n', year_str, doy_str);

% Process both resolutions
resolutions = {'p01', 'p011'};
for i = 1:length(resolutions)
    res = resolutions{i};
    fprintf('\nlandice_wrapper: ===== Processing %s resolution =====\n', res);

    % Call makeicefiles for this resolution
    [icesstfile, landicefile] = makeicefiles(input_dir, output_dir, ...
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