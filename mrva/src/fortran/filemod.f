!! filemod.f  (File I/O Module)

!! version 13.2.10 (readbip logic is tighter)
!! version 13.10.17 (initialcoeff dimension checking)

      module filemod


      type bip
        integer*4 :: n
        real*4, dimension(:), pointer :: x,y,t,sst,err
        integer*4 :: La,Lb
      end type bip


      type cspmm
        integer :: mx,my,mz,nv
        real :: xmin,xmax,ymin,ymax
        real, dimension(:,:,:,:), pointer :: csp
      end type cspmm


!!!!!!!!!!

      contains

!!!!!!!!!!!!!!!!!!!!

      subroutine readbiq(b,filename)
      type(bip) :: b
      character*(*) filename

      print*,'reading ',trim(filename)
      open(7,file=filename,form='unformatted',status='old',iostat=ios)
      if(ios>0) then
        print*,'  ... not opened.'
        b%n=0
      else
        read(7) b%n
        print*,b%n,' data points.'
        allocate(b%x(1:b%n))
        allocate(b%y(1:b%n))
        allocate(b%t(1:b%n))
        allocate(b%sst(1:b%n))
        allocate(b%err(1:b%n))
        read(7) b%x
        read(7) b%y
        read(7) b%t
        read(7) b%sst
        read(7) b%err
        close(7)
      endif

      end subroutine

!!!!!!!!!!!!!!!!!!!!

      subroutine writebiq(b,filename)
      type(bip) :: b
      character*(*) filename
      print*,'writing ',trim(filename)
      print*,b%n,' data points.'
      open(8,file=filename,form='unformatted',status='unknown')
      write(8) b%n
      write(8) b%x(1:b%n)
      write(8) b%y(1:b%n)
      write(8) b%t(1:b%n)
      write(8) b%sst(1:b%n)
      write(8) b%err(1:b%n)
      close(8)
      end subroutine

!!!!!!!!!!!!!!!!!!!!

      subroutine readbip(b,filename)
      ! can also read a "*.biq" file, identified by the file suffix.
      type(bip) :: b
      character*(*) filename

      print*,'reading ',trim(filename)
      open(7,file=filename,form='unformatted',status='old',iostat=ios)
      if(ios>0) then
        print*,'  ... not opened.'
        b%n=0
      else
        read(7) b%n
        print*,b%n,' data points.'
        allocate(b%x(1:b%n))
        allocate(b%y(1:b%n))
        allocate(b%t(1:b%n))
        allocate(b%sst(1:b%n))
        allocate(b%err(1:b%n))
        !if(index(filename,'.bip')>0) then  ! regular "bip" file:
        if(index(filename,'.bip',.true.)==len(trim(filename))-3) then  ! "bip":
          read(7) b%x,b%y,b%t,b%sst,b%err
        else  ! "biq" file by default:
          read(7) b%x
          read(7) b%y
          read(7) b%t
          read(7) b%sst
          read(7) b%err
        end if
        close(7)
      endif

      end subroutine

!!!!!!!!!!!!!!!!!!!!

      subroutine writebip(b,filename)
      type(bip) :: b
      character*(*) filename
      print*,'writing ',trim(filename)
      print*,b%n,' data points.'
      open(8,file=filename,form='unformatted',status='unknown')
      write(8) b%n
      write(8) b%x(1:b%n),b%y(1:b%n),b%t(1:b%n),b%sst(1:b%n),b%err(1:b%n)
      close(8)
      end subroutine

!!!!!!!!!!!!!!!!!!!!

      subroutine initialcoeff(ios,csp,coeffile)
      ! checks if coefficient file exists (otherwise returns ios>0);
      ! checks if the coefficient parameters are as intended;
      ! allocates coefficient field;
      ! reads the coefficients from coefficient file coeffile.
      use spmm
      character*(*) coeffile
      real, allocatable :: csp(:)
      integer :: ios
      real small; parameter(small=1.0e-8)  ! define a "practically zero" value.
      !
      print*,'reading ',trim(coeffile)
      open(8,file=coeffile,form='unformatted',status='old',iostat=ios)
      if(ios>0) then
        print*,'  ... not opened.'
        return
      end if
      !
      read(8) mxtmp,mytmp,mztmp,nvtmp
        if(mx/=mxtmp.or.my/=mytmp.or.mz/=mztmp.or.nv/=nvtmp) then
          print*,'coefficient integer paramter mismatch; just warning'
          print*,mx,mxtmp,my,mytmp,mz,mztmp,nv,nvtmp
