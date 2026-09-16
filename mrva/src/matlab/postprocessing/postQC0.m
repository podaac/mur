%% postQC0.m
%% post-production QC level 0:  file existence and size


%% output text:
fout=1;


%% product path:
pdir='/store/ghrsst/open/data/L4/GLOB/JPL/MUR';
%pdir='/home/tmchin/nas/L4/GLOB/JPL/MUR';
%pdir='/data/dev/scratch/tmchin/L4/GLOB/JPL/MUR';


%% product duration: begin and end dates (year,month,day):
dates={
%2002,6,1
2012,6,30
2014,12,28
};

year0=dates{1,1}; month0=dates{1,2}; day0=dates{1,3};
year1=dates{2,1}; month1=dates{2,2}; day1=dates{2,3};

  doy0=julian(day0,month0,year0);
  doy1=julian(day1,month1,year1);


%% loop for existence:
for year=year0:year1,

  ydir=sprintf('%s/%04d',pdir,year);

  if exist(ydir,'dir')==0,

    fprintf(fout,'@@@@@ Year %d does not exist @@@@@\n',year);

  else,

    fprintf(fout,'year %d .... \n',year);

    if year==year0, d0=doy0; else d0=1; end;
    if year==year1, d1=doy1; else d1=julian(31,12,year); end;

    for doy=d0:d1,
  
      ddir=sprintf('%s/%03d',ydir,doy);

      if exist(ddir,'dir')==0,

        fprintf(fout,'@@@@ ... Doy %d does not exist @@@@\n',doy);

      else,

        %d=dir([ddir,'/*MUR*']); ld=length(d);
%        d=dir([ddir,'/*fv04-MUR*']); ld=length(d);
        d=dir([ddir,'/*fv03-MUR*']); ld=length(d);
        if ld~=4,
          fprintf(fout,'@@@ ... Day %d has %d files @@@\n',doy,ld); break;
        else,
          if max([d.bytes])<2e8,
            fprintf(fout,'@@@ ... Day %d only has small files @@@\n',doy); break;
          end;
        end;

        d=dir([ddir,'/*fv04-MUR*bz2*']); ld=length(d);
        if ld~=2,
          fprintf(fout,'@@@ ... Day %d has %d *bz2* files @@@\n',doy,ld);
        end;

        d=dir([ddir,'/*fv04-MUR*xml*']); ld=length(d);
        if ld~=2,
          fprintf(fout,'@@@ ... Day %d has %d *xml* files @@@\n',doy,ld);
        end;

        d=dir([ddir,'/*fv04-MUR*md5*']); ld=length(d);
        if ld~=2,
          fprintf(fout,'@@@ ... Day %d has %d *md5* files @@@\n',doy,ld);
        end;

      end;  % if ddir exists.

    end;  % doy loop.

  end;  % if ydir exists.

end;  % year.
