%% pushMURnc.m


%% Source:

ncdir = '/nas/ftp/mur_sst/tmchin/GDS2/L4';

%
whichdays={
%2016,[42,43]
%2017,[268]
%2017,269:271
2020,80:80
};
realtime=0;
realtime=1;

%%%%%

L=11; region='Global'; hourAna=9;


%% Destination:

podaacpush=1;  % set this flag to push into PODAAC JPL-MUR-RTO depository.
%if realtime, podaacpush=0; end;

ncsubdir='GLOB/JPL/MUR';  % destination directory (will be created).
ncsubdir=[ncsubdir,'/v4'];  % destination directory (will be created).


version='04.1'; % is used to chose landmask & in both filename and metadata.


namebody=sprintf('%02d0000-JPL-L4_GHRSST-SSTfnd-MUR-GLOB-v02.0-fv%s',hourAna,version);  % GDS-2.0.


%compression='gzip';
%compression='bzip2';
compression='';

%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%

switch compression,
  case 'gzip', ctail='.gz';
  case 'bzip2', ctail='.bz2';
  otherwise, ctail='';
end;


%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%

fprintf(1,'starting main loop ... \n');

for daycounter=1:size(whichdays,1),
  year=whichdays{daycounter,1};
for day=whichdays{daycounter,2},


    %% make the destination:
    if strfind(ncdir,'delme'), 
      ddir = sprintf('%s/%03d',ncdir,day);
    else,
      ddir = sprintf('%s/%s',ncdir,ncsubdir);
      ddir = sprintf('%s/%04d/%03d',ddir,year,day);
    end;

    if realtime, ddir=[ddir,'nrt']; end;  % marker for rewriting.

    %%%%%%%%%%

    %% *.nc and *.xml file names:
    [d,m,y]=julian(day,year);
    ncbasename=sprintf('%04d%02d%02d%s.nc',y,m,d,namebody);
    ncname=sprintf('%s/%s',ddir,ncbasename);
    xmlbasename=sprintf('FR-%04d%02d%02d-%s.xml',y,m,d,namebody);
    xmlname=sprintf('%s/%s',ddir,xmlbasename);



  %%%%%%%%%%%%%%%%%%%%%%%%%%%%
  % compression and checksum %
  %%%%%%%%%%%%%%%%%%%%%%%%%%%%

  if 0,
    eval(sprintf('! %s -f %s',compression,ncname));
    back=pwd; cd(ddir);  % go to the data directory.
    eval(sprintf('! md5sum %s%s > %s%s.md5',ncbasename,ctail,ncname,ctail));
%    eval(sprintf('! md5sum %s > %s.md5',xmlbasename,xmlname));
    cd(back);
  end;



  %%%%%%%%%%%%%%%%%%%%%%%
  % "push" into PO.DAAC %
  %%%%%%%%%%%%%%%%%%%%%%%

  if podaacpush,
    back=pwd; cd(ddir);  % go to the data directory.
    %cmd=sprintf('!%s/putsftpfile.sh sftp-ghrsst@seafire JPL-MUR-RTO/tmp',back);
    cmd=sprintf('!%s/putsftpfile.sh gds2@ops-seafire.jpl.nasa.gov JPL/tmp',back);
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