!          stop '(initialcoeff)'
        end if
      mx=mxtmp; my=mytmp; mz=mztmp; nv=nvtmp;
      !
      read(8) xmintmp,xmaxtmp,ymintmp,ymaxtmp
        if(abs(xmin-xmintmp)>small.or.abs(xmax-xmaxtmp)>small.or.
     &     abs(ymin-ymintmp)>small.or.abs(ymax-ymaxtmp)>small) then
          print*,'coefficient real paramter mismatch; just warning'
          print*,xmin,xmintmp,xmax,xmaxtmp
          print*,ymin,ymintmp,ymax,ymaxtmp
!          stop '(initialcoeff)'
        end if
      xmin=xmintmp; xmax=xmaxtmp; ymin=ymintmp; ymax=ymaxtmp;
      !
      call spmRefresh
      allocate(csp(coeffSize))
      read(8) csp
      close(8)
      end subroutine

!!!!!!!!!!!!!!!!!!!!

      subroutine writecoeff(csp,filename)
      use spmm
      real csp(coeffSize)
      character*(*) filename
      print*,'writing ',trim(filename)
      open(8,file=filename,form='unformatted',status='unknown')
      write(8) mx,my,mz,nv
      write(8) xmin,xmax,ymin,ymax
      write(8) csp
      close(8)
      end subroutine

!!!!!!!!!!!!!!!!!!!!

      subroutine readcoeff(ios,csp,coeffile)
      ! allocates coefficient field
      ! reads the coefficients from coefficient file coeffile
      use spmm
      character*(*) coeffile
      real, allocatable :: csp(:)
      integer :: ios
      open(8,file=coeffile,form='unformatted',status='old',iostat=ios)
      if(ios>0) then
        print*,'readcoeff: Not opened: coefficient file',trim(coeffile)
        return
      end if
      read(8) mx,my,mz,nv
      read(8) xmin,xmax,ymin,ymax
      mx3 = mx+3-cix; my3 = my+3; mz3 = mz
      coeffSize = mx3*my3*mz3*nv
      hx=(xmax-xmin)/mx; hy=(ymax-ymin)/my
      allocate(csp(coeffSize))
      read(8) csp
      close(8)
      end subroutine

!!!!!!!!!!!!!!!!!!!!

      subroutine readcspmm(ios,c,filename)
      use spmm
      type(cspmm) :: c
      character*(*) filename
      open(8,file=filename,form='unformatted',status='old',iostat=ios)
      if(ios>0) then
        print*,'readcspmm: Not opened: coefficient file',trim(filename)
        return
      end if
      read(8) c%mx,c%my,c%mz,c%nv
      read(8) c%xmin,c%xmax,c%ymin,c%ymax
      mxc3 = c%mx+3-cix; myc3 = c%my+3; mzc3 = c%mz
      allocate(c%csp(mxc3,myc3,c%nv,mzc3))
      read(8) c%csp
      close(8)
      end subroutine

!!!!!!!!!!!!!!!!!!!!

      subroutine samplecspmm(c,x,y,outval)
      use spmm
      type(cspmm) :: c
      real x,y,outval
      mx=c%mx; my=c%my; mz=c%mz; nv=c%nv
      xmin=c%xmin; xmax=c%xmax; ymin=c%ymin; ymax=c%ymax
      mx3 = mx+3-cix; my3 = my+3; mz3 = mz
      coeffSize = mx3*my3*mz3*nv
      hx=(xmax-xmin)/mx; hy=(ymax-ymin)/my
      call spmPoint(1,1,c%csp,x,y,0,0,hx,hy,outval)
      end subroutine

