%% bic2biq.m
%% The same as bin2bip.m, except:
%% 1) bic.gz file is read;
%% 2) if the desired bic.gz file doesn't exist, it will complain and stop;
%% 3) biq file is written (actually no different from the recent bin2bip.m).
%% NOTE: many output names (e.g., "bipfile") still contains "bip" and "bin".

%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%

%% run control:

%sensors={ % sensor, bindir, binregion:
%'FNMOCs','/nas2/BIN','GLOBAL',
%'AATSRi','/nas2/BIN','NCAMERICA',
%'AMSREA','/nas2/BIN','NCAMERICA',
%'MODISA','/nas2/BIN','NCAMERICA',
%'MODIST','/nas2/BIN','NCAMERICA',
%};
%  bipdir='/tmp/bip';
%  coedir='/nas2/ecmwf/cbs';  % wind *.coe file directory.
%  years=2009;
%  yeardays=30;

%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%

%% parameters:

%  hourAna=9;  % UTC. Analysis Time.

%  dayrange=2;  % [day] window size will be "dayrange*2+1".
%               % assumed to be < 365.

  daytimeonly=0;  % [1 or 0] set to use only daytime data.

  mindaywind=600000.0; % [m/s] minimum daytime windspeed.
                  % set <=0 for no constraint; 
                  % set large (> 10000) for nighttime only.

%  sstOffset=273.15;  % reduce the SST magnitude (e.g., from Kelvin to Celcius)

%  region='NCAMERICA';  % analysis region.


%%%%%%%%%%%%%%%%%%%%%%%%%%%%%% %%%%%%%%%%%%%%%%%%%%%%%%%%%%%%

%% write input log file:
if 1,
  flog=fopen('bic2biq.input.log','w');
else,
  flog=1;
end;

%for year=years,
%for day=yeardays,
for isensor=1:size(sensors,1),
  sensor=sensors{isensor,1};
  bindir=sensors{isensor,2}; binregion=sensors{isensor,3};
  dayrange=sensors{isensor,6};



  %% sensor-dependent parameters:
      %% qtset = quality/type flag index set.
      %% biasflag = [1 or 0] set if bias data are subtracted.
      %% offset = [K] constant value to be subtracted.
      %% maxerr = [K for L2P, ProbGrossError for FNMOCs] error threshold.
      %% aerr = [K] assigned RMS error; set to 0 to use the L2P rms values.
  switch sensor,
    case 'FNMOCs', qtset=[4,5]; 
                           biasflag=0; offset=-273.15; maxerr=0.95; aerr=0.2;
    case 'AMSREA', qtset=[4]; biasflag=1; offset=0; maxerr=1.0; aerr=0;
    case 'AMSR2R', qtset=[4]; biasflag=1; offset=0; maxerr=1.0; aerr=0;
    case 'WINSAT', qtset=[4]; biasflag=1; offset=0; maxerr=1.0; aerr=0;
    case 'AATSRi', qtset=[4,5]; biasflag=1; offset=-0.17; maxerr=1.0; aerr=0;
