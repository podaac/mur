      program nearestneighbor
! finds the nearest neighbor in (x0,y0) for each element in (x1,y1).
! Use parallelization to compile! e.g.,  ifort -openmp nearest2.f

! mike chin, 10.6.1
!            12.1.18

      integer*4 :: n0,n1
      real*4, allocatable :: x0(:),y0(:),x1(:),y1(:),nearestdistance(:)
      integer*4, allocatable :: neighborindex(:)
      real*4 :: minDist,d,dx,dy,dmin

      integer :: percentdisplay
      parameter(percentdisplay=100000)

      open(7,file='nninput.dat',form='unformatted',status='old')
      read(7) n0,n1
      allocate(x0(n0),y0(n0),x1(n1),y1(n1))
      read(7) x0,y0
      read(7) x1,y1
      read(7) minDist
      close(7)

      if(.true.) then
        print*,n0,n1,minDist
        print*,x0(1),x0(n0),y0(1),y0(n0)
        print*,x1(1),x1(n1),y1(1),y1(n1)
      end if

      deg2rad=acos(-1.)/180.

!      allocate(dist2(n0),nearestdistance(n1),neighborindex(n1))
      allocate(nearestdistance(n1),neighborindex(n1))
!$OMP  PARALLEL DO PRIVATE(m,n,d,dx,dy,dmin,nsum,k) 
      do n=1,n1
        dmin=500.  ! initialize to an impossibly large distance [deg].
        dmin=dmin*dmin  ! work with squared distance.
        neighborindex(n)=0
        do m=1,n0
            dy=abs(y0(m)-y1(n))
            if(dy<=minDist) then
              dx=abs(x0(m)-x1(n))
              if(dx>360.) dx=dx-360.
              ! ~equatorial distance:
              dx=dx*cos( max(abs(y0(m)),abs(y1(n)))*deg2rad )  
              if(dx<=minDist) then
                d=dx*dx+dy*dy
                if(d<dmin) then
                  dmin=d
                  neighborindex(n)=m
                end if
              end if
            end if
        end do
        nearestdistance(n)=sqrt(dmin)

!        if(mod(n+1,percentdisplay).eq.0) print*,real(n)/real(n1)*100,'%'
        if(mod(n+1,percentdisplay).eq.0) then
          nsum=0
          do k=1,n1
            if(neighborindex(k)==0) nsum=nsum+1
          end do
          print*,real(nsum)/real(n1)*100,'%'
        end if

      end do
!$OMP  END PARALLEL DO


      open(8,file='nnoutput.dat',form='unformatted',status='unknown')
      write(8) n1
      write(8) nearestdistance,neighborindex
      close(8)

      end program
