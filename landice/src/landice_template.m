path('<replace_path>', path);
year=<replace_year>; day=<replace_day>;

[icesstfile,landicefile]=makeicefiles('<replace_in_dir>','<replace_out_dir>',year,day,'<replace_case>');

if length(landicefile),
    eval(sprintf('! gzip -f %s &',landicefile)); 
end;

if length(icesstfile),
    eval(sprintf('! gzip -f %s &',icesstfile));
end;