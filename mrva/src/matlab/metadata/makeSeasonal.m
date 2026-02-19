function sst = makeSeasonal( doy )

  seasonaldir = '/nas/ftp/mur_sst/tmchin/MUR25/seasonal';
  seasonalfile = sprintf('%s/mur_%03d.mat', seasonaldir, doy );

  if exist( seasonalfile, 'file' ),

      load( seasonalfile );  % --> sst.

  else,

      sst = MURto25( readSeasonal( doy ) );

      if 1,
        save( seasonalfile, 'sst' );
      end;

  end;
