function setup_environment()
%SETUP_ENVIRONMENT Set up environment variables for OSISAF ice data access
%   This function sets the environment variables needed for ice data
%   retrieval from OSI-SAF. Only sets default values if not already defined,
%   so the caller (run_mur_pipeline.py / the container's -e flags) always
%   wins.
%
%   OSI-SAF's anonymous FTP (ftp://osisaf.met.no) is dead -- connections to
%   it now time out -- so these defaults are the HTTPS THREDDS fileServer
%   endpoints. The variable names keep their _FTP_ spelling because they are
%   part of the container's published interface; readosisafice.m dispatches
%   on the URL scheme, so an ftp:// value still works if one is supplied.

% Current and recent days: the amsr2_conc tree, which despite its name now
% serves AMSR3 files from 2026-08-31 onward (see readosisafice.m).
osisaf_thredds = 'https://thredds.met.no/thredds/fileServer/osisaf/met.no/ice/amsr2_conc';

if isempty(getenv('OSISAF_FTP_ARCHIVE'))
    setenv('OSISAF_FTP_ARCHIVE', osisaf_thredds);
end
if isempty(getenv('OSISAF_FTP_PROD'))
    setenv('OSISAF_FTP_PROD', osisaf_thredds);
end

% No default for the reprocessed record (pre-2009 dates). Its old FTP path,
% ftp://osisaf.met.no/reprocessed/ice/conc/v1p2, is dead along with the rest
% of that host, and the polstere-100 "reproc" product it served has no
% verified HTTPS equivalent on thredds.met.no -- OSI-SAF appears to have
% superseded it with OSI-450-a, which uses a different grid and different
% filenames, so pointing this at a guessed URL would be worse than leaving
% it unset. Historical reprocessing must pass OSISAF_FTP_REPROCESSED
% explicitly; readosisafice.m reports the unset variable by name rather than
% timing out against a dead host.

fprintf('Environment variables set for OSISAF data access\n');

end
