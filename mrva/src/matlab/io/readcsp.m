function [csp,mx,my,mz,nv,xmin,xmax,ymin,ymax]=readcsp(filename)

f=fopen(filename,'r');
if f==-1, disp('no such csp file.'); return; end;
[mx,my,mz,nv]=fortread(f,'integer*4',1,'integer*4',1,...
                         'integer*4',1,'integer*4',1);
[xmin,xmax,ymin,ymax]=fortread(f,1,1,1,1);
      mx3 = mx; my3 = my+3; mz3 = mz;
%      coeffSize = mx3*my3*mz3*nv;
%      hx=(xmax-xmin)/mx; hy=(ymax-ymin)/my;
%csp=fortread(f,'real*4',[coeffSize,1]);
csp=fortread(f,'real*4',[mx3,my3]);
fclose(f);
