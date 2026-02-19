function icemap = makeMUR25ice( year, doy )

  icedir = '/nas/ftp/mur_sst/tmchin/MUR25/ice';
  icefile = sprintf('%s/%04d/icemap%04d_%03d.ice',icedir,year,year,doy);

  if exist( icefile, 'file' ),

      f = fopen( icefile, 'r' );
      [ii,jj] = fortread(f,'int',1,'int',1);
      icemap = fortread(f,'integer*1',[ii,jj]);  % 'icemap' will be "double".
      fclose(f);

  else,  % make from 'landice' data using MURto25.m:

      gridfile='/nas2/landice/%04d/landiceP01_%04d_%03d.gds.gz';
      tmpgridfile='/tmp/landice_%04d_%03d.gds';

      day = doy;
      gridfilegz=sprintf(gridfile,year,year,day);
      tmpmaskfile=sprintf(tmpgridfile,year,day);
      eval(sprintf('!zcat -f %s > %s',gridfilegz,tmpmaskfile));
      fprintf(1,'loading %s\n',tmpmaskfile);
      f=fopen(tmpmaskfile,'r');
      [ii,jj]=fortread(f,'int',1,'int',1);
      [mask,lon,lat]=fortread(f,'integer*1',[ii,jj],'real*4',ii,'real*4',jj);
      icemap=fortread(f,'integer*1',[ii,jj]);  % 'icemap' is "double".
      fclose(f);
      icemap = MURto25( icemap );

      system( sprintf('rm -f %s &',tmpmaskfile) );  % save /tmp space.

      if 1,  % save the content:
        if ~exist( sprintf('%s/%04d',icedir,year), 'dir' ),
          mkdir( sprintf('%s/%04d',icedir,year) );
        end;

        disp(['writing ',icefile]);
        f = fopen( icefile, 'w' );
        [ii,jj] = size( icemap );
        fortwrite(f,'int',ii,'int',jj);
        fortwrite(f,'integer*1', icemap);
        fclose(f);
      end;

  end;
        

