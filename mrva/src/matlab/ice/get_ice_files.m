%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
% Retrieve any ice data that was used %
%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
function ice_string = get_ice_files(filename, executing_function)

    if exist(filename,'file'),
        files = readlines(filename);
        ice_files = files(1:2);
        fprintf(1, '%s: read OSISAF ice files from %s.\n', filename, executing_function);
        ice_string = strjoin(ice_files,', ');
    else
        fprintf(1, '%s: No OSISAF ice files were found. Could not locate: %s.\n', filename, executing_function);
        ice_string = '';
    end
  
end