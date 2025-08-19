
%% source:
% ftp://www.star.nesdis.noaa.gov/pub/sod/sst/iquam/
% http://www.star.nesdis.noaa.gov/sod/sst/iquam/index.html

%filename='/tmp/IQUAM.NCEP.2010.07.HDF';
filename='/home/tmchin/iquam/IQUAM.NCEP.2010.07.HDF';


% open file:
fileID = hdfsd('start',filename, 'read');

% # data sets and attributes:
[ndatasets, nglobattr, status] = hdfsd('fileinfo', fileID);


fprintf(1,'fileID=%d, ndatasets=%d, nglobattr=%d\n',fileID,ndatasets,nglobattr);



%% Read global attributes:
if 0,
  for n=0:nglobattr-1,
    attribute_name = hdfsd('readattr', fileID, n),
    hdfsd( 'readattr', fileID, hdfsd('findattr',fileID,'attribute_name') );
  end;
end;


%% Read data contents:
if 0,
  disp('### FILE DATA CONTENTS: ###');
  for n=0:ndatasets-1,
    dataID = hdfsd('select', fileID, n);
    [name,ndim,dimvector,type,nattr] = hdfsd('getinfo', dataID);
    fprintf(1,'  %s: %s(%d) +%d\n',name,type,ndim,nattr);
  end;
end;

%  Year: int16(1) +1
%  Month: uint8(1) +1
%  Day: uint8(1) +1
%  Hour: uint8(1) +1
%  Minute: uint8(1) +1
%  Latitude: float(1) +2
%  Longitude: float(1) +2
%  ID: uint8(2) +1
%  Type: uint8(1) +1
%  Sea_Surface_Temperature: float(1) +2
%  Sea_Level_Press: float(1) +1
%  Wind_Direction: float(1) +2
%  Wind_Speed: float(1) +1
%  Air_Temperature: float(1) +2
%  Dew_Point: float(1) +2
%  Cloud_Coverage: float(1) +1
%  Quality_Flag: uint16(1) +1



if 0,  % how to find the data ID
hdfsd('nametoindex',fileID,'sst')
hdfsd('nametoindex',fileID,'longitude')
hdfsd('nametoindex',fileID,'latitude') 
end;


%% Read times:
  dataID = hdfsd('select', fileID, hdfsd('nametoindex',fileID,'Year') );
  [name,ndim,dims,type,nattr] = hdfsd('getinfo', dataID);
  startvector=zeros(size(dims)); stridevector=[]; endvector=dims;
year = hdfsd('readdata', dataID, startvector, stridevector, endvector);
    hdfsd('endaccess',dataID);
  dataID = hdfsd('select', fileID, hdfsd('nametoindex',fileID,'Month') );
  [name,ndim,dims,type,nattr] = hdfsd('getinfo', dataID);
  startvector=zeros(size(dims)); stridevector=[]; endvector=dims;
month = hdfsd('readdata', dataID, startvector, stridevector, endvector);
    hdfsd('endaccess',dataID);
  dataID = hdfsd('select', fileID, hdfsd('nametoindex',fileID,'Day') );
  [name,ndim,dims,type,nattr] = hdfsd('getinfo', dataID);
  startvector=zeros(size(dims)); stridevector=[]; endvector=dims;
day = hdfsd('readdata', dataID, startvector, stridevector, endvector);
    hdfsd('endaccess',dataID);
  dataID = hdfsd('select', fileID, hdfsd('nametoindex',fileID,'Hour') );
  [name,ndim,dims,type,nattr] = hdfsd('getinfo', dataID);
  startvector=zeros(size(dims)); stridevector=[]; endvector=dims;
hour = hdfsd('readdata', dataID, startvector, stridevector, endvector);
    hdfsd('endaccess',dataID);
  dataID = hdfsd('select', fileID, hdfsd('nametoindex',fileID,'Minute') );
  [name,ndim,dims,type,nattr] = hdfsd('getinfo', dataID);
  startvector=zeros(size(dims)); stridevector=[]; endvector=dims;
minu = hdfsd('readdata', dataID, startvector, stridevector, endvector);
    hdfsd('endaccess',dataID);


%% Read lon and lat: 
  dataID = hdfsd('select', fileID, hdfsd('nametoindex',fileID,'Longitude') );
  [name,ndim,dims,type,nattr] = hdfsd('getinfo', dataID);
  startvector=zeros(size(dims)); stridevector=[]; endvector=dims;
lon = hdfsd('readdata', dataID, startvector, stridevector, endvector);
    hdfsd('endaccess',dataID);
  dataID = hdfsd('select', fileID, hdfsd('nametoindex',fileID,'Latitude') );
  [name,ndim,dims,type,nattr] = hdfsd('getinfo', dataID);
  startvector=zeros(size(dims)); stridevector=[]; endvector=dims;
lat = hdfsd('readdata', dataID, startvector, stridevector, endvector);
    hdfsd('endaccess',dataID);


%% Read data: 
  dataID = hdfsd('select', fileID, hdfsd('nametoindex',fileID,'Quality_Flag') );
  [name,ndim,dims,type,nattr] = hdfsd('getinfo', dataID);
  startvector=zeros(size(dims)); stridevector=[]; endvector=dims;
qual = hdfsd('readdata', dataID, startvector, stridevector, endvector);
    hdfsd('endaccess',dataID);
  dataID = hdfsd('select', fileID, hdfsd('nametoindex',fileID,'Sea_Surface_Temperature') );
  [name,ndim,dims,type,nattr] = hdfsd('getinfo', dataID);
  startvector=zeros(size(dims)); stridevector=[]; endvector=dims;
sst = hdfsd('readdata', dataID, startvector, stridevector, endvector);
    hdfsd('endaccess',dataID);


%% other data: 
if 0,
  dataID = hdfsd('select', fileID, hdfsd('nametoindex',fileID,'Type') );
  [name,ndim,dims,type,nattr] = hdfsd('getinfo', dataID);
  startvector=zeros(size(dims)); stridevector=[]; endvector=dims;
Type = hdfsd('readdata', dataID, startvector, stridevector, endvector);
  dataID = hdfsd('select', fileID, hdfsd('nametoindex',fileID,'Sea_Level_Press') );
  [name,ndim,dims,type,nattr] = hdfsd('getinfo', dataID);
  startvector=zeros(size(dims)); stridevector=[]; endvector=dims;
ssp = hdfsd('readdata', dataID, startvector, stridevector, endvector);
  dataID = hdfsd('select', fileID, hdfsd('nametoindex',fileID,'Wind_Speed') );
  [name,ndim,dims,type,nattr] = hdfsd('getinfo', dataID);
  startvector=zeros(size(dims)); stridevector=[]; endvector=dims;
wind = hdfsd('readdata', dataID, startvector, stridevector, endvector);
  dataID = hdfsd('select', fileID, hdfsd('nametoindex',fileID,'Cloud_Coverage') );
  [name,ndim,dims,type,nattr] = hdfsd('getinfo', dataID);
  startvector=zeros(size(dims)); stridevector=[]; endvector=dims;
cloud = hdfsd('readdata', dataID, startvector, stridevector, endvector);
end;


%% quality filter for iQUAM:
inx=find( mod(qual,4)==0 );
lon=lon(inx); lat=lat(inx); sst=sst(inx); qual=qual(inx);
year=year(inx); month=month(inx); day=day(inx); hour=hour(inx); minu=minu(inx);


%% close file:
hdfsd('end',fileID);

