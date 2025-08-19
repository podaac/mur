%% makebii.m
%% downloads IQUAM HDF file and save as daily bii files.
%%
%% destination directory and output filename are set in writeiquambii.m

rewrite=1;

whichdays={
%2003,306
%2013,[96:97,143,162,206:210,236:245]
%2014,[33,35,51,53,54,84,85,101:104,142,293:304,308,311:314,332:334,344,363]
%2016,10:28
%2018,1:134
%2019,[282,283,289]
%2019,290:298
2019,297:301
};


system('rm -f iquam*.mat');  % clean up.


for daycounter=1:size(whichdays,1),
  year=whichdays{daycounter,1};

  for doy=whichdays{daycounter,2},

    makedailyiquam(year,doy,rewrite);

  end;
end;

system('rm -f iquam*.mat');  % clean up.
