function iceconvert(bipfile)
% modifies the ice bipfile created by /home/tmchin/ice/p01/saf2bip.m
% by conversion of the ice concentration (SIC) value to SST value
% using cubic relation similar to one used by Hurrell et al 2008 (J.Climate;
% also note that a quadratic relation was used by Rayner et al 2003 (JGR 108).
%
% The cubic relation is completely ad hoc, not even empirical.
%
% The SIC value is recovered from the weight ("w") value in bipfile.

%% parameters:
wgtmax=5.0;  % must match the value used in saf2bip.m.
minSIC=0.1;  % below this value would be considered "ice free".
minSIC=0.3;  % below this value would be considered "ice free". (2016.04.22)


%% read ice file:
f=fopen(bipfile,'r');
% Read first Fortran record: n (integer*4)
fread(f, 1, 'uint32');  % Record size marker (start)
n = fread(f, 1, 'int32');
fread(f, 1, 'uint32');  % Record size marker (end)

% Read second Fortran record: x,y,t,T,w arrays (5 * n real*4 values)
fread(f, 1, 'uint32');  % Record size marker (start)
x = fread(f, n, 'real*4=>single');
y = fread(f, n, 'real*4=>single');
t = fread(f, n, 'real*4=>single');
T = fread(f, n, 'real*4=>single');
w = fread(f, n, 'real*4=>single');
fread(f, 1, 'uint32');  % Record size marker (end)
fclose(f);


%% conversion:
sic=w/wgtmax;  % must reverse the procedure used by saf2bip.m.

  %% remove "free ice" samples:
  inx=find(sic>minSIC);
  x=x(inx); y=y(inx); t=t(inx); T=T(inx); w=w(inx); sic=sic(inx);
  n=length(T);

  %% convert SIC to SST and SST-weight:
  inx=find(sic<0.9);

  T= -1.8*ones(size(T));
  %T(inx)=2.5*(0.9-sic(inx)).^3-1.8;
%  T(inx)=3.5*(0.9-sic(inx)).^3-1.8; (2016.04.22)

  w=  4.0*ones(size(w));  % Note: 4.0 = 1/(0.5^2);
  %sigma=2.5*(0.9-sic(inx)).^3+0.5;
%  sigma=3.5*(0.9-sic(inx)).^3+0.5;
%  sigma=2.000*(0.729-(sic(inx).^3))+0.5;  % new formula; maybe better.
  sigma=2.057*(0.729-(sic(inx).^3))+0.5;  % from Tmax in Hurrell (2016.04.22)
  w(inx)=1./(sigma.^2);



%% re-write new file:
f=fopen(bipfile,'w');
fortwrite(f,'integer*4',n);
fortwrite(f,x,y,t,T,w);
fclose(f);
