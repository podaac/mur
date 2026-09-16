function cmpCMC( L, year, p3, p4 )
% cmpCMC( L, year, month, day )
% cmpCMC( L, year, doy )

dirL4='/store/ghrsst/open/data/GDS2/L4/GLOB/CMC/CMC0.1deg/v3';
%L4body='120000-CMC-L4_GHRSST-SSTfnd-CMC0.2deg-GLOB-v02.0-fv02.0.nc';
L4body='120000-CMC-L4_GHRSST-SSTfnd-CMC0.1deg-GLOB-v02.0-fv03.0.nc';

cspdir = '/nas4/cyc4out';

switch nargin,
  case 3, doy = p3;
      [year, month, day] = jude( year, doy );
  case 4, month = p3; day = p4;
      [year, doy] = jude( year, month, day );
  otherwise,
      error('cmpcsp needs three or four input arguments');
end;

%% file names:
  date = sprintf('%04d%02d%02d',year,month,day);
  cspfile = sprintf('%s/%04d/%s09_MRVA4_Global.c%02d',cspdir,year,date,L);
  L4file = sprintf('%s/%04d/%03d/%s%s',dirL4,year,doy,date,L4body);

  if ~exist(cspfile,'file'), error(['absent file: ',cspfile]); end;
  if ~exist(L4file,'file'), error(['absent file: ',L4file]); end;

%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%

    [ ref, x, y, t, mask ] = readL4core( L4file );
    ref( find( mask==2 | mask==4 ) ) = NaN;

    if 0,  % cutout Arctic Sea:
      jnx=find(y<65);
      ref=ref(:,jnx); y=y(jnx);
    end;

    mur = samplecsp( cspfile, x, y );

    dd = mur - ref;
    dd = dd( ~isnan(dd) );

disp(sprintf( 'mean: %.2e', mean(dd(:)) ));
disp(sprintf( 'std:  %.2e', std(dd(:))  ));
disp(sprintf( 'max:  %.2f', max(dd(:))  ));
disp(sprintf( 'min:  %.2f', min(dd(:))  ));

