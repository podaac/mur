function [l2pnames,minConfValue,cmd]=SensorTable(SensorName)

% sensor specifics:
switch upper(SensorName),

  case 'AMSR2R',
    l2pnames   = {'*_v8.2_*.nc','*_rt_*.nc'};
    minConfValue = 4;
    cmd = '';

  case 'AVMTBG',
    l2pnames   = {'*.nc'};
    minConfValue = 4;
    cmd = 'cat';

  case 'MODISA',
    l2pnames   = {'*.nc'};
    minConfValue = 5;
    cmd = 'cat';

  case 'MODIST',
    l2pnames   = {'*.nc'};
    minConfValue = 5;
    cmd = 'cat';

end;  % switch.
