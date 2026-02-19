function cmpcsp( L, year, p3, p4 )
% cmpcsp( L, year, month, day )
% cmpcsp( L, year, doy )

cdir0 = '/tmp/seamap';
cdir1 = '/nas4/cyc4out';

switch nargin,
  case 3, doy = p3;
      [year, month, day] = jude( year, doy );
  case 4, month = p3; day = p4;
      [year, doy] = jude( year, month, day );
  otherwise,
      error('cmpcsp needs three or four input arguments');
end;

filename = sprintf('%04d%02d%02d09_MRVA4_Global.c%02d',year,month,day,L);
cspfile0 = sprintf('%s/%s',cdir0,filename);
cspfile1 = sprintf('%s/%04d/%s',cdir1,year,filename);

if ~exist( cspfile0, 'file' ), error(['absent file: ',cspfile0]); end;
if ~exist( cspfile1, 'file' ), error(['absent file: ',cspfile1]); end;

disp( cspfile0 ); c0 = readcsp( cspfile0 );
disp( cspfile1 ); c1 = readcsp( cspfile1 );
disp(sprintf( 'mean: %.2e', mean(c1(:)-c0(:)) ));
disp(sprintf( 'std: %.2e', std(c1(:)-c0(:)) ));
disp(sprintf( 'max: %.2f', max(c1(:)-c0(:)) ));
disp(sprintf( 'min: %.2f', min(c1(:)-c0(:)) ));

