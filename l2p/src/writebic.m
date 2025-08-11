function writebic(bicfile,year,day,lon,lat,sst,bias,rms,hour,qt)
% writebic(bicfile,year,day,lon,lat,sst,bias,rms,hour,qt)


%%%%%%%%%%

sstscale=0.01;
hrsscale=0.01;
sstoffset=273.15;
c1=1/sstscale;
c2=1/hrsscale;

%%%%%%%%%%

      N=length(sst);

      % compress:
      sst=int16(round((sst-sstoffset)*c1));
      bias=int16(round(bias*c1));
      rms=uint8(round(rms*c1));
      hour=int16(round(hour*c2));
      qt=uint8(qt);

      % write:
      fprintf(1,'writebic: writing %s\n',bicfile);
      f=fopen(bicfile,'w');
      fortwrite(f,'integer*4',year,'integer*4',day,'integer*4',N);
      fortwrite(f,'real*4',sstoffset,'real*4',sstscale,'real*4',hrsscale);
      fortwrite(f,'real*4',lon,'real*4',lat,'integer*2',hour,'integer*2',sst,...
            'integer*2',bias,'uint8',rms,'uint8',qt);
      fclose(f);

      if 1,  % compress further:
        eval(sprintf('! gzip -f %s &',bicfile));
      end;

