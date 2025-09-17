function grid=readgrd(filename)

f=fopen(filename,'r');
% Read Fortran record header
rec_len1 = fread(f, 1, 'int32');
nlon = fread(f, 1, 'int32');
nlat = fread(f, 1, 'int32');
rec_len2 = fread(f, 1, 'int32');
assert(rec_len1 == rec_len2, 'Fortran record corruption detected in dimension read');

% Read grid data with direct type mapping (saves ~4.3 GB for global grids: int8→double→int8)
rec_len1 = fread(f, 1, 'int32');
grid = fread(f, [nlon,nlat], 'int8=>int8');
rec_len2 = fread(f, 1, 'int32');
assert(rec_len1 == rec_len2, 'Fortran record corruption detected in grid read');
fclose(f);

