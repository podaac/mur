%% seeerr.m

%% scales and translates MRVA *.u?? field.




targetMean=0.5;
targetMin=0.3;

%% empirical mean/std of *.u?? files:
%% e.g., for L=8, ave=1.7 and std=2.0.

uave=[
    0
    0.02
    0.06
    0.1
    0.4
    0.6
    1.3
    1.7
    4.1
    5.7
    6.8
];

udev=[
    0
    0.02
    0.05
    0.09
    0.7
    1.1
    1.7
    2.0
    4.0
    5.0
    5.0
];


for L=2:11,

  name=sprintf('fort.%02d',L+80);
  disp(name);

  f=fopen(name,'r');
    [ii,jj]=fortread(f,'int',1,'int',1);
  [t,x,y]=fortread(f,[ii,jj],ii,jj);
  fclose(f);

  inx=find(t>400); if length(inx), t(inx)=NaN*ones(size(inx)); end;
%  seetmp(x,y,t-273.15,[min(cbar),max(cbar)],cbar);

  if 0, % determin empirical statistics (scaling paramters):
    inx=find(~isnan(t(:))); uave(L)=mean(t(inx)); udev(L)=std(t(inx));
  end;

  if 1,  % scale and translate:
      t = (t-uave(L))/udev(L)*(targetMean-targetMin) + targetMean;
  end;

  inx=find(~isnan(t(:))); ave=mean(t(inx)); dev=std(t(inx));

fig 1;
  imagesc(x,y,sqrt(t'));axis xy;axis image;caxis([-2,2]*dev+ave);colorbar horiz;
%  imagesc(x,y,sqrt(t'));axis xy;axis image;caxis([0,1]);colorbar horiz;
  title(name,'interpreter','none'); drawnow;

fig 2; hist(t(:),100);
  title(sprintf('%f / %f',ave,dev));
  pause;
end;


