function [lon,lat,sst,hour]=readiquambin(filename)
  f=fopen(filename,'r');
  [year,doy,N]=fortread(f,'integer*4',1,'integer*4',1,'integer*4',1);
  [lon,lat,sst,hour]=fortread(f,'real*4',N,'real*4',N,'real*4',N,'real*4',N);
  fclose(f);

