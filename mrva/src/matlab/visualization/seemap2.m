
k0c=273.15;
badvalue=999;
cax=0:5:30;

%mapdir='/nas/ftp/mur_sst/tmchin';
%jpgdir='./';
%jpgdir='/nas/ftp/mur_sst/tmchin/images';

%mapset='ncamerica0';


%list=dir(sprintf('%s/%s/*.map',mapdir,mapset));


fig 1; set(gcf,'visible','off');



for L=2:10,

%  name=sprintf('%s/%s/%s',mapdir,mapset,list(k).name);
%  name='fort.187';
  name=sprintf('fort.%02d',L+80);
  disp(name);

  f=fopen(name,'r');
  [ii,jj]=fortread(f,'int',1,'int',1),
  [offset,scale]=fortread(f,1,1),
  [ti,x,y]=fortread(f,'integer*2',[ii,jj],ii,jj);
  t=ones(size(ti))*badvalue; 
  inx=find(ti>-1000);
  t(inx)=double(ti(inx))*scale+offset;
  fclose(f);


inx=1:10:length(x);
jnx=1:10:length(y);
  seetmp(x(inx),y(jnx),t(inx,jnx)-k0c,[min(cax),max(cax)],cax);
  title(name,'interpreter','none'); drawnow;

  eval(sprintf('print -dpng -r150 globalC%02d.png;',L));
  eval(sprintf('print -depsc -r300 globalC%02d.eps;',L));

end;



