function [T,x,y,t,w]=readbip(bipfile)

f=fopen(bipfile,'r');
n=fortread(f,'integer*4',1);
[x,y,t,T,w]=fortread(f,n,n,n,n,n);
fclose(f);

