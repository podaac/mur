%% csp2nc.m


% need this for Global file with both uncertainty and ice fields:
netcdf.setDefaultFormat('format_64bit');
  % see:  http://www.unidata.ucar.edu/software/netcdf/faq-lfs.html



%% Source:

cspdir='/nas/ftp/mur_sst/tmchin/cyc2out';  % source directory.
L=11; region='Global'; hourAna=9;

whichdays={
%2008,92:366
%2009,1:365
%2010,1:90
%2010,3:241
%2010,100:241
2010,3:241
};

%%%%%


%% Destination:

%ncdir='/tmp';  % destination directory (must exist).
ncdir='/nas/ftp/mur_sst/tmchin/L4';  % destination directory (must exist).
ncsubdir='GLOB/JPL/MUR';  % destination directory (will be created).

    %%   GDS 1.x:
    %%     yyyymmdd-JPL-L4UHfnd-GLOB-v01-fv01-MUR.nc
    %%   GDS 2.0:
    %%     yyyymmdd-JPL-L4_GHRSST-SSTfnd-MUR-GLOB-v02.0-fv01.0.nc

version='02';  % used in both filename and metadata.

namebody=sprintf('JPL-L4UHfnd-GLOB-v01-fv%s-MUR',version);
%namebody=sprintf('JPL-L4_GHRSST-SSTfnd-MUR-GLOB-v02.0-fv%s',version);

entryID='JPL-L4UHfnd-GLOB-MUR';  % for metadata.

cdy=2011; cdm=2; cdd=8;  % "creation date" (today), for metadata only.

%%%%%


%% Grid and landmask files:

box=[-180,180,-90,90];  % only for metadata (also "resolution" below).

%gridfile='/home/tmchin/grids/maskGlob1km.gds'; resolution='0.011 degrees'; 
%gridfile='/home/tmchin/grids/maskGlob8km.gds'; resolution='0.088 degrees'; 
gridfile='/home/tmchin/nas/landice/'; resolution='0.011 degrees'; 
  % "landice" mask is date dependent and MUST HAVE "iceIncluded=1"


%%%%%


%% error info:

%Lerr=6;  uave=0.6; udev=1.1;  % uncertainty data scale, mean, and std.
%Lerr=7;  uave=1.3; udev=1.7;  % uncertainty data scale, mean, and std.
Lerr=8;  uave=1.7; udev=2.0;  % uncertainty data scale, mean, and std.
targetMean=0.5;
targetMin=0.3;


%% netCDF contents:

errIncluded=1;  % set this to include analysis_error variable.
iceIncluded=1;  % set this to include ice variable.

badpixel=int16(-32768);  % *.map file convention.
minSSTvalue= -1.8+273.15;  % [degK] minimum possible analyzed SST value.

sstoffset=25+273.15; sstscale=0.001;
erroffset=0.0;    errscale=0.01;
iceoffset=0.0;    icescale=0.01;

%%%%%


%% post-processing:

%compression='gzip';
compression='bzip2';

%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%

switch compression,
  case 'gzip', ctail='.gz';
  case 'bzip2', ctail='.bz2';
  otherwise, ctail='';
end;


% Landmask file:
if ~iceIncluded,  % stationary landmask (no ice):
  landmaskfile=gridfile;
  fprintf(1,'loading %s\n',landmaskfile);
  f=fopen(landmaskfile,'r');
  [ii,jj]=fortread(f,'int',1,'int',1);
  [mask,lon,lat]=fortread(f,'integer*1',[ii,jj],'real*4',ii,'real*4',jj);
  fclose(f);
  clear lon lat;
  mask=int8(mask);
end; 


%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%

fprintf(1,'starting main loop ... \n');

for daycounter=1:size(whichdays,1),
  year=whichdays{daycounter,1};
for day=whichdays{daycounter,2},
fprintf(1,'Year %04d, Day %03d\n',year,day);


    %% make the destination:
    fprintf(1,'searching root directory %s\n',ncdir);
    if ~exist(ncdir,'dir'),
      fprintf(1,'*** Missing destination directory %s ***\n',ncdir);
      return;
    end;
    ddir=sprintf('%s/%s',ncdir,ncsubdir);
%    fprintf(1,'searching/making main directory %s\n',ncdir);
%    if ~exist(ddir,'dir'), eval(sprintf('! mkdir -p %s',ddir)); end;
    ddir=sprintf('%s/%04d/%03d',ddir,year,day);
