%% biasbip.m
function biasbip(refdata,sensors,year,day,bipdir,region)

%% 1) interpolate all residual bip files at resolution of Lbias;
%% 2) form satellite bias as difference between satellite & in-situ residuals;
%% 3) substract satellite bias from satellite bip files.
%% 4) If residual files are absent, bip files will not be altered.

%% input:
%%   sensors = copy of one used by the mrva script, e.g., mrva2com.m
%%   year, day, bipdir, region = also copies from the mrva script.



%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
% parameters:

Lbias=3;
Lbias=2;
Lbias=0;


% mrva parameters:
L0=Lbias; LF=Lbias;
decay=[48*ones(1,6),42,36,30,24,18,12];



%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%



nbipfile=size(sensors,1);


for n=0:nbipfile,

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
    ! ./mrva > log.biasbip;
    ! cat mrva.nml >> log.biasbip;
    eval(sprintf('!rm -f mrva_001.a%02d',LF));
    eval(sprintf('!rm -f fort.%02d',LF+80));

    % remove residual bip file:
%    delete(resfile);

  %% Determine and remove the sensor bias:

    % bip data file:
    bipfile=sprintf('%s/%s_%s_%04d_%03d.biq',bipdir,region,sensor,year,day);

    if n==0,  % save the reference coefficient:

      refcspfile='biasbip_ref.csp';
      eval(sprintf('!mv mrva.c%02d %s',LF,refcspfile));

      %delete(bipfile);  % reference data no longer needed.

    else,  % do the sensor bias:

      % sensor bip data:
      f=fopen(bipfile,'r');
        Nbip=fortread(f,'integer*4',1);
        lon=fortread(f,Nbip);
        lat=fortread(f,Nbip);
        hour=fortread(f,Nbip);
        sst=fortread(f,Nbip);
        wgt=fortread(f,Nbip);
      fclose(f);

      % bias determination:
      rsensor=samplecsp(sprintf('mrva.c%02d',LF),lon,lat);
      rinsitu=samplecsp(refcspfile,lon,lat);
      bias=rsensor-rinsitu;

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

    end; % else n==0.

end; % n.

delete(refcspfile);





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
        outval=fortread(f,nx);
        fclose(f);
        ! rm -f cbspoints.dat cbs.out cbsdata.out

