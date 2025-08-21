function checkfreedisk(dirpath,minP,minG)

if ~exist('minP','var'), minP=98; end;  % default min percentage.
if ~exist('minG','var'), minG=1.5; end; % default min gigabyte.

if ~exist('dirpath','var'), dirpath='.'; end;

%eval(sprintf('!df -Pk %s > /tmp/checkfreedisk.out',dirpath));
eval(sprintf('!df -Pm %s > /tmp/checkfreedisk.out',dirpath));

[n,p]=textread('/tmp/checkfreedisk.out','%*s%*d%*d%d%s%*[^\n]','headerlines',1);
%n=n/1e6;
n=n/1e3;
p=sscanf(p{:},'%d');

if p>minP | n<minG,
  txt=sprintf('Full Disk: %s %.1f%%, %.1fGb free',dirpath,p,n);
  mailsubject(txt);
  error(txt);
end;