%    case 'MODISA', qtset=[5]; biasflag=0; offset=-0.14; maxerr=99; aerr=0;
%    case 'MODIST', qtset=[5]; biasflag=0; offset=-0.14; maxerr=99; aerr=0;
    case 'MODISA', qtset=[5]; biasflag=0; offset=-0.20; maxerr=0.7; aerr=0;
    case 'MODIST', qtset=[5]; biasflag=0; offset=-0.20; maxerr=0.7; aerr=0;
    case 'RAN17G', qtset=[5]; biasflag=1; offset=0; maxerr=1.0; aerr=0;
    case 'AVH18G', qtset=[5]; biasflag=1; offset=0; maxerr=1.0; aerr=0;
    case 'AVH18L', qtset=[5]; biasflag=1; offset=0; maxerr=1.0; aerr=0;
    case 'AVH19G', qtset=[5]; biasflag=1; offset=0; maxerr=1.0; aerr=0;
    case 'AVMTAG', qtset=[5]; biasflag=1; offset=0; maxerr=1.0; aerr=0;
    case 'AVMTBG', qtset=[5]; biasflag=1; offset=0; maxerr=1.0; aerr=0;
    case 'PATH5D', qtset=[4,5]; biasflag=1; offset=0; maxerr=1.0; aerr=0;
    case 'PATH5N', qtset=[4,5]; biasflag=1; offset=0; maxerr=1.0; aerr=0;
    otherwise, error('bin2bip: no such "sensor".');
  end;

  

  %% region-dependent parameters, table from daily_extract.pro:
  switch region,
    case 'Global',      box=[-180., 180., -90., 90.]; % box=[];
    case 'NCAMERICA',   box=[-165.,  -30., -20., 62.];
    case 'HURRICANE',   box=[-101.,  -44.,  -3.,  35.];
    case 'WESTCOAST',   box=[-141.,  -89.,  14.,  51.];
    case 'EASTCOAST',   box=[-101.,  -39.,  14.,  51.];
    case 'Test',        box=[-140., 350., -30., 50.];
    case 'DXPACIFIC',   box=[120., 290., -20., 20.];
    case 'AMAMIOSHIMA', box=[125.,  132.,  26.,  32.];
    case 'OKINAWA',     box=[120.,  140.,  20.,  35.];
    otherwise, box=[];
  end;
  positivelongitude=0; % see checkDomainBox.pro
    if length(box), if box(2)>180,
      if box(1)<0, box(1)=box(1)+360; end;
      if box(1)>box(2), error('bin2bip: set "box" to [-180,180,...]'); end;
      positivelongitude=1;
    end; end;
      


%% write nml header file:

  if 1,
    filename=sprintf('bin2bip_head.nml');
    if length(box)==0, b=[-180,180,-90,90]; else b=box; end;
    f=fopen(filename,'w');
    fprintf(f,' $input\n');
    fprintf(f,'lonmin=%f\nlonmax=%f\n',b(1),b(2));
    fprintf(f,'latmin=%f\nlatmax=%f\n',b(3),b(4));
    fclose(f);
  end;



%% packing:

  lonbip=[]; latbip=[]; dhrbip=[]; sstbip=[]; rmsbip=[];

  for dt=-dayrange:dayrange,

      d=day+dt; y=year; 

      %% adjust if the date (y,d) is in a different year:
      if d<1,
        y=y-1;
        if mod(y,4)==0&(mod(y,100)~=0|mod(y,400)==0) md=366; else, md=365; end;
        d=d+md;
      else,
        if mod(y,4)==0&(mod(y,100)~=0|mod(y,400)==0) md=366; else, md=365; end;
        if d>md, d=d-md; y=y+1; end;
      end;



