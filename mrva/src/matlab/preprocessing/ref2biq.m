%% ref2biq.m

%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%

%% expected inputs:

% refdata={
%'FNMOCs','/nas2/fnmoc','GLOBAL',0,7, 3,
%};

%  years=2009;
%  yeardays=30;




%%%%%%%%%%%%%%%%%%%%%%%%%%%%%% %%%%%%%%%%%%%%%%%%%%%%%%%%%%%%

%for year=years,
%for day=yeardays,
for isensor=1:size(refdata,1),
  sensor=refdata{isensor,1};
  bindir=refdata{isensor,2};
  binregion=refdata{isensor,3};
  dayrange=refdata{isensor,6};



  %% sensor-dependent parameters:
      %% qtset = quality/type flag index set.
      %% biasflag = [1 or 0] set if bias data are subtracted.
      %% offset = [K] constant value to be subtracted.
      %% maxerr = [K for L2P, ProbGrossError for FNMOCs] error threshold.
      %% aerr = [K] assigned RMS error; set to 0 to use the L2P rms values.
      filetype='bic';
  switch sensor,
    case 'FNMOCs', qtset=[3,4,5,21,22,23]; 
                           biasflag=0; offset=-273.15; maxerr=0.95; aerr=0.2;
                              filetype='bin';
    case 'IQUAM0', qtset=[0:5];
                           biasflag=0; offset=-273.15; maxerr=0.95; aerr=0.2;
                              filetype='bii';
    case 'AMSREA', qtset=[4]; biasflag=1; offset=0; maxerr=99; aerr=0;
%    case 'AMSR2R', qtset=[4]; biasflag=1; offset=0; maxerr=99; aerr=0;
    case 'AMSR2R', qtset=[5]; biasflag=1; offset=0; maxerr=99; aerr=0;
    case 'AMSR2J', qtset=[4,5]; biasflag=1; offset=0; maxerr=99; aerr=0;
    case 'AATSRi', qtset=[4,5]; biasflag=1; offset=-0.17; maxerr=99; aerr=0;
%    case 'MODISA', qtset=[5]; biasflag=0; offset=-0.14; maxerr=99; aerr=0;
%    case 'MODIST', qtset=[5]; biasflag=0; offset=-0.14; maxerr=99; aerr=0;
    case 'MODISA', qtset=[5]; biasflag=0; offset=-0.20; maxerr=99; aerr=0;
    case 'MODIST', qtset=[5]; biasflag=0; offset=-0.20; maxerr=99; aerr=0;
    case 'AVH18G', qtset=[5]; biasflag=1; offset=0; maxerr=99; aerr=0;
    case 'AVH18L', qtset=[5]; biasflag=1; offset=0; maxerr=99; aerr=0;
    otherwise, error('bin2bip: no such "sensor".');
  end;

  

  box=[-180., 180., -90., 90.]; % box=[];
  positivelongitude=0; % see checkDomainBox.pro
    if length(box), if box(2)>180,
      if box(1)<0, box(1)=box(1)+360; end;
      if box(1)>box(2), error('bin2bip: set "box" to [-180,180,...]'); end;
      positivelongitude=1;
    end; end;
      



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

      switch filetype,

        case 'bin', %% read bin file:
        binfile=sprintf('%s/%04d/%s_%s_%04d_%03d.bin', ...
                       bindir,y,binregion,sensor,y,d);

        f=fopen(binfile,'r');
        if f==-1,
          fprintf(1,'NOT FOUND: %s\n',binfile);
          continue;  % move on to the next "for" iteration.
        end;

        fprintf(1,'reading: %s\n',binfile);
        [nyear,nday,N]=fortread(f,'integer*4',1,'integer*4',1,'integer*4',1);
        [lon,lat,sst,bias,rms,hour,qt,sun]=fortread(f,'real*4',N,'real*4',N,...
        'real*4',N,'real*4',N,'real*4',N,'real*4',N,'integer*4',N,'real*4',N);
        fclose(f);


        case 'bii',  %% read bii file:
        binfile=sprintf('%s/%04d/%s_%s_%04d_%03d.bii', ...
                       bindir,y,binregion,sensor,y,d);

        f=fopen(binfile,'r');
        if f==-1,
          fprintf(1,'NOT FOUND: %s\n',binfile);
          continue;  % move on to the next "for" iteration.
        end;

        fprintf(1,'reading: %s\n',binfile);
        % Read header record with direct type mapping
        rec_len1 = fread(f, 1, 'int32');
        N = fread(f, 1, 'int32');
        nyear = fread(f, 1, 'int16');
        nday = fread(f, 1, 'int16');
        rec_len2 = fread(f, 1, 'int32');
        assert(rec_len1 == rec_len2, 'Fortran record corruption in header');

        % Read data with direct type mapping and scaling (saves memory: int16→double→single)
        rec_len1 = fread(f, 1, 'int32');
        sst = single(fread(f, N, 'int16=>int16')) / 100;
        lon = single(fread(f, N, 'int16=>int16')) / 100;
        lat = single(fread(f, N, 'int16=>int16')) / 100;
        hour = single(fread(f, N, 'int16=>int16')) / 100;
        qt = fread(f, N, 'int8=>int8');
        rec_len2 = fread(f, 1, 'int32');
        assert(rec_len1 == rec_len2, 'Fortran record corruption in data');
        fclose(f);
        rms=ones(size(sst))*aerr;

        otherwise,
            error(['ref2biq cannot read the filetype ',filetype])
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
 


        inx=find(keep);
        sst=sst(inx); lon=lon(inx); lat=lat(inx); hour=hour(inx);
        fprintf(1,'.. %d points kept.\n',length(inx));

      %% bias:

        sst=sst-offset;

      %% hours from the reference epoch:

        % correct for L2P reference time:

        dhr=zeros(size(hour));


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

%% clean up:
clear lonbip latbip dhrbip sstbip wgtbip;
clear lon lat sst bias rms hour qt sun;
clear keep;
