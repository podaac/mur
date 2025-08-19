sources:
 ftp://www.star.nesdis.noaa.gov/pub/sod/sst/iquam/
 http://www.star.nesdis.noaa.gov/sod/sst/iquam/index.html

file name: IQUAM.NCEP.yyyy.mm.HDF

file contents:
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


Qualty_Flag
 Quality flags packed in 2 bytes. 
  Lower Byte: 
    bit 0-1 (Overall Quality):
      0-Normal, 2-Noisy, 1-Erroneous, 3-QC Unavailable; 
    bit 2-3 (Duplicate Check): 
      0-No duplicate, 1-Duplicate kept, 2-Duplicate removed;
    bit 4 (Track Check and Geolocation Check): 0-Pass, 1-Fail;
    bit 5 (SST Spike Check): 0-Pass, 1-Fail;
    bit 6 (ID Validity Check): 0-Valid, 1-Invalid;
    bit 7 (Number of Buddies): 0-Checked with 6+ Buddies, 1-Otherwise. 
  Higher Byte: the scaled Probability of Gross Error, 
  i.e. BYTE(Probability_of_Gross_Error * 255). 
 Please be advised that the quality flags are only intended for 
 sea surface temperatures. Other measurements have not been quality controlled.

%% quality filter for iQUAM:
inx=find( mod(quality_flag,4)==0 );
lon=lon(inx); lat=lat(inx); sst=sst(inx); % etc.



Type
  0: Unknown;
  1: Ship;
  2: Drifting Buoy;
  3: Open-sea Moored Buoy;
  4: Coastal Moored Buoy;
  5: Station.



% To get more info (reading attributes):

% open file:
fileID = hdfsd('start',filename, 'read');

% # data sets and attributes:
[ndatasets, nglobattr, status] = hdfsd('fileinfo', fileID);

% Read global attributes:
if 0,
  for n=0:nglobattr-1,
    attribute_name = hdfsd('readattr', fileID, n),
    hdfsd( 'readattr', fileID, hdfsd('findattr',fileID,'attribute_name') );
  end;
end;


%% Read file contents:
if 0,
  disp('### FILE DATA CONTENTS: ###');
  for n=0:ndatasets-1,
    dataID = hdfsd('select', fileID, n);
    [name,ndim,dimvector,type,nattr] = hdfsd('getinfo', dataID);
    fprintf(1,'  %s: %s(%d) +%d\n',name,type,ndim,nattr);
  end;
end;


%% Read data:
if 0,
  % given data name:
  dataID = hdfsd('select', fileID, hdfsd('nametoindex',fileID,dataname) );
  [name,ndim,dims,type,nattr] = hdfsd('getinfo', dataID);
  startvector=zeros(size(dims)); stridevector=[]; endvector=dims;
  data = hdfsd('readdata', dataID, startvector, stridevector, endvector);
  hdfsd('endaccess',dataID);
end;


%% Read attribute:
  % given data name:
  dataID = hdfsd('select', fileID, hdfsd('nametoindex',fileID,dataname) );
  [name,ndim,dims,type,nattr] = hdfsd('getinfo', dataID);
  for n=0:nattr-1,
    hdfsd('readattr', dataID, n),
  end;
  hdfsd('endaccess',dataID);



%% close file:
hdfsd('end',fileID);

