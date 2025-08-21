function logfilename=makebiq(sensors,year,day,hour,box,bipdir,coedir)
%% 0) sets the sensor-dependent parameter table;
%% 1) reads bin,bic,bii files and their gzipped/bzip2'ed versions;
%% 2) if the desired input file doesn't exist, it will complain and stop;
%% 3) biq file is written
%% NOTE: many output names (e.g., "bipfile") still contains "bip" and "bin".

hourAna=hour;  % analysis time.

if ~exist('coedir','var'), coedir=''; end;

logfilename='makebiq.log';

%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%

%% run control:

%sensors={ % sensor, bindir, binregion:
%'FNMOCs','/nas2/BIN','GLOBAL',
%'AATSRi','/nas2/BIN','NCAMERICA',
%'AMSREA','/nas2/BIN','NCAMERICA',
%'MODISA','/nas2/BIN','NCAMERICA',
%'MODIST','/nas2/BIN','NCAMERICA',
%};

%  year=2009;
%  day=30;
%  hourAna=9;  % UTC. Analysis Time.

%  box = [-180,180,-90,90];

%  bipdir='/tmp/bip';
%  coedir='/nas2/ecmwf/cbs';  % wind *.coe file directory.

%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%

%% parameters:


  excludedaytime=1;  % [1 or 0] set to use only nighttime data.

  mindaywind= -1;  % [m/s] minimum daytime windspeed.
                   % set <=0 to include all daytime data.
                   % set very large (> 1000) to exclude all daytime.
                   % if no wind file is found, all daytime data are excluded.

  sstOffset=273.15;  % reduce the SST magnitude (e.g., from Kelvin to Celcius)

  minRMS=0.1;  % min RMS value (as precaution against data errors).


%%%%%%%%%%%%%%%%%%%%%%%%%%%%%% %%%%%%%%%%%%%%%%%%%%%%%%%%%%%%




%% write input log file:
if 1,
  flog=fopen(logfilename,'w');
else,
  flog=1;
end;

%for year=years,
%for day=yeardays,
for isensor=1:size(sensors,1),
  sensor=sensors{isensor,1};
  indir=sensors{isensor,2}; inregion=sensors{isensor,3};
  dayrange=sensors{isensor,6};



  %% sensor-dependent parameters:
      %% qtset = quality/type flag index set.
      %% biasflag = [1 or 0] set if bias data are subtracted.
      %% offset = [K] constant value to be subtracted; set -273.15 if Celsius.
      %% maxerr = [K for L2P, ProbGrossError for FNMOCs] error threshold.
      %% aerr = [K] assigned RMS error; set to 0 to use the L2P rms values.
      %% irf = [flag] if set (IR sensors), daytime data exclusion is considered.
  switch sensor,

    case 'FNMOCs',
      qtset=[4,5]; biasflag=0; offset=-273.15; maxerr=0.95; aerr=0.2; irf=0;

    case 'IQUAM0',
      qtset=[0:5]; biasflag=0; offset=-273.15; maxerr=0.95; aerr=0.2; irf=0;

    case 'AMSREA',
      qtset=[4]; biasflag=1; offset=0; maxerr=1.0; aerr=0; irf=0;

    case 'AMSR2R',
      qtset=[5]; biasflag=1; offset=0; maxerr=1.0; aerr=0; irf=0;
      % qtset=[4]; biasflag=1; offset=0; maxerr=1.0; aerr=0; irf=0;

    case 'AMSR2J',
      qtset=[4,5]; biasflag=1; offset=0; maxerr=1.0; aerr=0; irf=0;

    case 'WINSAT',
      qtset=[4]; biasflag=1; offset=0; maxerr=1.0; aerr=0; irf=0;

    case 'AATSRi',
      qtset=[4,5]; biasflag=1; offset=-0.17; maxerr=1.0; aerr=0; irf=1;

    case 'MODISA',
      qtset=[5]; biasflag=0; offset=-0.20; maxerr=0.7; aerr=0; irf=1;
      % qtset=[5]; biasflag=0; offset=-0.14; maxerr=99; aerr=0; irf=1;

    case 'MODIST',
      qtset=[5]; biasflag=0; offset=-0.20; maxerr=0.7; aerr=0; irf=1;
      % qtset=[5]; biasflag=0; offset=-0.14; maxerr=99; aerr=0; irf=1;

    case 'VIIRSN',
      qtset=[5]; biasflag=0; offset=0; maxerr=1.0; aerr=0; irf=1;

    case 'VIIRSO',
      qtset=[5]; biasflag=0; offset=0; maxerr=1.0; aerr=0; irf=1;

    case 'RAN17G',
      qtset=[5]; biasflag=1; offset=0; maxerr=1.0; aerr=0; irf=1;

    case 'AVH18G',
      qtset=[5]; biasflag=1; offset=0; maxerr=1.0; aerr=0; irf=1;

    case 'AVH18L',
      qtset=[5]; biasflag=1; offset=0; maxerr=1.0; aerr=0; irf=1;

    case 'AVH19G',
      qtset=[5]; biasflag=1; offset=0; maxerr=1.0; aerr=0; irf=1;

    case 'AVMTAG',
      qtset=[5]; biasflag=1; offset=0; maxerr=1.0; aerr=0; irf=1;

    case 'AVMTBG',
      qtset=[5]; biasflag=1; offset=0; maxerr=1.0; aerr=0; irf=1;

    case 'PATH5D',
      qtset=[4,5]; biasflag=1; offset=0; maxerr=1.0; aerr=0; irf=1;

    case 'PATH5N',
      qtset=[4,5]; biasflag=1; offset=0; maxerr=1.0; aerr=0; irf=1;

    otherwise, error('makebiq: no such "sensor".');
  end;

  



