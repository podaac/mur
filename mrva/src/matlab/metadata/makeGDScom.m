%% makeGDScom.m (just the "csp2nc" part from mrva4com.m)

% remember to add "realtime" flag value in the 3rd column:
whichdays={
2014,291:293,0
2014,294:296,1
};


%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%

%% run control:

%if ~exist('realtime','var'),
%  realtime=1;  % set to run in "near real time" mode.
%  realtime=0;  % set to run in "near real time" mode.
%end;


%L0=2; LF=10; outL=LF;  % resolution of the netCDF (output) interpolation.
%L0=2; LF=11; outL=10;  % resolution of the netCDF (output) interpolation.
L0=2; LF=11; outL=10; outL4=11; % resolution of the netCDF (output).
%if realtime, LF=outL; end;


netcdfFlag=1;  % use csp2nc.m and csp2nc4.m if set.
ncdir='/nas/ftp/mur_sst/tmchin/L4';  % netcdf output directory (must exist).
nc4dir='/nas/ftp/mur_sst/tmchin/GDS2/L4';  % GDS2 output directory (must exist).





hourAna=9;  % UTC. Analysis Time.





region='Global';  box=[-180., 180., -90., 90.]; 



logdir='/tmp/logs';  % where log files will go.
%cspbasedir='/nas/ftp/mur_sst/tmchin/cyc4out';  % base directory of csp outputs.
cspbasedir='/nas4/cyc4out';  % base directory of csp outputs.
cspfmt='%04d%02d%02d%02d_MRVA4_%s';  % output file body name format.



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
      nc4dir='/tmp';  % netcdf output directory (must exist).
      delbipFlag=0;  % bip files erased if set.
      cspbasedir='/seaward/tmchin/cyc4out';
    end;

end;


%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%

%if ~exist(bipdir,'dir'), mkdir(bipdir); end;
%if ~exist(mapdir,'dir'), mkdir(mapdir); end;
if ~exist(logdir,'dir'), mkdir(logdir); end;
if ~exist(cspbasedir,'dir'), mkdir(cspbasedir); end;

checkfreedisk(cspbasedir,99,0.205);

%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%



for daycounter=1:size(whichdays,1),
  year=whichdays{daycounter,1};
  realtime=whichdays{daycounter,3};
for day=whichdays{daycounter,2},


    %% main output:
    cspdir=sprintf('%s/%04d',cspbasedir,year);
    if ~exist(cspdir,'dir'), eval(sprintf('! mkdir -p %s',cspdir)); end;

    [d,m,y]=julian(day,year);
    cspbody=sprintf(['%s/',cspfmt],cspdir,y,m,d,hourAna,region);






    %% make netCDF file:
    if netcdfFlag,
      if ~exist(logdir,'dir'), eval(sprintf('! mkdir %s',logdir)); end;

      %matlabcmd='/usr/local/bin/matlab -nodesktop -nosplash';
      %matlabcmd='/home/tmchin/matlabR2011b/bin/matlab -nodisplay';  % Matlab11.
      %matlabcmd='/usr/local/bin/matlab -nodisplay';  % no more Matlab11.
      matlabcmd='/opt/matlab/R2012b/bin/matlab -nodisplay';
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
      fprintf(f,'csp2nc;\n');
        % GDS2 below:
      fprintf(f,'L=%d;\n',outL4);
      fprintf(f,'ncdir=''%s'';\n',nc4dir);
      fprintf(f,'csp2nc4;\n');
      fclose(f);
      % ! /usr/local/bin/matlab -nodesktop -nosplash < matscript.m >& matlog &
      %eval(sprintf('! %s < %s >& %s &',matlabcmd,netCDFcmd,netCDFlog));
      eval(sprintf('! %s < %s >& %s ',matlabcmd,netCDFcmd,netCDFlog));
      delete(netCDFcmd);
    end;



end;
end;
