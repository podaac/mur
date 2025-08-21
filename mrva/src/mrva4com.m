% mrva4com.m
% version: 13.03.6
% version: 13.10.17

%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%

%% run control:

if ~exist('realtime','var'),
  realtime=1;  % set to run in "near real time" mode.
  realtime=0;  % set to run in "near real time" mode.
end;


%L0=2; LF=10; outL=LF;  % resolution of the netCDF (output) interpolation.
%L0=2; LF=11; outL=10;  % resolution of the netCDF (output) interpolation.
L0=2; LF=11; outL=10; outL4=11; % resolution of the netCDF (output).
%if realtime, LF=outL; end;


netcdfFlag=1;  % use csp2nc.m and csp2nc4.m if set.
ncdir=append(outdir,'/','1km')
mkdir(ncdir)


decay=[48*ones(1,6),42,36,30,24,18,12];
bgfile='';
coefile='';


config_string = fileread(configfile);
config_data = jsondecode(config_string)
disp(config_data)
exit()


refdata={ % sensor, bindir, binregion, La, Lb, dayrange:
          % (window size will be "dayrange*2+1", where dayrange < 365.)
'IQUAM0', append(indir,'/','iquam'),'Global',0,6, 3,
%'FNMOCs','/nas2/fnmoc','GLOBAL',0,6, 3,
};


sensors={ % sensor, bindir, binregion, La, Lb, dayrange:
'IQUAM0','/nas2/iquam','Global',0,6, 3,
%'AMSREA','/nas2/bic/AMSREA','Global',2,8,  2,
'AMSR2R','/nas2/bic/AMSR2R','Global',2,8,  2,
%'WINSAT','/nas2/bic/WINSAT','Global',2,8,  2,
'MODISA','/nas2/bic/MODISA','Global',2,12, 2,
'MODIST','/nas2/bic/MODIST','Global',2,12, 2,
%'VIIRSN','/nas2/bic/VIIRSN','Global',2,12, 2,
%'VIIRSO','/nas2/bic/VIIRSO','Global',2,12, 2,
%'AVH18G','/nas2/bic/AVH18G','Global',2,9,  2,
%'AVH19G','/nas2/bic/AVH19G','Global',2,9,  2,
'AVMTAG','/nas2/bic/AVMTAG','Global',2,9,  2,
'AVMTBG','/nas2/bic/AVMTBG','Global',2,9,  2,
%'PATH5D','/nas2/bic/PATH5D','Global',2,9,  2,
%'PATH5N','/nas2/bic/PATH5N','Global',2,9,  2,
%%'FNMOCs','/nas2/BIN','GLOBAL',2,6, 2,
%%'AATSRi','/nas2/BIN','Global',2,10, 2,
%%'AVH18L','/nas2/BIN','Global',2,10, 1,
};
coedir='/nas2/ecmwf/cbs';  % wind *.coe file directory.

sstOffset=273.15;  % reduce the SST magnitude (e.g., from Kelvin to Celcius)

hourAna=9;  % UTC. Analysis Time.

trimbipFlag=1;  % use trimbip.m if set.
biasbipFlag=1;  % use biasbip.m if set.
prepbipFlag=0;  % use prepbip.m if set.

icecapFlag=1;  % use Global_ice_*.bip.gz to set ice cap.
icedir='/nas/ftp/mur_sst/tmchin/landice';  % root dir of Global_ice_* files.

hiresgridFlag=1;  % use makehiresgrid.f to make dt_1km_data for GDS2.

%% set "whichdays" if you're running this script from another script.
if ~exist('whichdays','var'),  % set the dates here for "stand-alone" run.
  whichdays={
%2009,90:-1:1
%2009,90:90:360
%2011,241:-1:1
%2012,[10]
%2013,21:22
%2013,46:48
%2010,20:60:365
%2011,20:60:365
%2012,20:60:365
%2013,68:-1:60
%2013,74:-1:60
%2012,213:-1:1
%2011,365:-1:1
%2010,365:-1:1
%2010,193:-1:1
%2002,365:-1:152
%2002,365:-1:152
%2014,363:365
%2015,1:2
%2016,32:35
%2016,1:31
2020,244:-1:183
  };
end;


region='Global';  box=[-180., 180., -90., 90.]; 
%region='NCAMERICA',   box=[-165.,  -30., -20., 62.];
%region='DXPACIFIC',   box=[120., 290., -20., 20.];
%region='AMAMIOSHIMA', box=[125.,  132.,  26.,  32.];
%region='OKINAWA',     box=[120.,  140.,  20.,  35.];


