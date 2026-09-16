function makeMUR25( year, day, realtime, podaacpush );

%% defaults:

if ~exist('realtime','var'), realtime=0; end;
if ~exist('podaacpush','var'), podaacpush=1; end;

podaacpush=1;  %@@@


%% Inputs:

ncdir='/nas/ftp/mur_sst/tmchin/MUR25';  % destination directory (must exist).

cspdirfmt='/nas4/cyc4out/%04d';  % source directory.
cspfmt='%04d%02d%02d%02d_MRVA4_%s';  % source file body name format.


L=08; region='Global'; hourAna=9;


whichdays = { year, day:day };


%%%%%


%% Destination:


ncsubdir='GLOB/JPL/MUR';  % destination directory (will be created).

    %%   GDS 1.x:
    %%     yyyymmdd-JPL-L4UHfnd-GLOB-v01-fv01-MUR.nc
    %%   GDS 2.0:
    %%     yyyymmddhhmmss-JPL-L4_GHRSST-SSTfnd-MUR-GLOB-v02.0-fv01.0.nc

%version='04.1'; % is used to chose landmask & in both filename and metadata.
version='04.2'; % is used to chose landmask & in both filename and metadata.

%namebody=sprintf('%02d0000-JPL-MUR25-fv%s',hourAna,version);  % GDS-2.0.
namebody=sprintf('%02d0000-JPL-L4_GHRSST-SSTfnd-MUR25-GLOB-v02.0-fv%s',hourAna,version);  % GDS-2.0.

%entryID='JPL-L4UHfnd-GLOB-MUR';  % for metadata.
entryID=['MUR25-JPL-L4-GLOB-v',version]; % for metadata.

%% creation date (today):
cdy=str2num(datestr(datenum(date),'yyyy'));
cdm=str2num(datestr(datenum(date),'mm'));
cdd=str2num(datestr(datenum(date),'dd'));
cnH=str2num(datestr(datenum(now),'HH'));
cnM=str2num(datestr(datenum(now),'MM'));
cnS=str2num(datestr(datenum(now),'SS'));

%%%%%


%% Grid boundary and trimming:

box=[-180,180,-90,90];  trimGrid=0;  % for metadata and trimming.
%box=[-180,180,-79,89];  trimGrid = 1;  % for metadata and trimming.

  % If trimGrid is set, use "box" to trim each variable array.
  % However, netCDF4 compresses monotony well; so no trimming is fine.


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
hiresgridIncluded=0;  % set this to include dt_1km_data variable.
anomalyIncluded=1;

badpixel=int16(-32768);  % *.map file convention.
minSSTvalue= -1.8+273.15;  % [degK] minimum possible analyzed SST value.

sstoffset=25+273.15; sstscale=0.001;
erroffset=0.0;    errscale=0.01;
iceoffset=0.0;    icescale=0.01;


%% land mask (if ice is included, date dependent):

switch version,
  case {'04.1','04.2'},
    ncsubdir=[ncsubdir,'/v4'];  % destination directory (will be created).
    %resolution='0.01 degrees';  % for metadata.
    resolution='0.25 degrees';  % for metadata.
    resfloat=single(0.25);
    if iceIncluded,
      gridfile='/nas2/landice/%04d/landiceP01_%04d_%03d.gds.gz';
      tmpgridfile='/tmp/landice_%04d_%03d.gds';
      icefiles=sprintf('/nas/ftp/mur_sst/tmchin/landice/%04d/icefiles_%04d_%03d.txt',year,year,day);  % OSISAF ice file data
    end;
    landmaskfile='/home/tmchin/grids/MUR25grid.gds';
  otherwise,
    ncsubdir=[ncsubdir,'/v0'];  % destination directory (will be created).
    resolution='0.088 degrees'; % for metadata.
    resfloat=single(0.088);
    landmaskfile='/home/tmchin/grids/maskGlob8km.gds';
    icefiles=sprintf('/nas/ftp/mur_sst/tmchin/landice/%04d/icefiles_%04d_%03d.txt',year,year,day);  % OSISAF ice file data
    iceIncluded=0;  % force no ice.
end;

%%%%%

%% file/data compression:

nc4d=7;  % netcdf4 "deflation level".
compression='';  

switch compression,
  case '', ctail='';
  case 'gzip', ctail='.gz';
  case 'bzip2', ctail='.bz2';
  otherwise, ctail='';
end;

%%%%%%%%%%%%%%%%%%%%%%%%%%%%%% End Parameters %%%%%%%%%%%%%%%%%%%%%%%%%%%%%%


fprintf(1,'starting csp2nc4 ... \n');


