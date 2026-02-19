function [sst,lon,lat,qt,hour,bias,rms]=readbicgz(bicfile)
% [sst,lon,lat,qt,hour,bias,rms]=readbicgz(bicfile)


      eval(sprintf('!zcat %s > gunzipped.bic',bicfile));
%toc;
      f=fopen('gunzipped.bic','r');
      % Read header record
      rec_len1 = fread(f, 1, 'int32');
      nyear = fread(f, 1, 'int32');
      nday = fread(f, 1, 'int32');
      N = fread(f, 1, 'int32');
      rec_len2 = fread(f, 1, 'int32');
      assert(rec_len1 == rec_len2, 'Fortran record corruption in header');

      % Read scale factors
      rec_len1 = fread(f, 1, 'int32');
      off = fread(f, 1, 'single');
      scale1 = fread(f, 1, 'single');
      scale2 = fread(f, 1, 'single');
      rec_len2 = fread(f, 1, 'int32');
      assert(rec_len1 == rec_len2, 'Fortran record corruption in scales');

      % Read data with direct type mapping and scaling (saves ~2-4 GB: int16→double)
      rec_len1 = fread(f, 1, 'int32');
      lon = fread(f, N, 'single=>single');
      lat = fread(f, N, 'single=>single');
      hour = double(fread(f, N, 'int16=>int16')) * scale2;
      sst = double(fread(f, N, 'int16=>int16')) * scale1 + off;
      bias = double(fread(f, N, 'int16=>int16')) * scale1;
      rms = fread(f, N, 'uint8=>double');
      qt = fread(f, N, 'uint8=>double');
      rec_len2 = fread(f, 1, 'int32');
      assert(rec_len1 == rec_len2, 'Fortran record corruption in data');
      fclose(f);
%toc;
      !rm gunzipped.bic;
