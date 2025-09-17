%% pushL44.m

%% check the "pushed" files by:
%    sftp gds2@seafire.jpl.nasa.gov
%    cd JPL/tmp




%ncdir='/tmp';  % destination directory (must exist).
ncdir='/nas/ftp/mur_sst/tmchin/GDS2/L4';  % destination directory (must exist).


whichdays={
%2014,[359]
%2014,359:365
%2015,1:3
%2015,1:1
2015,[123]
};
realtime=0;

hourAna=9;


%%%%%


%% Destination:

podaacpush=1;  % set this flag to push into PODAAC JPL-MUR-RTO depository.
if realtime, podaacpush=0; end;


ncsubdir='GLOB/JPL/MUR';  % destination directory (will be created).

    %%   GDS 1.x:
    %%     yyyymmdd-JPL-L4UHfnd-GLOB-v01-fv01-MUR.nc
    %%   GDS 2.0:
    %%     yyyymmddhhmmss-JPL-L4_GHRSST-SSTfnd-MUR-GLOB-v02.0-fv01.0.nc

version='04.1'; % is used to chose landmask & in both filename and metadata.
%version='04'; % is used to chose landmask & in both filename and metadata.
%version='03'; % is used to chose landmask & in both filename and metadata.

%namebody=sprintf('-JPL-L4UHfnd-GLOB-v01-fv%s-MUR',version);  % GDS-1.x
namebody=sprintf('%02d0000-JPL-L4_GHRSST-SSTfnd-MUR-GLOB-v02.0-fv%s',hourAna,version);  % GDS-2.0.


%%%%%






%% land mask (if ice is included, date dependent):

switch version,
  case '03',
    ncsubdir=[ncsubdir,'/v3'];  % destination directory (will be created).
  case '04',
    ncsubdir=[ncsubdir,'/v4'];  % destination directory (will be created).
  case '04.1',
    ncsubdir=[ncsubdir,'/v4'];  % destination directory (will be created).
  otherwise,
    ncsubdir=[ncsubdir,'/v0'];  % destination directory (will be created).
end;

%%%%%

compression='none';
switch compression,
  case '', ctail='';
  case 'gzip', ctail='.gz';
  case 'bzip2', ctail='.bz2';
  otherwise, ctail='';
end;

%%%%%%%%%%%%%%%%%%%%%%%%%%%%%% End Parameters %%%%%%%%%%%%%%%%%%%%%%%%%%%%%%





for daycounter=1:size(whichdays,1),
  year=whichdays{daycounter,1};
for day=whichdays{daycounter,2},
fprintf(1,'***pushL44*** : Year %04d, Day %03d\n',year,day);

    ddir=sprintf('%s/%s',ncdir,ncsubdir);
    ddir=sprintf('%s/%04d/%03d',ddir,year,day);

    if realtime, ddir=[ddir,'nrt']; end;  % marker for rewriting.


    %% *.nc and *.xml file names:
    [d,m,y]=julian(day,year);
    ncbasename=sprintf('%04d%02d%02d%s.nc',y,m,d,namebody);



  %%%%%%%%%%%%%%%%%%%%%%%
  % "push" into PO.DAAC %
  %%%%%%%%%%%%%%%%%%%%%%%

  if podaacpush,
    back=pwd; cd(ddir);  % go to the data directory.
    %cmd=sprintf('!%s/putsftpfile.sh sftp-ghrsst@seafire JPL-MUR-RTO/tmp',back);
    cmd=sprintf('!%s/putsftpfile.sh gds2@seafire.jpl.nasa.gov JPL/tmp',back);
      pushname=sprintf('%s%s',ncbasename,ctail);
        disp(sprintf('%s %s %s',cmd,pushname,pushname));
        eval(sprintf('%s %s %s',cmd,pushname,pushname));
      pushname=[pushname,'.md5'];
        disp(sprintf('%s %s %s',cmd,pushname,pushname));
        eval(sprintf('%s %s %s',cmd,pushname,pushname));
%      pushname=xmlbasename;
%        disp(sprintf('%s %s %s',cmd,pushname,pushname));
%        eval(sprintf('%s %s %s',cmd,pushname,pushname));
%      pushname=[pushname,'.md5'];
%        disp(sprintf('%s %s %s',cmd,pushname,pushname));
%        eval(sprintf('%s %s %s',cmd,pushname,pushname));
    cd(back);
  end;


end;
end;
