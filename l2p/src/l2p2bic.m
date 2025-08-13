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

  year=str2double(year)
  day=str2double(day)

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

  lon=[]; lat=[]; hour=[];
  sst=[]; bias=[]; rms=[]; flag=[];

  for k=1:length(names),

    file=sprintf('%s/%s',indir,names(k).name);
    fprintf(1,'l2p2bic: reading %s\n',file);
    fprintf(flist,'%s\n',file);

    % read L2P file:
    [head, body, tail] = fileparts( file );
    tmp_dir = getenv("TMP_DIR")
    tmpncfile=[tmp_dir,'/',body,'.nc'];
    if length(uncompresscmd),
      eval(sprintf('! %s %s > %s',uncompresscmd,file,tmpncfile));
    else,
      tmpncfile=file;
    end;
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
      for j=1:length(tt),
        dt(:,j)=dt(:,j)+tt(j);
      end;
    end;

    % find lon-lat for L2P_GRIDDED format:
    if length(strfind(subdir,'L2P_GRIDDED')),
      if strfind(subdir,'L2P_GRIDDED')==1,
        xx=x; yy=y;
        [x,y]=ndgrid(xx,yy,ones(size(t)));
        clear xx yy;
      end;
    end;

    % trim by confidence:
    inx=find(prox(:)>=minConfValue);
    x=x(inx); y=y(inx); dt=dt(inx);
    tmp=tmp(inx); b=b(inx); sigma=sigma(inx); prox=prox(inx);

    % collect:
    lon=[lon;x(:)]; lat=[lat;y(:)]; hour=[hour;dt(:)]; 
    sst=[sst;tmp(:)]; bias=[bias;b(:)]; rms=[rms;sigma(:)]; flag=[flag;prox(:)];
    clear tmp x y t dt b sigma prox;

  end;

  fclose(flist);


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
