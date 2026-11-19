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

  % Preallocate arrays for better performance (trim at end).
  %
  % This used to be a flat 200M points for every sensor -- a MODIS worst case
  % of ~30M/day x 5 days, paid in full by all six. At 5 double arrays that is
  % 7.45 GiB allocated before a single point is read, whether the sensor is
  % MODISA or IQUAM0, which in the 2026-266 run contributed 212,612 points --
  % 0.1% of the allocation. DPS job 2026-09-24T16:51 was OOM-killed (exit 137)
  % part way through MODISA on a 16 GB worker with that 7.45 GiB standing.
  %
  % Sizing from the input files is safe in a way that restructuring this loop
  % is not: the arrays are trimmed to idx below regardless, so the data handed
  % downstream is bit-identical for any max_size >= the true point count, and
  % the doubling branch in the read loop already covers an underestimate. An
  % estimate that is wrong costs one reallocation, never a wrong answer.
  max_size = estimate_max_points(indir, inregion, sensor, year, day, dayrange);

  % NOTE: Must use double precision to match production behavior
  % Single precision causes weight calculation errors (1/rms^2 overflow)
  lonbip = NaN(max_size, 1);  % double (default)
  latbip = NaN(max_size, 1);  % double (default)
  dhrbip = NaN(max_size, 1);  % double (default)
  sstbip = NaN(max_size, 1);  % double (default)
  rmsbip = NaN(max_size, 1);  % double (default) - CRITICAL for weight calc
  idx = 0;  % Current index for filling arrays

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
          % Use fortread to handle Fortran record markers correctly
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

          % Read header with explicit Fortran record markers
          % Fortran record format: [record_length] [data...] [record_length]
          % NOTE: Must return double to match fortread behavior exactly
          rec_len1 = fread(f, 1, 'uint32');  % Record length marker (should be 12 for 3*int32)
          nyear = fread(f, 1, 'int32');      % Returns double (matches fortread 'integer*4')
          nday = fread(f, 1, 'int32');       % Returns double (matches fortread 'integer*4')
          N = fread(f, 1, 'int32');          % Returns double (matches fortread 'integer*4')
          rec_len2 = fread(f, 1, 'uint32');  % Trailing record length marker

          % Validate record markers (matches fortread behavior)
          expected_len1 = 12;  % 3 x int32 = 12 bytes
          if rec_len1 ~= expected_len1 || rec_len2 ~= expected_len1
            error('BIC header record mismatch in %s: expected %d, got leading=%d trailing=%d', ...
                  filename, expected_len1, rec_len1, rec_len2);
          end

          % Debug: check if nday is valid
          if nday < 1 || nday > 366
            fprintf(1,'WARNING: Invalid nday=%d in file %s (nyear=%d, N=%d)\n', nday, filename, nyear, N);
            fprintf(1,'  This will cause zensun4 to fail. Skipping this file.\n');
            fprintf(flog,'%s %04d %03d 0 points (invalid nday=%d)\n',sensor,y,d,nday);
            fclose(f);
            continue;
          end

          % Read scaling parameters with Fortran record markers
          % NOTE: Must return double to match fortread behavior exactly
          rec_len1 = fread(f, 1, 'uint32');  % Record length marker (should be 12 for 3*float32)
          off = fread(f, 1, 'float32');      % Returns double (matches fortread)
          scale1 = fread(f, 1, 'float32');   % Returns double (matches fortread)
          scale2 = fread(f, 1, 'float32');   % Returns double (matches fortread)
          rec_len2 = fread(f, 1, 'uint32');  % Trailing record length marker

          % Validate scaling record markers
          expected_len2 = 12;  % 3 x float32 = 12 bytes
          if rec_len1 ~= expected_len2 || rec_len2 ~= expected_len2
            error('BIC scaling record mismatch in %s: expected %d, got leading=%d trailing=%d', ...
                  filename, expected_len2, rec_len1, rec_len2);
          end

          % Read data arrays with Fortran record markers
          % NOTE: Must return double to match fortread behavior exactly
          % (fortread converts all types to float64/double)
          rec_len1 = fread(f, 1, 'uint32');  % Record length marker
          lon = fread(f, N, 'float32');      % Returns double (matches fortread 'real*4')
          lat = fread(f, N, 'float32');      % Returns double (matches fortread 'real*4')
          hour = fread(f, N, 'int16');       % Returns double (matches fortread 'integer*2')
          sst = fread(f, N, 'int16');        % Returns double (matches fortread 'integer*2')
          bias = fread(f, N, 'int16');       % Returns double (matches fortread 'integer*2')
          rms = fread(f, N, 'uint8');        % Returns double (matches fortread 'uint8')
          qt = fread(f, N, 'uint8');         % Returns double (matches fortread 'uint8')
          rec_len2 = fread(f, 1, 'uint32');  % Trailing record length marker
          fclose(f);

          % Validate data record markers
          % lon(4*N) + lat(4*N) + hour(2*N) + sst(2*N) + bias(2*N) + rms(N) + qt(N) = 16*N bytes
          expected_len3 = 16 * double(N);
          if rec_len1 ~= expected_len3 || rec_len2 ~= expected_len3
            error('BIC data record mismatch in %s: expected %d, got leading=%d trailing=%d (N=%d)', ...
                  filename, expected_len3, rec_len1, rec_len2, N);
          end

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
          hour=hour+double((julian(double(nday),1,double(nyear),3)-julian(1,1,1981,3)))*24;



        case '.bii',
          fprintf(1,'reading: %s\n',filename);
          f=fopen('makebiqinput.tmp','r');
          if f==-1,
            fprintf(1,'FAILED TO OPEN: %s\n',filename);
            fprintf(flog,'%s %04d %03d 0 points (no file)\n',sensor,y,d);
            continue;  % move on to the next "for" iteration.
          end;
          % Read header record with Fortran record markers
          % Record structure: [4-byte marker] [N:int32] [nyear:int16] [nday:int16] [4-byte marker]
          % NOTE: Must return double to match fortread behavior exactly
          rec_len1 = fread(f, 1, 'uint32');  % Leading record marker (should be 8)
          N = fread(f, 1, 'int32');          % Returns double (matches fortread 'int32')
          nyear = fread(f, 1, 'int16');      % Returns double (matches fortread 'int16')
          nday = fread(f, 1, 'int16');       % Returns double (matches fortread 'int16')
          rec_len2 = fread(f, 1, 'uint32');  % Trailing record marker

          % Validate header record markers
          expected_len1 = 8;  % int32 + int16 + int16 = 8 bytes
          if rec_len1 ~= expected_len1 || rec_len2 ~= expected_len1
            error('BII header record mismatch in %s: expected %d, got leading=%d trailing=%d', ...
                  filename, expected_len1, rec_len1, rec_len2);
          end

          % Read data record with Fortran record markers
          % Record structure: [4-byte marker] [sst] [lon] [lat] [hour] [qt] [4-byte marker]
          % NOTE: Must return double to match fortread behavior exactly
          rec_len1 = fread(f, 1, 'uint32');  % Leading record marker
          sst = fread(f, N, 'int16');        % Returns double (matches fortread 'int16')
          lon = fread(f, N, 'int16');        % Returns double (matches fortread 'int16')
          lat = fread(f, N, 'int16');        % Returns double (matches fortread 'int16')
          hour = fread(f, N, 'int16');       % Returns double (matches fortread 'int16')
          qt = fread(f, N, 'int8');          % Returns double (matches fortread 'int8')
          rec_len2 = fread(f, 1, 'uint32');  % Trailing record marker
          fclose(f);

          % Validate data record markers
          % sst(2*N) + lon(2*N) + lat(2*N) + hour(2*N) + qt(N) = 9*N bytes
          expected_len2 = 9 * double(N);
          if rec_len1 ~= expected_len2 || rec_len2 ~= expected_len2
            error('BII data record mismatch in %s: expected %d, got leading=%d trailing=%d (N=%d)', ...
                  filename, expected_len2, rec_len1, rec_len2, N);
          end

          %% format conversion:
          sst=single(sst)/100; lon=single(lon)/100; lat=single(lat)/100;
          hour=single(hour)/100; 
          rms=ones(size(sst))*aerr;
          qt=single(qt);
          bias=zeros(size(sst));
          sun= -ones(size(sst));  % always night time for in-situ data.

          %% add back the common reference time [hours]:
          hour=hour+double((julian(double(nday),1,double(nyear),3)-julian(1,1,1981,3)))*24;


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
                  % Container: Use fixed path to Fortran executables
                  fortran_bin='/opt/mrva/bin';
                  eval(sprintf('! %s/cbscoeff',fortran_bin)); % execute spline.
                  f=fopen('cbs.out','r');
                  fread(f, 1, 'uint32');           % Skip Fortran record marker (start)
                  wind = fread(f, nx, 'float32');  % Returns double for consistency
                  fread(f, 1, 'uint32');           % Skip Fortran record marker (end)
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
        n = length(lon);
        if idx + n > max_size
            % Expand memory if needed (should be rare with 200M preallocated)
            warning('Exceeded 200M estimate, doubling allocation...');
            new_size = max_size * 2;
            lonbip = [lonbip; NaN(new_size - max_size, 1)];  % double
            latbip = [latbip; NaN(new_size - max_size, 1)];  % double
            dhrbip = [dhrbip; NaN(new_size - max_size, 1)];  % double
            sstbip = [sstbip; NaN(new_size - max_size, 1)];  % double
            rmsbip = [rmsbip; NaN(new_size - max_size, 1)];  % double
            max_size = new_size;
        end

        lonbip(idx+1:idx+n) = lon(:);
        latbip(idx+1:idx+n) = lat(:);
        sstbip(idx+1:idx+n) = sst(:);
        dhrbip(idx+1:idx+n) = dhr(:);
        rmsbip(idx+1:idx+n) = rms(:);
        idx = idx + n;
  end;

  %% Trim arrays to actual size
  lonbip = lonbip(1:idx);
  latbip = latbip(1:idx);
  dhrbip = dhrbip(1:idx);
  sstbip = sstbip(1:idx);
  rmsbip = rmsbip(1:idx);

  %% Validate no NaN values leaked through
  if any(isnan(lonbip)) || any(isnan(latbip)) || any(isnan(sstbip)) || any(isnan(rmsbip))
      error(['NaN detected in BIQ data arrays after trimming!', newline, ...
             'This indicates a bug in data processing or file reading.', newline, ...
             'Sensor: %s, Year: %d, Day: %d', newline, ...
             'NaN counts: lon=%d, lat=%d, sst=%d, rms=%d'], ...
             sensor, year, day, ...
             sum(isnan(lonbip)), sum(isnan(latbip)), ...
             sum(isnan(sstbip)), sum(isnan(rmsbip)));
  end

  %% assign a constant RMS error if needed:
    if aerr>0, rmsbip=aerr*ones(size(sstbip)); end;


  %% shift longitude domain if needed:
    if box(2)>180,
      % Vectorized longitude wrapping (west)
      wrap_west = lonbip >= -180 & lonbip <= (box(2) - 360);
      lonbip(wrap_west) = lonbip(wrap_west) - 360;
    end;
    if box(1)<-180,
      % Vectorized longitude wrapping (east)
      wrap_east = lonbip >= (box(1) + 360) & lonbip <= 180;
      lonbip(wrap_east) = lonbip(wrap_east) + 360;
    end;


  %% subtract the offset (e.g., Kelvin to Celcius conversion):
    sstbip=sstbip-sstOffset;


  %% convert rms to weight:
    % Vectorized RMS minimum clamping
    rmsbip(rmsbip < minRMS) = minRMS;
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


