      program nearestneighbor
! finds the nearest neighbor in (x0,y0) for each element in (x1,y1).
! Use parallelization to compile! e.g.,  ifort -openmp nearest.f

! mike chin, 10.6.1

      integer*4 :: n0,n1
      real*4, allocatable :: x0(:),y0(:),x1(:),y1(:),nearestdistance(:)
      integer*4, allocatable :: neighborindex(:)
      real, allocatable :: dist2(:)

      integer :: percentdisplay
      parameter(percentdisplay=100000)

      open(7,file='nninput.dat',form='unformatted',status='old')
      read(7) n0,n1
      allocate(x0(n0),y0(n0),x1(n1),y1(n1))
      read(7) x0,y0
      read(7) x1,y1
      close(7)

      if(.true.) then
        print*,n0,n1
        print*,x0(1),x0(n0),y0(1),y0(n0)
        print*,x1(1),x1(n1),y1(1),y1(n1)
      end if

!      allocate(dist2(n0),nearestdistance(n1),neighborindex(n1))
      allocate(nearestdistance(n1),neighborindex(n1))
!$OMP  PARALLEL DO PRIVATE(m,n,dist2) 
      do n=1,n1
        allocate(dist2(n0))
        dist2(:) = abs(x0(:)-x1(n))
        do m=1,n0
          if(dist2(m)>360.) dist2(m)=dist2(m)-360.  ! cyclic longitude.
        end do
        dist2(:) = dist2(:)**2 + (y0(:)-y1(n))**2
        nearestdistance(n) = sqrt(minval(dist2))
        neighborindex(n) = minloc(dist2,dim=1)
        if(mod(n+1,percentdisplay).eq.0) print*,real(n)/real(n1)*100,'%'
        deallocate(dist2)
      end do
!$OMP  END PARALLEL DO


      open(8,file='nnoutput.dat',form='unformatted',status='unknown')
      write(8) n1
      write(8) nearestdistance,neighborindex
      close(8)

      end program
