function L4ghrsst2bip(l4file,bipfile,box,aerr,dhour)
% writes a bip file based on the content of the l4file.

% parameters:
  if ~exist('box','var'), box=[]; end; % bounding box (default=global).
  if ~exist('aerr','var'), aerr=0.75; end; % RMS error.
  if ~exist('dhour','var'), dhour=0.; end; % [hrs] difference to analysis time.
  sstOffset=273.15;  % reduce the SST magnitude (e.g., from Kelvin to Celcius)


% read L4 file:
  if ~exist(l4file,'file'),
    fprintf(1,'ERROR L4ghrsst2bip: following L4 file not found:\n%s\n',l4file);
    fprintf(1,'ERROR L4ghrsst2bip: ... bip file not written.\n');
    return;
  end;

  ncfile=l4file;
  ncid=netcdf.open(ncfile,'nowrite');

  % latitude:
  varid = netcdf.inqVarID(ncid,'lat');
  lat = netcdf.getVar(ncid,varid);

  % longitude:
  varid = netcdf.inqVarID(ncid,'lon');
  lon = netcdf.getVar(ncid,varid);

  % grids:
  [Lon,Lat]=ndgrid(lon,lat);
  Lon=Lon(:); Lat=Lat(:);

  % SST:
  varid = netcdf.inqVarID(ncid,'analysed_sst');
  sst = netcdf.getVar(ncid,varid);
  badpix = netcdf.getAtt(ncid,varid,'_FillValue');
  const = netcdf.getAtt(ncid,varid,'add_offset');
  scale = netcdf.getAtt(ncid,varid,'scale_factor');
  sst=double(sst);
  inx=find(sst(:)==badpix); if length(inx), sst(inx)=NaN*ones(size(inx)); end;
  SST=sst*double(scale)+double(const);
  SST=SST(:);

  netcdf.close(ncid);

% size check:
  if length(SST)~=length(Lon),
    fprintf(1,'ERROR L4ghrsst2bip: mismatch in variable size, %d vs %d\n',...
              length(SST),length(Lon) );
    fprintf(1,'ERROR L4ghrsst2bip: ... bip file not written.\n');
    return;
  end;


% set up arrays:

  % L4 values:
  inx=find(~isnan(SST));
  sstbip=SST(inx); lonbip=Lon(inx); latbip=Lat(inx);

  % subtract the offset (e.g., Kelvin to Celcius conversion):
  sstbip=sstbip-sstOffset;

  % data weights:
  rmsbip=aerr*ones(size(sstbip));
  wgtbip=1./(rmsbip.^2);

  % difference to the analysis time:
  dhrbip=dhour*ones(size(sstbip));

  % bounding box:
  if length(box),
    inx=find(lonbip>=box(1)&lonbip<=box(2)&latbip>=box(3)&latbip<=box(4));
    lonbip=lonbip(inx);
    latbip=latbip(inx);
    dhrbip=dhrbip(inx);
    sstbip=sstbip(inx);
    wgtbip=wgtbip(inx);
  end;


% write bip file:
  f=fopen(bipfile,'w');
  ndata=length(sstbip);
  fortwrite(f,'integer*4',ndata);
  fortwrite(f,lonbip,latbip,dhrbip,sstbip,wgtbip);
  fclose(f);


