
%cspfile='cyc3out/1988040909_MRVA3_Global.c00';
%L4file='19880409-NCDC-L4LRblend-GLOB-v01-fv02_0-AVHRR_OI.nc.bz2';
%year=1988; day=100;

LL=2:2;
out=[];



whichdays={
%1986,100:100:300
%1987,100:100:300
%1988,100:100:300
2000,100:100:300
2001,100:100:300
2002,100:100:300
};

% mrva parameters:
Ltrim=6;
L0=Ltrim; LF=Ltrim;
decay=[48*ones(1,6),42,36,30,24,18,12];
%sstOffset=273.15;  % reduce the SST magnitude (e.g., from Kelvin to Celcius)

for daycounter=1:size(whichdays,1),
  year=whichdays{daycounter,1};
for day=whichdays{daycounter,2},

  [dd,mm,yyyy]=julian(day,year);
  datestr=sprintf('%04d%02d%02d',yyyy,mm,dd);

  cspfile=sprintf('cyc3out/%s09_MRVA3_Global.c00',datestr);

  L4file=sprintf('%s-NCDC-L4LRblend-GLOB-v01-fv02_0-AVHRR_OI.nc.bz2',datestr);


  %% run mrvacx:

    disp(L4file);

    % make bip file:
    eval( sprintf('!%s %s > bgL4.nc','bzcat',L4file) );
    bipfile=sprintf('L4g2csp_%04d_%03d.bip',year,day);
    L4ghrsst2bip('bgL4.nc',bipfile,[]);


    % get (lon,lat):
    [sstnc,x,y]=readL4core('bgL4.nc'); [lon,lat]=ndgrid(x,y);
    delete('bgL4.nc');
    sstnc=sstnc(:); lon=lon(:); lat=lat(:);
    inx=find(~isnan(sstnc));
    sstnc=sstnc(inx); lon=lon(inx); lat=lat(inx);
    sstnc=sstnc-273.15;


    % make mrva.nml file:
    f=fopen('mrva.nml','w');
    b=[-180,180,-90,90];
    fprintf(f,' $input\n');
    fprintf(f,'lonmin=%f\nlonmax=%f\n',b(1),b(2));
    fprintf(f,'latmin=%f\nlatmax=%f\n',b(3),b(4));
      fprintf(f,'L0=%d\nLF=%d\n',L0,LF);
      fprintf(f,'decay=\n');
        fprintf(f,'  %f,%f,%f,%f,\n',decay(1:4));
        fprintf(f,'  %f,%f,%f,%f,\n',decay(5:8));
        fprintf(f,'  %f,%f,%f,%f,\n',decay(9:12));
      fprintf(f,'bgfile=''%s''\n',' ');
      fprintf(f,'coefile=''%s''\n',' ');
      fprintf(f,'nbipfile=%d\n',1);
      fprintf(f,'bipfile=\n');
      fprintf(f,'''%d'',''%d'',''%s'',\n',L0,LF,bipfile);
      fprintf(f,' $end\n');
      fclose(f);

    % run mrva:
    ! mrva > log.ref;
    ! cat mrva.nml >> log.ref;
    refcspfile=sprintf('mrva.c%02d',Ltrim);
    eval(sprintf('!rm -f mrva_001.a%02d',LF));
    eval(sprintf('!rm -f fort.%02d',LF+80));


    % resample at the bip file (lon,lat):
          eval(sprintf('! ln -sf %s cbsdata.out',refcspfile));

          f=fopen('cbspoints.dat','w');
          nx=length(sstnc);
          fortwrite(f,'integer*4',[nx,-1,0,0]);
          fortwrite(f,'real*4',lon,'real*4',lat);
          fclose(f);


          % Container: Use fixed path to Fortran executables
          fortran_bin='/opt/mrva/bin';
          eval(sprintf('! %s/cbscxcoeff',fortran_bin)); % execute spline.
          f=fopen('cbs.out','r');
          sstref=fortread(f,nx);
          fclose(f);
          ! rm -f cbspoints.dat cbs.out cbsdata.out






%[sstcsp,sstbip,lon,lat]=compCspL4(cspfile,ncfile,0:6);

sstbip=sstref;

%% filter data:
  if 1,
    inx=1:length(sstbip);

    % avoid polar:
      if 1, 
        jnx=find(lat(:)>=-60&lat(:)<=60);
        inx=intersect(inx(:),jnx(:));
      end;

    % pacific box:
      if 0, 
        jnx=find(lon(:)>=-180&lon(:)<-140&lat(:)>=-45&lat(:)<=45);
        inx=intersect(inx(:),jnx(:));
      end;

    if length(inx),
      lon=lon(inx);lat=lat(inx);sstbip=sstbip(inx);
    else,
      lon=[]; lat=[]; sstbip=[];
    end;
  end;

sstref=sstbip;

sstcsp=[];

for L=LL,
%  disp(sprintf('L=%d',L));
%  if L, cspfile(end-1:end)=sprintf('%02d',L); end;
   cspfile(end-1:end)=sprintf('%02d',L);
  disp(cspfile);

%% setup csp (e.g. MUR coefficient) file for the "cbscoeff":
          eval(sprintf('! ln -sf %s cbsdata.out',cspfile));

          f=fopen('cbspoints.dat','w');
          nx=length(sstbip);
          fortwrite(f,'integer*4',[nx,-1,0,0]);
          fortwrite(f,'real*4',lon,'real*4',lat);
          fclose(f);


%% run "cbscoeff"
          % Container: Use fixed path to Fortran executables
          fortran_bin='/opt/mrva/bin';
%          eval(sprintf('! %s/cbscoeff',fortran_bin)); % execute spline.
          eval(sprintf('! %s/cbscxcoeff',fortran_bin)); % execute spline.
          f=fopen('cbs.out','r');
          sst=fortread(f,nx);
          fclose(f);
          ! rm -f cbspoints.dat cbs.out cbsdata.out

  sstcsp=[sstcsp,sst(:)];
end;

% display
for k=1:length(LL), 
  d=sstcsp(:,k)-sstref;
  out=[out;[LL(k),mean(d(:)),std(d(:))]];
end;


end;
end;
