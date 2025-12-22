%% trimbip3a.m
function refcspfile=trimbip3a(sensors,year,day,bipdir,region,MURcsp)

% Container path configuration
fortran_bin = '/opt/mrva/bin';
L4_reference_root = '/data/static-resources/L4';

%% same as trimbip.m (see just below),
%% except that refcspfile is linked to MURcsp, if "MURcsp" is given.

%% 1) converts a global GHRSST L4 file into a bip file;
%% 2) converts the bip file into SP coefficient file by running "mrva";
%% 3) writes "trimbip.nml" and runs "trimbip" or "trimbip3".
%% 4) returns empty background file name IF no action is taken.

%% input:
%%   sensors = copy of one used by the mrva script, e.g., mrva1com.m
%%   year, day, bipdir = also copies from the mrva script.

if ~exist('MURcsp','var'), MURcsp=''; end;


%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
% parameters:

%% trimbip.f parameters:
stdcspfile=' ';  % defaults to 1-degree if nonexistent file is given.

sensparam={ % sensor_name, multiplier, wgtcutoff
    'WINSAT', 1.5, 0.001,
    'AMSREA', 1.5, 0.001,
    'AMSR2R', 1.5, 0.001,
    'AMSR2J', 1.5, 0.001,
    'AATSRi',  -1, 0.001,
    'MODISA', 1.0, 0.001,
    'MODIST', 1.0, 0.001,
    'VIIRSN', 1.5, 0.001,
    'VIIRSO', 1.5, 0.001,
    'RAN17G', 1.5, 0.001,
    'AVH18G', 1.5, 0.001,
    'AVH18L', 1.5, 0.001,
    'AVH19G', 1.5, 0.001,
    'AVMTAG', 1.5, 0.001,
    'AVMTBG', 1.5, 0.001,
    'ICOADS', 1.0, 0.001,
    'IQUAM0',  -1, 0.001,
    'FNMOCs', 1.0, 0.001,
    'PATH5D', 1.5, 0.001,
    'PATH5N', 1.5, 0.001,
};  % bipfile will NOT be trimmed if "multiplier <= 0".



%% background SST field (refcspfile):

L4dir=L4_reference_root;

L4list={  % choose only one:
'RV1','GLOB/NCDC/AVHRR_OI','*fv02*.bz2','bzcat'
%'RV2','GLOB/NCDC/AVHRR_AMSR_OI','*fv02*.bz2','bzcat'
%'OSTIA','GLOB/UKMO/OSTIA','*fv02*.bz2','bzcat'
%'ODYSSEA','GLOB/EUR/ODYSSEA','*fv02*.bz2','bzcat'
%'K10','GLOB/NAVO/K10_SST','*fv02*.bz2','bzcat'
%'ABOM','GLOB/ABOM/GAMSSA_28km/','*fv02*.bz2','bzcat'
};


% mrva parameters:
Ltrim=7;
L0=Ltrim; LF=Ltrim;
decay=[48*ones(1,6),42,36,30,24,18,12];
%sstOffset=273.15;  % reduce the SST magnitude (e.g., from Kelvin to Celcius)



%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%

%% output filename:


if length(MURcsp),  %% use MUR reference:

  refcspfile='MUR.csp';
  eval(sprintf('!ln -sf %s %s',MURcsp,refcspfile));

  %%%%%%%%%%%%%%%%%%%%%%%%%%%%
else,  %% use L4 reference:

  n=1;
  refcspfile=sprintf('%s.csp',L4list{n,1});

  %% look for the L4 file:

  dirname=sprintf('%s/%s/%04d/%03d/%s',L4dir,L4list{n,2},year,day,L4list{n,3});
  d=dir(dirname);
  if length(d),
    L4file=sprintf('%s/%s/%04d/%03d/%s',L4dir,L4list{n,2},year,day,d(end).name);
  else,  % file does not exist:
    fprintf(1,'trimbip error: %s not found\n',dirname);
    fprintf(1,'aborting trimbip.m\n');
    eval(sprintf('!rm -f %s',refcspfile));  % remove it to prevent mis-use.
    refcspfile='';
    return;
  end;


  %% prepare background coefficients:

    disp(L4file);

    % make bip file:
    eval( sprintf('!%s %s > bgL4.nc',L4list{n,4},L4file) );
    bipfile=sprintf('L4g2csp_%04d_%03d.bip',year,day);
    L4ghrsst2bip('bgL4.nc',bipfile,[]);
    delete('bgL4.nc');

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
      fprintf(f,'''%d'',''%d'',''%s'',\n',L0,LF,bipfile);
      fprintf(f,' $end\n');
      fclose(f);

    % run mrva:
    system([fortran_bin, '/mrva > log.ref']);
    eval(sprintf('!mv mrva.c%02d %s',LF,refcspfile));
    eval(sprintf('!rm -f mrva_001.a%02d',LF));
    eval(sprintf('!rm -f fort.%02d',LF+80));
    delete(bipfile);

end;

%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%

  %% run trimbip:

    % make trimbip.nml file:
    nbipfile=size(sensors,1);
    f=fopen('trimbip.nml','w');
      fprintf(f,' $input\n');
      fprintf(f,'nbipfile=%d\n',nbipfile);
      fprintf(f,'bipfile=\n');
      for n=1:nbipfile,
        sensor=sensors{n,1};
        inx=find(strcmp(sensor,sensparam(:,1)));
        if length(inx)==1,
          multiplier=sensparam{inx,2}; wgtcutoff=sensparam{inx,3};
        else,
          multiplier=-1; wgtcutoff=0;
        end;
       %bipfile=sprintf('%s/%s_%s_%04d_%03d.bip',bipdir,region,sensor,year,day);
        bipfile=sprintf('%s/%s_%s_%04d_%03d.biq',bipdir,region,sensor,year,day);
        fprintf(f,'''%f'',''%f'',''%s'',\n',multiplier,wgtcutoff,bipfile);
      end;
      fprintf(f,'reffile=\n''%s''\n',refcspfile);
      fprintf(f,'stdfile=\n''%s''\n',stdcspfile);
      fprintf(f,' $end\n');
    fclose(f);

    % run trimbip:
    system([fortran_bin, '/trimbip3']);


