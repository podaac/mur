function [solfac,zenith,azimuth,sunset,sunrise]=zensun4(day,time,lon,lat)
% [zenith,azimuth,solfac,sunset,sunrise]=zensun(day,time,lon,lat)
% finds solar position information given univeral time (day and time) and
% geographic coordinates.
%
% INPUT:
%   day         Julian day (positive scalar or vector)
%               (spring equinox =  80)
%               (summer solstice= 171)
%               (fall equinox   = 266)
%               (winter solstice= 356)
%
%   time        Universal Time in hours (scalar or vector) 
%
%   lat         geographic latitude of point on earth's surface (degrees)
%
%   lon         geographic longitude of point on earth's surface (degrees)
%
% OUTPUT:
%
%   zenith      solar zenith angle (degrees)
%
%   azimuth     solar azimuth  (degrees) 
%               Azimuth is measured clockwise from due north 
%
%   solfac      Solar flux multiplier.  SOLFAC=cosine(ZENITH)/RSUN^2
%               where rsun is the current earth-sun distance in
%               astronomical units.
%
%               NOTE: SOLFAC is negative when the sun is below the horizon 
%
%   sunrise     Time of sunrise (hours)
%
%   sunset      Time of sunset  (hours)

% based on IDL code by Paul Ricchiazzi 23oct92.
%
%; PROCEDURE: 
%;
%; 1.  Calculate the subsolar point latitude and longitude, based on
%;     DAY and TIME. Since each year is 365.25 days long the exact
%;     value of the declination angle changes from year to year.  For
%;     precise values consult THE AMERICAN EPHEMERIS AND NAUTICAL
%;     ALMANAC published yearly by the U.S. govt. printing office.  The
%;     subsolar coordinates used in this code were provided by a
%;     program written by Jeff Dozier.
%;
%;  2. Given the subsolar latitude and longitude, spherical geometry is
%;     used to find the solar zenith, azimuth and flux multiplier.
%;
%;  eqt = equation of time (minutes)  ; solar longitude correction = -15*eqt
%;  dec = declination angle (degrees) = solar latitude 


if length(time)*length(lon)*length(lat)==0,
  solfac=[]; zenith=[]; azimuth=[]; sunset=[]; sunrise=[];
  return;
end;


ndayo=[-4.0,...
        1.0,   6.0,  11.0,  16.0,  21.0,  26.0,  31.0,  36.0,  41.0,  46.0,...
       51.0,  56.0,  61.0,  66.0,  71.0,  76.0,  81.0,  86.0,  91.0,  96.0,...
      101.0, 106.0, 111.0, 116.0, 121.0, 126.0, 131.0, 136.0, 141.0, 146.0,...
      151.0, 156.0, 161.0, 166.0, 171.0, 176.0, 181.0, 186.0, 191.0, 196.0,...
      201.0, 206.0, 211.0, 216.0, 221.0, 226.0, 231.0, 236.0, 241.0, 246.0,...
      251.0, 256.0, 261.0, 266.0, 271.0, 276.0, 281.0, 286.0, 291.0, 296.0,...
      301.0, 306.0, 311.0, 316.0, 321.0, 326.0, 331.0, 336.0, 341.0, 346.0,...
      351.0, 356.0, 361.0, 366.0, 371.0];

eqto=[-0.62,...
      -3.23, -5.49, -7.60, -9.48,-11.09,-12.39,-13.34,-13.95,-14.23,-14.19,...
     -13.85,-13.22,-12.35,-11.26,-10.01, -8.64, -7.18, -5.67, -4.16, -2.69,...
      -1.29, -0.02,  1.10,  2.05,  2.80,  3.33,  3.63,  3.68,  3.49,  3.09,...
       2.48,  1.71,  0.79, -0.24, -1.33, -2.41, -3.45, -4.39, -5.20, -5.84,...
      -6.28, -6.49, -6.44, -6.15, -5.60, -4.82, -3.81, -2.60, -1.19,  0.36,...
       2.03,  3.76,  5.54,  7.31,  9.04, 10.69, 12.20, 13.53, 14.65, 15.52,...
      16.12, 16.41, 16.36, 15.95, 15.19, 14.09, 12.67, 10.93,  8.93,  6.70,...
       4.32,  1.86, -0.62, -3.23, -5.49];