function n = estimate_max_points(indir, inregion, sensor, year, day, dayrange)
% Upper bound on the points a sensor's window can contribute, from file sizes.
%
% Read-only, and deliberately generous. Its only job is to stop every sensor
% paying MODIS's worst case; being wrong costs one reallocation in the read
% loop, never a wrong result, because the arrays are trimmed to the true count
% before anything downstream sees them.
%
% Bytes per point, from the record-length assertions in the read branches
% below -- the same constants those branches use to validate rec_len:
%
%   .bin   32   lon,lat,sst,bias,rms,hour,qt,sun all 4-byte
%   .bic   16   lon(4) lat(4) hour(2) sst(2) bias(2) rms(1) qt(1)
%   .bii    9   sst(2) lon(2) lat(2) hour(2) qt(1)
%
% A compressed file's directory entry gives the COMPRESSED size, so a factor
% is applied rather than trusting it. Expected ratio for a .bic record, by
% field: lon/lat are float32 with near-random mantissas (~1.1x), hour/sst/bias
% are correlated int16 (~2x), rms/qt are repetitive uint8 (~5x) -- weighted,
% 16 bytes compress to about 10.7, so ~1.5x. GZIP_FACTOR is set to double that
% so the estimate stays an over-estimate without inflating MODIS back into the
% ceiling, which would waste the whole exercise on the one sensor that needs
% the help most.
  BYTES_PER_POINT = 16;   % assume .bic unless the name says otherwise
  GZIP_FACTOR     = 3;    % ~2x the ~1.5x this data actually achieves
  SAFETY          = 1.30; % headroom for mixed formats and header/marker bytes
  FLOOR_POINTS    = 1000000;      %  1M  -> 40 MB of arrays; cheap
  CEIL_POINTS     = 200000000;    % the historical flat value, never exceeded

  total = 0;
  for dt = -dayrange:dayrange
      % The year-rollover arithmetic is duplicated from the read loop rather
      % than factored out of it. Touching the loop that decides WHICH files
      % are read is the risk this whole change exists to avoid; a divergence
      % here only mis-sizes an allocation the doubling branch will fix.
      d = day + dt; y = year;
      if mod(y,4)==0 & (mod(y,100)~=0 | mod(y,400)==0), md = 366; else, md = 365; end;
      if d < 1
          y = y - 1;
          if mod(y,4)==0 & (mod(y,100)~=0 | mod(y,400)==0), md = 366; else, md = 365; end;
          d = d + md;
      elseif d > md
          d = d - md; y = y + 1;
      end

      dirlist = dir(sprintf('%s/%04d/%s_%s_%04d_%03d.b*', ...
                            indir, y, inregion, sensor, y, d));
      if isempty(dirlist), continue; end;

      bytes = double(dirlist(1).bytes);
      name  = dirlist(1).name;
      [~, body, tail] = fileparts(name);
      if strcmp(tail, '.gz') || strcmp(tail, '.bz2')
          bytes = bytes * GZIP_FACTOR;
          [~, ~, tail] = fileparts(body);
      end

      switch tail
        case '.bin', bpp = 32;
        case '.bii', bpp = 9;
        otherwise,   bpp = BYTES_PER_POINT;
      end
      total = total + bytes / bpp;
  end

  n = min(CEIL_POINTS, max(FLOOR_POINTS, ceil(total * SAFETY)));
  fprintf(1, '  %s: sizing BIQ arrays for %d points (%.2f GiB)\n', ...
          sensor, n, n * 8 * 5 / 2^30);
