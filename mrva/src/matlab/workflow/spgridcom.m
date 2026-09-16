% spgridcom.m

%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%

%% run control:

region='NCAMERICA';  % analysis region (see bin2bip.m for list).
outgridfile='/home/tmchin/pathfinder/ryan/ryanNCAMERICA.out';  % output grid.

% Below is from bin2bip.m, which should be moved to mrva0com.m:
  hourAna=9;  % UTC. Analysis Time.


sstOffset=273.15;  % reduce the SST magnitude (e.g., from Kelvin to Celcius)


%years=2009;
%yeardays=30;

whichdays={
%2008,92,366
%2009,1,88
2008,365,366
2009,1,2
};


outdir='/nas2/mrva0out';  % where the coefficients are.
%mapdir='/nas/ftp/mur_sst/tmchin/ncamerica0';  % where the results would go.
mapdir='./test';  % where the results would go.
mapL0=10; mapLF=10;  % resolution range of the map(s) to be created.
mapbody='MUR_NCAMERICA_1km';  % main name for *.map file.
maptime0='000000Z'; maptime1='180000Z'; % [hhmmss] time range for buoy matchup.



%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%

for daycounter=1:size(whichdays,1),
  year=whichdays{daycounter,1};
for day=whichdays{daycounter,2},


    %% run spgrid:

    f=fopen('spgrid.nml','w');
    fprintf(f,' $input\n');
    fprintf(f,'sstoffset=%f\n',sstOffset);
    fprintf(f,'nlist=%d\n',mapLF-mapL0+1);
    fprintf(f,'coeffilelist=\n');
    for L=mapL0:mapLF
      fprintf(f,'''%d'',''./mrva.c%02d'',\n',L,L);
    end;
    fprintf(f,'outgridfile=\n''%s''\n',outgridfile);
    fprintf(f,' $end\n');

    ! spgrid;


    %% link to the coefficients:
    if ~exist(outdir,'dir'), 
          fprintf(1,'*** ERROR *** missing directory: %s\n',outdir);
          fprintf(1,'*** ABORTING ***\n');
          return;
    end;
      

    for L=mapL0:mapLF
        [d,m,y]=julian(day,year);

        name=sprintf('%s/%04d%02d%02d%02d-JPL-L4',outdir,y,m,d,hourAna);
        name=sprintf('%s-SSTfnd-MUR_%s-fv00.c%02d',name,region,L);

        if ~exist(name,'file'),
          fprintf(1,'*** ERROR *** missing file: %s\n',name);
          fprintf(1,'*** ABORTING ***\n');
          return;
        end;

        eval(sprintf('!ln -f %s ./mrva.c%02d',name,L));
    end;


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

end;
end;
