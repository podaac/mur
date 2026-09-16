      program spgrid

! multi-resolution variational analysis

      use filemod
      use spmm



      ! spm data:
      real, allocatable:: csp(:)

#ifdef DEBUG
      ! test interpolation variable (only needed for debug):
      real :: test_sst
#endif

      ! output grid file:
      character*128 :: coeffilelist(2,20),coeffile,gridfile

      integer :: ios,L,nlist

      real :: offset,sscale,minsst

      ! name list variables:
      namelist /input/ offset,sscale,minsst,nlist,
     &                 coeffilelist,gridfile


!
! input parameters from namelist file:
!
      open(7,file='spgrid.nml',form='formatted',status='old')
      read(7,nml=input)
      close(7)

#ifdef DEBUG
      ! DEBUG: Print namelist parameters
      print*,'========================================'
      print*,'SPGRID DEBUG: Namelist parameters:'
      print*,'  offset  = ', offset, ' (K)'
      print*,'  sscale  = ', sscale
      print*,'  minsst  = ', minsst, ' (K)'
      print*,'  nlist   = ', nlist
      print*,'  gridfile= ', trim(gridfile)
      print*,'  cix (compile-time) = ', cix
      print*,'========================================'
#endif



!
! spm domain:
!

      do n=1,nlist
        read(coeffilelist(1,n),*) L
        coeffile=trim(coeffilelist(2,n))
        print*,'Reading ',coeffile
        call readcoeff(ios,csp,coeffile)

#ifdef DEBUG
        ! DEBUG: Verify module state after readcoeff
        print*,'----------------------------------------'
        print*,'DEBUG: Module state after readcoeff:'
        print*,'  ios = ', ios
        print*,'  mx,my,mz,nv = ', mx, my, mz, nv
        print*,'  mx3,my3,mz3 = ', mx3, my3, mz3
        print*,'  xmin,xmax = ', xmin, xmax
        print*,'  ymin,ymax = ', ymin, ymax
        print*,'  hx,hy = ', hx, hy
        print*,'  coeffSize = ', coeffSize
        if(allocated(csp)) then
          print*,'  csp allocated, size = ', size(csp)
          print*,'  csp range = ', minval(csp), maxval(csp)
          print*,'  csp sum = ', sum(csp)
          print*,'  csp(1:5) = ', csp(1), csp(2), csp(3), csp(4), csp(5)
        else
          print*,'  WARNING: csp NOT allocated!'
        end if

        ! DEBUG: Direct spmPoint test BEFORE calling outscaledgds
        if(ios==0 .and. allocated(csp)) then
          print*,'DEBUG: Direct spmPoint tests (in spgrid main):'
          ! Test at equator (0,0) - should be tropical
          call spmPoint(1,1,csp,0.0,0.0,0,0,0.25,0.25,test_sst)
          print*,'  spmPoint(0,0) = ', test_sst, ' +273.15 = ',
     &           test_sst+273.15, 'K = ', test_sst, 'C'
          ! Test at California coast
          call spmPoint(1,1,csp,-120.0,30.0,0,0,0.25,0.25,test_sst)
          print*,'  spmPoint(-120,30) = ', test_sst, ' +273.15 = ',
     &           test_sst+273.15, 'K = ', test_sst, 'C'
          ! Test at Southern Ocean
          call spmPoint(1,1,csp,0.0,-60.0,0,0,0.25,0.25,test_sst)
          print*,'  spmPoint(0,-60) = ', test_sst, ' +273.15 = ',
     &           test_sst+273.15, 'K = ', test_sst, 'C'
          ! Test at Arctic
          call spmPoint(1,1,csp,0.0,80.0,0,0,0.25,0.25,test_sst)
          print*,'  spmPoint(0,80) = ', test_sst, ' +273.15 = ',
     &           test_sst+273.15, 'K = ', test_sst, 'C'
          print*,'  (Expected: tropical ~27C, S.Ocean ~2C, Arctic ~0C)'
          print*,'----------------------------------------'
        end if
#endif

        if(ios==0)
     &    call outscaledgds(csp,L,gridfile,offset,sscale,minsst)
        deallocate(csp)
      end do

      end