!!!!!!!!!!!!!!!!!!!!

      subroutine outgrid(csp,L,gridfile,sstref)
      ! reads pathfinder grid file "gridfile",
      ! evaluates SST values at the grids from coefficient csp at scale L,
      ! adds "sstref" to each SST value,
      ! writes results to Fortran binary file:  fort.80+L
      use spmm
      real csp(*),sstref
      integer L
      character*(*) gridfile

      real :: badpixel,minsst
      parameter(badpixel=999.)  ! "bad pixel" value.
      parameter(minsst=-1.8)    ! minimum SST value in decC.

      real, allocatable::  sst(:,:),lon(:),lat(:)

      open(7,file=gridfile,form='unformatted',status='old',iostat=ios)
      if(ios>0) then
        print*,'ERROR: opening output-grid file',trim(gridfile)
        stop 'ABORT: mrva'
      end if
      read(7) nlon,nlat
      print*,'output grid size:',nlon,nlat
      allocate(lon(nlon),lat(nlat),sst(nlon,nlat))
      read(7) lon,lat,sst
      close(7)

      dx=(lon(nlon)-lon(1))/(nlon-1)
      dy=(lat(nlat)-lat(1))/(nlat-1)
      
      do j=1,nlat
        y=lat(j)
        do i=1,nlon
          x=lon(i)
          if (x.gt.180.) x=x-360.
          if (sst(i,j).lt.badpixel) then
            call spmPoint(1,1,csp,x,y,0,0,dx,dy,sst(i,j))
            if(sst(i,j).lt.minsst) sst(i,j)=minsst
            sst(i,j)=sst(i,j)+sstref
          else
            sst(i,j)=badpixel
          end if
        end do
      end do

      write(80+L) nlon,nlat
      write(80+L) sst,lon,lat
      deallocate(lon,lat,sst)
      end subroutine

!!!!!!!!!!!!!!!!!!!!

      subroutine outgridscaled(csp,L,gridfile,offset,sscale,minsst)
      ! reads pathfinder grid file "gridfile",
      ! evaluates SST values at the grids from coefficient csp at scale L,
      ! adds "sstref" to each SST value,
      ! writes results to Fortran binary file:  fort.180+L
      use spmm
      real csp(*),offset,sscale,minsst
      integer L
      character*(*) gridfile

      real :: sstref,sst
      parameter(sstref=273.15)

      real*4, allocatable::  lon(:),lat(:)
      integer*2, allocatable::  grid(:,:)

      open(7,file=gridfile,form='unformatted',status='old',iostat=ios)
      if(ios>0) then
        print*,'ERROR: opening output-grid file',trim(gridfile)
        stop 'ABORT: mrva'
      end if
      read(7) nlon,nlat
      print*,'output grid size:',nlon,nlat
      allocate(lon(nlon),lat(nlat))
      allocate(grid(nlon,nlat))
      read(7) grid,lon,lat
      close(7)

      dx=(lon(nlon)-lon(1))/(nlon-1)
      dy=(lat(nlat)-lat(1))/(nlat-1)
      
      ! apply netCDF-like transformation to SST; save to "grid(:,:)":
      do j=1,nlat
        y=lat(j)
        do i=1,nlon
          x=lon(i)
          if (grid(i,j).eq.0) then  ! "solid-land" pixel:
            grid(i,j)=-32768
          else  ! ==4 would be "inland water" but it's ok too:
            call spmPoint(1,1,csp,x,y,0,0,dx,dy,sst)
            sst=sst+sstref
            if(sst<minsst) sst=minsst
            grid(i,j)=nint( (sst-offset)/sscale )
          end if
        end do
      end do

      write(180+L) nlon,nlat
      write(180+L) offset,sscale
      write(180+L) grid,lon,lat
      deallocate(lon,lat,grid)
      end subroutine