deco=[-23.35,...
     -23.06,-22.57,-21.91,-21.06,-20.05,-18.88,-17.57,-16.13,-14.57,-12.91,...
     -11.16, -9.34, -7.46, -5.54, -3.59, -1.62,  0.36,  2.33,  4.28,  6.19,...
       8.06,  9.88, 11.62, 13.29, 14.87, 16.34, 17.70, 18.94, 20.04, 21.00,...
      21.81, 22.47, 22.95, 23.28, 23.43, 23.40, 23.21, 22.85, 22.32, 21.63,...
      20.79, 19.80, 18.67, 17.42, 16.05, 14.57, 13.00, 11.33,  9.60,  7.80,...
       5.95,  4.06,  2.13,  0.19, -1.75, -3.69, -5.62, -7.51, -9.36,-11.16,...
     -12.88,-14.53,-16.07,-17.50,-18.81,-19.98,-20.99,-21.85,-22.52,-23.02,...
     -23.33,-23.44,-23.35,-23.06,-22.57];



nday=(-1:368)'; % need to be daily; see "inx" below.
  out=interp1(ndayo,[eqto(:),deco(:)],nday,'linear');
eqt=out(:,1)/60;
dec=out(:,2);


deg2rad=pi/180;

%
% compute the subsolar coordinates
%

% fractional day number with 12am 1jan = 1:
%tt=mod( (floor(day)+time/24)-1, 365.25 )+1;
tt=double(day)+time/24; tt=tt(:);

%  eqtime=interp1(nday,eqt,tt,'spline')/60;
%  decang=interp1(nday,dec,tt,'spline');
%  eqtime=interp1(nday,eqt,tt,'linear')/60;
%  decang=interp1(nday,dec,tt,'linear');

inx=floor(tt); r=tt-inx;
inx=inx+1-min(nday);
eqtime=eqt(inx+1,:).*r+eqt(inx,:).*(1-r);
decang=dec(inx+1,:).*r+dec(inx,:).*(1-r);
clear inx r;

latsun=decang;
lonsun=-15*(time-12+eqtime);



%toc;

%; compute the solar zenith, azimuth and flux multiplier

t0=(90-lat)*deg2rad;     % colatitude of point
t1=(90-latsun)*deg2rad;  % colatitude of sun

p0=lon*deg2rad;     % longitude of point
p1=lonsun*deg2rad;  % longitude of sun

% rotated coordinates:
  zz=cos(t0).*cos(t1)+sin(t0).*sin(t1).*cos(p1-p0); % up         

  rsun=1-0.01673*cos(0.9856*(tt-2).*deg2rad); % earth-sun distance in AU
  solfac=zz./(rsun.^2);
  if nargout==1, return; end;

  zenith=acos(zz)/deg2rad;      % solar zenith
  inx=find((p1-p0)<0); if length(inx), zenith(inx)=-zenith(inx); end;
  if nargout==2, return; end;

  xx=sin(t1).*sin(p1-p0);                           % east-west 
  yy=sin(t0).*cos(t1)-cos(t0).*sin(t1).*cos(p1-p0); % north-south

% output angles:
  azimuth=atan2(xx,yy)./deg2rad; % solar azimuth 
  if nargout==3, return; end;

% output sunrise/sunset time:
if 0,
  noon=12-lon/15; % universal time of noon
  angsun=6.96e10./(1.5e13*rsun); % solar disk half-angle
  arg=-(sin(angsun)+cos(t0)*cos(t1))./(sin(t0)*sin(t1));
  sunrise = zeros(size(tt));
  sunset  = ones(size(tt))*24;
  index = find(abs(arg) <= 1);
  if length(index),
    dtime=acos(arg(index))/(15*deg2rad);
    sunrise(index)=noon-eqtime(index)-dtime;
    sunset(index) =noon-eqtime(index)+dtime;
  end;
end;


