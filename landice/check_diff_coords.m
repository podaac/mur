% Check coordinates of mask differences

% Read the p01 landmask file
landmask_file = '/Users/jleach/Documents/Development/MUR/mur/landice/input/grids/maskGLOBp01deg.gds';

f = fopen(landmask_file, 'r');

% Read dimensions
header1 = fread(f, 1, 'uint32=>uint32');
ii = fread(f, 1, 'int32=>int32');
jj = fread(f, 1, 'int32=>int32');
trailer1 = fread(f, 1, 'uint32=>uint32');

fprintf('Grid dimensions: ii=%d, jj=%d\n', ii, jj);

% Read mask and coordinates
header2 = fread(f, 1, 'uint32=>uint32');
mask = fread(f, [ii, jj], 'int8=>int8');
mlon = fread(f, ii, 'single=>single');
mlat = fread(f, jj, 'single=>single');
trailer2 = fread(f, 1, 'uint32=>uint32');

fclose(f);

% Difference indices from the comparison
diffs = [
    5508, 31736;
    5508, 31738;
    5509, 31736;
    5509, 31738;
    5510, 31736;
    5511, 31736;
];

fprintf('\nActual coordinates of differences:\n');
fprintf('Index (i, j) -> (lat, lon) [mask value]\n');
for idx = 1:size(diffs, 1)
    i = diffs(idx, 1);
    j = diffs(idx, 2);
    lat = mlon(i);
    lon = mlat(j);
    mask_val = mask(i, j);
    fprintf('  (%5d, %5d) -> (%7.3f°, %8.3f°) [mask=%d]\n', ...
        i, j, lat, lon, mask_val);
end

% Get range
i_vals = unique(diffs(:, 1));
j_vals = unique(diffs(:, 2));

fprintf('\nLatitude range: %.3f° to %.3f°\n', ...
    mlon(min(i_vals)), mlon(max(i_vals)));
fprintf('Longitude range: %.3f° to %.3f°\n', ...
    mlat(min(j_vals)), mlat(max(j_vals)));

fprintf('\nContext:\n');
fprintf('  Latitude ~%.1f° \n', mlon(5508));
fprintf('  Longitude ~%.1f°\n', mlat(31736));

% Check if near polar region
if abs(mlon(5508)) > 80
    fprintf('  -> Near polar region (|lat| > 80°)\n');
elseif abs(mlon(5508)) > 60
    fprintf('  -> High latitude region (|lat| > 60°)\n');
else
    fprintf('  -> Mid latitude region\n');
end