% need this for Global file with both uncertainty and ice fields:
netcdf.setDefaultFormat('format_64bit');
  % see:  http://www.unidata.ucar.edu/software/netcdf/faq-lfs.html


fprintf(1,'checking for disk space ... \n');
  checkfreedisk(ncdir,98,1.5);


for daycounter=1:size(whichdays,1),
  year=whichdays{daycounter,1};
for day=whichdays{daycounter,2},
fprintf(1,'***csp2nc4*** : Year %04d, Day %03d\n',year,day);

    cspdir = sprintf(cspdirfmt,year);

    if ismember( version, {'04.2'} ),
      mjd = julian( day, year );
      %if mjd<=julian(2,4,2006,3) && mjd>=julian(1,9,2002,3),
      if mjd<=53827 && mjd>=52518,
        cspdir = sprintf('/nas5/cyc5out/%04d',year);
      end;
    end;

    %% source file base path:
    [d,m,y]=julian(day,year);
    cspbody=sprintf(['%s/',cspfmt],cspdir,y,m,d,hourAna,region);


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


    %% ice data if needed:
    if iceIncluded,
%      gridfilegz=sprintf(gridfile,year,year,day);
%      tmpmaskfile=sprintf(tmpgridfile,year,day);
%      eval(sprintf('!zcat -f %s > %s',gridfilegz,tmpmaskfile));
%      fprintf(1,'loading %s\n',tmpmaskfile);
%      f=fopen(tmpmaskfile,'r');
%      [ii,jj]=fortread(f,'int',1,'int',1);
%      [mask,lon,lat]=fortread(f,'integer*1',[ii,jj],'real*4',ii,'real*4',jj);
%      icemap=fortread(f,'integer*1',[ii,jj]);  % 'icemap' is "double".
%      fclose(f);
%      icemap = MURto25( icemap );
      icemap = makeMUR25ice( year, day );
    end;

    %% landmask data:
    fprintf(1,'loading %s\n',landmaskfile);
    f=fopen(landmaskfile,'r');
    % Record 1: dimensions
    fread(f, 1, 'uint32');  % skip Fortran record marker
    ii = fread(f, 1, 'int32=>int32');
    jj = fread(f, 1, 'int32=>int32');
    fread(f, 1, 'uint32');  % skip Fortran record marker
    % Record 2: mask and coordinates
    fread(f, 1, 'uint32');  % skip Fortran record marker
    mask = fread(f, [ii, jj], 'int8=>int8');
    lon = fread(f, ii, 'float32=>single');
    lat = fread(f, jj, 'float32=>single');
    fread(f, 1, 'uint32');  % skip Fortran record marker
    fclose(f);
    clear lon lat;
    mask=int8(mask);

if iceIncluded,  % update landmask using ice data:
  knx=find(icemap>0 & mask==1);
    if length(knx), mask(knx)=9*ones(size(knx),'int8'); end;
  %knx=find(icemap>0 & mask==3);
  %  if length(knx), mask(knx)=11*ones(size(knx),'int8'); end;
  knx=find(icemap>0 & mask==5);
    if length(knx), mask(knx)=13*ones(size(knx),'int8'); end;
end;

