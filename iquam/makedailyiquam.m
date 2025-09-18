function makedailyiquam(year,doy,rewrite)
%% makedaily.m
%% downloads IQUAM netCDF file and save as daily bii files.



  %% detination directory:
  ddir='/home/earmstro/mur/mur_production_test_from_tebaldi/data/iquam';

  %% subdirectory:
  edir=sprintf('/home/earmstro/mur/mur_production_test_from_tebaldi/data/iquam/%04d',year);
  if ~exist(edir,'dir'), eval(sprintf('! mkdir -p %s',edir)); end;

  %% filename:  
  filename=sprintf('%s/Global_IQUAM0_%04d_%03d.bii',edir,year,doy);


if ~exist('rewrite','var'), rewrite=0; end;

if (~rewrite) & exist(filename,'file'), return; end;


    %% netCDF file:
    [day,month]=julian(doy,year);
    %ifile=sprintf('IQUAM.NCEP.%04d.%02d.HDF',year,month);
    %localfile=sprintf('%s.mat',ifile);
    ifile=sprintf('%04d%02d-STAR-L2i_GHRSST-SST-iQuam-*.nc',year,month);
    %localfile=sprintf('iquam.%04d.%02d.mat',year,month);
    localfile=sprintf('%s/iquam.%04d.%02d.mat',pwd,year,month);

    %% download, read HDF file, and quality control:
    if ~exist(localfile,'file'), 

      %% download:
      %iurl='ftp://www.star.nesdis.noaa.gov/pub/sod/sst/iquam';
      %iurl='ftp://ftp.star.nesdis.noaa.gov/pub/sod/sst/iquam/v2.00';
      iurl='ftp://ftp.star.nesdis.noaa.gov/pub/sod/sst/iquam/v2.10';
      cmd=sprintf('! wget "%s/%s"',iurl,ifile);
      eval(cmd);
      disp(cmd);

      %% read:
      ddir = dir( ifile );
      if length(ddir),
        ncfile = ddir(1).name;
      else,
        disp(sprintf('IQUAM failed to download on %04d/%03d',year,doy));
        return;
      end;

      [dayf, hour, minute, lon, lat, sst, qual, pt] = readnc( ncfile );
      delete( ncfile );

      %f=hdfreadopen(ifile);
      %  dayf=hdfreadvariable(f,'Day');
      %  hour=hdfreadvariable(f,'Hour');
      %  minute=hdfreadvariable(f,'Minute');
      %  lon=hdfreadvariable(f,'Longitude');
      %  lat=hdfreadvariable(f,'Latitude');
      %  sst=hdfreadvariable(f,'Sea_Surface_Temperature');
      %  qual=hdfreadvariable(f,'Quality_Flag');
      %  pt=hdfreadvariable(f,'Type');
      %hdfreadclose(f);
      %delete(ifile);

      %% conversion:
      hour = hour+minute/60;
      %knx=find(lon>180);  if length(knx), lon(knx)=lon(knx)-360; end;
      sst = sst - 273.15;  % ncfile uses Kelvin.

      %% quality control:
      %% http://www.star.nesdis.noaa.gov/sod/sst/iquam/index.html
      %knx=find( mod(qual,4)==0 );
      knx=find( qual>=5 );
      dayf=dayf(knx); hour=hour(knx); pt=pt(knx);
      sst=sst(knx); lon=lon(knx); lat=lat(knx);

      %% save the contents:
      save(localfile,'dayf','hour','pt','sst','lon','lat');

    else,  % read from mat file:

      disp(['makedailyiquam: reading ',localfile]);
      load(localfile);

    end;

    %% extract daily components:
    knx=find(dayf==day);
      hour=hour(knx); pt=pt(knx);
      sst=sst(knx); lon=lon(knx); lat=lat(knx);


    %% write file:  (from writeiquambii)
      f=fopen(filename,'w');
      if f==-1, error(['cannot write/open to ',filename]); end;

      %% data conversion:
      N=length(sst(:));
      sst=int16(sst*100);
      lon=int16(lon*100);
      lat=int16(lat*100);
      hour=int16(hour*100);
      pt=int8(pt);

      %% write
      fortwrite(f,'int32',N,'int16',year,'int16',doy);
      fortwrite(f,'int16',sst,'int16',lon,'int16',lat,'int16',hour,'int8',pt);
      fclose(f);



