function [day,mon,year]=julian(p1,p2,p3,p4)
%
% [day,mon,year]= julian(JD)
%   converts Julian Day Number to calendar day.
% [day,mon,year]= julian(MJD)
%   if day < 100,000
%   converts Modified Julian Day (MJD) to calendar day.
% [doy,year] = julian(day)
%   same as above, but returns doy ("day of year") instead of (day,mon).
%
% [day,mon] = julian(doy,year)
%   converts from julian to annual calendar day.
% MJD = julian(doy,year)
%   same as above, but returns MJD.
% string=julian(day), string=julian(day,year)
%   same as above but returns common calendar-day string.
%
% day = julian(day,month,year)
%   converts from calendar to julian day.
% day = julian(day,month,year,choice)
%   "choice" controls the output:
%   choice=1, the calendar day
%   choice=2, Julian Day Number
%             Julian dates (abbreviated JD) are a continuous count of days
%             and fractions since *NOON* Univeral Time on January 1, 4713 BC.
%             http://aa.usno.navy.mil/data/docs/JulianDate.html
%   choice=3, Modified Julian Day Number (MJD)
%             MJD = JD - 2400000.5.

% mike chin, 99.6.16
%            00.9.7 (Julian Day Number added)
%            02.2.26 (corrected for noon reference of JD)
%            15.3.5 (added the [doy,year]=julian(MJD/JD) option)
%            15.4.6 (added the MJD=julian(doy,year) option)

MJD2JD=2400000.5;
% Julian dates (abbreviated JD) are a continuous count of days
% and fractions since *NOON* Univeral Time on January 1, 4713 BC.
% http://aa.usno.navy.mil/data/docs/JulianDate.html


switch nargin,
  case 1, % Julian Day Number to calendar.
    clear year mon;
    if p1<1000000,  % MJD:
      day=floor(p1); 
    else,  % JD (referenced at noon!):
      day=floor(p1-MJD2JD);
    end;
    [day,year]=MJD2year(day);
  case 2, % julian to calendar, year specified.
    day=p1; year=p2; clear mon;
    if nargout==1, day=day+year2MJD(year); return; end;
  case 3, % calendar to julian.
    day=p1; mon=p2; year=p3;
    choice=0;  % default choice.
  case 4, % calendar to julian.
    day=p1; mon=p2; year=p3;
    choice=p4;
  otherwise,
    disp('too little or too many inputs.'); return;
end;

months=[
31,28,31,30,31,30,31,31,30,31,30,31
];

if exist('year')==1,  % check for leap year:
  if isLeap(year), months(2)=29; end;
end;

if exist('mon')==1,  % calendar to julian:
  if year<0,
    disp('No negative years, please.');
    day=0; mon=0; return;
  end;
  if ~any(mon==(1:12)),
    disp('Date must be specified as (day,month,year).');
    day=0; mon=0; return;
  end;
  if mon>1, day=day+sum(months(1:(mon-1))); end;

  switch choice,
%    case 2, day=day+year2JD(year);
%    case 3, day=day+year2JD(year)-MJD2JD;
    case 2, day=day+year2MJD(year)+MJD2JD;
    case 3, day=day+year2MJD(year);
  end;
else,                % julian to calendar:
  if nargout==2&nargin==1, mon=year; return; end;  % returns [doy,year].
  if sum(months)<day,
    disp('That is not a Julian day!');
    day=0; mon=0; return;
  end;
  mon=min(find(cumsum(months)>=day));
  if mon>1, day=day-sum(months(1:(mon-1))); end;
  %
  if nargout==0, 
    monthname='JanFebMarAprMayJunJulAugSepOctNovDec';
    monthname=reshape(monthname,3,12)';
    disp(sprintf('      %s %d, %d',monthname(mon,:),day,year));
  end;
  if nargout==0|(nargout==1&nargin<3),
    monthname='JanFebMarAprMayJunJulAugSepOctNovDec';
    monthname=reshape(monthname,3,12)';
    day=sprintf('%d.%s.%d',day,monthname(mon,:),year);
  end;
end;

%%%%%%%%%%
function [day,year]=JD2year(jd)
% converts Julian Day Number to 
% the caldendar year and the annual Julian day.
%year0=1950;  jd0=2433282;  % A reference data.
year0=1800;  jd0=2378495.5;  % The reference data.
years=floor(year0+(jd-jd0)/366) : ceil(year0+(jd-jd0)/365);
jds=year2JD(years);
inx=find(jds<jd);
year=max(years(inx));
day=jd-max(jds(inx));

%%%%%%%%%%
function jd=year2JD(year)
% converts the sets of the "year" to Julian Day numbers
% at the beginning (Jan.0, 00:00hr) of each year.
%
%year0=1950;  jd0=2433282;  % The reference data.
%year0=1960;  jd0=2436934;  % The reference data.
%year0=1960;  jd0=2436933.5;  % The reference data.
year0=1800;  jd0=2378495.5;  % The reference data.
%
y=min([year(:);year0]):max([year(:);year0]); y=y(:);
days=ones(size(y))*365+isLeap(y);  % "isLeap" returns 1 if true.
days=cumsum([0;days]);
inx=find(y==year0);
jd = days - days( find(y==year0) ) + jd0;
jd=jd(find(y==min(year)):find(y==max(year)));

%%%%%%%%%%
function flag=isLeap(year)
flag = (rem(year,4)==0) & (~( rem(year,100)==0&rem(year,400)~=0 ));

%%%%%%%%%%
function [day,year]=MJD2year(jd)
% converts Modified Julian Date to 
% the caldendar year and the annual Julian day.
year0=1860;  jd0=409;  % The reference data.
years=floor(year0+(jd-jd0)/366) : ceil(year0+(jd-jd0)/365);
jds=year2MJD(years);
inx=find(jds<jd);
year=max(years(inx));
day=jd-max(jds(inx));

%%%%%%%%%%
function jd=year2MJD(year)
% converts the sets of the "year" to Modified Julian Date
% at the beginning (Jan.0, 00:00hr) of each year.
%
year0=1860;  jd0=409;  % The reference data.
%
y=min([year(:);year0]):max([year(:);year0]); y=y(:);
days=ones(size(y))*365+isLeap(y);  % "isLeap" returns 1 if true.
days=cumsum([0;days]);
inx=find(y==year0);
jd = days - days( find(y==year0) ) + jd0;
jd=jd(find(y==min(year)):find(y==max(year)));
