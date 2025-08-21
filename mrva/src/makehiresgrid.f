! makehiresgrid.f
! make a grid of smallest-magnitude dt from "hour" variable of given biq files.

      program makehiresgrid


      ! parameters:
      integer maxbiq
      parameter(maxbiq=50)         ! max number of biq data files.
      integer*1 fillvalue
      parameter(fillvalue=-128)    ! not a number.

      ! output grid:
      integer*1,allocatable :: grid(:,:)

      ! input parametgers:
      character*128 :: biqfiles(maxbiq), outfile

      integer*4 nbiqfile   ! number of input files.
      integer*4 nlon,nlat  ! output gridsize

      real*8  lon0,lat0  ! grid origin coordinates
      real*8  dlon,dlat  ! grid intervals
      real*8  flon,flat  ! grid point frequencies

      ! biq file contents:
      integer*4 :: ndata
      real*4, allocatable :: lon(:), lat(:), hour(:)
      integer*1 :: dt

      ! grid contents:

      ! name list variables:
      namelist /input/ lon0,lat0,dlon,dlat,
     &                 nlon,nlat,nbiqfile,biqfiles,outfile


!
! input parameters from namelist file:
!
      open(7,file='makehiresgrid.nml',form='formatted',status='old')
      read(7,nml=input)
      close(7)
      flon=1.0/dlon
      flat=1.0/dlat

!
! initialize output grid:
!
      allocate(grid(nlon,nlat))
      do j=1,nlat
      do i=1,nlon
        grid(i,j)=fillvalue
      end do
      end do

!
! main loop; fill the grid:
!

      do m=1,nbiqfile

        ! read biq file:
        print*,'makehiresgrid: ',trim(biqfiles(m))
        open(7,file=trim(biqfiles(m)),form='unformatted',status='old')
        read(7) ndata
        allocate(lon(ndata),lat(ndata),hour(ndata))
        read(7) lon
        read(7) lat
        read(7) hour
        close(7)
        print*,' ... read.'

        ! assign grid values:
        do n=1,ndata

          ! find grid coordinates:
          i=nint( (lon(n)-lon0)*flon )+1
          if( i==0 ) i=nlon
          j=nint( (lat(n)-lat0)*flat )+1

          ! assign dt value:
          if( i>=1.and.i<=nlon.and.j>=1.and.j<=nlat ) then
            dt=nint(hour(n))
            if( abs(hour(n))>127. ) dt=fillvalue
            if( grid(i,j)==fillvalue.or.abs(grid(i,j))>abs(dt) ) then
              grid(i,j)=dt
            end if
          end if

        end do  ! n.
        print*,' ... gridded.'

        deallocate(lon,lat,hour)

      end do  ! m.

!
! write output grid:
!
      open(8,file=trim(outfile),form='unformatted',status='unknown')
      write(8) nlon,nlat
      write(8) grid
      close(8)

      end program