%outgridfile='/home/tmchin/pathfinder/ryan/ryanNCAMERICA.out';  % map grid.
%outgridfile='/home/tmchin/pathfinder/ryan/gmt_landmask_global.map';
outgridfile='/home/tmchin/pathfinder/ryan/Global10km.out';  % map grid.

mapL0=outL; mapLF=outL;  % resolution range of the map(s) to be created.
mapbody='MUR_Global_1km';  % main name for *.map file.
maptime0='000000Z'; maptime1='180000Z'; % [hhmmss] time range for buoy matchup.


bipdir='./bip';       % where bip files will be stored (then deleted).
mapdir='/tmp/mrva4map';  % where map files will go.
logdir='/tmp/logs';  % where log files will go.
cspbasedir='/nas/ftp/mur_sst/tmchin/cyc4out';  % base directory of csp outputs.
cspbasedir='/nas4/cyc4out';  % base directory of csp outputs.
cspfmt='%04d%02d%02d%02d_MRVA4_%s';  % output file body name format.


delbipFlag=1;  % bip files erased if set.

%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%

if 0,  % set this for testing:
  netcdfFlag=0;  % use csp2nc.m if set.
  delbipFlag=0;  % bip files erased if set.
  cspbasedir='./cyc4out';  % base directory of csp file outputs.
  mapdir='./mrva4map';  % where map files will go.
  logdir='./logs';  % where log files will go.

    if 1,  % set this to test GHRSST outputs:
      netcdfFlag=1;  % use csp2nc.m if set.
      ncdir='/tmp';  % netcdf output directory (must exist).
      delbipFlag=0;  % bip files erased if set.
      cspbasedir='/nas5/cyc4out';
    end;

end;


%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%

if ~exist(bipdir,'dir'), mkdir(bipdir); end;
if ~exist(mapdir,'dir'), mkdir(mapdir); end;
if ~exist(logdir,'dir'), mkdir(logdir); end;
if ~exist(cspbasedir,'dir'), mkdir(cspbasedir); end;

checkfreedisk(cspbasedir,99,0.205);

%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%



for daycounter=1:size(whichdays,1),
  year=whichdays{daycounter,1};
for day=whichdays{daycounter,2},

    %% main output:
    cspdir=sprintf('%s/%04d',cspbasedir,year);
    if ~exist(cspdir,'dir'), eval(sprintf('! mkdir -p %s',cspdir)); end;

    [d,m,y]=julian(day,year);
    cspbody=sprintf(['%s/',cspfmt],cspdir,y,m,d,hourAna,region);




    %% make *.bip/biq files:

      %% main datasets:
      logfile=makebiq(sensors,year,day,hourAna,box,bipdir,coedir);

      if exist(logfile,'file'),
        if realtime,  % add a realtime marker in the csp text:
            realtimemsg='RealTime 0 0 0 (realtime if this line exists)';
            eval(sprintf('!echo "%s" > rtline.txt',realtimemsg));
            eval(sprintf('!cat %s >> rtline.txt',logfile));
            eval(sprintf('!mv rtline.txt %s',logfile));
        end;
        name=sprintf('%s_inputs.txt',cspbody);
        eval(sprintf('!mv %s %s',logfile,name));
      end;

      %% reference data:
      makebiq(refdata,year,day,hourAna,box,bipdir);
        % If a data set appears in both "sensors" and "refdata",
        % the "refdata" one will be executed.


    %% set sst values under ice:

      % ice data are from pre-made bip files (e.g. $home/ice/makeice.m)
      % and are directly assimilated by mrva.

    if icecapFlag,  
      %icesstfile=sprintf('%s/icefile.bip',bipdir);
      icesstfile=sprintf('%s/icesst_%04d_%03d.bip',bipdir,year,day);
      icefile=sprintf('%s/%04d/Global_ice_%04d_%03d.bip',icedir,year,year,day);
      eval(sprintf('!zcat %s.gz > %s',icefile,icesstfile));
      iceconvert(icesstfile);  % added 12.12.18
      %
      polarcap=sprintf('%s/cylindercap.bip',bipdir);
      eval(sprintf('!ln -sf /nas2/landice/CylinderP01_edge.bip %s',polarcap));
    else,
      icesstfile=[];
    end;


    %% reference/background field:
    if 1,  % construct reference field from scratch (makeref.m):

      Lref=7;
      Lref0=L0;
      coefile='';

      %% For NRT run, update coefile and Lref0:
      if realtime,  % set up "coefile";
        Lnrt0=6;  % make sure to cover the buoys.
        y=year; d=day-1;  % use previous day's MUR
        %% adjust if the date (y,d) is in a different year:
        if d<1,
          y=y-1;
          if mod(y,4)==0&(mod(y,100)~=0|mod(y,400)==0),md=366;else,md=365;end;
          d=d+md;
        else,
          if mod(y,4)==0&(mod(y,100)~=0|mod(y,400)==0),md=366;else,md=365;end;
          if d>md, d=d-md; y=y+1; end;
        end;
        [d,m,y]=julian(d,y);
        name=sprintf(['%s/%04d/',cspfmt],cspbasedir,y,y,m,d,hourAna,region);
        coefile=sprintf('%s.c%02d',name,Lnrt0);
        Lref0=Lnrt0;
      end;


      %excludelist={'MODISA','MODIST','PATH5D','PATH5N','VIIRSN'};
      excludelist={'AVH18G','MODISA','MODIST','PATH5D','PATH5N','VIIRSN'};
      [o,inx]=setdiff(sensors(:,1),excludelist);
      inx=sort(inx);
      reffile=makeref(year,day,sensors(inx,:),Lref0,Lref,...
                      bipdir,decay,icesstfile,polarcap,coefile);

      
      %% For NRT, direct the main mrva run to use background coefile:
      if realtime,  % use the reffile as the initial coefficient:
        coefile=reffile;
        L0=Lref;  % initial scale must match coefile's.
      end;

    else,  % use default reference field (trimbip3.m):
        reffile='';
    end;




    %% outlier and bias removal:

    if trimbipFlag,  

      %% outlier removal:
      %trimbip([refdata;sensors],year,day,bipdir,region);
      %trimbip(sensors,year,day,bipdir,region);
      trimbip3a(sensors,year,day,bipdir,region,reffile);

      if biasbipFlag,  %% intersensor bias removal:
