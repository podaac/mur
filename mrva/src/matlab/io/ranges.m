function key=ranges()

key={
'AMSREA',01,'AMSRE-REMSS, ',0,0,0,0
'WINSAT',02,'WSAT-REMSS, ',0,0,0,0
'MODISA',03,'MODIS_A-JPL, ',0,0,0,0
'MODIST',04,'MODIS_T-JPL, ',0,0,0,0
'AVH18G',05,'AVHRR18_G-NAVO, ',0,0,0,0
'AVH19G',06,'AVHRR19_G-NAVO, ',0,0,0,0
'AVMTAG',07,'AVHRR_METOP_A-EUMETSAT, ',0,0,0,0
'PATH5D',08,'AVHRR_Pathfinder-PFV5.2-NODC_day, ',0,0,0,0
'PATH5N',09,'AVHRR_Pathfinder-PFV5.2-NODC_night, ',0,0,0,0
'IQUAM0',10,'iQUAM-NOAA/NESDIS, ',0,0,0,0
'AVMTBG',11,'AVHRR_METOP_B-EUMETSAT, ',0,0,0,0
};
key={
'AMSREA',0,0,0,0
'WINSAT',0,0,0,0
'MODISA',0,0,0,0
'MODIST',0,0,0,0
'AVH18G',0,0,0,0
'AVH19G',0,0,0,0
'AVMTAG',0,0,0,0
'AVMTBG',0,0,0,0
'PATH5D',0,0,0,0
'PATH5N',0,0,0,0
'IQUAM0',0,0,0,0
};



for year=2002:2013,
  for doy=1:366,

    [d,m,y]=julian(doy,year);

    if d,

      path=sprintf('/home/tmchin/nas/cyc3out/%04d',y);
      path=sprintf('%s/%04d%02d%02d09_MRVA3_Global_inputs.txt',path,y,m,d);

      if ~exist(path,'file'), continue; end;

      sourcelist=txt2sourcedata(path);
      inx=find(ismember(key(:,1),sourcelist));

      for i=inx(:)',
        key{i,4}=year; key{i,5}=doy;
      end;

      jnx=find(~[key{inx,3}]);
      for j=jnx(:)',
        i=inx(j);
        key{i,2}=year; key{i,3}=doy;
      end;

    end;

  end;
end;








function sourcedata=txt2sourcedata(path)

icedata='Ice_Conc-OSISAF';

key={
'AMSREA',01,'AMSRE-REMSS, '
'WINSAT',02,'WSAT-REMSS, '
'MODISA',03,'MODIS_A-JPL, '
'MODIST',04,'MODIS_T-JPL, '
'AVH18G',05,'AVHRR18_G-NAVO, '
'AVH19G',06,'AVHRR19_G-NAVO, '
'AVMTAG',07,'AVHRR_METOP_A-EUMETSAT, '
'PATH5D',08,'AVHRR_Pathfinder-PFV5.2-NODC_day, '
'PATH5N',09,'AVHRR_Pathfinder-PFV5.2-NODC_night, '
'IQUAM0',10,'iQUAM-NOAA/NESDIS, '
};

[label,number]=textread(path,'%s%*d%*d%d%*[^\n]');

out=[];
for k=1:length(label),
  if number(k)>0,
    inx=strmatch(label{k},key(:,1));
    out=[out;key{inx(1),2}];
  end;
end;
out=unique(out);

sourcedata=key(out,1);
sourcedata=unique(sourcedata);
%sourcedata=[sourcedata{:}];

%if isice,
%  sourcedata=[sourcedata,icedata];
%else,
%  sourcedata=sourcedata(1:end-2);
%end;