%      %% read bin file:
%      binfile=sprintf('%s/%s_%s_%04d_%03d.bin',bindir,binregion,sensor,y,d);
%
%      f=fopen(binfile,'r');
%      if f==-1,
%        fprintf(1,'NOT FOUND: %s\n',binfile);
%        continue;  % move on to the next "for" iteration.
%      end;
%
%      fprintf(1,'reading: %s\n',binfile);
%      [nyear,nday,N]=fortread(f,'integer*4',1,'integer*4',1,'integer*4',1);
%      [lon,lat,sst,bias,rms,hour,qt,sun]=fortread(f,'real*4',N,'real*4',N,...
%        'real*4',N,'real*4',N,'real*4',N,'real*4',N,'integer*4',N,'real*4',N);
%      fclose(f);
%
%      %% time correction (10.9.8):
%      if mean(hour)<100,  % old/standard form (common with RTO):
%        %% add back the common reference time [hours]:
%        hour=hour+(julian(nday,1,nyear,3)-julian(1,1,1981,3))*24;
%      else,  % buggy new form:
%        %% correct for the BUG [hours]:
%        hour=hour+(julian(nday,1,nyear,3)-julian(1,1,1981,3))/3600;
%      end;


      %% read bic file:
      %bicfile=sprintf('%s/%s_%s_%04d_%03d.bic.gz',bindir,binregion,sensor,y,d);
      bicfile=sprintf('%s/%04d/%s_%s_%04d_%03d.bic.gz',...
                      bindir,y,binregion,sensor,y,d);
      fprintf(1,'reading: %s\n',bicfile);

      if ~exist(bicfile,'file'),
        fprintf(1,'NOT FOUND: %s\n',bicfile);
        fprintf(flog,'%s %04d %03d 0 points (no file)\n',sensor,y,d);
        continue;  % move on to the next "for" iteration.
        %error(sprintf(1,'NOT FOUND: %s\n',bicfile));
            % ideally, add code to go fetch the bicfile.
      end;

      eval(sprintf('!zcat %s > gunzipped.bic',bicfile));

      f=fopen('gunzipped.bic','r');
      % Read header record
      rec_len1 = fread(f, 1, 'int32');
      nyear = fread(f, 1, 'int32');
      nday = fread(f, 1, 'int32');
      N = fread(f, 1, 'int32');
      rec_len2 = fread(f, 1, 'int32');
      assert(rec_len1 == rec_len2, 'Fortran record corruption in header');

      % Read scale factors
      rec_len1 = fread(f, 1, 'int32');
      off = fread(f, 1, 'single');
      scale1 = fread(f, 1, 'single');
      scale2 = fread(f, 1, 'single');
      rec_len2 = fread(f, 1, 'int32');
      assert(rec_len1 == rec_len2, 'Fortran record corruption in scales');

      if N==0,
        fclose(f);
        fprintf(1,'NO CONTENT: %s\n',bicfile);
        fprintf(flog,'%s %04d %03d 0 points (no content)\n',sensor,y,d);
        continue;  % move on to the next "for" iteration.
      end;

      % Read data with direct type mapping and scaling (saves ~2-4 GB: int16→double)
      rec_len1 = fread(f, 1, 'int32');
      lon = fread(f, N, 'single=>single');
      lat = fread(f, N, 'single=>single');
      hour = double(fread(f, N, 'int16=>int16')) * scale2;
      sst = double(fread(f, N, 'int16=>int16')) * scale1 + off;
      bias = double(fread(f, N, 'int16=>int16')) * scale1;
      rms = fread(f, N, 'uint8=>double');
      qt = fread(f, N, 'uint8=>double');
      rec_len2 = fread(f, 1, 'int32');
      assert(rec_len1 == rec_len2, 'Fortran record corruption in data');
      fclose(f);

      !rm gunzipped.bic;

      %% estimate the solfac (either zensun4 or zensun3 would work):
      sun=zensun4(nday,hour,lon,lat);
      %sun=cos(zensun3(nday,hour,lon,lat)/180*pi)/...
      %   ( 1-0.01673*cos(2*pi*(nday-2)/365.25) )^2;
          % zensun3 can find "zenith" angle.

      %% add back the common reference time [hours]:
      hour=hour+(julian(nday,1,nyear,3)-julian(1,1,1981,3))*24;




      %% trimming:

        keep=ones(N,1);
%disp(sum(keep));

          %% quality/type flag:
            keep=keep.*ismember(qt,qtset);
%disp(sum(keep));

          %% domain box:
            if length(box),
              keep=keep.*(lon>=box(1)&lon<=box(2)&lat>=box(3)&lat<=box(4));
            end;
%disp(sum(keep));

          %% rms/PGE error:
            keep=keep.*(rms<=maxerr);
%disp(sum(keep));
 
          %% daytime only?:
            if daytimeonly,
              keep=keep.*(sun>=0);
            end;