%        biasbip(refdata,sensors,year,day,bipdir,region);
%        biaslist={'MODISA','MODIST'};
        biaslist={'MODISA','MODIST','VIIRSN'};
        inx=find( ismember(sensors(:,1),biaslist) );
        biasbip4(sensors(inx,:),year,day,bipdir,region);
      end;

    else,

      %% to be phased out:
      if prepbipFlag,  prepbip(sensors,year,day,bipdir); end;

    end;




    %% run mrva:

    f=fopen('mrva.nml','w');
    fprintf(f,' $input\n');
    fprintf(f,'lonmin=%f\nlonmax=%f\n',box(1),box(2));
    fprintf(f,'latmin=%f\nlatmax=%f\n',box(3),box(4));
    fprintf(f,'L0=%d\nLF=%d\n',L0,LF);
    fprintf(f,'decay=\n');
      fprintf(f,'  %f,%f,%f,%f,\n',decay(1:4));
      fprintf(f,'  %f,%f,%f,%f,\n',decay(5:8));
      fprintf(f,'  %f,%f,%f,%f,\n',decay(9:12));
    fprintf(f,'bgfile=''%s''\n',bgfile);
    fprintf(f,'coefile=''%s''\n',coefile);
    nbipfile=size(sensors,1);
    if length(icesstfile)
      fprintf(f,'nbipfile=%d\nbipfile=\n',nbipfile+2);
      %fprintf(f,'''%d'',''%d'',''%s'',\n',L0,6,icesstfile);
      fprintf(f,'''%d'',''%d'',''%s'',\n',L0,9,icesstfile);
      fprintf(f,'''%d'',''%d'',''%s'',\n',L0,9,polarcap);
    else,
      fprintf(f,'nbipfile=%d\nbipfile=\n',nbipfile);
    end;
    for n=1:nbipfile,
      sensor=sensors{n,1};
      %bipfile=sprintf('%s/%s_%s_%04d_%03d.bip',bipdir,region,sensor,year,day);
      bipfile=sprintf('%s/%s_%s_%04d_%03d.biq',bipdir,region,sensor,year,day);
      fprintf(f,'''%d'',''%d'',''%s'',\n',sensors{n,4},sensors{n,5},bipfile);
    end;
    fprintf(f,' $end\n');
    fclose(f);

    ! ./mrva;



    %% for seeerr.m (run spgrid first):
    f=fopen('spgrid.nml','w');
    fprintf(f,' $input\n');
    fprintf(f,'sstoffset=%f\n',0);
    fprintf(f,'nlist=%d\n',LF-L0+1);
    fprintf(f,'coeffilelist=\n');
    for L=L0:LF
      name=sprintf('%s.u%02d',cspbody,L);
      fprintf(f,'''%d'',''%s'',\n',L,name);
    end;
    fprintf(f,'outgridfile=\n''%s''\n',outgridfile);
    fprintf(f,' $end\n');
    fclose(f);



    %% save coefficients (analysis and uncertainty):

    for L=L0:LF

        name=sprintf('%s.c%02d',cspbody,L);
        eval(sprintf('!mv ./mrva.c%02d %s',L,name));

      if ismember(L,6:8),  % save space by saving only selected uncertainty:
        name=sprintf('%s.u%02d',cspbody,L);
        eval(sprintf('!mv ./mrva.u%02d %s',L,name));
      end;

    end;


    %% make MUR25 first:
    makeMUR25( year, day, realtime, 1 );


    %% *.map file:
    if ~exist(mapdir,'dir'), eval(sprintf('! mkdir %s',mapdir)); end;

    for L=mapL0:mapLF

        f=fopen(sprintf('fort.%02d',80+L),'r');
        [idm,jdm]=fortread(f,'integer*4',1,'integer*4',1);
        fclose(f);

        [d,m,y]=julian(day,year);
        name=sprintf('%s/%d%02d%02dT%s',mapdir,y,m,d,maptime0);
        name=sprintf('%s-%d%02d%02dT%s',name,y,m,d,maptime1);

        name=sprintf('%s-%s-%dx%d.map',name,mapbody,idm,jdm);
        eval(sprintf('!mv fort.%02d %s',80+L,name));

    end;


    %% HiResGrid (dt_1km_data) for GDS2:
    if hiresgridFlag,
      hiresgridfile=makehiresgrid(year,day,sensors(:,1));
      %%disp(['created: ',hiresgridfile]);
      %%if 0, % save dt_1km_data (large file):
      %%  system(sprintf('cp -p %s /home/tmchin/nas/grd/',hiresgridfile));
      %%end;
    end;


    %% make netCDF file:
    if netcdfFlag,
      if ~exist(logdir,'dir'), eval(sprintf('! mkdir %s',logdir)); end;

      %matlabcmd='/usr/local/bin/matlab -nodesktop -nosplash';
      %matlabcmd='/home/tmchin/matlabR2011b/bin/matlab -nodisplay';  % Matlab11.
      %matlabcmd='/usr/local/bin/matlab -nodisplay';  % no more Matlab11.
      %matlabcmd='/opt/matlab/R2012b/bin/matlab -nodisplay';
      matlabcmd='/opt/matlab/R2021b/bin/matlab -nodisplay';

      netCDFcmd=sprintf('matscript%04d_%03d.m',year,day);
      netCDFlog=sprintf('%s/csp2nc_%04d_%03d.log',logdir,year,day);
      f=fopen(netCDFcmd,'w');
      fprintf(f,'ncdir=''%s'';\n',ncdir);
      fprintf(f,'cspdir=''%s'';\n',cspdir);
      fprintf(f,'cspfmt=''%s'';\n',cspfmt); % used only by csp2nc4.m
      fprintf(f,'L=%d;\n',outL);
      fprintf(f,'region=''%s'';\n',region);
      fprintf(f,'hourAna=%d;\n',hourAna);
      fprintf(f,'whichdays={%d,%d:%d};\n',year,day,day);
      fprintf(f,'realtime=%d;\n',realtime);
%      fprintf(f,'csp2nc;\n');  % GDS1 discontinued.
        % GDS2 below:
      fprintf(f,'L=%d;\n',outL4);
      if hiresgridFlag, % comment out fprintf below to stop packaging "dt":
        fprintf(f,'hiresgridfile=''%s'';\n',hiresgridfile); % includes "dt".
      end;
%      fprintf(f,'csp2nc4;\n');
      fprintf(f,'csp2nc4a;\n');  % anomaly field added ("experimental field')
      fclose(f);
      % ! /usr/local/bin/matlab -nodesktop -nosplash < matscript.m >& matlog &
      eval(sprintf('! %s < %s >& %s &',matlabcmd,netCDFcmd,netCDFlog));
      delete(netCDFcmd);
    end;


    %% clean up bip files:
    if delbipFlag,
      ! rm -f ./bip/*.bip ./bip/*.biq
    end;

      % ALSO CLEAN UP THE refdata.bip and icesstfile

    %% clean up results:
%    eval(sprintf('! mv *.nml %s/',cspdir));
%    eval(sprintf('! mv mrva.c?? %s/',cspdir));
%    eval(sprintf('! mv mrva_???.a%02d %s/',LF,cspdir));


end;
end;