!!!!!!!!!!!!!!!!!!!!

      subroutine outscaledgds(csp,L,gridfile,offset,sscale,minsst)
      ! reads GDS valued grid file "gridfile",
      ! evaluates SST values at the grids from coefficient csp at scale L,
      ! adds "sstref" to each SST value,
      ! writes results to Fortran binary file:  fort.180+L
      use spmm
      real csp(*),offset,sscale,minsst
      integer L
      character*(*) gridfile

      real :: sstref,sst
      parameter(sstref=273.15)

      real*4, allocatable::  lon(:),lat(:)
      integer*1, allocatable::  grid(:,:)
      integer*2, allocatable::  out(:,:)

      open(7,file=gridfile,form='unformatted',status='old',iostat=ios)
      if(ios>0) then
        print*,'ERROR: opening output-grid file',trim(gridfile)
        stop 'ABORT: mrva'
      end if
      read(7) nlon,nlat
      print*,'output grid size:',nlon,nlat
      allocate(lon(nlon),lat(nlat))
      allocate(grid(nlon,nlat))
      read(7) grid,lon,lat
      close(7)

      ! DEBUG: Print grid file coordinate ranges
      print*,'DEBUG outscaledgds: Grid file info:'
      print*,'  gridfile = ', trim(gridfile)
      print*,'  nlon,nlat = ', nlon, nlat
      print*,'  lon range = ', lon(1), ' to ', lon(nlon)
      print*,'  lat range = ', lat(1), ' to ', lat(nlat)
      print*,'  land pixels (grid==2) count = ', count(grid==2)
      print*,'  water pixels count = ', count(grid/=2)

      allocate(out(nlon,nlat))

      dx=(lon(nlon)-lon(1))/(nlon-1)
      dy=(lat(nlat)-lat(1))/(nlat-1)
      print*,'  dx,dy = ', dx, dy

      ! DEBUG: Check if grid lon/lat falls within coefficient domain
      print*,'DEBUG outscaledgds: Domain check:'
      print*,'  Coeff domain: x=[',xmin,',',xmax,'] y=[',ymin,',',ymax,']'
      print*,'  Grid domain:  x=[',lon(1),',',lon(nlon),
     &       '] y=[',lat(1),',',lat(nlat),']'
      if(lon(1).lt.xmin .or. lon(nlon).gt.xmax) then
        print*,'  WARNING: Grid lon outside coeff domain!'
      end if
      if(lat(1).lt.ymin .or. lat(nlat).gt.ymax) then
        print*,'  WARNING: Grid lat outside coeff domain!'
      end if

      ! apply netCDF-like transformation to SST; save to "grid(:,:)":
      ! DEBUG: Sample spmPoint at a few test locations before main loop
      print*,'DEBUG outscaledgds: Testing spmPoint at sample locations:'
      print*,'  Module state: mx,my = ', mx, my
      print*,'  Module state: xmin,xmax = ', xmin, xmax
      print*,'  Module state: ymin,ymax = ', ymin, ymax
      print*,'  Module state: hx,hy = ', hx, hy
      call spmPoint(1,1,csp,0.0,0.0,0,0,dx,dy,sst)
      print*,'  spmPoint(0,0) raw = ', sst, ' +sstref = ', sst+sstref
      call spmPoint(1,1,csp,-120.0,30.0,0,0,dx,dy,sst)
      print*,'  spmPoint(-120,30) raw = ', sst, ' +sstref = ', sst+sstref
      call spmPoint(1,1,csp,0.0,-60.0,0,0,dx,dy,sst)
      print*,'  spmPoint(0,-60) raw = ', sst, ' +sstref = ', sst+sstref

      do j=1,nlat
        y=lat(j)
        do i=1,nlon
          x=lon(i)
          if (grid(i,j).eq.2) then  ! "solid-land" pixel:
            out(i,j)=-32768
          else  ! ==4 would be "inland water" but it's ok too:
            call spmPoint(1,1,csp,x,y,0,0,dx,dy,sst)
            sst=sst+sstref
            if(sst<minsst) sst=minsst
            out(i,j)=nint( (sst-offset)/sscale )
          end if
        end do
      end do

      ! DEBUG: Print SST range statistics after computation
      print*,'DEBUG outscaledgds: Output statistics:'
      print*,'  offset = ', offset, ' sscale = ', sscale
      print*,'  sstref = ', sstref, ' minsst = ', minsst
      print*,'  int16 range (excl -32768) = ',
     &       minval(out, out.ne.-32768), maxval(out, out.ne.-32768)
      print*,'  SST range (K) = ',
     &       minval(out, out.ne.-32768)*sscale+offset,
     &       maxval(out, out.ne.-32768)*sscale+offset
      print*,'  SST range (C) = ',
     &       minval(out, out.ne.-32768)*sscale+offset-273.15,
     &       maxval(out, out.ne.-32768)*sscale+offset-273.15

      write(180+L) nlon,nlat
      write(180+L) offset,sscale
      write(180+L) out,lon,lat
      deallocate(lon,lat,grid,out)
      end subroutine



