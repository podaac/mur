%% pushL4.m from csp2nc.m

%% SEE ALSO:  makeGDScom.m


% need this for Global file with both uncertainty and ice fields:
netcdf.setDefaultFormat('format_64bit');
  % see:  http://www.unidata.ucar.edu/software/netcdf/faq-lfs.html



%% Source:  (COMMENTED OUT FOR USE BY mrva2com.m)

ncdir='/nas3/L4';  % destination directory (must exist).

cspdir='/nas4/cyc4out';  % source directory.
cspbasedir=cspdir;  % cspdir is remade each year.
L=10; region='Global'; hourAna=9;
%
whichdays={
%2013,365:-1:1
%2012,366:-1:1
%2012,208:-1:1
%2011,365:-1:1
%2010,365:-1:1
%2009,365:-1:1
%2008,366:-1:1
%2007,365:-1:1
%2006,365:-1:1
2015,[122]
};
realtime=0;

%%%%%


%% Destination:

podaacpush=1;  % set this flag to push into PODAAC JPL-MUR-RTO depository.
if realtime, podaacpush=0; end;

ncsubdir='GLOB/JPL/MUR';  % destination directory (will be created).

    %%   GDS 1.x:
    %%     yyyymmdd-JPL-L4UHfnd-GLOB-v01-fv01-MUR.nc
    %%   GDS 2.0:
    %%     yyyymmdd-JPL-L4_GHRSST-SSTfnd-MUR-GLOB-v02.0-fv01.0.nc

%version='03';  % used in both filename and metadata.
version='04';  % used in both filename and metadata.

namebody=sprintf('JPL-L4UHfnd-GLOB-v01-fv%s-MUR',version);
%namebody=sprintf('JPL-L4_GHRSST-SSTfnd-MUR-GLOB-v02.0-fv%s',version);

entryID='JPL-L4UHfnd-GLOB-MUR';  % for metadata.

%% creation date (today):
%cdy=2011; cdm=2; cdd=8;  % "creation date" (today), for metadata only.
cdy=str2num(datestr(datenum(date),'yyyy'));
cdm=str2num(datestr(datenum(date),'mm'));
cdd=str2num(datestr(datenum(date),'dd'));

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
  % Read Fortran record header
  rec_len1 = fread(f, 1, 'int32');
  ii = fread(f, 1, 'int32');
  jj = fread(f, 1, 'int32');
  rec_len2 = fread(f, 1, 'int32');
  assert(rec_len1 == rec_len2, 'Fortran record corruption detected in dimension read');

  % Read landmask data with direct type mapping (saves ~4.3 GB: int8→double→int8)
  rec_len1 = fread(f, 1, 'int32');
  mask = fread(f, [ii,jj], 'int8=>int8');
  lon = fread(f, ii, 'single=>single');
  lat = fread(f, jj, 'single=>single');
  rec_len2 = fread(f, 1, 'int32');
  assert(rec_len1 == rec_len2, 'Fortran record corruption detected in landmask read');
  fclose(f);
  clear lon lat;
end; 


%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%

fprintf(1,'starting main loop ... \n');

for daycounter=1:size(whichdays,1),
  year=whichdays{daycounter,1};
  cspdir=sprintf('%s/%04d',cspbasedir,year);
