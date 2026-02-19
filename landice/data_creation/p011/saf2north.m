% saf2north.m

% get a lookup table from OSI SAF data file (grib)
% to each "sea" point in the northern half of Global pathfinder (1km) grid.


% resolution:
mindistance=0.2; % [degrees]; equatorial ~degree-distance for SAF's 10km res.
  % see below for graphical determination of this value.

% grid data:
%Glob1km.mask';
landmaskfile=getenv("LAND_MASK_FILE")


% OSI SAF data:
% latlonOSISAFnh.mat
safname=getenv("SAF_NAME")
% landindexNH.mat
landindexname=getenv("LAND_INDEX_NAME")



% read grid data:
  fprintf(1,'loading %s\n',landmaskfile);
  f=fopen(landmaskfile,'r');
  % Read Fortran record with dimensions
  record_header = fread(f, 1, 'uint32');
  ii = fread(f, 1, 'int32=>int32');
  jj = fread(f, 1, 'int32=>int32');
  record_trailer = fread(f, 1, 'uint32');
  % Read Fortran record with mask and coordinates
  record_header = fread(f, 1, 'uint32');
  mask = fread(f, [ii,jj], 'int16=>int16');
  lon = fread(f, ii, 'single=>single');
  lat = fread(f, jj, 'single=>single');
  record_trailer = fread(f, 1, 'uint32');
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
inx=find(yg>(min(yi)-mindistance)); % no ice BELOW this latitude.
jnx=find(mask==1 | mask==2 | mask==4);  % mask = {0, 1, 2, 4}
mnx=intersect(inx,jnx);

  if 0,  % plot the inputs:
    plot(xg(mnx),yg(mnx),'k.','markersize',2);
    hold on; plot(xi,yi,'r.','markersize',2); hold off
  end;



% find nearest distance and indexes using MATLAB:
fprintf(1,'Running nearest neighbor search in MATLAB...\n');
n_saf = length(xi);      % number of SAF points
n_grid = length(mnx);    % number of grid points

dval = inf(n_grid, 1);   % minimum distances
iinx = zeros(n_grid, 1); % indices of nearest SAF points

deg2rad = pi/180;

% For each grid point, find nearest SAF point
for grid_idx = 1:n_grid
    if mod(grid_idx, 10000) == 0
        fprintf(1,'  Progress: %.1f%%\n', 100 * grid_idx / n_grid);
    end
    
    grid_lon = xg(mnx(grid_idx));
    grid_lat = yg(mnx(grid_idx));
    
    min_dist_sq = inf;
    best_saf_idx = 0;
    
    for saf_idx = 1:n_saf
        saf_lon = xi(saf_idx);
        saf_lat = yi(saf_idx);
        
        % Calculate latitude difference
        dy = abs(saf_lat - grid_lat);
        if dy <= mindistance
            % Calculate longitude difference with wraparound
            dx = abs(saf_lon - grid_lon);
            if dx > 360
                dx = dx - 360;
            end
            % Handle crossing 0/360 boundary
            if dx > 180
                dx = 360 - dx;
            end
            
            % Apply cosine correction for latitude convergence
            cos_lat = cos(max(abs(saf_lat), abs(grid_lat)) * deg2rad);
            dx = dx * cos_lat;
            
            if dx <= mindistance
                % Calculate squared distance
                dist_sq = dx*dx + dy*dy;
                if dist_sq < min_dist_sq
                    min_dist_sq = dist_sq;
                    best_saf_idx = saf_idx;
                end
            end
        end
    end
    
    dval(grid_idx) = sqrt(min_dist_sq);
    iinx(grid_idx) = best_saf_idx;
end

fprintf(1,'Nearest neighbor search completed.\n');

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

save saf2north iceinx gridinx;