%disp(sum(keep));

          %% nighttime only?:
            % see "daytime windspeed".

          %% daytime windspeed:
            if mindaywind>0,
              %
              jnx=find(sun>0);  % indexes to be discarded (all daytime points).
              % some sensors are exempt:
              if any(strcmp(sensor,{'AMSREA','AMSR2R','FNMOCs'})), jnx=[]; end;
              %
              %% save daytime data if wind is high enough:
              if mindaywind<1e3, 
                windfile=sprintf('%s/windspeed%04d_%03d.coe',coedir,y,d);
                if exist(windfile)~=2,
                  fprintf(1,'.. No wind file: %s\n',windfile);
                  fprintf(1,'.... all daytime data discarded\n');
                else,
                  %% read wind data (from pre-prepared *.coe file):
                  fprintf(1,'.. Reading wind %s\n',windfile);
                  eval(sprintf('! ln -sf %s cbsdata.out',windfile));
                  f=fopen('cbspoints.dat','w');
                  nx=length(jnx); x=lon(jnx);
                  knx=find(x<0); if length(knx), x=x+360; end;
                  fortwrite(f,'integer*4',[nx,-1,0,0]);
                  fortwrite(f,'real*4',x,'real*4',lat(jnx));
                  fclose(f);
                  % Container: Use fixed path to Fortran executables
                  fortran_bin='/opt/mrva/bin';
                  eval(sprintf('! %s/cbscoeff',fortran_bin)); % execute spline.
                  f=fopen('cbs.out','r');
                  wind=fortread(f,nx);
                  fclose(f);
                  ! rm -f cbspoints.dat cbs.out cbsdata.out
                  %% discard only low-wind points:
                  jnx=jnx( find(wind<mindaywind) );
                end;
              end;
              %
              keep(jnx)=zeros(size(jnx));
            end;
%disp([sum(keep),length(find(sun>0))-length(jnx)]);

        inx=find(keep);
        lon=lon(inx); lat=lat(inx); hour=hour(inx);
        sst=sst(inx); bias=bias(inx); rms=rms(inx);
        fprintf(1,'.. %d points kept.\n',length(inx));

        fprintf(flog,'%s %04d %03d %d points\n',sensor,y,d,length(inx));

      %% bias:

        if biasflag, sst=sst-bias; end;
        sst=sst-offset;

      %% hours from the reference epoch:

        % correct for L2P reference time:
        hourRef=(julian(nday,1,nyear,3)-julian(1,1,1981,3))*24;
        if strcmp(sensor,'FNMOCs'), hourRef=0; end;
        hour=hour-hourRef;
%disp([mean(hour),std(hour),min(hour),max(hour)]);

        dhr=hour+dt*24-hourAna;


      %% collect arrays:
        lonbip=[lonbip;lon(:)];
        latbip=[latbip;lat(:)];
        sstbip=[sstbip;sst(:)];
        dhrbip=[dhrbip;dhr(:)];
        rmsbip=[rmsbip;rms(:)];
  end;



  %% assign a constant RMS error if needed:
    if aerr>0, rmsbip=aerr*ones(size(sstbip)); end;


  %% shift longitude domain if needed:
    if positivelongitude,
      inx=find(lonbip<0);
      if length(inx), lonbip(inx)=lonbip(inx)+360; end;
    end;


  %% subtract the offset (e.g., Kelvin to Celcius conversion):
    sstbip=sstbip-sstOffset;


  %% convert rms to weight:
    wgtbip=1./(rmsbip.^2);

  %% write file 

  %bipfile=sprintf('%s/%s_%s_%04d_%03d.bip',bipdir,region,sensor,year,day);
  bipfile=sprintf('%s/%s_%s_%04d_%03d.biq',bipdir,region,sensor,year,day);
  f=fopen(bipfile,'w');
  ndata=length(sstbip);
  fortwrite(f,'integer*4',ndata);
  %fortwrite(f,lonbip,latbip,dhrbip,sstbip,wgtbip);
  fortwrite(f,lonbip);
  fortwrite(f,latbip);
  fortwrite(f,dhrbip);
  fortwrite(f,sstbip);
  fortwrite(f,wgtbip);
  fclose(f);


end; % for sensor.
%end;
%end;

if flog>1, fclose(flog); end;

%% clean up:
clear lonbip latbip dhrbip sstbip wgtbip;
clear lon lat sst bias rms hour qt sun;
clear keep;
