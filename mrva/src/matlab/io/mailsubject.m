function mailsubject(subject)
tolist='mike.chin@jpl.nasa.gov,toshio.m.chin@jpl.nasa.gov';
cclist='tmchin@jpl.nasa.gov';

% write mail text:
f=fopen('mail.txt','w');
fprintf(f,'From: MUR_PRODUCTION_\n');
fprintf(f,'To: %s\n',tolist);
fprintf(f,'Cc: %s\n',cclist);
fprintf(f,'Subject: %s\n\n',subject);

fprintf(f,'Local time by matlab was %s\n',datestr(now));
fclose(f);

% send mail:
eval(sprintf('! /usr/sbin/sendmail -t < mail.txt'));