for day=whichdays{daycounter,2},
fprintf(1,'Year %04d, Day %03d\n',year,day);




    %% make the destination:
    fprintf(1,'searching root directory %s\n',ncdir);
    if ~exist(ncdir,'dir'),
      fprintf(1,'*** Missing destination directory %s ***\n',ncdir);
      return;
    end;
    ddir=sprintf('%s/%s',ncdir,ncsubdir);
    fprintf(1,'searching/making main directory %s\n',ncdir);
    if ~exist(ddir,'dir'), eval(sprintf('! mkdir -p %s',ddir)); end;
    ddir=sprintf('%s/%04d/%03d',ddir,year,day);
    if realtime, ddir=[ddir,'nrt']; end;  % marker for rewriting.
    fprintf(1,'making directory %s\n',ddir);
    eval(sprintf('! mkdir -p %s',ddir));


    %% landmask and ice data if needed:
    if iceIncluded,
      eval(sprintf('!zcat -f %s/%04d/landice_%04d_%03d.gds.gz > tmp.gds',...
                            gridfile,year,year,day));
      landmaskfile='tmp.gds';
      fprintf(1,'loading %s\n',landmaskfile);
      f=fopen(landmaskfile,'r');
      % Read Fortran record header
      rec_len1 = fread(f, 1, 'int32');
      ii = fread(f, 1, 'int32');
      jj = fread(f, 1, 'int32');
      rec_len2 = fread(f, 1, 'int32');
      assert(rec_len1 == rec_len2, 'Fortran record corruption detected in dimension read');

      % Read landmask data with direct type mapping (saves ~4.3 GB: int8→double→int8)
      rec_len1 = fread(f, 1, 'int32');
      mask = fread(f, [ii,jj], 'int8=>int8');
      lon = fread(f, ii, 'single=>single');
      lat = fread(f, jj, 'single=>single');
      rec_len2 = fread(f, 1, 'int32');
      assert(rec_len1 == rec_len2, 'Fortran record corruption detected in landmask read');

      % Read ice map data with direct type mapping (saves ~4.3 GB: int8→double→int8)
      rec_len1 = fread(f, 1, 'int32');
      icemap = fread(f, [ii,jj], 'int8=>int8');
      rec_len2 = fread(f, 1, 'int32');
      assert(rec_len1 == rec_len2, 'Fortran record corruption detected in icemap read');
      fclose(f);
      clear lon lat;
    else,
      landmaskfile=gridfile;
    end;


    %% interpolate sst from csp file:
    f=fopen('spgrid.nml','w');
    fprintf(f,' $input\n');
    fprintf(f,'offset=%f\n',sstoffset);
    fprintf(f,'sscale=%f\n',sstscale);
    fprintf(f,'minsst=%f\n',minSSTvalue);
    fprintf(f,'nlist=%d\n',1);
    fprintf(f,'coeffilelist=\n');
      %% csp file name:
      [d,m,y]=julian(day,year);
      %name=sprintf('%s/%04d%02d%02d%02d_MRVA3_%s.c%02d',...
      name=sprintf('%s/%04d%02d%02d%02d_MRVA4_%s.c%02d',...
                    cspdir,y,m,d,hourAna,region,L);
      fprintf(f,'''%d'',''%s'',\n',L,name);
    fprintf(f,'gridfile=\n''%s''\n',landmaskfile);
    fprintf(f,' $end\n');
    fclose(f);

    ! spgrid;

    f=fopen(sprintf('./fort.%d',L+180),'r');
    % Read Fortran record header
    rec_len1 = fread(f, 1, 'int32');
    ii = fread(f, 1, 'int32');
    jj = fread(f, 1, 'int32');
    rec_len2 = fread(f, 1, 'int32');
    assert(rec_len1 == rec_len2, 'Fortran record corruption detected in dimension read');

    % Read offset and scale
    rec_len1 = fread(f, 1, 'int32');
    offset = fread(f, 1, 'single');
    sscale = fread(f, 1, 'single');
    rec_len2 = fread(f, 1, 'int32');
    assert(rec_len1 == rec_len2, 'Fortran record corruption detected in offset/scale read');

    % Read SST grid with direct type mapping (saves ~3.7 GB: int16→double→int16)
    rec_len1 = fread(f, 1, 'int32');
    msst = fread(f, [ii,jj], 'int16=>int16');
    mlon = fread(f, ii, 'single=>single');
    mlat = fread(f, jj, 'single=>single');
    rec_len2 = fread(f, 1, 'int32');
    assert(rec_len1 == rec_len2, 'Fortran record corruption detected in SST grid read');
    fclose(f);


    %% data source:
    [d,m,y]=julian(day,year);
    name=sprintf('%s/%04d%02d%02d%02d_MRVA4_%s_inputs.txt',...
                    cspdir,y,m,d,hourAna,region);
    sourcedata=txt2sourcedata(name,iceIncluded);


    %% interpolate error field from csp file:
    if errIncluded,
      f=fopen('spgrid.nml','w');
      fprintf(f,' $input\n');
      fprintf(f,'offset=%f\n',uave*uave+273.15);
      fprintf(f,'sscale=%f\n',sstscale);
      fprintf(f,'minsst=%f\n',0.0+273.15);
      fprintf(f,'nlist=%d\n',1);
      fprintf(f,'coeffilelist=\n');
      [d,m,y]=julian(day,year);
      %name=sprintf('%s/%04d%02d%02d%02d_MRVA3_%s.u%02d',...
      name=sprintf('%s/%04d%02d%02d%02d_MRVA4_%s.u%02d',...
                    cspdir,y,m,d,hourAna,region,Lerr);
      fprintf(f,'''%d'',''%s'',\n',Lerr,name);
      fprintf(f,'gridfile=\n''%s''\n',landmaskfile);
      fprintf(f,' $end\n');
      fclose(f);

      ! spgrid;

      f=fopen(sprintf('./fort.%d',Lerr+180),'r');
      % Read Fortran record header
      rec_len1 = fread(f, 1, 'int32');
      ii = fread(f, 1, 'int32');
      jj = fread(f, 1, 'int32');
      rec_len2 = fread(f, 1, 'int32');
      assert(rec_len1 == rec_len2, 'Fortran record corruption detected in dimension read');

      % Read offset and scale
      rec_len1 = fread(f, 1, 'int32');
      offset = fread(f, 1, 'single');
      sscale = fread(f, 1, 'single');
      rec_len2 = fread(f, 1, 'int32');
      assert(rec_len1 == rec_len2, 'Fortran record corruption detected in offset/scale read');

      % Read error grid with direct type mapping
      rec_len1 = fread(f, 1, 'int32');
      err = fread(f, [ii,jj], 'int16=>int16');
      elon = fread(f, ii, 'single=>single');
      elat = fread(f, jj, 'single=>single');
      rec_len2 = fread(f, 1, 'int32');
      assert(rec_len1 == rec_len2, 'Fortran record corruption detected in error grid read');
      fclose(f);
      enx=find(err(:)==-32768);if length(enx),err(enx)=NaN*ones(size(enx));end;
      clear elon elat enx;
      err=sqrt(err*sscale+offset-273.15);  % spgrid adds 273.15.
      err = (err-uave)/udev*(targetMean-targetMin) + targetMean;
      err=single(err);
    end;

    ! rm -f tmp.gds;


    %%%%%%%%%%

    %% *.nc and *.xml file names:
    [d,m,y]=julian(day,year);
    ncbasename=sprintf('%04d%02d%02d-%s.nc',y,m,d,namebody);
    ncname=sprintf('%s/%s',ddir,ncbasename);
    xmlbasename=sprintf('FR-%04d%02d%02d-%s.xml',y,m,d,namebody);
    xmlname=sprintf('%s/%s',ddir,xmlbasename);

    %% File open:
    %% mode='64bit_offset'; % for files larger than 2Gb.
    %% mode='noclobber'; % do not overwrite existing file.
      mode=0;  % overwrites existing file.
      ncid = netcdf.create(ncname, mode);

    %% Define dimensions:  dimid = netcdf.defDim(ncid,dimname,dimlen)
        d0 = netcdf.defDim(ncid,'time',1);
        d1 = netcdf.defDim(ncid,'lat',length(mlat));
        d2 = netcdf.defDim(ncid,'lon',length(mlon));


    %% Define each variable and its attributes:
    %%        varid = netcdf.defVar(ncid,varname,xtype,dimids);
    %%        netcdf.putAtt(ncid,varid,attrname,attrvalue);
    %% "xtype": 1='byte', 2='char', 3='short', 4='int', 5='float', 6='double'.

        v0 = netcdf.defVar(ncid,'time',4,[d0]);
        netcdf.putAtt(ncid,v0,'long_name','reference time of sst field');
        netcdf.putAtt(ncid,v0,'standard_name','time');
        netcdf.putAtt(ncid,v0,'axis','T');
        netcdf.putAtt(ncid,v0,'units','seconds since 1981-01-01 00:00:00 UTC');

        v1 = netcdf.defVar(ncid,'lat',5,[d1]);
        netcdf.putAtt(ncid,v1,'long_name','latitude');
        netcdf.putAtt(ncid,v1,'standard_name','latitude');
        netcdf.putAtt(ncid,v1,'axis','Y');
        netcdf.putAtt(ncid,v1,'units','degrees_north');
        netcdf.putAtt(ncid,v1,'valid_min',single(box(3)));
        netcdf.putAtt(ncid,v1,'valid_max',single(box(4)));

        v2 = netcdf.defVar(ncid,'lon',5,[d2]);
        netcdf.putAtt(ncid,v2,'long_name','longitude');
        netcdf.putAtt(ncid,v2,'standard_name','longitude');
        netcdf.putAtt(ncid,v2,'axis','X');
        netcdf.putAtt(ncid,v2,'units','degrees_east');
        netcdf.putAtt(ncid,v2,'valid_min',single(box(1)));
        netcdf.putAtt(ncid,v2,'valid_max',single(box(2)));

        v3 = netcdf.defVar(ncid,'analysed_sst',3,[d2,d1,d0]);
        netcdf.putAtt(ncid,v3,'long_name','analysed sea surface temperature');
        netcdf.putAtt(ncid,v3,'standard_name','sea_surface_foundation_temperature');
%        netcdf.putAtt(ncid,v3,'type','foundation');
        netcdf.putAtt(ncid,v3,'units','kelvin');
        netcdf.putAtt(ncid,v3,'_FillValue',int16(-32768));
        netcdf.putAtt(ncid,v3,'add_offset',sstoffset);
        netcdf.putAtt(ncid,v3,'scale_factor',sstscale);
        netcdf.putAtt(ncid,v3,'valid_min',int16(-32767));
        netcdf.putAtt(ncid,v3,'valid_max',int16(32767));
        if realtime,
          netcdf.putAtt(ncid,v3,'comment','Interim near-real-time (nrt) version; to be replaced by Final version');
        end;

      if errIncluded, 
        v4 = netcdf.defVar(ncid,'analysis_error',3,[d2,d1,d0]);
        netcdf.putAtt(ncid,v4,'long_name','estimated error standard deviation of analysed_sst');
        netcdf.putAtt(ncid,v4,'units','kelvin');
        netcdf.putAtt(ncid,v4,'_FillValue',int16(-32768));
        netcdf.putAtt(ncid,v4,'add_offset',erroffset);
        netcdf.putAtt(ncid,v4,'scale_factor',errscale);
        netcdf.putAtt(ncid,v4,'valid_min',int16(0));
        netcdf.putAtt(ncid,v4,'valid_max',int16(32767));
      end;

        v5 = netcdf.defVar(ncid,'mask',1,[d2,d1,d0]);
        netcdf.putAtt(ncid,v5,'long_name','sea/land field composite mask');
        netcdf.putAtt(ncid,v5,'_FillValue',int8(-128));
        netcdf.putAtt(ncid,v5,'flag_values',int8([1,2,3,5,9,11,13]));
        netcdf.putAtt(ncid,v5,'flag_meanings','1=open-sea; 2=land; 3=coast/shore; 5=open-lake; 9=open-sea with ice in the grid; 11=coast/shore with ice in the grid; 13=open-lake with ice in the grid');

      if iceIncluded,
        v6 = netcdf.defVar(ncid,'sea_ice_fraction',1,[d2,d1,d0]);
        netcdf.putAtt(ncid,v6,'long_name','sea ice area fraction');
        netcdf.putAtt(ncid,v6,'standard_name','sea ice area fraction');
        netcdf.putAtt(ncid,v6,'units','fraction (between 0 and 1)');
        netcdf.putAtt(ncid,v6,'_FillValue',int8(-128));
        netcdf.putAtt(ncid,v6,'add_offset',iceoffset);
        netcdf.putAtt(ncid,v6,'scale_factor',icescale);
        netcdf.putAtt(ncid,v6,'valid_min',int8(0));
        netcdf.putAtt(ncid,v6,'valid_max',int8(100));
        netcdf.putAtt(ncid,v6,'source','EUMETSAT OSI-SAF, copyright EUMETSAT');
      end;

    %% global attributes:
        varid=netcdf.getConstant('GLOBAL');
        if realtime, version=[version,'nrt']; end;
        if realtime,
          str='Daily MUR SST, Interim near-real-time (nrt) product';
        else,
          str='Daily MUR SST, Final product';
        end;
        netcdf.putAtt(ncid,varid,'title',str);
        if realtime,
          str='Interim-MUR(nrt) will be replaced by MUR-Final in about 3 days; MUR = "Multi-scale Ultra-high Reolution"; produced under NASA MEaSUREs program.';
        else,
          str='MUR = "Multi-scale Ultra-high Reolution"; produced under NASA MEaSUREs program';
        end;
        netcdf.putAtt(ncid,varid,'comment',str);
        netcdf.putAtt(ncid,varid,'Conventions','CF-1.5');
        netcdf.putAtt(ncid,varid,'DSD_entry_id',entryID);
        netcdf.putAtt(ncid,varid,'references','ftp://mariana.jpl.nasa.gov/mur_sst/tmchin/docs/ATBD/');
%        netcdf.putAtt(ncid,varid,'source_data','MODIS_A-JPL-L2P, MODIS_T-JPL-L2P, AMSRE-REMSS-L2P, AVHRR18_G-NAVO-L2P');
        netcdf.putAtt(ncid,varid,'source_data',sourcedata);
        netcdf.putAtt(ncid,varid,'institution','Jet Propulsion Laboratory');
        netcdf.putAtt(ncid,varid,'contact','ghrsst@podaac.jpl.nasa.gov');
        netcdf.putAtt(ncid,varid,'GDS_version_id','GDS-v1.0-rev1.6');
        netcdf.putAtt(ncid,varid,'netcdf_version_id','3.5');
        netcdf.putAtt(ncid,varid,'creation_date',sprintf('%04d-%02d-%02d',cdy,cdm,cdd));
        netcdf.putAtt(ncid,varid,'product_version',version);
        if realtime,
          str='Interim near-real-time (nrt) version created at nominal 1-day latency.';
        else,
          str='Final version created at nominal 4-day latency; replaced Interim nrt (1-day latency) version.';
        end;
        netcdf.putAtt(ncid,varid,'history',str);
        netcdf.putAtt(ncid,varid,'spatial_resolution',resolution);
      [d,m,y]=julian(day,year); mjd=julian(d,m,y,3); hA=hourAna;
        netcdf.putAtt(ncid,varid,'start_date',sprintf('%04d-%02d-%02d',y,m,d));
        netcdf.putAtt(ncid,varid,'start_time',sprintf('%02d:00:00 UTC',hA));
        netcdf.putAtt(ncid,varid,'stop_date',sprintf('%04d-%02d-%02d',y,m,d));
        netcdf.putAtt(ncid,varid,'stop_time',sprintf('%02d:00:00 UTC',hA));
        netcdf.putAtt(ncid,varid,'southernmost_latitude',single(box(3)));
        netcdf.putAtt(ncid,varid,'northernmost_latitude',single(box(4)));
        netcdf.putAtt(ncid,varid,'westernmost_longitude',single(box(1)));
        netcdf.putAtt(ncid,varid,'easternmost_longitude',single(box(2)));
        netcdf.putAtt(ncid,varid,'file_quality_index','0'); % 0=unknown; 1=best


      netcdf.endDef(ncid);


      %%        netcdf.putVar(ncid,varid,data)

        % time:
        [d,m,y]=julian(day,year);
        %sec=(julian(d,m,y,3)-julian(1,1,1981,3))*86400;
        sec=(julian(d,m,y,3)-julian(1,1,1981,3)+hourAna/24)*86400;
        netcdf.putVar(ncid,v0,int32(sec))

        % lat-lon:
        netcdf.putVar(ncid,v1,single(mlat))
        netcdf.putVar(ncid,v2,single(mlon))
        clear mlon mlat;

        % sst:
        netcdf.putVar(ncid,v3,msst)

        inx=find(msst~=badpixel);

      if errIncluded,
        % error:
        data=ones(size(msst),'int16')*int16(-32768);
        data(inx)=int16( (err(inx)-erroffset)/errscale );
        netcdf.putVar(ncid,v4,data)
      end;
        clear err;

        % land mask:
        netcdf.putVar(ncid,v5,mask)
        clear mask;

      if iceIncluded,
        % ice fraction:
        data=ones(size(icemap),'int8')*int8(-128);
        %jnx=intersect(inx,find(icemap>=0&icemap<=100));
        jnx=find(icemap>=0&icemap<=100);
        data(jnx)=int8( icemap(jnx) );
        netcdf.putVar(ncid,v6,data)
      end;
        clear icemap;

        clear inx jnx data;
        clear msst;

      netcdf.close(ncid);



      %%%%%%%%%%%%%%%
      % *.xml entry %
      %%%%%%%%%%%%%%%
      today=datestr(datenum(cdy,cdm,cdd),'yyyymmddTHHMMSS');
      [d,m,y]=julian(day,year); mjd=julian(d,m,y,3); hA=hourAna;
      startdate=datestr(datenum(y,m,d,hA,0,0),'yyyymmddTHHMMSS');
      stopdate=datestr(datenum(y,m,d,hA,0,0),'yyyymmddTHHMMSS');
      creationdate=datestr(datenum(cdy,cdm,cdd),'yyyymmddTHHMMSS');
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
      fprintf(f,'<FR_Revision_History>First created, %04d-%02d-%02d.</FR_Revision_History> \n',cdy,cdm,cdd);
      fprintf(f,'</Metadata_History> \n');
      fprintf(f,'<File_Compression>%s</File_Compression>\n',compression);
      fprintf(f,'</MMR_FR>\n');
      fclose(f);



  %%%%%%%%%%%%%%%%%%%%%%%%%%%%
  % compression and checksum %
  %%%%%%%%%%%%%%%%%%%%%%%%%%%%

  eval(sprintf('! %s -f %s',compression,ncname));
  back=pwd; cd(ddir);  % go to the data directory.
  eval(sprintf('! md5sum %s%s > %s%s.md5',ncbasename,ctail,ncname,ctail));
  eval(sprintf('! md5sum %s > %s.md5',xmlbasename,xmlname));
  cd(back);



  %%%%%%%%%%%%%%%%%%%%%%%
  % "push" into PO.DAAC %
  %%%%%%%%%%%%%%%%%%%%%%%

  if podaacpush,
    back=pwd; cd(ddir);  % go to the data directory.
    cmd=sprintf('!%s/putsftpfile.sh sftp-ghrsst@seafire JPL-MUR-RTO/tmp',back);
      pushname=sprintf('%s%s',ncbasename,ctail);
        disp(sprintf('%s %s %s',cmd,pushname,pushname));
        eval(sprintf('%s %s %s',cmd,pushname,pushname));
      pushname=[pushname,'.md5'];
        disp(sprintf('%s %s %s',cmd,pushname,pushname));
        eval(sprintf('%s %s %s',cmd,pushname,pushname));
      pushname=xmlbasename;
        disp(sprintf('%s %s %s',cmd,pushname,pushname));
        eval(sprintf('%s %s %s',cmd,pushname,pushname));
      pushname=[pushname,'.md5'];
        disp(sprintf('%s %s %s',cmd,pushname,pushname));
        eval(sprintf('%s %s %s',cmd,pushname,pushname));
    cd(back);
  end;


end;
end;
