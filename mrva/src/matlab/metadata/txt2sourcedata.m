function [sourcedata, sensordata, platformdata] = txt2sourcedata( path, isice )

icedata = 'Ice_Conc-OSISAF';


sourcetable = { % label, source, sensor, platform
'MODIST','MODIS_T-JPL, '                ,'MODIS, '  ,'Terra, '
'MODISA','MODIS_A-JPL, '                ,'MODIS, '  ,'Aqua, '
'VIIRSN','VIRRS_NPP-NAVO, '             ,'VIIRS, '  ,'Suomi NPP, '
'VIIRSO','VIRRS_NPP-OSPO, '             ,'VIIRS, '  ,'Suomi NPP, '
'AMSREA','AMSRE-REMSS, '                ,'AMSR-E, ' ,'Aqua, '
'WINSAT','WSAT-REMSS, '                 ,'WindSat, ','Coriolis, '
'AMSR2R','AMSR2-REMSS, '                ,'AMSR2, '  ,'GCOM-W, '
'RAN17G','AVHRR17_G-ACSPO, '            ,'AVHRR, '  ,'NOAA-17, '
'AVH18G','AVHRR18_G-NAVO, '             ,'AVHRR, '  ,'NOAA-18, '
'AVH19G','AVHRR19_G-NAVO, '             ,'AVHRR, '  ,'NOAA-19, '
'AVMTAG','AVHRRMTA_G-NAVO, '            ,'AVHRR, '  ,'MetOp-A, '
'AVMTBG','AVHRRMTB_G-NAVO, '            ,'AVHRR, '  ,'MetOp-B, '
'PATH5D','Pathfinder-PFV5.2day-NODC, '  ,'AVHRR, '  ,'NOAA-series, '
'PATH5N','Pathfinder-PFV5.2night-NODC, ','AVHRR, '  ,'NOAA-series, '
'IQUAM0','iQUAM-NOAA/NESDIS, '          ,'in-situ, ','Buoys/Ships, '
};


%% read data usagle file:
[label, number] = textread( path,'%s%*d%*d%d%*[^\n]' );

%% find labels of sensors that were used at least once:
label = label( find( number>0 ));  
label = unique( label );

%% match up against the sourcetable:
[label, inx] = intersect( sourcetable(:,1), label, 'stable' );

%% sources:
sourcedata = [sourcetable{inx,2}];  % expand into a single string.
if isice,
  sourcedata = [sourcedata,icedata];  % add ice data source.
else,
  sourcedata = sourcedata(1:end-2);  % remove trailing comma+space.
end;

%% sensors and platforms:
sensordata = unique( sourcetable(inx,3), 'stable');
sensordata = [sensordata{:}];
sensordata = sensordata(1:end-2);

platformdata = unique( sourcetable(inx,4), 'stable');
platformdata = [platformdata{:}];
platformdata = platformdata(1:end-2);
