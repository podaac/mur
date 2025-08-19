%% makebin.m
%% downloads IQUAM HDF file and save as daily bin files.
%%
%% destination directory and output filename are set in writeiquambin.m


if ~exist('whichdays','var'),  % set the dates here for "stand-alone" run.
  whichdays={
%2002,1:365
2003,1:365
2004,1:366
2005,1:365
2006,1:365
2007,1:365
2008,1:366
2009,1:365
2010,1:365
2011,1:365
2012,1:366
  };
end;


for daycounter=1:size(whichdays,1),
  year=whichdays{daycounter,1};
  first=1;  % download flag.

  for doy=whichdays{daycounter,2},


    %% HDF file:
    [day,month]=julian(doy,year);
    ifile=sprintf('IQUAM.NCEP.%04d.%02d.HDF',year,month);


    %% download, read HDF file, and quality control:
    if day==1 | first,
      first=0;

      %% download:
      iurl='ftp://www.star.nesdis.noaa.gov/pub/sod/sst/iquam';
      cmd=sprintf('! wget %s/%s',iurl,ifile);
      eval(cmd);

      %% read:
      if ~exist(ifile,'file'), error('file to read does not exist'); end;
      f=hdfreadopen(ifile);
        dayf=hdfreadvariable(f,'Day');
        hour=hdfreadvariable(f,'Hour');
        minute=hdfreadvariable(f,'Minute');
        lon=hdfreadvariable(f,'Longitude');
        lat=hdfreadvariable(f,'Latitude');
        sst=hdfreadvariable(f,'Sea_Surface_Temperature');
        qual=hdfreadvariable(f,'Quality_Flag');
      hdfreadclose(f);
      delete(ifile);

      %% conversion:
      hour=hour+minute/60;
      knx=find(lon>180);  if length(knx), lon(knx)=lon(knx)-360; end;

      %% quality control:
      %% http://www.star.nesdis.noaa.gov/sod/sst/iquam/index.html
      knx=find( mod(qual,4)==0 );
      dayf=dayf(knx); hour=hour(knx);
      sst=sst(knx); lon=lon(knx); lat=lat(knx);

    end;

    %% extract daily components and write output:
    knx=find(dayf==day);
    writeiquambin(year,doy,lon(knx),lat(knx),sst(knx),hour(knx));

  end;
end;
