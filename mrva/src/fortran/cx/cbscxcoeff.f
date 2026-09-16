      program cbscxcoeff

      use spmm

      ! interpolant locations:
      integer*4 :: nx,ny,nd
      real*4,dimension(:),allocatable :: xo,yo
      logical :: grid

      ! spm data:
      real, allocatable:: csp(:)

      ! output:
      integer*4 :: lx,ly  ! differentiation orders.
      real*4,dimension(:),allocatable :: zo



!
! read locations:
!
      open(7,file='cbspoints.dat',form='unformatted',status='old',iostat=ios)
      if(ios.ne.0) then
        print*,'CBS Error opening "cbspoints.dat"; aborted'
        stop
      endif

      read(7) nx,ny,lx,ly
      if(nx*ny.gt.0) then
            grid=.true.
            allocate(xo(nx),yo(ny))
            allocate(zo(nx*ny))
      else
            grid=.false.
            nd=abs(nx*ny)
            allocate(xo(nd),yo(nd))
            allocate(zo(nd))
      endif
      read(7) xo,yo
      close(7)



!      
! read coefficient file:
!

      open(8,file='cbsdata.out',form='unformatted',status='old',iostat=ios)
      if(ios.ne.0) then
        print*,'CBS Error opening "cbsdata.lout"; abort'
        stop
      end if
      read(8) mx,my,mz,nv
      read(8) xmin,xmax,ymin,ymax
      mx3 = mx+3-cix; my3 = my+3; mz3 = mz
      coeffSize = mx3*my3*mz3*nv
      hx=(xmax-xmin)/mx; hy=(ymax-ymin)/my
      allocate(csp(coeffSize))
      read(8) csp
      close(8)

!
! interpolate:
!



      if(grid) then
            do j=1,ny
            do i=1,nx
              k=nx*(j-1)+i
              call spmpoint(1,1,csp,xo(i),yo(j),lx,ly,1.,1.,zo(k))
            enddo
            enddo
      else
            do k=1,nd
              call spmpoint(1,1,csp,xo(k),yo(k),lx,ly,1.,1.,zo(k))
            enddo
      endif

      deallocate(csp)



!
! write out:
!

      open(8,file='cbs.out',form='unformatted')
      write(8) zo
      close(8)

      end program


