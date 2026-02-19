
%cspfile='cyc3out/1988040909_MRVA3_Global.c00';
%L4file='19880409-NCDC-L4LRblend-GLOB-v01-fv02_0-AVHRR_OI.nc.bz2';
%year=1988; day=100;

LL=1:4;
LL=2:2;
out=[];



whichdays={
1986,100:100:300
1987,100:100:300
1988,100:100:300
%2000,100:100:300
%2001,100:100:300
%2002,100:100:300
};


for daycounter=1:size(whichdays,1),
  year=whichdays{daycounter,1};
for day=whichdays{daycounter,2},

  [dd,mm,yyyy]=julian(day,year);
  datestr=sprintf('%04d%02d%02d',yyyy,mm,dd);

  cspfile=sprintf('cyc3out/%s09_MRVA3_Global.c00',datestr);

  L4file=sprintf('%s-NCDC-L4LRblend-GLOB-v01-fv02_0-AVHRR_OI.nc.bz2',datestr);

  [sstcsp,sstref,lon,lat]=compCspL4(cspfile,L4file,LL);

  % display
  for k=1:length(LL), 
    d=sstcsp(:,k)-sstref;
    out=[out;[LL(k),mean(d(:)),std(d(:))]];
  end;


end;
end;
