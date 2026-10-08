function sst = makeSeasonal( doy )
%
% STALE -- not on the container's code path, and broken if it ever is.
%
% Line 12 calls readSeasonal(doy), but 27b005e changed that signature to
% readSeasonal(seasonal_file). The same oversight broke csp2nc4a for every
% run until 2026-10-06; this copy survives only because nothing in the
% container reaches it. makeMUR25_container.m uses its own
% makeSeasonal_container(doy, seasonal_file, cache_dir), which takes the
% resolved path; the only caller of THIS function is the heritage
% mrva/src/matlab/ice/makeMUR25.m, which the container does not run.
%
% It is still COPIED into the image (the Dockerfile takes metadata/*.m), so a
% future caller would hit the same type error on exist(). Left unchanged
% rather than guessed at: the hardcoded /nas path on line 3 means it was
% never container-ready, and deciding what it should take is a separate
% question from fixing the live bug.

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
