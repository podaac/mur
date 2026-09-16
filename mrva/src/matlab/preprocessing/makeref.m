function name=makeref(year,day,sensors,L0,LF,bipdir,decay,...
                      icesstfile,polarcap,coefile)
%% makeref:  function to run a mrva and return csp file (for reference field).

% mike chin, 13.10.17 (non empty coefile can be specified)


region='Global';  box=[-180., 180., -90., 90.];
bgfile='';
if ~exist('coefile','var'), coefile=''; end;

    %% run mrva:

    f=fopen('mrva.nml','w');
    fprintf(f,' $input\n');
    fprintf(f,'lonmin=%f\nlonmax=%f\n',box(1),box(2));
    fprintf(f,'latmin=%f\nlatmax=%f\n',box(3),box(4));
    fprintf(f,'L0=%d\nLF=%d\n',L0,LF);
    fprintf(f,'decay=\n');
      fprintf(f,'  %f,%f,%f,%f,\n',decay(1:4));
      fprintf(f,'  %f,%f,%f,%f,\n',decay(5:8));
      fprintf(f,'  %f,%f,%f,%f,\n',decay(9:12));
    fprintf(f,'bgfile=''%s''\n',bgfile);
    fprintf(f,'coefile=''%s''\n',coefile);
    nbipfile=size(sensors,1);
    if length(icesstfile)
      fprintf(f,'nbipfile=%d\nbipfile=\n',nbipfile+2);
      %fprintf(f,'''%d'',''%d'',''%s'',\n',L0,6,icesstfile);
      fprintf(f,'''%d'',''%d'',''%s'',\n',L0,9,icesstfile);
      fprintf(f,'''%d'',''%d'',''%s'',\n',L0,9,polarcap);
    else,
      fprintf(f,'nbipfile=%d\nbipfile=\n',nbipfile);
    end;
    for n=1:nbipfile,
      sensor=sensors{n,1};
      %bipfile=sprintf('%s/%s_%s_%04d_%03d.bip',bipdir,region,sensor,year,day);
      bipfile=sprintf('%s/%s_%s_%04d_%03d.biq',bipdir,region,sensor,year,day);
      fprintf(f,'''%d'',''%d'',''%s'',\n',sensors{n,4},sensors{n,5},bipfile);
    end;
    fprintf(f,' $end\n');
    fclose(f);

    ! /opt/mrva/bin/mrva;

name=sprintf('mrva.c%02d',LF);

