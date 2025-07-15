function flag=fortwrite(file,varargin)
% flag = fortwrite(file,variabletype1,variable1,variabletype2,variable2, ...)
% writes a Fortran (f77) readable binary data file,
% where "file" is the file indentifier returned by the matlab built-in
% command "fopen" (see "help fopen"),
% "variable1", "variable2", "variable3", ... etc. are matlab variable names,
% "variabletype1", "variabletype2", ... etc. are the Fortran formats that
% you wish to represent the corresponding variables (see "help fread").
% (You can optionally skip the variabletype, in which case a default
%  variable type, usually "real*4", is assigned.)
% The function returns the total number of bytes written in "flag".
%
% Example:
%   ff=fopen('my.data','w');
%   fortwrite(ff,'real',x,'integer',y);
%   fclose(ff);

% mike chin, 03.7.20

defaulttype='real*4';

otype={};  % list of variable types.
osize=[];  % list of variable sizes (in bytes).
inxvar=[];  % variable index.

vartype='';
for k=1:length(varargin),
  if ischar(varargin{k}),  % specified variable type:
    if length(vartype),
      flag=0;
      error('input syntax error: variable name is missing.');
    else,
      vartype=varargin{k};
      % default sizes for the integer and floating-point variables:
      switch vartype,
        case 'int', vartype='integer*4';
        case 'integer', vartype='integer*4';
        case 'real', vartype=defaulttype;
        case 'float', vartype=defaulttype;
      end;
    end;
  else,
    if length(vartype)==0, vartype=defaulttype; end;
    inxvar=[inxvar,k];
    otype={otype{:},vartype};
    vartype='';
  end;
end;

if length(inxvar)~=length(otype), error('Bad error; contact author.'); end;
if 0,  % debug:
  varargin{inxvar},
  otype,
end;

for k=1:length(otype),
  switch otype{k},
      case 'integer*1', osize=[osize,1];
      case 'integer*2', osize=[osize,2];
      case 'integer*4', osize=[osize,4];
      case 'integer*8', osize=[osize,8];
      case 'int8', osize=[osize,1];
      case 'int16', osize=[osize,2];
      case 'int32', osize=[osize,4];
      case 'int64', osize=[osize,8];
      case 'uint8', osize=[osize,1];
      case 'uint16', osize=[osize,2];
      case 'uint32', osize=[osize,4];
      case 'uint64', osize=[osize,8];
      case 'real*4', osize=[osize,4];
      case 'real*8', osize=[osize,8];
      case 'single', osize=[osize,4];
      case 'double', osize=[osize,8];
      case 'float32', osize=[osize,4];
      case 'float64', osize=[osize,8];
      default, error(sprintf('Sorry, type %s not recognized.',otype{k}));
  end;
end;

n=0;  % total # of bytes to be written (initialized).
for k=1:length(inxvar),
  n=n+prod(size(varargin{inxvar(k)}))*osize(k);
end;

fwrite(file,n,'int32');
for k=1:length(inxvar),
  fwrite(file,varargin{inxvar(k)},otype{k});
end;
fwrite(file,n,'int32');

flag=n;


