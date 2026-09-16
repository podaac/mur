% bii2biq.m

%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%

%% expected inputs:

if 0,

  refdata={
  'IQUAM0','/nas2/iquam','Global',0,7, 3,
  };

  year=2010;
  day=200;
  hourAna=9;  % UTC. Analysis Time.

  dayrange=2;  % [day] window size will be "dayrange*2+1".
               % assumed to be < 365.

  region='Global';  % analysis region.

  bipdir='/tmp';

end;




%%%%%%%%%%%%%%%%%%%%%%%%%%%%%% %%%%%%%%%%%%%%%%%%%%%%%%%%%%%%


for isensor=1:size(refdata,1),
  sensor=refdata{isensor,1};
  biidir=refdata{isensor,2};
  region=refdata{isensor,3};
  dayrange=refdata{isensor,6};





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


      %% read bii file:
      biifile=sprintf('%s/%04d/%s_%s_%04d_%03d.bii',...
                      biidir,y,region,sensor,y,d);
      fprintf(1,'reading: %s\n',biifile);

      if ~exist(biifile,'file'),
        fprintf(1,'NOT FOUND: %s\n',biifile);
        fprintf(flog,'%s %04d %03d 0 points (no file)\n',sensor,y,d);
        continue;  % move on to the next "for" iteration.
        %error(sprintf(1,'NOT FOUND: %s\n',biifile));
            % ideally, add code to go fetch the biifile.
      end;

      f=fopen(biifile,'r');

      % Read Fortran record header (byte count)
      m = fread(f, 1, 'uint32');

      % Read header: N (int32), nyear (int16), nday (int16)
      N = fread(f, 1, 'int32');
      nyear = fread(f, 1, 'int16');
      nday = fread(f, 1, 'int16');

      % Read Fortran record trailer and verify
      n = fread(f, 1, 'uint32');
      if m ~= n
          error('refbii2biq: Fortran record size mismatch in header');
      end

      % Read Fortran record header for data arrays
      m = fread(f, 1, 'uint32');

      % Read data arrays directly as single precision with scaling
      % Using int16=>single to read as int16 and output as single in one step
      sst = fread(f, N, 'int16=>single') / 100;  % Celsius
      lon = fread(f, N, 'int16=>single') / 100;  % Degrees
      lat = fread(f, N, 'int16=>single') / 100;  % Degrees
      hour = fread(f, N, 'int16=>single') / 100;  % Hours
      pt = fread(f, N, 'int8=>int8');  % Platform type (keep as int8)

      % Read Fortran record trailer and verify
      n = fread(f, 1, 'uint32');
      if m ~= n
          error('refbii2biq: Fortran record size mismatch in data arrays');
      end

      fclose(f);

      dhr=hour+dt*24-hourAna;

      rms=ones(size(pt),'single')*0.5;
%      inx=find(pt==5);  % ship:
%        if length(inx), rms(inx)=ones(size(inx),'single')*2.0; end; 
%      inx=find(ismember(pt,[6,7,12,17]));  % buoys, XBT, CTD:
%        if length(inx), rms(inx)=ones(size(inx),'single')*0.5; end; 


      %% collect arrays:
        lonbip=[lonbip;lon(:)];
        latbip=[latbip;lat(:)];
        sstbip=[sstbip;sst(:)];
        dhrbip=[dhrbip;dhr(:)];
        rmsbip=[rmsbip;rms(:)];
  end;


  %% convert rms to weight:
    wgtbip=1./(rmsbip.^2);


  %% write biq file:

  bipfile=sprintf('%s/%s_%s_%04d_%03d.biq',bipdir,region,sensor,year,day);
  f=fopen(bipfile,'w');
  ndata=length(sstbip);
  fortwrite(f,'integer*4',ndata);
  %fortwrite(f,lonbip,latbip,dhrbip,sstbip,wgtbip);  % THIS IS *.bip FILE.
  fortwrite(f,lonbip);
  fortwrite(f,latbip);
  fortwrite(f,dhrbip);
  fortwrite(f,sstbip);
  fortwrite(f,wgtbip);
  fclose(f);

end;