%%%%%%%%%%

function fileID=hdfreadopen(filename,contents)
% fileID=hdfreadopen(filename,contents)
% open and HDF file using matlab hdfsd and returns its file ID.
%
% If "contents" flag is set, a list of its variable contents is printed.
%
% The file is close if the "contents" flag is set (default: contents=0).


if ~exist('contents','var'), contents=0; end;

fileID = hdfsd('start',filename, 'read');

if fileID==-1,
  disp(sprintf('hdfreadopen: %s not found.',filename)); return; 
end;

if contents,
  [ndatasets, nglobattr, status] = hdfsd('fileinfo', fileID);

  fprintf(1,'ndatasets=%d, nglobattr=%d\n',ndatasets,nglobattr);

  disp(sprintf('### %s, CONTENTS: ###',filename));
  for n=0:ndatasets-1,
    dataID = hdfsd('select', fileID, n);
    [name,ndim,dimvector,type,nattr] = hdfsd('getinfo', dataID);
    fprintf(1,'  %s: %s(%d) +%d\n',name,type,ndim,nattr);
    hdfsd('endaccess',dataID);
  end;

  hdfsd('end',fileID);
end;


function val=hdfreadvariable(fileID,varname)
% val=hdfreadvariable(fileID,'varname')
% returns value "val" of the HDF file variable named "varname".

dataID = hdfsd('select', fileID, hdfsd('nametoindex',fileID,varname) );

if dataID==-1,
  disp(sprintf('"%s" not found in fileID %d',varname,fileID));
  val=[];
  return;
end;

[name,ndim,dims,type,nattr] = hdfsd('getinfo', dataID);
startvector=zeros(size(dims)); stridevector=[]; endvector=dims;
  val = hdfsd('readdata', dataID, startvector, stridevector, endvector);
hdfsd('endaccess',dataID);


function status=hdfreadclose(fileID)
% closes the opened HDF file.
status = hdfsd('end',fileID);


function [dayf,hour,minute,lon,lat,sst,qual,pt] = readnc( ncfile )

ncid=netcdf.open(ncfile,'nowrite');

  dayf = netcdf.getVar( ncid, netcdf.inqVarID( ncid, 'day' ) );
  bad = netcdf.getAtt( ncid, netcdf.inqVarID( ncid, 'day' ), '_FillValue' );
  dayf( find( dayf==bad ) ) = NaN;

  hour = netcdf.getVar( ncid, netcdf.inqVarID( ncid, 'hour' ) );
  bad = netcdf.getAtt( ncid, netcdf.inqVarID( ncid, 'hour' ), '_FillValue' );
  hour( find( hour==bad ) ) = NaN;

  minute = netcdf.getVar( ncid, netcdf.inqVarID( ncid, 'minute' ) );
  bad = netcdf.getAtt( ncid, netcdf.inqVarID( ncid, 'minute' ), '_FillValue' );
  minute( find( minute==bad ) ) = NaN;

  lon = netcdf.getVar( ncid, netcdf.inqVarID( ncid, 'lon' ) );

  lat = netcdf.getVar( ncid, netcdf.inqVarID( ncid, 'lat' ) );

  sst = netcdf.getVar( ncid, netcdf.inqVarID( ncid, 'sst' ) );
  bad = netcdf.getAtt( ncid, netcdf.inqVarID( ncid, 'sst' ), '_FillValue' );
  sst( find( sst==bad ) ) = NaN;

  qual = netcdf.getVar( ncid, netcdf.inqVarID( ncid, 'quality_level' ) );
  bad = netcdf.getAtt(ncid,netcdf.inqVarID(ncid,'quality_level'),'_FillValue');
  qual( find( qual==bad ) ) = NaN;

  pt = netcdf.getVar( ncid, netcdf.inqVarID( ncid, 'platform_type' ) );
  bad = netcdf.getAtt(ncid,netcdf.inqVarID(ncid,'platform_type'),'_FillValue');
  pt( find( pt==bad ) ) = NaN;


netcdf.close(ncid);

