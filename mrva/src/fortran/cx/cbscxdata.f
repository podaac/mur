      program cbscxdata

      use spmm

      ! inputs:
      integer*4 :: nd
      real*4 :: weight
      real*4, dimension(:), allocatable:: xx,yy,dd,ww

      ! parameters:
      real*4 :: x0,x1,y0,y1,dx,dy
      real*4 :: wx,wy,wxx,wyy,wxy
      real*4 :: epsln,betamin

      real, allocatable:: w1(:,:),w2(:,:),w11(:,:),w22(:,:),w12(:,:)
      real, allocatable:: lon(:),lat(:)

      ! outputs:
      real, allocatable:: csp(:)

      ! defaults smoothness:
      data wx,wy,wxx,wyy,wxy/0.005,0.005,0.01,0.01,0.02/
      data epsln, betamin / 1.0e-8, 1.0e3 /


      namelist /input/ x0,x1,y0,y1,dx,dy,wx,wy,wxx,wyy,wxy


!      
! read and close files:
!

      ! read inputs:
      open(7,file='cbsinput.dat',form='unformatted',status='old',iostat=ios)
      if (ios.ne.0) then
          print*,'CBS: Error opening "cbsinput.dat"; aborted'
          stop
      else
          read(7) nd,weight
          allocate(xx(nd),yy(nd),dd(nd),ww(nd))
          if (weight.le.0.0) then
              read(7) xx,yy,dd,ww
          else
              read(7) xx,yy,dd
              ww(:)=weight
          endif
          close(7)
      endif

      ! read parameters:
      open(9,file='cbsdata.nml',form='formatted',status='old',iostat=ios)
      if (ios.eq.0) then  ! read them from the nml file:
        read(9,nml=input)
        close(9)
      else  ! use defaults:
        x0=minval(xx(:))
        x1=maxval(xx(:))
        y0=minval(yy(:))
        y1=maxval(yy(:))
        dx=sqrt( ((x1-x0)*(y1-y0))/real(nd) )
        dy=dx
      endif
        
      print*,'CBS: parameters:'
      print*,x0,x1,y0,y1,dx,dy
      print*,wx,wy,wxx,wyy,wxy

      
!      
! spm domain:
!
      mz=1
      nv=1
      hx = x1-x0
      hy = y1-y0
      mx0 = nint( hx/dx +0.5 )
      my0 = nint( hy/dy +0.5 )
      hx = abs(dx*mx0 - hx)/2
      hy = abs(dy*my0 - hy)/2
      xmin=x0
      xmax=x1
      if(cix==0) xmin=x0-hx
      if(cix==0) xmax=x1+hx
      ymin=y0-hy
      ymax=y1+hy
      mx=mx0
      my=my0


!
! spm:
!

      call spmInit

!      call spmThinPlate(wx,wy,wxx,wyy,wxy,1,1)
      allocate(w1(mx3,my3),w2(mx3,my3),lon(mx3),lat(my3))
      allocate(w11(mx3,my3),w22(mx3,my3),w12(mx3,my3))
          call spmXY(lon,lat)
          deg2rad=atan(1.)*4./180.
          do j=1,my3
          do i=1,mx3
            w1(i,j)=1./max( (cos(lat(j)*deg2rad))**2, 0.03)
            w11(i,j)=1./max( (cos(lat(j)*deg2rad))**4, 0.03)
            w12(i,j)=1./max( (cos(lat(j)*deg2rad))**2, 0.03)
          end do
          end do
          c=1.
          w11(:,:)=c*wxx*w11(:,:)
          w1(:,:)=c*wx*w1(:,:)
          w12(:,:)=c*wxy*w12(:,:)
          w2(:,:)=c*wy; w22(:,:)=c*wyy
      call spmThinPlateIJ(w1,w2,w11,w22,w12,1,1)
      deallocate(w1,w2,lon,lat,w11,w22,w12)


      call spmData(1,1,xx,yy,dd,ww,nd)

      allocate(csp(coeffSize)); csp=0.0
      call spmPCG(csp,mx3*my3,epsln,betamin)


      call writecoeff(csp,'cbsdata.out')

      end program


!!!!!!!!!!!!!!!!!!!!

      subroutine writecoeff(csp,filename)
      ! saves the coefficients to file:  fort.60+L
      use spmm
      real csp(coeffSize)
      character*(*) filename
      open(8,file=filename,form='unformatted')
      write(8) mx,my,mz,nv
      write(8) xmin,xmax,ymin,ymax
      write(8) csp
      close(8)
      end subroutine

