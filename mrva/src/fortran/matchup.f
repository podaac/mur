      program matchup

! prints matchup statistics.

      use spmm
      use filemod


      ! parameters:
      integer maxbip
      real SSToffset   
      parameter(maxbip=50)         ! max number of bip data files.
      parameter(SSToffset=273.15)  ! Kelvin at freezing.


      ! spm data:
      real, allocatable:: csp(:)
      type(bip) :: d(maxbip), e(maxbip)
      integer, allocatable :: inx(:)


      ! data sets:
      character*128 filename
      
      ! name list:
      real lonmin,lonmax,latmin,latmax
      character*128 coefile ! background coefficient field.
      character*128 bipfile(3,maxbip) ! main data files.
      integer nbipfile  ! number of data files.

      namelist /input/ lonmin,lonmax,latmin,latmax,
     &                 coefile,nbipfile,bipfile



!
! input parameters from namelist file:
!
      open(7,file='matchup.nml',form='formatted',status='old')
      read(7,nml=input)
      close(7)



!      
! read data files:
!

      print*,'Data:'
      do m=1,nbipfile
        read(bipfile(1,m),*) d(m)%La
        read(bipfile(2,m),*) d(m)%Lb
        filename=trim(bipfile(3,m))
        call readbip(d(m),trim(filename))
        print*,'  ... ',d(m)%n,' points.'
        if(d(m)%n>0) then
          allocate(inx(1:d(m)%n)); inx(:)=0
          kount=0
          do k=1,d(m)%n
            if(d(m)%x(k)>=lonmin.and.d(m)%x(k)<=lonmax.and.
     &         d(m)%y(k)>=latmin.and.d(m)%y(k)<=latmax) then
                  kount=kount+1
                  inx(kount)=k
            end if
          end do
          print*,'  ... narrowed to ',kount,' points.'
          if (kount>0) then
            e(m)%n=kount
            allocate(e(m)%x(1:kount))
            allocate(e(m)%y(1:kount))
            allocate(e(m)%t(1:kount))
            allocate(e(m)%sst(1:kount))
            allocate(e(m)%err(1:kount))
            e(m)%x(:)=d(m)%x(inx(1:kount))
            e(m)%y(:)=d(m)%y(inx(1:kount))
            e(m)%t(:)=d(m)%t(inx(1:kount))
            e(m)%sst(:)=d(m)%sst(inx(1:kount))
            e(m)%err(:)=d(m)%err(inx(1:kount))
            print*,'  ... box: ',minval(e(m)%x),maxval(e(m)%x),
     &                           minval(e(m)%y),maxval(e(m)%y)
            print*,'  ... time range: ',minval(e(m)%t),maxval(e(m)%t)
            print*,'  ... sst: ',sum(e(m)%sst)/e(m)%n,
     &                           minval(e(m)%sst),maxval(e(m)%sst)
            print*,'  ... err: ',sum(e(m)%err)/e(m)%n,
     &                           minval(e(m)%err),maxval(e(m)%err)
          end if
          deallocate(inx)
        end if
      end do




!      
! spm:
!


      call readcoeff(ios,csp,coefile)

 
        ! data residual:
          do m=1,nbipfile
            jblk=d(m)%n/nProcessors  ! nProcessors set in spmm.f
!$OMP PARALLEL DO PRIVATE(n,sstL) SCHEDULE(STATIC,jblk)
            do n=1,d(m)%n
              call spmPoint(1,1,csp,e(m)%x(n),e(m)%y(n),0,0,hx,hy,sstL)
              e(m)%sst(n)=e(m)%sst(n)-sstL
            end do
!$OMP END PARALLEL DO
            print*,' '
            print*,trim(coefile)
            print*,'vs ',trim(bipfile(3,m))
            print*,'  off =',sum(e(m)%sst(:))/e(m)%n
            print*,'  RMS =',sqrt(sum(e(m)%sst(:)**2)/e(m)%n)
            print*,'  Max =',maxval(e(m)%sst)
     &      ,'@(',e(m)%x(maxloc(e(m)%sst)),e(m)%y(maxloc(e(m)%sst)),')'
            print*,'  Min =',minval(e(m)%sst)
     &      ,'@(',e(m)%x(minloc(e(m)%sst)),e(m)%y(minloc(e(m)%sst)),')'

          end do


      end program
