
year=2009;
day=256;

%box=[-180,180,-50,50];
box=[-180,180,-90,90];

%% mur file:
murlist={
%'/nas/ftp/mur_sst/tmchin/cyc3out','09_MRVA3_Global.c'
'/tmp/cyc3/cyc3out','09_MRVA3_Global.c'
'/nas/ftp/mur_sst/tmchin/cyc2out','09_MRVA2_Global.c'
'/nas/ftp/mur_sst/tmchin/cyc3out','09_MRVA2_Global.c'
%'/tmp/cyc3/cyc3out','09_MRVA3_Global.c'
%'/tmp/cyc/mrva2out','09_MRVA2_Global.c'
%'/tmp/cyc.saved/new1/mrva2out','09_MRVA2_Global.c'
%'/tmp/cyc/new/mrva2out','09_MRVA2_Global.c'
};

LL=6:11;

%% reference SST fields

L4dir='/store/ghrsst/open/data/L4';

L4list={  % choose only one:
'RV1','GLOB/NCDC/AVHRR_OI','*fv02*.bz2','bzcat'
'RV2','GLOB/NCDC/AVHRR_AMSR_OI','*fv02*.bz2','bzcat'
'OSTIA','GLOB/UKMO/OSTIA','*fv02*.bz2','bzcat'
'K10','GLOB/NAVO/K10_SST','*fv01*.bz2','bzcat'
%%'REM','GLOB/REMSS/mw_ir_OI/','*fv03*.gz','zcat'
%%'ABOM','GLOB/ABOM/GAMSSA_28km/','*fv01*.bz2','bzcat'
%%'ODYSSEA','GLOB/EUR/ODYSSEA','*fv02*.bz2','bzcat'
};


%g=fopen('validate.out','w');

nMUR=size(murlist,1);
nL4=size(L4list,1);
bias=zeros(length(LL),nL4,nMUR);
STD=zeros(length(LL),nL4,nMUR);
MAX=zeros(length(LL),nL4,nMUR);
MIN=zeros(length(LL),nL4,nMUR);
L4str={};

for n=1:size(L4list,1),

  dirname=sprintf('%s/%s/%04d/%03d/%s',L4dir,L4list{n,2},year,day,L4list{n,3});
  d=dir(dirname);
  if length(d),
    L4file=sprintf('%s/%s/%04d/%03d/%s',L4dir,L4list{n,2},year,day,d(end).name);
  else,  % file does not exist:
    fprintf(1,'error: %s not found\n',L4list{n,1});
    continue;
  end;

  disp(L4list{n,1});
  ncfile='L4.nc';

%  fprintf(g,'%s\n',L4list{n,1});

  eval( sprintf('!%s %s > %s',L4list{n,4},L4file,ncfile) );

  for L=LL,
  for o=1:size(murlist,1),

    murdir=murlist{o,1};
    murbody=murlist{o,2};

    [d,m,y]=julian(day,year);
    murfile=sprintf('%s/%04d%02d%02d%s%02d',murdir,y,m,d,murbody,L);

    stat=compL4mur(ncfile,murfile,box),
      bias(L-min(LL)+1,n,o)=stat(1);
      STD(L-min(LL)+1,n,o)=stat(2);
      MAX(L-min(LL)+1,n,o)=stat(3);
      MIN(L-min(LL)+1,n,o)=stat(4);

%    fprintf(g,' %s\n%10.4f%10.4f%10.4f%10.4f\n',murfile,stat(1:4));

  end;
  end;
  L4str={L4str{:},L4list{n,1}};
end;

%fclose(g);
%!rm -f L4.nc outgrid.out fort.80;
!rm -f L4.nc outgrid.out fort.180;

save validate L4str bias STD MAX MIN;

lt={'-','--',':','-.'};

if 1, % plot

  subplot(2,2,1);
%  plot(LL,bias(:,:,1)); hold on; plot(LL,bias(:,:,2),'--'); hold off;
  for n=1:nMUR,plot(LL,bias(:,:,n),lt{n});hold on;end;hold off;
  title('Bias'); set(gca,'xtick',LL);
      
  subplot(2,2,2);
%  plot(LL,STD(:,:,1)); hold on; plot(LL,STD(:,:,2),'--'); hold off;
  for n=1:nMUR,plot(LL,STD(:,:,n),lt{n});hold on;end;hold off;
  title('STD'); set(gca,'xtick',LL);

  subplot(2,2,3);
%  plot(LL,MAX(:,:,1)); hold on; plot(LL,MAX(:,:,2),'--'); hold off;
  for n=1:nMUR,plot(LL,MAX(:,:,n),lt{n});hold on;end;hold off;
  title('Max deviation'); set(gca,'xtick',LL);

  legend(L4str,2);
      
  subplot(2,2,4);
%  plot(LL,MIN(:,:,1)); hold on; plot(LL,MIN(:,:,2),'--'); hold off;
  for n=1:nMUR,plot(LL,MIN(:,:,n),lt{n});hold on;end;hold off;
  title('Min deviation'); set(gca,'xtick',LL);

  orient landscape;
  print -depsc validate.eps;

end;
