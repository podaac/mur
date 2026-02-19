function seetmp(x,y,t,trange,cbar,landthresh,landcolor)
% seetmp(x,y,t,trange,cbar,landthresh,landcolor)
% plots "temperature" map with landmask and colorbar.
%
% (x,y,t) = lon and lat vectors and temperature map matrix.
% optional paramters:
% trange = temperature range to be shown, defaults [min(t),max(t)].
% cbar = colorbar tick labels, hozontal/vertical vector for horiz/vert colorbar,
%        default, no colorbar.
% landthresh = threshold temperature value above which is considered to be
%              the land, default 400.  If a NaN value is present, then
%              this threshold is ignored and NaN is used as the land marker.
% landcolor = land mask color, default [0 0 0] (black).


if nargin<7, landcolor=[0 0 0]; end;  % default land color is black.
if nargin<6, landthresh=[]; end;  % land mask threshold (max) value.
if nargin<5, cbar=[]; end;  % no colorbar.
if nargin<4, trange=[min(t(:)),max(t(:))]; end;

if nargin==4 & length(trange)>2, cbar=trange; trange=[min(cbar),max(cbar)]; end;

% take transpose of the image:
t=t';

% landmask:
if length(landthresh),
  inx=find(t>=landthresh);
  if length(inx), t(inx)=NaN*ones(size(inx)); end;
end;


h=imagesc(x,y,t); axis image; axis xy;
caxis(trange);
% land mask:
if any(isnan(t(:))),
  set(h,'alphadata',~isnan(t))
  set(gca,'color',landcolor);  % landcolor.

  % for printing.
  set(gcf,'color',[1 1 1]);
  set(gcf,'inverthardcopy','off');
end;

% color bar:
if length(cbar),
  if size(cbar,1)<size(cbar,2),
    c=colorbar('horiz');
    set(c,'xtick',cbar,'xticklabel',cbar);
  else,
    c=colorbar('vert');
    set(c,'ytick',cbar,'yticklabel',cbar);
  end;
end;

