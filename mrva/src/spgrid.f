      program spgrid

! multi-resolution variational analysis

      use filemod
      use spmm



      ! spm data:
      real, allocatable:: csp(:)


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



!      
! spm domain:
!

      do n=1,nlist
        read(coeffilelist(1,n),*) L
        coeffile=trim(coeffilelist(2,n))
        print*,'Reading ',coeffile
        call readcoeff(ios,csp,coeffile)
        if(ios==0)
     &    call outscaledgds(csp,L,gridfile,offset,sscale,minsst)
        deallocate(csp)
      end do

      end
