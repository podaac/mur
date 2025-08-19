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