%    fprintf(1,'making directory %s\n',ddir);
%    eval(sprintf('! mkdir -p %s',ddir));



    %%%%%%%%%%

    %% *.nc and *.xml file names:
    [d,m,y]=julian(day,year);
    ncbasename=sprintf('%04d%02d%02d-%s.nc',y,m,d,namebody);
    ncname=sprintf('%s/%s',ddir,ncbasename);
    xmlbasename=sprintf('FR-%04d%02d%02d-%s.xml',y,m,d,namebody);
    xmlname=sprintf('%s/%s',ddir,xmlbasename);




      %%%%%%%%%%%%%%%
      % *.xml entry %
      %%%%%%%%%%%%%%%
      today=datestr(datenum(cdy,cdm,cdd),'yyyymmddTHHMMSS');
      [d,m,y]=julian(day,year); mjd=julian(d,m,y,3);
%      [d,m,y]=julian(mjd-1);
%      startdate=datestr(datenum(y,m,d,21,0,0),'yyyymmddTHHMMSS');
%      [d,m,y]=julian(mjd);
%      stopdate=datestr(datenum(y,m,d,21,0,0),'yyyymmddTHHMMSS');
      startdate=datestr(datenum(y,m,d,0,0,0),'yyyymmddTHHMMSS');
      stopdate=datestr(datenum(y,m,d,24,0,0),'yyyymmddTHHMMSS');
      creationdate=datestr(datenum(2010,12,8),'yyyymmddTHHMMSS');
      releasedate=creationdate;

      f=fopen(xmlname,'w');
      fprintf(f,'<?xml version="1.0" encoding="UTF-8"?>\n');
      fprintf(f,'<!DOCTYPE MMR_FR SYSTEM "mmr_fr.dtd">\n');
      fprintf(f,'<MMR_FR> \n');
      fprintf(f,'<Entry_ID>%s</Entry_ID>\n',entryID);
      fprintf(f,'<File_Name>%s</File_Name> \n',ncbasename);
      fprintf(f,'<File_Release_Date>%sZ</File_Release_Date>\n',releasedate);
      fprintf(f,'<File_Version>%s</File_Version>\n',version);
      fprintf(f,'<Temporal_Coverage> \n');
      fprintf(f,'<Start_Date>%sZ</Start_Date>\n',startdate);
      fprintf(f,'<Stop_Date>%sZ</Stop_Date>\n',stopdate);
      fprintf(f,'</Temporal_Coverage> \n');
      fprintf(f,'<Spatial_Coverage> \n');
      fprintf(f,'<Southernmost_Latitude>%.2f</Southernmost_Latitude>\n',box(3));
      fprintf(f,'<Northernmost_Latitude>%.2f</Northernmost_Latitude>\n',box(4));
      fprintf(f,'<Westernmost_Longitude>%.2f</Westernmost_Longitude>\n',box(1));
      fprintf(f,'<Easternmost_Longitude>%.2f</Easternmost_Longitude>\n',box(2));
      fprintf(f,'</Spatial_Coverage> \n');
      fprintf(f,'<Personnel>\n');
      fprintf(f,'  <Role>Technical Contact</Role>\n');
      fprintf(f,'  <First_Name>Edward</First_Name>\n');
      fprintf(f,'  <Last_Name>Armstrong</Last_Name>\n');
      fprintf(f,'  <Email>ghrsst@podaac.jpl.nasa.gov</Email>\n');
      fprintf(f,'  <Phone>818-393-6710</Phone>\n');
      fprintf(f,'  <Fax>818-393-2718</Fax>\n');
      fprintf(f,'  <Address>JPL, 4800 Oak Grove Dr, Pasadena, CA 91109, USA</Address>\n');
      fprintf(f,'</Personnel>\n');
      fprintf(f,'<Metadata_History> \n');
      fprintf(f,'<FR_File_Version>%s</FR_File_Version> \n',version);
      fprintf(f,'<FR_Creation_Date>%sZ</FR_Creation_Date> \n',creationdate);
      fprintf(f,'<FR_Last_Revision_Date>%sZ</FR_Last_Revision_Date> \n',today);
      fprintf(f,'<FR_Revision_History>First created, 2010-12-08.</FR_Revision_History> \n');
      fprintf(f,'</Metadata_History> \n');
      fprintf(f,'<File_Compression>%s</File_Compression>\n',compression);
      fprintf(f,'</MMR_FR>\n');
      fclose(f);


  %%%%%%%%%%%%%%%%%%%%%%%%%%%%
  % compression and checksum %
  %%%%%%%%%%%%%%%%%%%%%%%%%%%%

%  eval(sprintf('! %s -f %s',compression,ncname));
  back=pwd; cd(ddir);  % go to the data directory.
%  eval(sprintf('! md5sum %s%s > %s%s.md5',ncbasename,ctail,ncname,ctail));
  eval(sprintf('! md5sum %s > %s.md5',xmlbasename,xmlname));
  cd(back);

end;
end;
