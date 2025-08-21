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
n=fortread(f,'integer*4',1);
[x,y,t,T,w]=fortread(f,n,n,n,n,n);
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
