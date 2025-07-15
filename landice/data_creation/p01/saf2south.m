% saf2south.m

% get a lookup table from OSI SAF data file (grib)
% to each "sea" point in the southern half of Global 0.01-deg grid.


% resolution:
mindistance=0.2; % [degrees]; equatorial ~degree-distance for SAF's 10km res.
  % see below for graphical determination of this value.

% grid data:
% maskGLOBp01deg.gds';
landmaskfile=getenv("LAND_MASK_FILE")


% OSI SAF data:
% latlonOSISAFsh.mat
safname=getenv("SAF_NAME")
% landindexSH.mat
landindexname=getenv("LAND_INDEX_NAME")



% read grid data:
  fprintf(1,'loading %s\n',landmaskfile);
  f=fopen(landmaskfile,'r');
  [ii,jj]=fortread(f,'int',1,'int',1);
  [mask,lon,lat]=fortread(f,'integer*1',[ii,jj],'real*4',ii,'real*4',jj);
  fclose(f);
[xg,yg]=ndgrid(lon,lat);
xg=xg(:); yg=yg(:);


% read saf data:
load('-mat',safname);  % lon, lat.
lon=fliplr(lon); lat=fliplr(lat);  % the necessary flip.
%inx=find(lon>=box(1)&lon<=box(2)&lat>=box(3)&lat<=box(4));
load('-mat',landindexname);  % landinx, ReadMe.
jnx=setdiff(1:length(lon(:)),landinx);  % not land index.
%snx=intersect(inx,jnx);
snx=jnx;
xi=lon(snx); yi=lat(snx);

% select relevant grid points:
inx=find(yg<(max(yi)+mindistance)); % no ice ABOVE this latitude.
%jnx=find(mask==1 | mask==2 | mask==4);  % mask = {0, 1, 2, 4}
jnx=find(mask~=2);  % not "solid land"
mnx=intersect(inx,jnx);

  if 0,  % plot the inputs:
    plot(xg(mnx),yg(mnx),'k.','markersize',2);
    hold on; plot(xi,yi,'r.','markersize',2); hold off
  end;



% find nearest distance and indexes:
if 1,  % run "nearest.f":
  f=fopen('nninput.dat','w');
    fortwrite(f,'integer*4',length(xi),'integer*4',length(mnx));
    fortwrite(f,'real*4',xi,'real*4',yi);
    fortwrite(f,'real*4',xg(mnx),'real*4',yg(mnx));
    fortwrite(f,'real*4',mindistance)
  fclose(f);

%  ! ifort -openmp nearest.f; a.out
  ! ifort -openmp nearest2.f; a.out

  f=fopen('nnoutput.dat','r');
    n=fortread(f,'integer*4',1);
    [dval,iinx]=fortread(f,'real*4',n,'integer*4',n);
  fclose(f);
end;

% explore for the cut-off distance:
if 0,
  cut=0.1:0.1:2.0;
  for c=cut,
    inx=find(dval<=c);
    if length(inx),  % see coverage over (xg,yg):
      plot(xg(mnx),yg(mnx),'r.','markersize',2); %axis(box)
      hold on; plot(xg(mnx(inx)),yg(mnx(inx)),'c.','markersize',2); hold off
      title(num2str(c));
      %% details should be looked at:
      %axis([-62,-50,45,51]);
      %axis([-50,-40,55,62]);
      %axis([-165,-150,55,62]);
      pause;
    end;
  end;
  %% --> 0.2 is chosen; some "undetermined" values deep in fjords.
end;



% select the output and save:
inx=find(dval<=mindistance);
iceinx=snx(iinx(inx));  % index for the SAF ice concentration matrix.
gridinx=mnx(inx);  % corresponding nearest neighbor index for NCAMERICA grod.

iceinx=int32(iceinx);
gridinx=int32(gridinx);

save saf2south iceinx gridinx;

% clean up:
! rm nninput.dat nnoutput.dat a.out;