%% packing:

  lonbip=[]; latbip=[]; dhrbip=[]; sstbip=[]; rmsbip=[];

  for dt=-dayrange:dayrange,
%  for dt=-dayrange:0,  % (13.10.17, for testing NRT; remove for operations)

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

      %% find the source bic/bin/bii file for the day (y,d):
      infile=sprintf('%s/%04d/%s_%s_%04d_%03d.b*',indir,y,inregion,sensor,y,d);
      dirlist=dir(infile);
      if length(dirlist)<1,
        fprintf(1,'NOT FOUND: %s\n',infile);
        fprintf(flog,'%s %04d %03d 0 points (no file)\n',sensor,y,d);
        continue;  % move on to the next "for" iteration.
      end;
      if length(dirlist)>1,
        fprintf(1,'Using ONLY ONE of MULTIPLE FOUND: %s\n',infile);
      end;

      %% find file type and uncompress/link source file:
      infile=sprintf('%s/%04d/%s',indir,y,dirlist(1).name);
      [head,body,tail]=fileparts(dirlist(1).name);
      switch tail
        case '.gz',
          eval(sprintf('!zcat %s > makebiqinput.tmp',infile));
          [head,body,tail]=fileparts(body);
        case '.bz2',
          eval(sprintf('!bzcat %s > makebiqinput.tmp',infile));
          [head,body,tail]=fileparts(body);
        otherwise,
          eval(sprintf('!ln -sf %s makebiqinput.tmp',infile));
      end;
      filetype=tail;
      filename=sprintf('%s/%s',indir,body);
          
      %% read file according to the filetype:
      switch filetype,


        case '.bin',
          fprintf(1,'reading: %s\n',filename);
          f=fopen('makebiqinput.tmp','r');
          if f==-1,
            fprintf(1,'FAILED TO OPEN: %s\n',filename);
            fprintf(flog,'%s %04d %03d 0 points (no file)\n',sensor,y,d);
            continue;  % move on to the next "for" iteration.
          end;
         [nyear,nday,N]=fortread(f,'integer*4',1,'integer*4',1,'integer*4',1);
         [lon,lat,sst,bias,rms,hour,qt,sun]=fortread(f,'real*4',N,'real*4',N,...
         'real*4',N,'real*4',N,'real*4',N,'real*4',N,'integer*4',N,'real*4',N);
          fclose(f);

          %% add back the common reference time [hours]:
          if mean(hour)<100,  % old/standard form (common with RTO):
            hour=hour+(julian(nday,1,nyear,3)-julian(1,1,1981,3))*24;
          else,  % buggy new form (BUG correction in some format):
            hour=hour+(julian(nday,1,nyear,3)-julian(1,1,1981,3))/3600;
          end;


        case '.bic',
          fprintf(1,'reading: %s\n',filename);
          f=fopen('makebiqinput.tmp','r');
          if f==-1,
            fprintf(1,'FAILED TO OPEN: %s\n',filename);
            fprintf(flog,'%s %04d %03d 0 points (no file)\n',sensor,y,d);
            continue;  % move on to the next "for" iteration.
          end;
          [nyear,nday,N]=fortread(f,'integer*4',1,'integer*4',1,'integer*4',1);
          [off,scale1,scale2]=fortread(f,'real*4',1,'real*4',1,'real*4',1);
          [lon,lat,hour,sst,bias,rms,qt]=fortread(f,'real*4',N,'real*4',N,...
            'integer*2',N,'integer*2',N,'integer*2',N,'uint8',N,...
            'uint8',N);
          fclose(f);

          %% format conversion:
          sst=double(sst)*scale1+off;
          bias=double(bias)*scale1; rms=double(rms)*scale1;
          hour=double(hour)*scale2;
          qt=double(qt);

          %% estimate the solfac (either zensun4 or zensun3 would work):
          sun=zensun4(nday,hour,lon,lat);
          %sun=cos(zensun3(nday,hour,lon,lat)/180*pi)/...
          %   ( 1-0.01673*cos(2*pi*(nday-2)/365.25) )^2;
              % zensun3 can find "zenith" angle.
          if ismember(sensor,{'FNMOCs','IQUAM0'}), sun=-ones(size(sst)); end;

          %% add back the common reference time [hours]:
          hour=hour+(julian(nday,1,nyear,3)-julian(1,1,1981,3))*24;



        case '.bii', 
          fprintf(1,'reading: %s\n',filename);
          f=fopen('makebiqinput.tmp','r');
          if f==-1,
            fprintf(1,'FAILED TO OPEN: %s\n',filename);
            fprintf(flog,'%s %04d %03d 0 points (no file)\n',sensor,y,d);
            continue;  % move on to the next "for" iteration.
          end;
          [N,nyear,nday]=fortread(f,'int32',1,'int16',1,'int16',1);
          [sst,lon,lat,hour,qt]=fortread(f,'int16',N,...
              'int16',N,'int16',N,'int16',N,'int8',N);
          fclose(f);

          %% format conversion:
          sst=single(sst)/100; lon=single(lon)/100; lat=single(lat)/100;
          hour=single(hour)/100; 
          rms=ones(size(sst))*aerr;
          qt=single(qt);
          bias=zeros(size(sst));
          sun= -ones(size(sst));  % always night time for in-situ data.

          %% add back the common reference time [hours]:
          hour=hour+(julian(nday,1,nyear,3)-julian(1,1,1981,3))*24;


        otherwise,
            error(['makebiq cannot read the filetype ',filetype])

      end;  % switch filetype.

      !rm makebiqinput.tmp;
      if N==0,
        fprintf(1,'NO CONTENT: %s\n',filename);
        fprintf(flog,'%s %04d %03d 0 points (no content)\n',sensor,y,d);
        continue;  % move on to the next "for" iteration.
      end;




      %% trimming:

        keep=ones(N,1);

          %% quality/type flag:
            keep=keep.*ismember(qt,qtset);

          %% domain box:
            if length(box),
              keep=keep.*(lon>=box(1)&lon<=box(2)&lat>=box(3)&lat<=box(4));
            end;

          %% rms/PGE error:
            keep=keep.*(rms<=maxerr);
 
          %% daytime data?:
            if excludedaytime & irf,

              keep=keep.*(sun<=0);  % keep only nighttime data.

            else,  % include both daytime & nighttime data, unless .....

              if mindaywind>0 & irf,  % exclude daytime data in low-wind areas:
                jnx=find(sun>0); % indexes to be discarded (all daytime points).
              
                %% save daytime data if wind is high enough:
                windfile=sprintf('%s/windspeed%04d_%03d.coe',coedir,y,d);
                if exist(windfile)~=2 | mindaywind>999,
                  fprintf(1,'.. No wind file: %s\n',windfile);
                  fprintf(1,'.. or large min wind speed %f\n',mindaywind);
                  fprintf(1,'.... ALL DAYTIME DATA DISCARDED\n');
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
                  hdir=getenv('HOME');
                  eval(sprintf('! %s/bin/cbscoeff',hdir)); % execute spline.
                  f=fopen('cbs.out','r');
                  wind=fortread(f,nx);
                  fclose(f);
                  ! rm -f cbspoints.dat cbs.out cbsdata.out
                  %% discard only low-wind points:
                  jnx=jnx( find(wind<mindaywind) );
                end;

                keep(jnx)=zeros(size(jnx));
              end;

            end;

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
        %hourRef=(julian(nday,1,nyear,3)-julian(1,1,1981,3))*24;  % BUG.
        hourRef=(julian(day,1,year,3)-julian(1,1,1981,3))*24;

        dhr=hour-hourRef-hourAna;

        if ismember(sensor,{'FNMOCs','IQUAM0'}), dhr=zeros(size(sst)); end;

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
    if box(2)>180,
      inx=find(lonbip>=-180&lonbip<=(box(2)-360));
      if length(inx), lonbip(inx)=lonbip(inx)-360; end;
    end;
    if box(1)<-180,
      inx=find(lonbip>=(box(1)+360)&lonbip<=180);
      if length(inx), lonbip(inx)=lonbip(inx)+360; end;
    end;


  %% subtract the offset (e.g., Kelvin to Celcius conversion):
    sstbip=sstbip-sstOffset;


  %% convert rms to weight:
    rnx=find(rmsbip<minRMS); if length(rnx), rmsbip(rnx)=minRMS; end;
    wgtbip=1./(rmsbip.^2);

  %% write file 

  %bipfile=sprintf('%s/%s_%s_%04d_%03d.bip',bipdir,region,sensor,year,day);
  bipfile=sprintf('%s/%s_%s_%04d_%03d.biq',bipdir,inregion,sensor,year,day);
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
