function [out, SCALE, OFFSET] = samplegdscsp( cspfile, gdsfile, scale, offset )
% [out, SCALE, OFFSET] = samplegdscsp( cspfile, gdsfile, scale, offset )
%
% samples the 'cspfile' over the given grid in 'gdsfile'.
% The badpixel (-32768) value is used where the grid==2 (land).
% The output is returned as an "integer*2" array,
% *unless* only 'out' is the sole output in which case the badpixel is
% converted into NaN and scale and offset are applied to the other values.


%% executable:
  hostname = textscan( lower(getenv('HOST')), '%s', 'delimiter', '.' );
  switch hostname{1}{1},
    case 'seaeddy', cmd = '/home/tmchin/util/seaeddy/samplegdscsp';
    case 'seaward', cmd = '/home/tmchin/util/seaward/samplegdscsp';
    case 'seamap', cmd = '/home/tmchin/util/seamap/samplegdscsp';
    otherwise, cmd = '/home/tmchin/util/seaeddy/samplegdscsp';
  end;

%% parameters (defaults):
  if ~exist('offset','var'), offset = 0; end;
  if ~exist('scale','var'), scale = 0.01; end;

%% write samplecspgds.nml:
  f = fopen( 'samplegdscsp.nml', 'w' );
  fprintf(f,' $input\noffset=%f\nsscale=%f\n',offset,scale);
  fprintf(f,'nlist=1\ncoeffilelist=\n');
  fprintf(f,'''%s'',\n',cspfile);
  fprintf(f,'gridfile=\n''%s''\n $end\n',gdsfile);
  fclose( f );

%% execute fortran code:
  system( cmd );

%% read the output:
  f=fopen('fort.181','r');
    [ii,jj]=fortread(f,'int',1,'int',1);
    [OFFSET,SCALE]=fortread(f,'real*4',1,'real*4',1);
    [out,x,y]=fortread(f,'integer*2',[ii,jj],'real*4',ii,'real*4',jj);
  fclose(f);

  if abs(scale-SCALE) > 1e-8, disp([SCALE,scale]); end;
  if abs(offset-OFFSET) > 1e-8, disp([OFFSET,offset]); end;

  if nargout==1,
    out( find( out == -32768 ) ) = NaN;
    out = double(out)*SCALE + OFFSET;
  end;

  !rm -f fort.181;
