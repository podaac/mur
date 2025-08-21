function varargout=fortread(file,varargin)
% [variable1,variable2,...] = fortread( file, variabletype1, variablesize1,
%                                        varialbetype2, variablesize2, ...)
% reads arrays from a Fortran (f77) binary data file into matlab, where
% "file" is the file identifier for the Fortran data file which has already
% been open by the matlab command "fopen",
% "variabletype" is the format of each array ("integer", "real", etc.) as
% specified for the matlab command "fread" (Please read "help fread"),
% "variablesize" is a scalar/vector specifying the dimension of the
% variable to be read (multi-dimensional arrays are allowed).
%
% Example:
%   ff=fopen('my.data','r');
%   [x,y]=fortread(ff,'real*4',[7,3],'integer*4',8);
%   fclose(ff);

% mike chin, 03.7.20
%            15.1.30 (uint32 is used instead of int32)


defaulttype='real*4';

m=fread(file,1,'uint32');

out={};
vartype='';
for k=1:length(varargin),
  if ischar(varargin{k}),  % specified variable type:
    if length(vartype),
      errtxt='File rewound; re-read from beginning.';
      errtxt=['Variable size must be specified.  ',errtxt];
      frewind(file);
      error(errtxt);
    else,
      vartype=varargin{k};
    end;
  else,
    if length(vartype),
      switch vartype,
        case 'integer', vartype='integer*4';
        case 'real', vartype=defaulttype;
      end;
      x=fread(file,prod(varargin{k}),vartype);
      if prod(size(x))==prod(varargin{k}),
        if length(varargin{k})>1, x=reshape(x,varargin{k}); end;
      else,
        x=[];
      end;
      vartype='';
      out={out{:},x};
    else, % default variable type:
      x=fread(file,prod(varargin{k}),defaulttype);
      if prod(size(x))==prod(varargin{k}),
        if length(varargin{k})>1, x=reshape(x,varargin{k}); end;
      else,
        x=[];
      end;
      out={out{:},x};
    end;
  end; 
end;

n=fread(file,1,'uint32');
if m~=n, error('ERROR in "fortread": mismatch in total byte size'); end;

%if nargout~=length(out),
%  error('ERROR in "fortread":  incorrect number of output variable(s)');
%end;
varargout=out;

