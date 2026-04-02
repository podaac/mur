function [l2pnames,minConfValue,cmd,subdir]=SensorTable(SensorName)

% sensor specifics:
switch upper(SensorName),

  case 'AMSR2R',
    l2pnames   = {'*_v8.2_*.nc','*_rt_*.nc'};
    minConfValue = 4;
    cmd = '';
    subdir='GDS2/L2P/AMSR2/REMSS/v8.2';

  case 'AVMTBG',
    l2pnames   = {'*.nc'};
    minConfValue = 4;
    cmd = 'cat';
    subdir='GDS2/L2P/AVHRRMTB_G/NAVO/v2';

  case 'MODISA',
    l2pnames   = {'*.nc'};
    minConfValue = 5;
    cmd = 'cat';
    subdir='GDS2/L2P/MODIS_A/JPL/v2019.0';

  case 'MODIST',
    l2pnames   = {'*.nc'};
    minConfValue = 5;
    cmd = 'cat';
    subdir='GDS2/L2P/MODIS_T/JPL/v2019.0';

  case 'AVMTAG',
    l2pnames   = {'*.nc'};
    minConfValue = 4;
    cmd = 'cat';
    subdir='GDS2/L2P/AVHRRMTA_G/NAVO/v2';

end;  % switch.