!!!!!!!!!!!!!!!!!!!!

      subroutine outovergds(csp,L,gridfile,offset,sscale)
      ! same as "outscaledgds" above, except:
      !  -- no scaling by 273.15 (no assumption that it's SST field),
      !  -- no minimum floor value enforced (again no SST assumption).
      ! It does:
      !   -- place "badpixel=-32768" value over where gds==2,
      !   -- scale and offset the valid output values,
      !   -- return the main output as an integer*2 array.
      !   -- save the output in file "fort.180+L"
      ! Choose any arbitrary natural number for L; your choice.
      use spmm
      real csp(*),offset,sscale,minsst
      integer L
      character*(*) gridfile

      real :: sstref,sst

      real*4, allocatable::  lon(:),lat(:)
      integer*1, allocatable::  grid(:,:)
      integer*2, allocatable::  out(:,:)

      open(7,file=gridfile,form='unformatted',status='old',iostat=ios)
      if(ios>0) then
        print*,'ERROR: opening output-grid file',trim(gridfile)
        stop 'ABORT: mrva'
      end if
      read(7) nlon,nlat
      print*,'output grid size:',nlon,nlat
      allocate(lon(nlon),lat(nlat))
      allocate(grid(nlon,nlat))
      read(7) grid,lon,lat
      close(7)

      allocate(out(nlon,nlat))

      dx=(lon(nlon)-lon(1))/(nlon-1)
      dy=(lat(nlat)-lat(1))/(nlat-1)
      
      ! apply netCDF-like transformation to SST; save to "grid(:,:)":
      do j=1,nlat
        y=lat(j)
        do i=1,nlon
          x=lon(i)
          if (grid(i,j).eq.2) then  ! "solid-land" pixel:
            out(i,j)=-32768
          else  ! ==4 would be "inland water" but it's ok too:
            call spmPoint(1,1,csp,x,y,0,0,dx,dy,sst)
            out(i,j)=nint( (sst-offset)/sscale )
          end if
        end do
      end do

      write(180+L) nlon,nlat
      write(180+L) offset,sscale
      write(180+L) out,lon,lat
      deallocate(lon,lat,grid,out)
      end subroutine



!!!!!!!!!!!!!!!!!!!!

      subroutine writestdcoeff(filename)
      use spmm
      character*(*) filename
      real, allocatable :: cstd(:,:)
      real small; parameter(small=1.0e-8)  ! define a "practically zero" value.
      allocate(cstd(-1:mx+1-cix,-1:my+1))
      jblk=max(1,my3/nProcessors)
!$OMP  PARALLEL DO PRIVATE(i,j) SCHEDULE(STATIC,jblk)
      do j=-1,my+1
      do i=-1,mx+1-cix
#ifdef MATRIX_FREE
        cstd(i,j)=get_diagonal_mf(i,j,1,1)
#else
        cstd(i,j)=infoMatrix(i,j,0,0,1,1,1)
#endif
        if(cstd(i,j).lt.small) cstd(i,j)=small
        cstd(i,j)=1./sqrt(cstd(i,j))
      end do
      end do
!$OMP  END PARALLEL DO
      print*,'writing ',trim(filename)
      open(8,file=filename,form='unformatted',status='unknown')
      write(8) mx,my,mz,nv
      write(8) xmin,xmax,ymin,ymax
      write(8) cstd
      close(8)
      deallocate(cstd)
      end subroutine

!!!!!!!!!!!!!!!!!!!!

      subroutine writevarcoeff(filename)
      use spmm
      character*(*) filename
      real, allocatable :: cstd(:,:)
      real small; parameter(small=1.0e-8)  ! define a "practically zero" value.
      allocate(cstd(-1:mx+1-cix,-1:my+1))
      jblk=max(1,my3/nProcessors)
!$OMP  PARALLEL DO PRIVATE(i,j) SCHEDULE(STATIC,jblk)
      do j=-1,my+1
      do i=-1,mx+1-cix
#ifdef MATRIX_FREE
        cstd(i,j)=get_diagonal_mf(i,j,1,1)
#else
        cstd(i,j)=infoMatrix(i,j,0,0,1,1,1)
#endif
        if(cstd(i,j).lt.small) cstd(i,j)=small
        cstd(i,j)=1./(cstd(i,j))
      end do
      end do
!$OMP  END PARALLEL DO
      print*,'writing ',trim(filename)
      open(8,file=filename,form='unformatted',status='unknown')
      write(8) mx,my,mz,nv
      write(8) xmin,xmax,ymin,ymax
      write(8) cstd
      close(8)
      deallocate(cstd)
      end subroutine

!!!!!!!!!!!!!!!!!!!!


      end module

