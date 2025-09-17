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
if nargin<6, landthresh=400; end;  % land mask threshold (max) value.
if nargin<5, cbar=[]; end;  % no colorbar.
if nargin<4, trange=[min(t(:)),max(t(:))]; end;

if nargin==4 & length(trange)>2, cbar=trange; trange=[min(cbar),max(cbar)]; end;

% take transpose of the image:
t=t';

% land mask:
if any(isnan(t(:))),
  mask=isnan(t);
else,
  mask=(t>=landthresh);
end;

% set up image:
N=64;  % color resolution.
N=64*2;  % color resolution.
if length(trange)~=2, trange=[min(t(:)),max(t(:))]; end;
in=ind2rgb( gray2ind( mat2gray(t,trange), N), jet(N) );  % no mask image.

% the image:
in_uint8 = im2uint8(in);
  out_red   = in_uint8(:,:,1);
  out_green = in_uint8(:,:,2);
  out_blue  = in_uint8(:,:,3);
% set mask:
color_uint8 = im2uint8(landcolor);
  out_red(mask)   = color_uint8(1);
  out_green(mask) = color_uint8(2);
  out_blue(mask)  = color_uint8(3);
% combine:
out = cat(3, out_red, out_green, out_blue);

% display:
image(x,y,out); 
axis image;
axis xy;

% color bar:
if length(cbar),
  if size(cbar,1)<size(cbar,2),
    c=colorbar('horiz');
    set(c,'xtick',(cbar-min(cbar))*64/(trange(2)-trange(1))+0.5,...
          'xticklabel',cbar);
  else,
    c=colorbar('vert');
    set(c,'ytick',(cbar-min(cbar))*64/(trange(2)-trange(1))+0.5,...
          'yticklabel',cbar);
  end;
end;

