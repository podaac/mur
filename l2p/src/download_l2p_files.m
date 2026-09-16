function files = download_l2p_files(collection, start_date, end_date, output_dir)
%DOWNLOAD_L2P_FILES Download L2P files from NASA Earthdata using CMR API
%
%   files = download_l2p_files(collection, start_date, end_date, output_dir)
%
%   Downloads L2P NetCDF files for a given collection and date range using
%   NASA's Common Metadata Repository (CMR) API and HTTPS data access.
%
%   INPUTS:
%       collection  - PO.DAAC collection short name (e.g., 'AMSR2-REMSS-L2P-v8.2')
%       start_date  - Start date string 'YYYY-MM-DD' or 'YYYY-MM-DDTHH:MM:SSZ'
%       end_date    - End date string 'YYYY-MM-DD' or 'YYYY-MM-DDTHH:MM:SSZ'
%       output_dir  - Directory to save downloaded files
%
%   OUTPUTS:
%       files       - Cell array of downloaded file paths
%
%   AUTHENTICATION:
%       Requires .netrc file with NASA Earthdata credentials at:
%       - /root/.netrc (for containers)
%       - ~/.netrc (for local)
%
%       Format:
%           machine urs.earthdata.nasa.gov
%               login your-username
%               password your-password
%
%   EXAMPLE:
%       files = download_l2p_files('AMSR2-REMSS-L2P-v8.2', ...
%                                  '2025-08-08', '2025-08-08', '/data/input');

% ========================================================================
% VALIDATION
% ========================================================================

if ~exist(output_dir, 'dir')
    mkdir(output_dir);
    fprintf('Created output directory: %s\n', output_dir);
end

% Ensure dates have time component
if ~contains(start_date, 'T')
    start_date = [start_date 'T00:00:00Z'];
end
if ~contains(end_date, 'T')
    end_date = [end_date 'T23:59:59Z'];
end

fprintf('Searching CMR for collection: %s\n', collection);
fprintf('  Date range: %s to %s\n', start_date, end_date);

% ========================================================================
% READ .NETRC FOR AUTHENTICATION
% ========================================================================

netrc_file = find_netrc();
if isempty(netrc_file)
    warning('No .netrc file found - download may fail without authentication');
    username = '';
    password = '';
else
    [username, password] = parse_netrc(netrc_file);
    fprintf('Using credentials from: %s\n', netrc_file);
end

% ========================================================================
% SEARCH CMR API FOR GRANULES
% ========================================================================

% NASA CMR API endpoint
cmr_url = 'https://cmr.earthdata.nasa.gov/search/granules.json';

% Build query parameters
params = {
    'short_name', collection, ...
    'temporal', sprintf('%s,%s', start_date, end_date), ...
    'page_size', '2000', ...  % Max results per page
    'sort_key', '-start_date'  % Newest first
};

% Convert params to URL query string
query_string = '';
for i = 1:2:length(params)
    if i > 1
        query_string = [query_string '&'];
    end
    query_string = [query_string params{i} '=' urlencode(params{i+1})];
end

search_url = [cmr_url '?' query_string];

fprintf('Querying CMR API...\n');

% Set HTTP options for CMR search (no auth needed for search)
options = weboptions('Timeout', 30, 'ContentType', 'json');

try
    response = webread(search_url, options);
catch ME
    error('CMR search failed: %s', ME.message);
end

% Parse response
if isfield(response, 'feed') && isfield(response.feed, 'entry')
    entries = response.feed.entry;
    fprintf('Found %d granules\n', length(entries));
else
    fprintf('No granules found for this collection and date range\n');
    files = {};
    return;
end

% ========================================================================
% DOWNLOAD EACH GRANULE
% ========================================================================

files = {};
success_count = 0;
fail_count = 0;

