% bii2biq.m

%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%

%% parameters:

if 0,  % stand alone mode:

  year=1988;
  day=360;
  dayrange=7;

  biidir='/data/icoads';
  sensor='ICOADS';
  hourAna=9;  % UTC. Analysis Time.
  region='Global';  % analysis region.

  bipdir='/tmp';

else,  % work like bic2biq:

  isensor=find( strcmp(sensors(:,1),'ICOADS') );

    sensor=sensors{isensor,1};

    biidir=sensors{isensor,2}; 
    region=sensors{isensor,3};
    dayrange=sensors{isensor,6};

end;


%% write input log file:
  if 1,
    flog=fopen('bii2biq.input.log','w');
  else,
    flog=1;
  end;

%% write nml header file:

  filename=sprintf('bin2bip_head.nml');
  if ~exist(filename,'file'),
    b=[-180,180,-90,90];
    f=fopen(filename,'w');
    fprintf(f,' $input\n');
    fprintf(f,'lonmin=%f\nlonmax=%f\n',b(1),b(2));
    fprintf(f,'latmin=%f\nlatmax=%f\n',b(3),b(4));
    fclose(f);
  end;


%%%%%%%%%%%%%%%%%%%%%%%%%%%%%% %%%%%%%%%%%%%%%%%%%%%%%%%%%%%%




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
      biifile=sprintf('%s/%04d/%s_%04d_%03d.bii',...
                      biidir,y,lower(sensor),y,d);
      fprintf(1,'reading: %s\n',biifile);

      if ~exist(biifile,'file'),
        fprintf(1,'NOT FOUND: %s\n',biifile);
        fprintf(flog,'%s %04d %03d 0 points (no file)\n',sensor,y,d);
        continue;  % move on to the next "for" iteration.
        %error(sprintf(1,'NOT FOUND: %s\n',biifile));
            % ideally, add code to go fetch the biifile.
      end;

      f=fopen(biifile,'r');
      % Read header record with direct type mapping
      rec_len1 = fread(f, 1, 'int32');
      N = fread(f, 1, 'int16');
      nyear = fread(f, 1, 'int16');
      nday = fread(f, 1, 'int16');
      rec_len2 = fread(f, 1, 'int32');
      assert(rec_len1 == rec_len2, 'Fortran record corruption in header');

      % Read data with direct type mapping and scaling (saves memory: int16→double→single)
      rec_len1 = fread(f, 1, 'int32');
      sst = single(fread(f, N, 'int16=>int16')) / 10;  % Celcius
      lon = single(fread(f, N, 'int16=>int16')) / 100;
      lat = single(fread(f, N, 'int16=>int16')) / 100;
      hour = single(fread(f, N, 'int16=>int16')) / 100;
      pt = fread(f, N, 'int8=>int8');
      rec_len2 = fread(f, 1, 'int32');
      assert(rec_len1 == rec_len2, 'Fortran record corruption in data');
      fclose(f);

      dhr=hour+dt*24-hourAna;

      rms=ones(size(pt),'single')*5.0;
      inx=find(pt==5);  % ship:
        if length(inx), rms(inx)=ones(size(inx),'single')*2.0; end; 
      inx=find(ismember(pt,[6,7,12,17]));  % buoys, XBT, CTD:
        if length(inx), rms(inx)=ones(size(inx),'single')*0.5; end; 
%      inx=find(ismember(pt,[6,7,12,17]));  % buoys, XBT, CTD:
%        if length(inx), rms(inx)=ones(size(inx),'single')*0.5; end; 
%      inx=find(ismember(pt,[7]));  % buoys, XBT, CTD:
%        if length(inx), rms(inx)=ones(size(inx),'single')*0.5; end; 


      %% collect arrays:
        lonbip=[lonbip;lon(:)];
        latbip=[latbip;lat(:)];
        sstbip=[sstbip;sst(:)];
        dhrbip=[dhrbip;dhr(:)];
        rmsbip=[rmsbip;rms(:)];
  end;

  if flog>1, fclose(flog); end;


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

