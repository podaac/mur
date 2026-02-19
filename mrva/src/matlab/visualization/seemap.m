
k0c=273.15;
cbar=0:5:30;

%mapdir='/nas/ftp/mur_sst/tmchin';
mapdir='.';
%mapdir='/tmp';

mapset='mrva4map'; cbar=0:5:30;
%mapset='amami0'; cax=[23,31];
%mapset='amami0.2'; cax=[22,30];


list=dir(sprintf('%s/%s/*.map',mapdir,mapset));



for k=1:length(list),

  name=sprintf('%s/%s/%s',mapdir,mapset,list(k).name);
  disp(name);

  f=fopen(name,'r');
    [ii,jj]=fortread(f,'int',1,'int',1);
  [t,x,y]=fortread(f,[ii,jj],ii,jj);
  fclose(f);

  inx=find(t>400); if length(inx), t(inx)=NaN*ones(size(inx)); end;
%  seetmp(x,y,t-273.15,[min(cbar),max(cbar)],cbar);
  imagesc(x,y,t'-273.15); axis xy; caxis([min(cbar),max(cbar)]); colorbar;

%  imagesc(x,y,t'-k0c); axis xy; axis image; caxis(cax); colorbar horiz;
%  imagesc(x,y,t'-k0c); axis xy; axis image;  colorbar horiz;
%axis([-70-3,-70+3,35-1,35+4]); caxis([15,25]);
  title(name,'interpreter','none'); drawnow;

  pause;
end;