for i = 1:length(entries)
    entry = entries(i);

    % Extract download URL
    download_url = '';
    if isfield(entry, 'links')
        for j = 1:length(entry.links)
            link = entry.links(j);
            if isfield(link, 'rel') && strcmp(link.rel, 'http://esipfed.org/ns/fedsearch/1.1/data#')
                if isfield(link, 'href') && contains(link.href, '.nc')
                    download_url = link.href;
                    break;
                end
            end
        end
    end

    if isempty(download_url)
        fprintf('  [%d/%d] No download URL found - skipping\n', i, length(entries));
        fail_count = fail_count + 1;
        continue;
    end

    % Extract filename from URL
    [~, filename, ext] = fileparts(download_url);
    % Remove query parameters if present
    if contains(filename, '?')
        parts = split(filename, '?');
        filename = parts{1};
    end
    if contains(ext, '?')
        parts = split(ext, '?');
        ext = parts{1};
    end
    local_file = fullfile(output_dir, [filename ext]);

    % Skip if file already exists
    if exist(local_file, 'file')
        fprintf('  [%d/%d] Already exists: %s\n', i, length(entries), [filename ext]);
        files{end+1} = local_file;
        success_count = success_count + 1;
        continue;
    end

    fprintf('  [%d/%d] Downloading: %s\n', i, length(entries), [filename ext]);

    % Download with authentication
    try
        % Set HTTP options with authentication
        if ~isempty(username)
            options = weboptions('Timeout', 300, ...
                                'Username', username, ...
                                'Password', password);
        else
            options = weboptions('Timeout', 300);
        end

        websave(local_file, download_url, options);
        files{end+1} = local_file;
        success_count = success_count + 1;
        fprintf('    -> Success (%.2f MB)\n', dir(local_file).bytes / 1024^2);

    catch ME
        fprintf('    -> Failed: %s\n', ME.message);
        fail_count = fail_count + 1;
        if exist(local_file, 'file')
            delete(local_file);  % Remove partial download
        end
    end
end

fprintf('\nDownload Summary:\n');
fprintf('  Success: %d\n', success_count);
fprintf('  Failed:  %d\n', fail_count);
fprintf('  Total:   %d\n', length(entries));

end

% ========================================================================
% HELPER FUNCTIONS
% ========================================================================

function netrc_file = find_netrc()
    %FIND_NETRC Locate .netrc file

    % Try common locations
    locations = {
        '/root/.netrc',
        fullfile(getenv('HOME'), '.netrc'),
        fullfile(getenv('USERPROFILE'), '.netrc')  % Windows
    };

    for i = 1:length(locations)
        if ~isempty(locations{i}) && exist(locations{i}, 'file')
            netrc_file = locations{i};
            return;
        end
    end

    netrc_file = '';
end

function [username, password] = parse_netrc(netrc_file)
    %PARSE_NETRC Parse .netrc file for urs.earthdata.nasa.gov credentials

    username = '';
    password = '';

    try
        fid = fopen(netrc_file, 'r');
        if fid == -1
            return;
        end

        in_earthdata_block = false;

        while ~feof(fid)
            line = fgetl(fid);

            % Skip comments and empty lines
            if isempty(line) || startsWith(strtrim(line), '#')
                continue;
            end

            % Check if we're in the earthdata machine block
            if contains(line, 'machine') && contains(line, 'urs.earthdata.nasa.gov')
                in_earthdata_block = true;
                continue;
            end

            % If we hit another machine block, we're done
            if in_earthdata_block && contains(line, 'machine') && ~contains(line, 'urs.earthdata.nasa.gov')
                break;
            end

            % Extract login
            if in_earthdata_block && contains(line, 'login')
                tokens = strsplit(strtrim(line));
                for i = 1:length(tokens)
                    if strcmp(tokens{i}, 'login') && i < length(tokens)
                        username = tokens{i+1};
                        break;
                    end
                end
            end

            % Extract password
            if in_earthdata_block && contains(line, 'password')
                tokens = strsplit(strtrim(line));
                for i = 1:length(tokens)
                    if strcmp(tokens{i}, 'password') && i < length(tokens)
                        password = tokens{i+1};
                        break;
                    end
                end
            end
        end

        fclose(fid);

    catch ME
        warning('Failed to parse .netrc: %s', ME.message);
    end
end
