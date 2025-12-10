function l2p2bic(sensor,region,indir,bicdir,year,day,rewrite)
% l2p2bic(sensor,region,bicdir,year,day)
% converts L2P (and L2P_GRIDDED) files to a bic file for a given date.

  if ~exist('rewrite','var'), rewrite=0; end;

  %% inputs (examples):
  %  sensor='winsat'; year=2012; day=010;
  %  sensor='winsat'; year=2012; day=030;
  %  sensor='amsrea';  year=2011; day=239;
  %  sensor='avh19g';  year=2012; day=210;
  %  sensor='avh19g';  year=2012; day=215;
  %  sensor='avmtag';  year=2012; day=220;
  %  sensor='modisa';  year=2012; day=230;
  %
  %  region='Global';
  %

  year=str2double(year);
  day=str2double(day);

  %%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
  sensor=upper(sensor);
  %filedir=sprintf('%s/%s/%04d',bicdir,sensor,year);
  filedir=bicdir;
  mkdir(filedir)
  bicfilegz=sprintf('%s/%s_%s_%04d_%03d.bic.gz',filedir,region,sensor,year,day);
  if exist(bicfilegz,'file')&(rewrite==0),
    fprintf(1,'File exists; will NOT be reproduced:\n ... %s\n',bicfilegz);
    return;
  end;

  %% get sensor specific data-file parameters:
  [l2pnames,minConfValue,uncompresscmd,subdir]=SensorTable(sensor);


  %% get actual file names:
  for k=1:length(l2pnames),
    files=sprintf('%s/%s',indir,l2pnames{k});
    names=dir(files);
    if length(names), break; end;  % match priority in the order of "l2pnames".
  end;


  % for i = 1:length(names)
  %     disp(names(i).name);
  % end
  % exit()

  %% reference time adjustment (set to beginning of year/day):
  %tref=int32(julian(day,1,year,3)-julian(1,1,1981,3))*86400;
  tref=int64(julian(day,1,year,3)-julian(1,1,1981,3))*86400;

  %% fill data by reading each file:
  listfile=append(filedir,'/L2Plist_',region,'_',sensor,'_',string(year),'_',string(day),'.txt')
  fprintf(1,'l2p2bic: writing %s\n',listfile);
  flist=fopen(listfile,'w');

  % Pre-allocate in chunks for efficiency (avoiding repeated resizing)
  chunk_size = 100000;  % Allocate in 100k point chunks
  max_size = chunk_size;
  lon = zeros(max_size, 1, 'single');
  lat = zeros(max_size, 1, 'single');
  hour = zeros(max_size, 1, 'single');
  sst = zeros(max_size, 1, 'single');
  bias = zeros(max_size, 1, 'single');
  rms = zeros(max_size, 1, 'single');
  flag = zeros(max_size, 1, 'single');
  current_idx = 0;

  for k=1:length(names),

    file=sprintf('%s/%s',indir,names(k).name);
    fprintf(1,'l2p2bic: reading %s\n',file);
    fprintf(flist,'%s\n',file);

    % read L2P file:
    [head, body, tail] = fileparts( file );
    tmp_dir = getenv("TMP_DIR");
    tmpncfile=[tmp_dir,'/',body,'.nc'];
    if length(uncompresscmd),
      eval(sprintf('! %s %s > %s',uncompresscmd,file,tmpncfile));
    else,
      tmpncfile=file;
    end;

    % Try to read file, skip if corrupted
    try
      if length( strfind( subdir, '/L3U/' )),
        if length( strfind( subdir, '/VIIRS_NPP/OSPO/' )),
          [tmp,x,y,t,dt,b,sigma,prox]=readL3UasL2Pviirso(tmpncfile);
        else,
          [tmp,x,y,t,dt,b,sigma,prox]=readL3UasL2P(tmpncfile);
        end;
      else,
        %[tmp,x,y,t,dt,b,sigma,rjct,conf,prox]=readL2Pcore(tmpncfile);
        [tmp,x,y,t,dt,b,sigma,rjct,conf,prox]=readL2Pboth(tmpncfile);
        clear rjct conf;
      end;
      t = int64(t);
    catch ME
      fprintf(1,'WARNING: Failed to read %s: %s\n',file,ME.message);
      fprintf(1,'  Skipping corrupted or empty file\n');
      continue;
    end;
    % if length(uncompresscmd), delete(tmpncfile); end;

    % skip to next file if there is no SST content:
    if length( tmp )==0, continue; end;

  
    % time adjustment (translation):
    tt=double(t-tref)/3600;
    dt=double(dt)/3600;
    if length(tt)==1,
      dt=dt(:)+tt;
    else,  % multiple time fields per file:
      s=size(dt); n=length(s); m=prod(s(1:n-1)); n=s(n);
      if n~=length(tt), error('l2p2bic: # time stamps mismatches dim(dt)'); end;
      dt=reshape(dt,m,n);
      % Vectorized broadcasting instead of loop
      dt = dt + tt(:)';
    end;

    % find lon-lat for L2P_GRIDDED format:
    if length(strfind(subdir,'L2P_GRIDDED')),
      if strfind(subdir,'L2P_GRIDDED')==1,
        xx=x; yy=y;
        [x,y]=ndgrid(xx,yy,ones(size(t)));
        clear xx yy;
      end;
    end;

    % trim by confidence using logical mask:
    mask = prox(:) >= minConfValue;
    x=x(mask); y=y(mask); dt=dt(mask);
    tmp=tmp(mask); b=b(mask); sigma=sigma(mask); prox=prox(mask);

    % collect data with chunked pre-allocation:
    n_new = length(x);
    new_idx = current_idx + n_new;

    % Expand arrays if needed (in chunks)
    if new_idx > max_size,
      max_size = max_size + chunk_size;
      lon(max_size) = 0;
      lat(max_size) = 0;
      hour(max_size) = 0;
      sst(max_size) = 0;
      bias(max_size) = 0;
      rms(max_size) = 0;
      flag(max_size) = 0;
    end;

    % Store data
    idx_range = (current_idx+1):new_idx;
    lon(idx_range) = x(:);
    lat(idx_range) = y(:);
    hour(idx_range) = dt(:);
    sst(idx_range) = tmp(:);
    bias(idx_range) = b(:);
    rms(idx_range) = sigma(:);
    flag(idx_range) = prox(:);
    current_idx = new_idx;
    clear tmp x y t dt b sigma prox;

  end;

  fclose(flist);

  % Trim arrays to actual size
  lon = lon(1:current_idx);
  lat = lat(1:current_idx);
  hour = hour(1:current_idx);
  sst = sst(1:current_idx);
  bias = bias(1:current_idx);
  rms = rms(1:current_idx);
  flag = flag(1:current_idx);

  % Filter out NaN/invalid values before writing to BIC
  % This prevents: NaN SST -> int16(0) -> 0.0°C in output
  % Also filters sentinel values like -999.0 in coordinates
  valid_mask = ~isnan(sst) & ~isnan(lon) & ~isnan(lat) & isfinite(sst) & ...
               isfinite(lon) & isfinite(lat);

  n_invalid = sum(~valid_mask);
  if n_invalid > 0
      fprintf('  Warning: Filtering %d invalid observations (NaN/Inf coordinates or SST)\n', n_invalid);
  end

  lon = lon(valid_mask);
  lat = lat(valid_mask);
  hour = hour(valid_mask);
  sst = sst(valid_mask);
  bias = bias(valid_mask);
  rms = rms(valid_mask);
  flag = flag(valid_mask);


%% compare against an existing bic file:
  if 0,  % testing only:
    bicfile=sprintf('/nas2/bic/%s/%04d/Global_%s_%04d_%03d.bic',...
                              sensor,year,sensor,year,day);
    [T,b,sig,x,y,t,qt]=readbic(bicfile);

    [mean(x-lon),mean(y-lat),mean(qt-double(flag))],
    [max(abs(x-lon)),max(abs(y-lat)),max(abs(qt-double(flag)))],
    [mean(T-sst),mean(b-bias),mean(sig-rms)],
    [std(T-sst),std(b-bias),std(sig-rms)],
    [mean(t-hour),std(t-hour),max(t-hour),min(t-hour)],
  end;


%% write bic file:
  %filedir=sprintf('%s/%s/%04d',bicdir,sensor,year);
  %filedir=sprintf('%s/%04d',bicdir,year);
  if ~exist(filedir,'dir'), eval(sprintf('!mkdir -p %s',filedir)); end;

  bicfile=append(filedir,'/',region,'_',sensor,'_',string(year),'_',string(day),'.bic');
  writebic(bicfile,year,day,lon,lat,sst,bias,rms,hour,flag);
  % writebic does gzipping.
