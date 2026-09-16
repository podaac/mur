function setup_environment()
%SETUP_ENVIRONMENT Set up environment variables for OSISAF FTP access
%   This function sets the environment variables needed for ice data retrieval
%   from OSISAF FTP servers. Only sets default values if not already defined.

% OSISAF FTP server URLs - only set if not already defined
if isempty(getenv('OSISAF_FTP_REPROCESSED'))
    setenv('OSISAF_FTP_REPROCESSED', 'ftp://osisaf.met.no/reprocessed/ice/conc/v1p2');
end
if isempty(getenv('OSISAF_FTP_ARCHIVE'))
    setenv('OSISAF_FTP_ARCHIVE', 'ftp://osisaf.met.no/archive/ice/conc');
end
if isempty(getenv('OSISAF_FTP_PROD'))
    setenv('OSISAF_FTP_PROD', 'ftp://osisaf.met.no/prod/ice/conc');
end

fprintf('Environment variables set for OSISAF FTP access\n');

end