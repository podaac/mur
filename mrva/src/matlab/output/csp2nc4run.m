%% csp2nc4run.m

%nc4d=7;  % netcdf4 "deflation level".

% need this for Global file with both uncertainty and ice fields:
%netcdf.setDefaultFormat('format_64bit');
  % see:  http://www.unidata.ucar.edu/software/netcdf/faq-lfs.html



%% Source:  (COMMENTED OUT FOR USE BY mrva4com.m)

%ncdir='/tmp';  % destination directory (must exist).
%ncdir='/data/nc4/ghrsst/open/data/L4';  % destination directory (must exist).
%ncdir='/data/dev/scratch/tmchin/nc4mine'; % destination directory (must exist).
ncdir='/nas/ftp/mur_sst/tmchin/GDS2/L4';  % destination directory (must exist).

cspbasedir='/nas4/cyc4out';  % base directory of csp source.

%cspfmt='%04d%02d%02d%02d_MRVA3_%s';  % output file body name format.
cspfmt='%04d%02d%02d%02d_MRVA4_%s';  % output file body name format.



%L=10; region='Global'; hourAna=9;
L=11; region='Global'; hourAna=9;

%whichdays={
%2012,1:2
%};
%realtime=0;
whichdays={
%2013,200
%2013,[100,200,300]
%2004,220
%2015,1:3
%2014,359:365
%2009,365:-1:1
%2008,366:-1:1
%2007,365:-1:1
%2006,365:-1:1
%2005,365:-1:1
%2004,366:-1:1
%2003,365:-1:1
%2002,365:-1:152
2018,5:5
};
realtime=0;
hiresgridFlag=1;


%%%%%

fprintf(1,'starting main loop ... \n');

for daycounter=1:size(whichdays,1),
  year=whichdays{daycounter,1};
for day=whichdays{daycounter,2},
fprintf(1,'Year %04d, Day %03d\n',year,day);

  if hiresgridFlag,
   hiresgridfile=sprintf('/home/tmchin/nas/grd/hiresdt_%04d_%03d.grd',year,day);
  end;

  cspdir=sprintf('%s/%04d',cspbasedir,year);

  csp2nc4;


end;
end;

