      program samplegdscsp

! evaluates the given csp file(s) over the given gds grid.
!
! The samples are scaled about an offset and returned as an integer array,
! like netCDF.  The actual sampling is done by function "outovergds" in
! file "filemod.f".
!
! The output are returns in file(s): fort.181, fort.182, fort.183, ...
! in order.


      use filemod
      use spmm


      ! spm data:
      real, allocatable:: csp(:)


      ! output grid file:
      character*128 :: coeffilelist(20), coeffile, gridfile

      integer :: ios, L, nlist

      real :: offset, sscale
      
      ! name list variables:
      namelist /input/ offset,sscale,nlist,
     &                 coeffilelist, gridfile


!
! input parameters from namelist file:
!
      open(7,file='samplegdscsp.nml',form='formatted',status='old')
      read(7,nml=input)
      close(7)



!      
! spm domain:
!

      do n=1,nlist
        coeffile = trim( coeffilelist(n) )
        print*,'Reading ',coeffile
        call readcoeff( ios, csp, coeffile )
        if(ios==0)
     &    call outovergds( csp, n, gridfile, offset, sscale )
        deallocate(csp)
      end do

      end
