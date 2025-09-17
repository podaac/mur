%% biasbip4.m
function biasbip4(sensors,year,day,bipdir,region)

%% 1) interpolate all residual bip files at resolution of Lbias;
%% 2) form satellite bias as difference between satellite & in-situ residuals;
%% 3) substract satellite bias from satellite bip files.
%% 4) If residual files are absent, bip files will not be altered.

%% input:
%%   sensors = copy of one used by the mrva script, e.g., mrva2com.m
%%   year, day, bipdir, region = also copies from the mrva script.



%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
% parameters:

%Lbias=4;
%Lbias=3;
Lbias=2;
%Lbias=0;


% mrva parameters:
L0=Lbias; LF=Lbias;
decay=[48*ones(1,6),42,36,30,24,18,12];



%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%


nbipfile=size(sensors,1);


for n=1:nbipfile,

  %% Coefficients of the residual files:

    % reference coefficients are obtained first:
    if n==0,  % do the reference (in situ) residual file:
      sensor=refdata{1,1};
    else,  % do the sensor residual files:
      sensor=sensors{n,1};
    end;


    % residual bip file:
    resfile=sprintf('%s/%s_%s_%04d_%03d.biq.res.biq',...
                     bipdir,region,sensor,year,day);

    fprintf(1,'BiasBip: making L%d for %s\n',Lbias,resfile);

    % make mrva.nml file:
    f=fopen('mrva.nml','w');
      b=[-180,180,-90,90];
      fprintf(f,' $input\n');
      fprintf(f,'lonmin=%f\nlonmax=%f\n',b(1),b(2));
      fprintf(f,'latmin=%f\nlatmax=%f\n',b(3),b(4));
      fprintf(f,'L0=%d\nLF=%d\n',L0,LF);
      fprintf(f,'decay=\n');
        fprintf(f,'  %f,%f,%f,%f,\n',decay(1:4));
        fprintf(f,'  %f,%f,%f,%f,\n',decay(5:8));
        fprintf(f,'  %f,%f,%f,%f,\n',decay(9:12));
      fprintf(f,'bgfile=''%s''\n',' ');
      fprintf(f,'coefile=''%s''\n',' ');
      fprintf(f,'nbipfile=%d\n',1);
      fprintf(f,'bipfile=\n');
      fprintf(f,'''%d'',''%d'',''%s'',\n',L0,LF,resfile);
      fprintf(f,' $end\n');
    fclose(f);


    % run mrva:
    ! /opt/mrva/bin/mrva > log.biasbip;
    ! cat mrva.nml >> log.biasbip;
    eval(sprintf('!rm -f mrva_001.a%02d',LF));
    eval(sprintf('!rm -f fort.%02d',LF+80));

    % remove residual bip file:
    delete(resfile);

  %% Determine and remove the sensor bias:

    % bip data file:
    bipfile=sprintf('%s/%s_%s_%04d_%03d.biq',bipdir,region,sensor,year,day);


      % sensor bip data:
      f=fopen(bipfile,'r');
        % Read first Fortran record: Nbip (integer*4)
        fread(f, 1, 'uint32');  % Record size marker (start)
        Nbip = fread(f, 1, 'int32');
        fread(f, 1, 'uint32');  % Record size marker (end)

        % Read second Fortran record: lon,lat,hour,sst,wgt arrays (5 * Nbip real*4 values)
        fread(f, 1, 'uint32');  % Record size marker (start)
        lon = fread(f, Nbip, 'real*4=>single');
        lat = fread(f, Nbip, 'real*4=>single');
        hour = fread(f, Nbip, 'real*4=>single');
        sst = fread(f, Nbip, 'real*4=>single');
        wgt = fread(f, Nbip, 'real*4=>single');
        fread(f, 1, 'uint32');  % Record size marker (end)
      fclose(f);

      % bias determination:
%      rsensor=samplecsp(sprintf('mrva.c%02d',LF),lon,lat);
%      rinsitu=samplecsp(refcspfile,lon,lat);
%      bias=rsensor-rinsitu;
      bias=samplecsp(sprintf('mrva.c%02d',LF),lon,lat);

      % remove bias:
      sst=sst-bias;

      % write new bip data file:
      f=fopen(bipfile,'w');
        fortwrite(f,'integer*4',Nbip);
        fortwrite(f,lon);
        fortwrite(f,lat);
        fortwrite(f,hour);
        fortwrite(f,sst);
        fortwrite(f,wgt);
      fclose(f);

      fprintf(1,'BiasBip: corrected %s\n',resfile);


end; % n.






%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%

function outval=samplecsp(cspfile,lon,lat)

  if ~exist(cspfile,'file'), outval=zeros(size(lon)); return; end;

  eval(sprintf('! ln -sf %s cbsdata.out',cspfile));
  
  %% run "cbscoeff" (non-global) or "cbscxcoeff" (global):

        f=fopen('cbspoints.dat','w');
        nx=length(lon);
        fortwrite(f,'integer*4',[nx,-1,0,0]);
        fortwrite(f,'real*4',lon,'real*4',lat);
        fclose(f);

        % Container: Use fixed path to Fortran executables
        fortran_bin='/opt/mrva/bin';
        %eval(sprintf('! %s/cbscoeff',fortran_bin)); % execute spline.
        eval(sprintf('! %s/cbscxcoeff',fortran_bin)); % execute spline.
        f=fopen('cbs.out','r');
        % Read Fortran record with markers
        fread(f, 1, 'uint32');  % Skip record marker
        outval = fread(f, nx, 'real*4=>single');
        fread(f, 1, 'uint32');  % Skip record marker
        fclose(f);
        ! rm -f cbspoints.dat cbs.out cbsdata.out

