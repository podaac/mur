function showcsp(cspfile,lon,lat);



sst=samplecsp(cspfile,lon,lat); 

sst=sst-273.15;

imagesc(lon,lat,sst'); axis xy;

geoshow('landareas.shp', 'FaceColor', 'black');
