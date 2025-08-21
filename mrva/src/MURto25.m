function out = MURto25( in )
% out = MURto25( in )
%
% converts an MUR matrix/vector to an MUR25 matrix/vector
% by local averaging.
%
% The returned values will be "double".


%% dimensions:
  iMUR = 36000; jMUR = 17999;  
  i25  = 1440;  j25  = 720;

%% transform operators:
  Tlon = sparse( i25, iMUR );
    for i=1:i25, Tlon( i , i*25+(-13:-12) ) = 1/2; end;
  Tlat = sparse( j25, jMUR );
    for j=1:j25, Tlat( j , j*25+(-13:-12) ) = 1/2; end;

%% transform:
  if isvector( in ),

      switch length(in),
        case iMUR,  out = Tlon *double( in(:) );
        case jMUR,  out = Tlat *double( in(:) );
        otherwise,  error('### input not in MUR dimension ###');
      end;

  else,

      if (size(in,1)-iMUR) || (size(in,2)-jMUR),
        error('### input not in MUR dimension ###');
      end;

      out = Tlon *double( in )* Tlat';

  end;