%    %% hires grid data for dt_1km_data variable:
%    if hiresgridIncluded,
%      if exist('hiresgridfile','var'),  % should have been made by mrva4com.m.
%          if exist(hiresgridfile,'file'),
%            f=fopen(hiresgridfile,'r');
%            [nhireslon,nhireslat]=fortread(f,'integer*4',1,'integer*4',1);
%            dt_1km_data=fortread(f,'integer*1',[nhireslon,nhireslat]);
%            clear nhireslon nhireslat;
%            disp(['HiResGrid to be included: ',hiresgridfile]);
%            fclose(f);
%          else,
%            hiresgridIncluded=0;
%          end;
%      else,
%        hiresgridIncluded=0;
%      end;
%    end;


    %% interpolate sst from csp file:
    f=fopen('spgrid.nml','w');
    fprintf(f,' $input\n');
    fprintf(f,'offset=%f\n',sstoffset);
    fprintf(f,'sscale=%f\n',sstscale);
    fprintf(f,'minsst=%f\n',minSSTvalue);
    fprintf(f,'nlist=%d\n',1);
    fprintf(f,'coeffilelist=\n');
      %% csp file name:
      name=sprintf('%s.c%02d',cspbody,L);
      fprintf(f,'''%d'',''%s'',\n',L,name);
    fprintf(f,'gridfile=\n''%s''\n',landmaskfile);
    fprintf(f,' $end\n');
    fclose(f);

    ! spgrid;

    f=fopen(sprintf('./fort.%d',L+180),'r');
    % Record 1: dimensions
    fread(f, 1, 'uint32');  % skip Fortran record marker
    ii = fread(f, 1, 'int32=>int32');
    jj = fread(f, 1, 'int32=>int32');
    fread(f, 1, 'uint32');  % skip Fortran record marker
    % Record 2: scaling parameters
    fread(f, 1, 'uint32');  % skip Fortran record marker
    offset = fread(f, 1, 'float32=>single');
    sscale = fread(f, 1, 'float32=>single');
    fread(f, 1, 'uint32');  % skip Fortran record marker
    % Record 3: SST data and coordinates
    fread(f, 1, 'uint32');  % skip Fortran record marker
    msst = fread(f, [ii, jj], 'int16=>int16');
    mlon = fread(f, ii, 'float32=>single');
    mlat = fread(f, jj, 'float32=>single');
    fread(f, 1, 'uint32');  % skip Fortran record marker
    fclose(f);


    %% sst anomaly:
    if anomalyIncluded,
      ssta = double(msst)*sscale+offset;
      %ssta = ssta - MURto25( readSeasonal( day ) );
      ssta = ssta - makeSeasonal( day );
    end;


    %% data source:
    [d,m,y]=julian(day,year);
    name=sprintf('%s_inputs.txt',cspbody);
    [sourcedata,sensordata,platformdata]=txt2sourcedata(name,iceIncluded);


    %% interpolate error field from csp file:
    if errIncluded,
      f=fopen('spgrid.nml','w');
      fprintf(f,' $input\n');
      fprintf(f,'offset=%f\n',uave*uave+273.15);
      fprintf(f,'sscale=%f\n',sstscale);
      fprintf(f,'minsst=%f\n',0.0+273.15);
      fprintf(f,'nlist=%d\n',1);
      fprintf(f,'coeffilelist=\n');
      name=sprintf('%s.u%02d',cspbody,Lerr);
      fprintf(f,'''%d'',''%s'',\n',Lerr,name);
      fprintf(f,'gridfile=\n''%s''\n',landmaskfile);
      fprintf(f,' $end\n');
      fclose(f);

      ! spgrid;

      f=fopen(sprintf('./fort.%d',Lerr+180),'r');
      % Record 1: dimensions
      fread(f, 1, 'uint32');  % skip Fortran record marker
      ii = fread(f, 1, 'int32=>int32');
      jj = fread(f, 1, 'int32=>int32');
      fread(f, 1, 'uint32');  % skip Fortran record marker
      % Record 2: scaling parameters
      fread(f, 1, 'uint32');  % skip Fortran record marker
      offset = fread(f, 1, 'float32=>single');
      sscale = fread(f, 1, 'float32=>single');
      fread(f, 1, 'uint32');  % skip Fortran record marker
      % Record 3: error field and coordinates
      fread(f, 1, 'uint32');  % skip Fortran record marker
      err = fread(f, [ii, jj], 'int16=>int16');
      elon = fread(f, ii, 'float32=>single');
      elat = fread(f, jj, 'float32=>single');
      fread(f, 1, 'uint32');  % skip Fortran record marker
      fclose(f);
      % Vectorized NaN assignment
      err(err == -32768) = NaN;
      clear elon elat;
      err=sqrt(err*sscale+offset-273.15);  % spgrid adds 273.15.
      err = (err-uave)/udev*(targetMean-targetMin) + targetMean;
      err=single(err);
    end;

%    ! rm -f tmp.gds;
%    system( sprintf('rm -f %s',tmpmaskfile) );

    %% revert "shore-line" flag values to "land"
    %% (previously done by: grids/gmt/maskbin2gds.m, ice/p01/saf2bip.m)
    if 1,  % turn them to simple "land" flag:
      % Vectorized mask value remapping
      mask(mask==3 | mask==7 | mask==11 | mask==15) = int8(2);
    end;

    %%%%%%%%%%

    %% trim the variable fields according to "box":
    if trimGrid,
      fprintf(1,'### TRIMMING to [%.2f, %.2f, %.2f, %.2f] ###\n',...
                 box(1),box(2),box(3),box(4));
      jnx=find( mlat>=box(3) & mlat<=box(4) );
      mlat=mlat(jnx);
      msst=msst(:,jnx);
      mask=mask(:,jnx);
      err=err(:,jnx);
      icemap=icemap(:,jnx);
    end;

    %%%%%%%%%%

    %% *.nc and *.xml file names:
    [d,m,y]=julian(day,year);
    ncbasename=sprintf('%04d%02d%02d%s.nc',y,m,d,namebody);
    ncname=sprintf('%s/%s',ddir,ncbasename);

    %% File open:
    %% mode='64bit_offset'; % for files larger than 2Gb.
    %% mode='noclobber'; % do not overwrite existing file.
      %mode=0;  % overwrites existing file.
      mode = netcdf.getConstant('NETCDF4');
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
        netcdf.putAtt(ncid,v0,'coverage_content_type','coordinate');
        netcdf.putAtt(ncid,v0,'axis','T');
        netcdf.putAtt(ncid,v0,'units','seconds since 1981-01-01 00:00:00 UTC');
        netcdf.putAtt(ncid,v0,'comment','Nominal time of analyzed fields');

        v1 = netcdf.defVar(ncid,'lat',5,[d1]);
        netcdf.defVarDeflate(ncid,v1,true,true,nc4d);
        netcdf.putAtt(ncid,v1,'long_name','latitude');
        netcdf.putAtt(ncid,v1,'standard_name','latitude');
        netcdf.putAtt(ncid,v1,'coverage_content_type','coordinate');
        netcdf.putAtt(ncid,v1,'axis','Y');
        netcdf.putAtt(ncid,v1,'units','degrees_north');
        netcdf.putAtt(ncid,v1,'valid_min',single(box(3)));
        netcdf.putAtt(ncid,v1,'valid_max',single(box(4)));
        netcdf.putAtt(ncid,v1,'comment','geolocations inherited from the input data without correction');

        v2 = netcdf.defVar(ncid,'lon',5,[d2]);
        netcdf.defVarDeflate(ncid,v2,true,true,nc4d);
        netcdf.putAtt(ncid,v2,'long_name','longitude');
        netcdf.putAtt(ncid,v2,'standard_name','longitude');
        netcdf.putAtt(ncid,v2,'coverage_content_type','coordinate');
        netcdf.putAtt(ncid,v2,'axis','X');
        netcdf.putAtt(ncid,v2,'units','degrees_east');
        netcdf.putAtt(ncid,v2,'valid_min',single(box(1)));
        netcdf.putAtt(ncid,v2,'valid_max',single(box(2)));
        netcdf.putAtt(ncid,v2,'comment','geolocations inherited from the input data without correction');

        v3 = netcdf.defVar(ncid,'analysed_sst',3,[d2,d1,d0]);
        netcdf.defVarChunking(ncid,v3,"CHUNKED",[1440 720 1]);
        netcdf.defVarDeflate(ncid,v3,true,true,nc4d);
        netcdf.putAtt(ncid,v3,'long_name','analysed sea surface temperature');
        netcdf.putAtt(ncid,v3,'standard_name','sea_surface_foundation_temperature');
        netcdf.putAtt(ncid,v3,'coverage_content_type','physicalMeasurement');
        netcdf.putAtt(ncid,v3,'units','kelvin');
%        netcdf.putAtt(ncid,v3,'_FillValue',int16(-32768));
        netcdf.defVarFill(ncid,v3,false,int16(-32768));
        netcdf.putAtt(ncid,v3,'add_offset',sstoffset);
        netcdf.putAtt(ncid,v3,'scale_factor',sstscale);
        netcdf.putAtt(ncid,v3,'valid_min',int16(-32767));
        netcdf.putAtt(ncid,v3,'valid_max',int16(32767));
        if realtime,
          str='Interim near-real-time (nrt) version using Multi-Resolution Variational Analysis (MRVA) method for interpolation; to be replaced by Final version';
        else,
          str='"Final" version using Multi-Resolution Variational Analysis (MRVA) method for interpolation';
        end;
        netcdf.putAtt(ncid,v3,'comment',str);
        netcdf.putAtt(ncid,v3,'coordinates','lon lat');
        netcdf.putAtt(ncid,v3,'source',sourcedata);

      if errIncluded, 
        v4 = netcdf.defVar(ncid,'analysis_error',3,[d2,d1,d0]);
        netcdf.defVarChunking(ncid,v4,"CHUNKED",[1440 720 1]);
        netcdf.defVarDeflate(ncid,v4,true,true,nc4d);
        netcdf.putAtt(ncid,v4,'long_name','estimated error standard deviation of analysed_sst');
        netcdf.putAtt(ncid,v4,'coverage_content_type','qualityInformation');
        netcdf.putAtt(ncid,v4,'units','kelvin');
%        netcdf.putAtt(ncid,v4,'_FillValue',int16(-32768));
        netcdf.defVarFill(ncid,v4,false,int16(-32768));
        netcdf.putAtt(ncid,v4,'add_offset',erroffset);
        netcdf.putAtt(ncid,v4,'scale_factor',errscale);
        netcdf.putAtt(ncid,v4,'valid_min',int16(0));
        netcdf.putAtt(ncid,v4,'valid_max',int16(32767));
        netcdf.putAtt(ncid,v4,'comment','uncertainty in "analysed_sst"');
        netcdf.putAtt(ncid,v4,'coordinates','lon lat');
      end;

        v5 = netcdf.defVar(ncid,'mask',1,[d2,d1,d0]);
        netcdf.defVarChunking(ncid,v5,"CHUNKED",[1440 720 1]);
        netcdf.defVarDeflate(ncid,v5,true,true,nc4d);
        netcdf.putAtt(ncid,v5,'long_name','sea/land field composite mask');
%        netcdf.putAtt(ncid,v5,'_FillValue',int8(-128));
        netcdf.putAtt(ncid,v5,'coverage_content_type','referenceInformation');
        netcdf.defVarFill(ncid,v5,false,int8(-128));
        netcdf.putAtt(ncid,v5,'valid_min',int8(1));
        netcdf.putAtt(ncid,v5,'valid_max',int8(31));
        %netcdf.putAtt(ncid,v5,'flag_values',int8([1,2,3,5,9,11,13]));
        %netcdf.putAtt(ncid,v5,'flag_meanings','1=open-sea; 2=land; 3=coast/shore; 5=open-lake; 9=open-sea with ice in the grid; 11=coast/shore with ice in the grid; 13=open-lake with ice in the grid');
        netcdf.putAtt(ncid,v5,'flag_masks',int8([1,2,4,8,16]));
        %netcdf.putAtt(ncid,v5,'flag_values',int8([1,2,5,9,13]));
        netcdf.putAtt(ncid,v5,'flag_meanings','water land optional_lake_surface sea_ice optional_river_surface');
        netcdf.putAtt(ncid,v5,'comment','flag interpretation as integer values:  1=water, 2=land, 5=lake, 9=water with ice in the grid, 13=lake with ice in the grid, 17=river');
%        netcdf.putAtt(ncid,v5,'comment','mask can be used to further filter the data.');
        netcdf.putAtt(ncid,v5,'coordinates','lon lat');
        netcdf.putAtt(ncid,v5,'source','GMT "grdlandmask", ice flag from sea_ice_fraction data');

      if iceIncluded,
        ice_string=get_ice_files(icefiles, 'makeMUR25');
        v6 = netcdf.defVar(ncid,'sea_ice_fraction',1,[d2,d1,d0]);
        netcdf.defVarChunking(ncid,v6,"CHUNKED",[1440 720 1]);
        netcdf.defVarDeflate(ncid,v6,true,true,nc4d);
        netcdf.putAtt(ncid,v6,'long_name','sea ice area fraction');
        netcdf.putAtt(ncid,v6,'standard_name','sea_ice_area_fraction');
        netcdf.putAtt(ncid,v6,'coverage_content_type','auxiliaryInformation');
        %netcdf.putAtt(ncid,v6,'units','fraction (between 0 and 1)');
        %netcdf.putAtt(ncid,v6,'units','1 (dimensionless)');
        %netcdf.putAtt(ncid,v6,'units','1');
        %netcdf.putAtt(ncid,v6,'units','percent');
%        netcdf.putAtt(ncid,v6,'_FillValue',int8(-128));
        netcdf.defVarFill(ncid,v6,false,int8(-128));
        netcdf.putAtt(ncid,v6,'add_offset',iceoffset);
        netcdf.putAtt(ncid,v6,'scale_factor',icescale);
        netcdf.putAtt(ncid,v6,'valid_min',int8(0));
        netcdf.putAtt(ncid,v6,'valid_max',int8(100));
        netcdf.putAtt(ncid,v6,'source','EUMETSAT OSI-SAF, copyright EUMETSAT');
        comment_string = sprintf('ice fraction is a dimensionless quantity between 0 and 1; it has been interpolated by a nearest neighbor approach; EUMETSAT OSI-SAF files used: %s.',ice_string);
        netcdf.putAtt(ncid,v6,'comment',comment_string);
        netcdf.putAtt(ncid,v6,'coordinates','lon lat');
      end;

%      if hiresgridIncluded,
%        v7 = netcdf.defVar(ncid,'dt_1km_data',1,[d2,d1,d0]);
%        netcdf.defVarDeflate(ncid,v7,true,true,nc4d);
%        netcdf.putAtt(ncid,v7,'long_name','time to most recent 1km data');
%        netcdf.putAtt(ncid,v7,'standard_name','time to most recent 1km data');
%        netcdf.putAtt(ncid,v7,'units','hours');
%        netcdf.defVarFill(ncid,v7,false,int8(-128));
%        %netcdf.putAtt(ncid,v7,'add_offset',0);
%        %netcdf.putAtt(ncid,v7,'scale_factor',1);
%        netcdf.putAtt(ncid,v7,'valid_min',int8(-127));
%        netcdf.putAtt(ncid,v7,'valid_max',int8(127));
%        netcdf.putAtt(ncid,v7,'source','MODIS and VIIRS pixels ingested by MUR');
%        netcdf.putAtt(ncid,v7,'comment','The grid value is hours between the analysis time and the most recent MODIS or VIIRS 1km L2P datum within 0.01 degrees from the grid point.  "Fill value" indicates absence of such 1km data at the grid point.');
%        netcdf.putAtt(ncid,v7,'coordinates','lon lat');
%      end;

      if anomalyIncluded,
        v8 = netcdf.defVar(ncid,'sst_anomaly',3,[d2,d1,d0]);
        netcdf.defVarChunking(ncid,v8,"CHUNKED",[1440 720 1]);
        netcdf.defVarDeflate(ncid,v8,true,true,nc4d);
        netcdf.putAtt(ncid,v8,'long_name','SST anomaly from a seasonal SST climatology based on the MUR data over 2003-2014 period');
        netcdf.putAtt(ncid,v8,'coverage_content_type','auxiliaryInformation');
        netcdf.putAtt(ncid,v8,'units','kelvin');
%        netcdf.putAtt(ncid,v8,'_FillValue',int16(-32768));
        netcdf.defVarFill(ncid,v8,false,int16(-32768));
        netcdf.putAtt(ncid,v8,'add_offset',0.0);
        netcdf.putAtt(ncid,v8,'scale_factor',sstscale);
        netcdf.putAtt(ncid,v8,'valid_min',int16(-32767));
        netcdf.putAtt(ncid,v8,'valid_max',int16(32767));
        netcdf.putAtt(ncid,v8,'comment','anomaly reference to the day-of-year average between 2003 and 2014');
        netcdf.putAtt(ncid,v8,'coordinates','lon lat');
      end;


    %% global attributes:
        varid=netcdf.getConstant('GLOBAL');
        if realtime, version=[version,'nrt']; end;
        netcdf.putAtt(ncid,varid,'Conventions','CF-1.7, ACDD-1.3');
        if realtime,
          str='Daily 0.25-degree MUR SST, Interim near-real-time (nrt) product';
        else,
          str='Daily 0.25-degree MUR SST, Final product';
        end;
        netcdf.putAtt(ncid,varid,'title',str);
        netcdf.putAtt(ncid,varid,'summary','A low-resolution version of the MUR SST analysis, a merged, multi-sensor L4 Foundation SST analysis product from JPL.');
        netcdf.putAtt(ncid,varid,'keywords','Oceans > Ocean Temperature > Sea Surface Temperature'); 
        netcdf.putAtt(ncid,varid,'keywords_vocabulary','NASA Global Change Master Directory (GCMD) Science Keywords'); 
        netcdf.putAtt(ncid,varid,'standard_name_vocabulary','NetCDF Climate and Forecast (CF) Metadata Convention');
        netcdf.putAtt(ncid,varid,'history','This is an intermediate analysis (called "sibling") resulted during production of the full-resolution (0.01 horizontal degrees) MUR SST analysis.  See "reference" below.');
        netcdf.putAtt(ncid,varid,'source',sourcedata);
        netcdf.putAtt(ncid,varid,'platform',platformdata);
        netcdf.putAtt(ncid,varid,'instrument',sensordata);
        netcdf.putAtt(ncid,varid,'sensor',sensordata);
        netcdf.putAtt(ncid,varid,'processing_level','L4');
        netcdf.putAtt(ncid,varid,'cdm_data_type','grid');
        %netcdf.putAtt(ncid,varid,'product_version','4.1(25km)');
        %netcdf.putAtt(ncid,varid,'product_version','4.1');
        netcdf.putAtt(ncid,varid,'product_version',version);
        netcdf.putAtt(ncid,varid,'references','Chin et al. (2017) "Remote Sensing of Environment", volulme 200, pages 154-169.  http://dx.doi.org/10.1016/j.rse.2017.07.029');
        netcdf.putAtt(ncid,varid,'creator_name','JPL MUR SST project');
        netcdf.putAtt(ncid,varid,'creator_email','ghrsst@podaac.jpl.nasa.gov');
        netcdf.putAtt(ncid,varid,'creator_url','http://podaac.jpl.nasa.gov/Multi-scale_Ultra-high_Resolution_MUR-SST');
        netcdf.putAtt(ncid,varid,'creator_url','http://mur.jpl.nasa.gov');
        netcdf.putAtt(ncid,varid,'creator_institution','Jet Propulsion Laboratory');
        netcdf.putAtt(ncid,varid,'institution','Jet Propulsion Laboratory');
        netcdf.putAtt(ncid,varid,'project','NASA MEaSUREs and COVERAGE');
        netcdf.putAtt(ncid,varid,'program','NASA Earth Science Data and Information System (ESDIS)');
        netcdf.putAtt(ncid,varid,'southernmost_latitude',single(box(3)));
        netcdf.putAtt(ncid,varid,'northernmost_latitude',single(box(4)));
        netcdf.putAtt(ncid,varid,'westernmost_longitude',single(box(1)));
        netcdf.putAtt(ncid,varid,'easternmost_longitude',single(box(2)));
        netcdf.putAtt(ncid,varid,'geospatial_lat_min',single(box(3)));
        netcdf.putAtt(ncid,varid,'geospatial_lat_max',single(box(4)));
        netcdf.putAtt(ncid,varid,'geospatial_lon_min',single(box(1)));
        netcdf.putAtt(ncid,varid,'geospatial_lon_max',single(box(2)));
        netcdf.putAtt(ncid,varid,'geospatial_lat_units','degrees north');
        netcdf.putAtt(ncid,varid,'geospatial_lat_resolution',resfloat);
        netcdf.putAtt(ncid,varid,'geospatial_lon_units','degrees east');
        netcdf.putAtt(ncid,varid,'geospatial_lon_resolution',resfloat);
      timestamp=sprintf('%04d%02d%02dT%02d%02d%02dZ',cdy,cdm,cdd,cnH,cnM,cnS);
        netcdf.putAtt(ncid,varid,'date_created',timestamp);
      [d,m,y]=julian(day,year); hA=hourAna; mjd=julian(d,m,y,3)+hA/24;
      timestamp=sprintf('%04d%02d%02dT%02d0000Z',y,m,d,hA);
        netcdf.putAtt(ncid,varid,'start_time',timestamp);
        netcdf.putAtt(ncid,varid,'stop_time',timestamp);
      [d,m,y]=julian(mjd-12/24); hA=mod(hourAna-12,24);
      timestamp=sprintf('%04d%02d%02dT%02d0000Z',y,m,d,hA);
        netcdf.putAtt(ncid,varid,'time_coverage_start',timestamp);
      [d,m,y]=julian(mjd+12/24); hA=mod(hourAna-12,24);
      timestamp=sprintf('%04d%02d%02dT%02d0000Z',y,m,d,hA);
        netcdf.putAtt(ncid,varid,'time_coverage_end',timestamp);
        netcdf.putAtt(ncid,varid,'time_coverage_resolution','P1D');
        netcdf.putAtt(ncid,varid,'license','These data are available free of charge under data policy of JPL PO.DAAC.');
        netcdf.putAtt(ncid,varid,'id',entryID);
        netcdf.putAtt(ncid,varid,'product_version',version);
        netcdf.putAtt(ncid,varid,'uuid','27665bc0-d5fc-11e1-9b23-0800200c9a66');
        netcdf.putAtt(ncid,varid,'date_created',sprintf('%04d-%02d-%02d',cdy,cdm,cdd));

        if realtime,
          str='near real time (nrt) version created at nominal 1-day latency.';
        else,
          str='created at nominal 4-day latency; replaced nrt (1-day latency) version.';
        end;
        netcdf.putAtt(ncid,varid,'history',str);
        if realtime,
          str='Interim-MUR(nrt) will be replaced by MUR-Final in about 3 days; MUR = "Multi-scale Ultra-high Resolution"';
        else,
          str='MUR = "Multi-scale Ultra-high Resolution"';
        end;
        netcdf.putAtt(ncid,varid,'comment',str);

        netcdf.putAtt(ncid,varid,'naming_authority','org.ghrsst');
        netcdf.putAtt(ncid,varid,'gds_version_id','2.0');
        %netcdf.putAtt(ncid,varid,'netcdf_version_id','4.1');
        netcdf.putAtt(ncid,varid,'netcdf_version_id',version);
        netcdf.putAtt(ncid,varid,'spatial_resolution',resolution);
        netcdf.putAtt(ncid,varid,'publisher_name','GHRSST Project Office');
        netcdf.putAtt(ncid,varid,'publisher_url','https://www.ghrsst.org');
        netcdf.putAtt(ncid,varid,'publisher_email','gpc@ghrsst.org');
        %netcdf.putAtt(ncid,varid,'file_quality_level','1'); % 0=unknown; 1=best
        netcdf.putAtt(ncid,varid,'file_quality_level',int32(3)); % 0=unknown; 1=best
%%        netcdf.putAtt(ncid,varid,'Metadata_Conventions','Unidata Observation Dataset v1.0');
        netcdf.putAtt(ncid,varid,'metadata_link',['http://podaac.jpl.nasa.gov/ws/metadata/dataset/?format=iso&shortName=',entryID]);
        netcdf.putAtt(ncid,varid,'acknowledgment','Please acknowledge the use of these data with the following statement:  These data were provided by JPL under support by NASA MEaSUREs and COVERAGE programs.');

if 0,  %%% for metadata garbage:
        if realtime,
          str='nrt-MUR will be replaced by MUR (reanalysis) in about 3 days';
        else,
          str='reanalysis';
        end;
        %netcdf.putAtt(ncid,varid,'DSD_entry_id',entryID);
%        netcdf.putAtt(ncid,varid,'metadata_link','http://data.nodc.noaa.gov/cgi-bin/fgdc?id=nodc.noaa.gov:FGDC-GHRSST_all-JPL-L4UHfnd-GLOB-v01-MUR;view=text');
end;


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

%      if hiresgridIncluded,
%        % dt_1km_data:
%        data=ones(size(dt_1km_data),'int8')*int8(-128);
%        jnx=find(dt_1km_data>=-127&dt_1km_data<=127);
%        data(jnx)=int8( dt_1km_data(jnx) );
%        netcdf.putVar(ncid,v7,data)
%      end;
        clear dt_1km_data;

      if anomalyIncluded,
        % anomaly
        inx=find(msst~=badpixel);
        data=ones(size(ssta),'int16')*int16(-32768);
        data(inx)=int16( (ssta(inx))/sstscale );
        netcdf.putVar(ncid,v8,data)
      end;

        clear inx jnx data;
        clear msst;

      netcdf.close(ncid);






  %%%%%%%%%%%%%%%%%%%%%%%%%%%%
  % compression and checksum %
  %%%%%%%%%%%%%%%%%%%%%%%%%%%%

  if length(compression), eval(sprintf('! %s -f %s',compression,ncname)); end;
  back=pwd; cd(ddir);  % go to the data directory.
  eval(sprintf('! md5sum %s%s > %s%s.md5',ncbasename,ctail,ncname,ctail));
  cd(back);



  %%%%%%%%%%%%%%%%%%%%%%%
  % "push" into PO.DAAC %
  %%%%%%%%%%%%%%%%%%%%%%%
  
  % SFTP
  % if podaacpush,
  %   back=pwd; cd(ddir);  % go to the data directory.
  %   %cmd=sprintf('!%s/putsftpfile.sh sftp-ghrsst@seafire JPL-MUR-RTO/tmp',back);
  %   %cmd=sprintf('!%s/putsftpfile.sh gds2@seafire.jpl.nasa.gov JPL/tmp',back);
  %   cmd=sprintf('!%s/putsftpfile.sh gds2@ops-seafire.jpl.nasa.gov JPL/tmp',back);
  %     pushname=sprintf('%s%s',ncbasename,ctail);
  %       disp(sprintf('%s %s %s',cmd,pushname,pushname));
  %       eval(sprintf('%s %s %s',cmd,pushname,pushname));
  %     pushname=[pushname,'.md5'];
  %       disp(sprintf('%s %s %s',cmd,pushname,pushname));
  %       eval(sprintf('%s %s %s',cmd,pushname,pushname));
  %   cd(back);
  % end;
  
  % S3 UPLOAD
  if podaacpush,
    s3_bucket='podaac-dev-ghrsst-jpl'
    dataset_key='MUR25-JPL-L4-GLOB-v04.2'
    back=pwd; cd(ddir);  % go to the data directory.
    cmd=sprintf('!%s/upload.py %s %s',back,s3_bucket,dataset_key)
    pushname=sprintf('%s%s',ncbasename,ctail);
    disp(sprintf('%s %s',cmd,pushname));
    eval(sprintf('%s %s',cmd,pushname));
    pushname=[pushname,'.md5'];
    disp(sprintf('%s %s',cmd,pushname));
    eval(sprintf('%s %s',cmd,pushname));
    cd(back);
  end;  


end;
end;
