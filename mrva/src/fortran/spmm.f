!! spmm.f  (SP Multivariate Module)


!! release, 13.01.10
!! release, 10.11.03
!! info pair is double precision, 09.2

      module spmm

      integer nProcessors
!      parameter(nProcessors=24)  !! for OpenMP
      parameter(nProcessors=64)  !! for OpenMP

      integer cix
      parameter(cix=3)

      real weightmin
      parameter(weightmin=0.01)

      integer mx, my
      integer mz
      integer nv
      real xmin,xmax,ymin,ymax

      real hx, hy
      integer mx3,my3,mz3
      integer coeffSize
      integer infoSize

! Storage precision for infoMatrix ONLY. real*4 by default; build with
! -DINFOMATRIX_R8 to restore real*8.
!
! infoMatrix is 49 reals per coefficient and dominates everything else. At
! L=11 the working set is 55.48 GiB with real*8, of which infoMatrix is
! 49.43. In real*4 that becomes 24.72, for 30.77 GiB total.
!
! real*4 is the DEFAULT because real*8 does not fit anywhere we can run. The
! largest usable DPS pool is 64 GiB, production peaks near 72 GB at L=11 once
! MATLAB -- still resident while this runs -- is counted, and the one 64 GiB
! pool with more cores cannot reach the Docker socket. A real*8 build is
! therefore not a fallback we can select; it is a configuration with no
! machine. Leaving it the default would mean shipping something that cannot
! execute.
!
! Why single precision is defensible here -- it is already the precision this
! solver works in everywhere else:
!   - the PCG vectors r,p,z,w and the arrays behind them (u,v,h) are real*4
!   - csp/dsp, the coefficients being solved for, are real*4
!   - there is no implicit none in this file, so rhoNew -- the convergence
!     reduction, sum(r*z) over every coefficient -- is real*4 as well
!   - the preconditioner is diagonal (diagPCG=.true.), and nothing here is
!     factorized: the pointer named L is the thin-plate stencil accumulator,
!     not a Cholesky factor
!   - mrva.f already loosens the tolerance to 1.0e-3 for L>=9, far above what
!     real*4 can resolve
! So real*8 on the matrix was the last double in a single-precision solver,
! and the convergence test could not perceive the digits it cost 25 GiB for.
!
! infoVector stays real*8: it is the right-hand side, it is 1.01 GiB, and
! halving it would save nothing worth arguing about.
!
! STILL UNVALIDATED. The obvious check -- process a day both ways and diff --
! cannot be run, because the real*8 side does not fit. Validation is therefore
! against PRODUCTION output for the same day, which is the real reference
! anyway. Until that comparison exists, treat any L4 granule this produces as
! provisional. A cheaper partial check is available if wanted: at LF=9 both
! precisions fit easily (3.46 GiB), so a reduced-level run could be diffed
! both ways to catch a gross error, though it would not exercise L=10-11.
#ifdef INFOMATRIX_R8
      integer, parameter :: imk = 8
#else
      integer, parameter :: imk = 4
#endif

! Matrix-free mode: comment out infoMatrix allocation to save memory
! MATRIX_FREE mode computes stencil coefficients on-the-fly
#ifndef MATRIX_FREE
      real(imk), allocatable, target :: infoMatrix(:,:,:,:,:,:,:)
#endif
      real*8, allocatable, target :: infoVector(:,:,:,:)

      real S00(-3:3,-3:3),S11(-3:3,-3:3),S22(-3:3,-3:3)
      real S01(-3:3,-3:3),S10(-3:3,-3:3)

! Matrix-free: store weight matrices for on-the-fly computation
      real, allocatable :: wx_mf(:,:), wy_mf(:,:)
      real, allocatable :: wxx_mf(:,:), wyy_mf(:,:), wxy_mf(:,:)
 

      contains


!!   spmInit, 02.6, 08.8
!!   spmRefresh, 08.8
!!   spmXY, 10.8
!!   spmDoubleGrid, 95.3
!!   spmDiagonal, 02.6, 08.8
!!   spmThinPlate, 02.6, 08.8, 09.4
!!   spmDirectThin, 10.8
!!   spmThinPlateIJ, 10.8
!!   spmDirectThinIJ, 10.8
!!   spmBoundary, spmIJThin, 09.2
!!   spmHNSdata, 09.9
!!   spmData, 02.7, 08.8, 08.11 ,09.8
!!   spmDataScale, 08.11, 09.4 ,09.8
!!   spmDataScaleP, 08.11, 09.4 ,09.8
!!   spmDataScaleQ, 10.2
!!   spmDataWithBiasScale, 13.1
!!   spmDataWithBiasScaleQ, 13.1
!!   spmRhoWeightScale, 08.11
!!   spmPoint, 02.6
!!   bsp3, 86.11
!!   spmSOR, 02.6, 08.8
!!   spmPCG, 02.7, 08.8, 09.4


!!!!!!!!!!
      subroutine spmInit

      integer iS00(-3:3,-3:3),iS11(-3:3,-3:3),iS22(-3:3,-3:3)
      integer iS01(-3:3,-3:3),iS10(-3:3,-3:3)

      data iS00/ 
     .      0,      0,      0,     20,    129,     60,      1,
     .      0,      0,    129,   1208,   1062,    120,      1,
     .      0,     60,   1062,   2396,   1191,    120,      1,
     .      1,    120,   1191,   2416,   1191,    120,      1,
     .      1,    120,   1191,   2396,   1062,     60,      0,
     .      1,    120,   1062,   1208,    129,      0,      0,
     .      1,     60,    129,     20,      0,      0,      0/
      data iS11/
     .      0,      0,      0,      6,      7,    -12,     -1,
     .      0,      0,      7,     40,    -22,    -24,     -1,
     .      0,    -12,    -22,     74,    -15,    -24,     -1,
     .     -1,    -24,    -15,     80,    -15,    -24,     -1,
     .     -1,    -24,    -15,     74,    -22,    -12,      0,
     .     -1,    -24,    -22,     40,      7,      0,      0,
     .     -1,    -12,      7,      6,      0,      0,      0/
      data iS22/
     .      0,      0,      0,      2,     -3,      0,      1,
     .      0,      0,     -3,      8,     -6,      0,      1,
     .      0,      0,     -6,     14,     -9,      0,      1,
     .      1,      0,     -9,     16,     -9,      0,      1,
     .      1,      0,     -9,     14,     -6,      0,      0,
     .      1,      0,     -6,      8,     -3,      0,      0,
     .      1,      0,     -3,      2,      0,      0,      0/
      data iS01/ 
     .      0,      0,      0,    -10,     -9,     18,      1,
     .      0,      0,    -71,   -160,    174,     56,      1,
     .      0,    -38,   -254,    -10,    245,     56,      1,
     .     -1,    -56,   -245,      0,    245,     56,      1,
     .     -1,    -56,   -245,     10,    254,     38,      0,
     .     -1,    -56,   -174,    160,     71,      0,      0,
     .     -1,    -18,      9,     10,      0,      0,      0/
      data iS10/ 
     .      0,      0,      0,    -10,    -71,    -38,     -1,
     .      0,      0,     -9,   -160,   -254,    -56,     -1,
     .      0,     18,    174,    -10,   -245,    -56,     -1,
     .      1,     56,    245,      0,   -245,    -56,     -1,
     .      1,     56,    245,     10,   -174,    -18,      0,
     .      1,     56,    254,    160,      9,      0,      0,
     .      1,     38,     71,     10,      0,      0,      0/

      do j=-3,3
      do i=-3,3
        S00(i,j)=real(iS00(j,i))/5040.
        S11(i,j)=real(iS11(j,i))/120.
        S22(i,j)=real(iS22(j,i))/6. 
        S01(i,j)=real(iS01(j,i))/720.
        S10(i,j)=real(iS10(j,i))/720.
      end do
      end do

      mx3 = mx+3-cix
      my3 = my+3
      mz3 = mz
      coeffSize = mx3*my3*mz3*nv
      infoSize = coeffSize*49*nv

      hx=(xmax-xmin)/mx
      hy=(ymax-ymin)/my

#ifndef MATRIX_FREE
      allocate(infoMatrix(-1:mx+1-cix,-1:my+1,-3:3,-3:3,nv,nv,mz3))
      infoMatrix=0.
#else
      ! Matrix-free mode: allocate weight matrices instead
      allocate(wx_mf(-1:mx+1-cix,-1:my+1))
      allocate(wy_mf(-1:mx+1-cix,-1:my+1))
      allocate(wxx_mf(-1:mx+1-cix,-1:my+1))
      allocate(wyy_mf(-1:mx+1-cix,-1:my+1))
      allocate(wxy_mf(-1:mx+1-cix,-1:my+1))
      wx_mf=0.; wy_mf=0.; wxx_mf=0.; wyy_mf=0.; wxy_mf=0.
      print*,'MATRIX-FREE MODE: No infoMatrix allocation'
      print*,'  Memory saved: ~',infoSize*8/(1024**3),'GB'
#endif
      allocate(infoVector(-1:mx+1-cix,-1:my+1,nv,mz3))
      infoVector=0.

      end subroutine

!!!!!!!!!!
      subroutine spmRefresh

#ifndef MATRIX_FREE
      deallocate(infoMatrix,infoVector)
#else
      deallocate(wx_mf,wy_mf,wxx_mf,wyy_mf,wxy_mf)
      deallocate(infoVector)
#endif

      mx3 = mx+3-cix
      my3 = my+3
      mz3 = mz
      coeffSize = mx3*my3*mz3*nv
      infoSize = coeffSize*49*nv

      hx=(xmax-xmin)/mx
      hy=(ymax-ymin)/my

#ifndef MATRIX_FREE
      allocate(infoMatrix(-1:mx+1-cix,-1:my+1,-3:3,-3:3,nv,nv,mz3))
      infoMatrix=0.
#else
      ! Matrix-free mode: reallocate weight matrices
      allocate(wx_mf(-1:mx+1-cix,-1:my+1))
      allocate(wy_mf(-1:mx+1-cix,-1:my+1))
      allocate(wxx_mf(-1:mx+1-cix,-1:my+1))
      allocate(wyy_mf(-1:mx+1-cix,-1:my+1))
      allocate(wxy_mf(-1:mx+1-cix,-1:my+1))
      wx_mf=0.; wy_mf=0.; wxx_mf=0.; wyy_mf=0.; wxy_mf=0.
#endif
      allocate(infoVector(-1:mx+1-cix,-1:my+1,nv,mz3))
      infoVector=0.

      end subroutine

!!!!!!!!!!
      subroutine spmXY(x,y)
      real x(-1:mx+1-cix)
      real y(-1:my+1)
      do i=-1,mx+1-cix
        x(i)=hx*i+hx/2+xmin+(cix*hx)/3
      end do
      do j=-1,my+1
        y(j)=hy*j+hy/2+ymin
      end do
      end subroutine

!!!!!!!!!!
      subroutine spmDoubleGrid(c,nx,ny,d)
      integer nx,ny
      real c(nx+3-cix,ny+3),d(nx*2+3-cix,ny*2+3)
      jblk=max((ny+3)/nProcessors,1)
!$OMP  PARALLEL DO PRIVATE(i,j,temp1,temp2)
!$OMP& SCHEDULE(STATIC,jblk)
      
      do j=1,(ny+3)
        do i=(nx+1-cix),1,-1
          d(i*2+1,j)=(c(i+1,j)+c(i+2,j))*0.500
          d(i*2,j)=(c(i,j)+6.*c(i+1,j)+c(i+2,j))*0.125
        enddo
        d(1,j)=(c(1,j)+c(2,j))*0.500
        if(cix>0) then  
          d(nx*2-2,j)=(c(nx-1,j)+6.*c(nx,j)+c(1,j))*0.125
          d(nx*2-1,j)=(c(nx,j)+c(1,j))*0.500
          d(nx*2,  j)=(c(nx,j)+6.*c(1,j)+c(2,j))*0.125
        end if
      enddo
!$OMP  END PARALLEL DO
      jblk=max((nx*2+3-cix)/nProcessors,1)
!$OMP  PARALLEL DO PRIVATE(i,j,temp1,temp2)
!$OMP& SCHEDULE(STATIC,jblk)
      
      do i=1,(nx*2+3-cix)
        do j=(ny+1),2,-1
          d(i,j*2+1)=(d(i,j+1)+d(i,j+2))*0.500
          d(i,j*2)=(d(i,j)+6.*d(i,j+1)+d(i,j+2))*0.125
        enddo
        temp1=d(i,1)
        temp2=d(i,2)
        d(i,1)=(temp1+temp2)*0.500
        d(i,2)=(temp1+6.*temp2+d(i,3))*0.125
        d(i,3)=(temp2+d(i,3))*0.500
      enddo
!$OMP  END PARALLEL DO
      end subroutine

!!!!!!!!!!
      subroutine spmDiagonal(w,n)
#ifndef MATRIX_FREE
      real(imk), pointer :: Asp(:,:,:,:,:,:,:)
      Asp=>infoMatrix
      do k=1,mz3
      do j=-1,my+1
      do i=-1,mx+1-cix
        Asp(i,j,0,0,n,n,k)=Asp(i,j,0,0,n,n,k)+w
      end do
      end do
      end do
#endif
      end subroutine

!!!!!!!!!!
      subroutine spmThinPlate(wx,wy,wxx,wyy,wxy,n,k)
      real wx,wy,wxx,wyy,wxy
      integer n,k

#ifndef MATRIX_FREE
      real*8, pointer :: bsp(:,:,:,:)
      real(imk), pointer :: Asp(:,:,:,:,:,:,:)
      bsp=>infoVector
      Asp=>infoMatrix

      jblk=max(my3/nProcessors,1)
!$OMP  PARALLEL DO SCHEDULE(STATIC,jblk)
!$OMP& PRIVATE(i,j,ki,lj,kia,kib,lja,ljb,irS,icS,jrS,jcS)
      do j=-1,my+1
        if(j.le.1) then  
          lja=-1-j
          ljb=3
          jrS=-3-lja
        elseif(j.ge.my-1) then  
          lja=-3
          ljb=my+1-j
          jrS=3-ljb
        else  
          lja=-3
          ljb=3
          jrS=0
        endif
      do i=-1,mx+1-cix
        if(i.le.1.and.cix==0) then  
          kia=-1-i
          kib=3
          irS=-3-kia
        elseif(i.ge.mx-1.and.cix==0) then  
          kia=-3
          kib=mx+1-i
          irS=3-kib
        else  
          kia=-3
          kib=3
          irS=0
        endif
      do lj=lja,ljb
        jcS=lj
      do ki=kia,kib
        icS=ki
        !!!
        Asp(i,j,ki,lj,n,n,k)=Asp(i,j,ki,lj,n,n,k)
     .                +wx*S11(irS,icS)*S00(jrS,jcS)
     .                +wy*S00(irS,icS)*S11(jrS,jcS)
     .                +wxx*S22(irS,icS)*S00(jrS,jcS)
     .                +wyy*S00(irS,icS)*S22(jrS,jcS)
     .                +wxy*S11(irS,icS)*S11(jrS,jcS)
        !!!
      end do
      end do
      end do
      end do
!$OMP  END PARALLEL DO
#endif
      end subroutine

!!!!!!!!!!
      subroutine spmDirectThin(wx,wy,wxx,wyy,wxy,n,k)
      real wx,wy,wxx,wyy,wxy
      integer n,k

#ifndef MATRIX_FREE
      real*8 L1(-1:1,-2:2),L2(-2:2,-2:2)
      real(imk), pointer :: L(:,:,:,:,:,:,:)
      L=>infoMatrix

      L1(:,:)=0.; L1(0:1,-1)=-1.; L1(-1:0,1)=-1.
      L1(-1,0)=1.; L1(1,0)=1.; L1(0,0)=2.
      L1(:,:)=L1(:,:)/2.

      L2(:,:)=0.; L2(0:2,-2)=1.; L2(-2:0,2)=1.
      L2(-2,1)=-2.; L2(-1,-1)=-2.; L2(1,1)=-2.; L2(2,-1)=-2.
      L2(-1,1)=-4.; L2(0,-1)=-4.; L2(0,1)=-4.; L2(1,-1)=-4.
      L2(-2,0)=1.; L2(2,0)=1.; L2(-1,0)=5.; L2(1,0)=5.; L2(0,0)=6.
      L2(:,:)=L2(:,:)/6.

      jblk=max(my3/nProcessors,1)
!$OMP  PARALLEL DO SCHEDULE(STATIC,jblk)
!$OMP& PRIVATE(i,j,i1,i2,j1,j2)
      do j=-1,my+1
        j1=0
        if(j==-1)   j1=-1
        if(j==my+1) j1=1
        j2=0
        if(j==-1)  j2=-2
        if(j==0)   j2=-1
        if(j==my)  j2=1
        if(j==my+1)j2=2
      do i=-1,mx+1-cix
        i1=0
        i2=0
        if(cix==0) then
          if(i==-1)   i1=-1
          if(i==mx+1) i1=1
          if(i==-1)  i2=-2
          if(i==0)   i2=-1
          if(i==mx)  i2=1
          if(i==mx+1)i2=2
        end if
        !!!
        L(i,j,-2:2,0,n,n,k)=L(i,j,-2:2,0,n,n,k)+wx*L1(i1,-2:2)
     .                                        +wxx*L2(i2,-2:2)
        L(i,j,0,-2:2,n,n,k)=L(i,j,0,-2:2,n,n,k)+wy*L1(j1,-2:2)
     .                                        +wyy*L2(j2,-2:2)
        !!!
        if(i1==0.and.j1==0) then
          ww=wxy*0.25
          L(i,j,0,0,n,n,k)=L(i,j,0,0,n,n,k)+wxy
          L(i,j,0,-1,n,n,k)=L(i,j,0,-1,n,n,k)-ww
          L(i,j,0,1,n,n,k)=L(i,j,0,1,n,n,k)-ww
          L(i,j,-1,0,n,n,k)=L(i,j,-1,0,n,n,k)-ww
          L(i,j,1,0,n,n,k)=L(i,j,1,0,n,n,k)-ww
        end if
        !!!
      end do
      end do
!$OMP  END PARALLEL DO
#endif
      end subroutine

!!!!!!!!!!
      subroutine spmThinPlateIJ(wx,wy,wxx,wyy,wxy,n,k)
      real wx(-1:mx+1-cix,-1:my+1),wy(-1:mx+1-cix,-1:my+1)
      real wxx(-1:mx+1-cix,-1:my+1),wyy(-1:mx+1-cix,-1:my+1)
      real wxy(-1:mx+1-cix,-1:my+1)
      integer n,k

#ifdef MATRIX_FREE
      ! Matrix-free mode: store weights for later use in matvec
      wx_mf = wx
      wy_mf = wy
      wxx_mf = wxx
      wyy_mf = wyy
      wxy_mf = wxy
      ! No stencil computation needed - done on-the-fly in matvec
      return
#endif

#ifndef MATRIX_FREE
      real*8, pointer :: bsp(:,:,:,:)
      real(imk), pointer :: Asp(:,:,:,:,:,:,:)
      bsp=>infoVector
      Asp=>infoMatrix

      jblk=max(my3/nProcessors,1)
!$OMP  PARALLEL DO SCHEDULE(STATIC,jblk)
!$OMP& PRIVATE(i,j,ki,lj,kia,kib,lja,ljb,irS,icS,jrS,jcS)
      do j=-1,my+1
        if(j.le.1) then  
          lja=-1-j
          ljb=3
          jrS=-3-lja
        elseif(j.ge.my-1) then  
          lja=-3
          ljb=my+1-j
          jrS=3-ljb
        else  
          lja=-3
          ljb=3
          jrS=0
        endif
      do i=-1,mx+1-cix
        if(i.le.1.and.cix==0) then  
          kia=-1-i
          kib=3
          irS=-3-kia
        elseif(i.ge.mx-1.and.cix==0) then  
          kia=-3
          kib=mx+1-i
          irS=3-kib
        else  
          kia=-3
          kib=3
          irS=0
        endif
      do lj=lja,ljb
        jcS=lj
      do ki=kia,kib
        icS=ki
        !!!
        Asp(i,j,ki,lj,n,n,k)=Asp(i,j,ki,lj,n,n,k)
     .                +wx(i,j)*S11(irS,icS)*S00(jrS,jcS)
     .                +wy(i,j)*S00(irS,icS)*S11(jrS,jcS)
     .                +wxx(i,j)*S22(irS,icS)*S00(jrS,jcS)
     .                +wyy(i,j)*S00(irS,icS)*S22(jrS,jcS)
     .                +wxy(i,j)*S11(irS,icS)*S11(jrS,jcS)
        !!!
      end do
      end do
      end do
      end do
!$OMP  END PARALLEL DO
#endif
      end subroutine

#ifdef MATRIX_FREE
!!!!!!!!!!
! Matrix-free matrix-vector product: w = A*p
! Computes stencil on-the-fly using stored weights
!!!!!!!!!!
      subroutine matvec_matrix_free(p,w,n,k)
      real p(-1:mx+1-cix,-1:my+1,nv,mz3)
      real w(-1:mx+1-cix,-1:my+1,nv,mz3)
      integer n,k

      jblk=max(my3/nProcessors,1)
!$OMP  PARALLEL DO SCHEDULE(STATIC,jblk)
!$OMP& PRIVATE(i,j,ki,lj,kia,kib,lja,ljb,irS,icS,jrS,jcS,io,jo,Aval)
      do j=-1,my+1
        ! Boundary handling for j direction
        if(j.le.1) then
          lja=-1-j
          ljb=3
          jrS=-3-lja
        elseif(j.ge.my-1) then
          lja=-3
          ljb=my+1-j
          jrS=3-ljb
        else
          lja=-3
          ljb=3
          jrS=0
        endif

      do i=-1,mx+1-cix
        ! Boundary handling for i direction
        if(i.le.1.and.cix==0) then
          kia=-1-i
          kib=3
          irS=-3-kia
        elseif(i.ge.mx-1.and.cix==0) then
          kia=-3
          kib=mx+1-i
          irS=3-kib
        else
          kia=-3
          kib=3
          irS=0
        endif

        w(i,j,n,k) = 0.

        ! Compute stencil on-the-fly
        do lj=lja,ljb
          jcS=lj
          jo=j+lj
        do ki=kia,kib
          icS=ki
          io=i+ki
          if(cix>0) io=modulo(io+1,mx)-1

          ! Apply the thin-plate stencil formula
          Aval = wx_mf(i,j)*S11(irS,icS)*S00(jrS,jcS)
     .          +wy_mf(i,j)*S00(irS,icS)*S11(jrS,jcS)
     .          +wxx_mf(i,j)*S22(irS,icS)*S00(jrS,jcS)
     .          +wyy_mf(i,j)*S00(irS,icS)*S22(jrS,jcS)
     .          +wxy_mf(i,j)*S11(irS,icS)*S11(jrS,jcS)

          w(i,j,n,k) = w(i,j,n,k) + Aval*p(io,jo,n,k)
        enddo
        enddo
      enddo
      enddo
!$OMP  END PARALLEL DO
      end subroutine

!!!!!!!!!!
! Get diagonal element for preconditioning in matrix-free mode
!!!!!!!!!!
      function get_diagonal_mf(i,j,n,k) result(diag)
      integer i,j,n,k
      real*8 diag
#ifdef MATRIX_FREE
      ! For thin-plate spline, diagonal is at ki=0, lj=0
      ! with irS=0, icS=0, jrS=0, jcS=0
      diag = wx_mf(i,j)*S11(0,0)*S00(0,0)
     .      +wy_mf(i,j)*S00(0,0)*S11(0,0)
     .      +wxx_mf(i,j)*S22(0,0)*S00(0,0)
     .      +wyy_mf(i,j)*S00(0,0)*S22(0,0)
     .      +wxy_mf(i,j)*S11(0,0)*S11(0,0)
#endif
      end function
#endif

!!!!!!!!!!
      subroutine spmDirectThinIJ(wx,wy,wxx,wyy,wxy,n,k)
      real wx(-1:mx+1-cix,-1:my+1),wy(-1:mx+1-cix,-1:my+1)
      real wxx(-1:mx+1-cix,-1:my+1),wyy(-1:mx+1-cix,-1:my+1)
      real wxy(-1:mx+1-cix,-1:my+1)
      integer n,k

#ifndef MATRIX_FREE
      real*8 L1(-1:1,-2:2),L2(-2:2,-2:2)
      real(imk), pointer :: L(:,:,:,:,:,:,:)
      L=>infoMatrix

      L1(:,:)=0.; L1(0:1,-1)=-1.; L1(-1:0,1)=-1.
      L1(-1,0)=1.; L1(1,0)=1.; L1(0,0)=2.
      L1(:,:)=L1(:,:)/2.

      L2(:,:)=0.; L2(0:2,-2)=1.; L2(-2:0,2)=1.
      L2(-2,1)=-2.; L2(-1,-1)=-2.; L2(1,1)=-2.; L2(2,-1)=-2.
      L2(-1,1)=-4.; L2(0,-1)=-4.; L2(0,1)=-4.; L2(1,-1)=-4.
      L2(-2,0)=1.; L2(2,0)=1.; L2(-1,0)=5.; L2(1,0)=5.; L2(0,0)=6.
      L2(:,:)=L2(:,:)/6.

      jblk=max(my3/nProcessors,1)
!$OMP  PARALLEL DO SCHEDULE(STATIC,jblk)
!$OMP& PRIVATE(i,j,i1,i2,j1,j2)
      do j=-1,my+1
        j1=0
        if(j==-1)   j1=-1
        if(j==my+1) j1=1
        j2=0
        if(j==-1)  j2=-2
        if(j==0)   j2=-1
        if(j==my)  j2=1
        if(j==my+1)j2=2
      do i=-1,mx+1-cix
        i1=0
        i2=0
        if(cix==0) then
          if(i==-1)   i1=-1
          if(i==mx+1) i1=1
          if(i==-1)  i2=-2
          if(i==0)   i2=-1
          if(i==mx)  i2=1
          if(i==mx+1)i2=2
        end if
        !!!
        L(i,j,-2:2,0,n,n,k)=L(i,j,-2:2,0,n,n,k)+wx(i,j)*L1(i1,-2:2)
     .                                        +wxx(i,j)*L2(i2,-2:2)
        L(i,j,0,-2:2,n,n,k)=L(i,j,0,-2:2,n,n,k)+wy(i,j)*L1(j1,-2:2)
     .                                        +wyy(i,j)*L2(j2,-2:2)
        !!!
        if(i1==0.and.j1==0) then
          ww=wxy(i,j)*0.25
          L(i,j,0,0,n,n,k)=L(i,j,0,0,n,n,k)+wxy(i,j)
          L(i,j,0,-1,n,n,k)=L(i,j,0,-1,n,n,k)-ww
          L(i,j,0,1,n,n,k)=L(i,j,0,1,n,n,k)-ww
          L(i,j,-1,0,n,n,k)=L(i,j,-1,0,n,n,k)-ww
          L(i,j,1,0,n,n,k)=L(i,j,1,0,n,n,k)-ww
        end if
        !!!
      end do
      end do
!$OMP  END PARALLEL DO
#endif
      end subroutine


!!!!!!!!!!
      subroutine spmBoundary(wx,wy,wxx,wyy,wxy,n,k)
      real wx,wy,wxx,wyy,wxy
      integer n,k

      do i=-1,mx+1-cix
        call spmIJThin(wx,wy,wxx,wyy,wxy,n,k,i,-1)
        call spmIJThin(wx,wy,wxx,wyy,wxy,n,k,i,my+1)
      end do

      if(cix==0) then
        do j=-1,my+1
          call spmIJThin(wx,wy,wxx,wyy,wxy,n,k,-1,j)
          call spmIJThin(wx,wy,wxx,wyy,wxy,n,k,mx+1,j)
        end do
      end if

      end subroutine


!!!!!!!!!!
      subroutine spmIJThin(wx,wy,wxx,wyy,wxy,n,k,i,j)
      real wx,wy,wxx,wyy,wxy
      integer n,k,i,j

#ifndef MATRIX_FREE
      real*8, pointer :: bsp(:,:,:,:)
      real(imk), pointer :: Asp(:,:,:,:,:,:,:)
      bsp=>infoVector
      Asp=>infoMatrix
        if(j.le.1) then  
          lja=-1-j
          ljb=3
          jrS=-3-lja
        elseif(j.ge.my-1) then  
          lja=-3
          ljb=my+1-j
          jrS=3-ljb
        else  
          lja=-3
          ljb=3
          jrS=0
        endif
        if(i.le.1.and.cix==0) then  
          kia=-1-i
          kib=3
          irS=-3-kia
        elseif(i.ge.mx-1.and.cix==0) then  
          kia=-3
          kib=mx+1-i
          irS=3-kib
        else  
          kia=-3
          kib=3
          irS=0
        endif
      do lj=lja,ljb
        jcS=lj
      do ki=kia,kib
        icS=ki
        !!!
        Asp(i,j,ki,lj,n,n,k)=Asp(i,j,ki,lj,n,n,k)
     .                +wx*S11(irS,icS)*S00(jrS,jcS)
     .                +wy*S00(irS,icS)*S11(jrS,jcS)
     .                +wxx*S22(irS,icS)*S00(jrS,jcS)
     .                +wyy*S00(irS,icS)*S22(jrS,jcS)
     .                +wxy*S11(irS,icS)*S11(jrS,jcS)
        !!!
      end do
      end do
#endif
      end subroutine


!!!!!!!!!!
      subroutine spmHNSdata(xd,yd,Ex,Ey,Et,wd,nd)
      integer nd
      real xd(nd),yd(nd),Ex(nd),Ey(nd),Et(nd),wd(nd)

      real bx(4),by(4)
      real*8, pointer :: bsp(:,:,:,:)
#ifndef MATRIX_FREE
      real(imk), pointer :: Asp(:,:,:,:,:,:,:)
#endif
      bsp=>infoVector
#ifndef MATRIX_FREE
      Asp=>infoMatrix
#endif
      do 200 id=1,nd
        if(wd(id).le.0.0) goto 200
        if((xd(id).lt.xmin).or.(xd(id).gt.xmax)) goto 200
        if((yd(id).lt.ymin).or.(yd(id).gt.ymax)) goto 200
        rx=(xd(id)-xmin)/hx
        ry=(yd(id)-ymin)/hy
        ip=int(rx)
        jp=int(ry)
        if(xd(id).eq.xmax) ip=mx-1
        if(yd(id).eq.ymax) jp=my-1
        rx=rx-ip
        ry=ry-jp
        call bsp3(rx,1.,0,bx)
        call bsp3(ry,1.,0,by)
        if(cix>0) ip=modulo(ip+1,mx)-1  
        do j1=-1,2 
        do i1=-1,2
          ii=ip+i1
          if(cix>0) ii=modulo(ii+1,mx)-1  
          jj=jp+j1
          c1=bx(3-i1)*by(3-j1)*wd(id)
          bsp(ii,jj,1,1)=bsp(ii,jj,1,1)-c1*Ex(id)*Et(id)
          bsp(ii,jj,2,1)=bsp(ii,jj,2,1)-c1*Ey(id)*Et(id)
          do j2=-1,2 
          do i2=-1,2
            ki=i2-i1
            lj=j2-j1
            c2=c1*bx(3-i2)*by(3-j2)
#ifndef MATRIX_FREE
            Asp(ii,jj,ki,lj,1,1,1)=Asp(ii,jj,ki,lj,1,1,1)+
     &          c2*Ex(id)*Ex(id)
            Asp(ii,jj,ki,lj,2,2,1)=Asp(ii,jj,ki,lj,2,2,1)+
     &          c2*Ey(id)*Ey(id)
            Asp(ii,jj,ki,lj,1,2,1)=Asp(ii,jj,ki,lj,1,2,1)+
     &          c2*Ex(id)*Ey(id)
            Asp(ii,jj,ki,lj,2,1,1)=Asp(ii,jj,ki,lj,2,1,1)+
     &          c2*Ey(id)*Ex(id)
#endif
          enddo
          enddo
        enddo
        enddo
200   continue
      end subroutine



!!!!!!!!!!
      subroutine spmData(n,k,xd,yd,zd,wd,nd)
      integer n,nd
      real xd(nd),yd(nd),zd(nd),wd(nd)

      real bx(4),by(4)
      real*8, pointer :: bsp(:,:,:,:)
#ifndef MATRIX_FREE
      real(imk), pointer :: Asp(:,:,:,:,:,:,:)
#endif
      bsp=>infoVector
#ifndef MATRIX_FREE
      Asp=>infoMatrix
#endif
      do 200 id=1,nd
        if(wd(id).le.weightmin) goto 200
        if((xd(id).lt.xmin).or.(xd(id).gt.xmax)) goto 200
        if((yd(id).lt.ymin).or.(yd(id).gt.ymax)) goto 200
        rx=(xd(id)-xmin)/hx
        ry=(yd(id)-ymin)/hy
        ip=int(rx)
        jp=int(ry)
        if(xd(id).eq.xmax) ip=mx-1
        if(yd(id).eq.ymax) jp=my-1
        rx=rx-ip
        ry=ry-jp
        call bsp3(rx,1.,0,bx)
        call bsp3(ry,1.,0,by)
        if(cix>0) ip=modulo(ip+1,mx)-1  
        do j1=-1,2 
        do i1=-1,2
          ii=ip+i1
          if(cix>0) ii=modulo(ii+1,mx)-1  
          jj=jp+j1
          bsp(ii,jj,n,k)=bsp(ii,jj,n,k)+bx(3-i1)*by(3-j1)*zd(id)*wd(id)
          do j2=-1,2
          do i2=-1,2
            ki=i2-i1
            lj=j2-j1
#ifndef MATRIX_FREE
              Asp(ii,jj,ki,lj,n,n,k)=Asp(ii,jj,ki,lj,n,n,k)+
     &          bx(3-i1)*by(3-j1)*bx(3-i2)*by(3-j2)*wd(id)
#endif
          enddo
          enddo
        enddo
        enddo
200   continue
      end subroutine

!!!!!!!!!!
      subroutine spmDataScale(n,k,xd,yd,zd,wd,nd,scaling)
      integer n,nd
      real xd(nd),yd(nd),zd(nd),wd(nd)
      real scaling(-1:mx+1-cix,-1:my+1)

      real bx(4),by(4)
      real*8, pointer :: bsp(:,:,:,:)
#ifndef MATRIX_FREE
      real(imk), pointer :: Asp(:,:,:,:,:,:,:)
#endif
      bsp=>infoVector
#ifndef MATRIX_FREE
      Asp=>infoMatrix
#endif

      do 200 id=1,nd
        if(wd(id).le.weightmin) goto 200
        if((xd(id).lt.xmin).or.(xd(id).gt.xmax)) goto 200
        if((yd(id).lt.ymin).or.(yd(id).gt.ymax)) goto 200
        rx=(xd(id)-xmin)/hx
        ry=(yd(id)-ymin)/hy
        ip=int(rx)
        jp=int(ry)
        if(xd(id).eq.xmax) ip=mx-1
        if(yd(id).eq.ymax) jp=my-1
        rx=rx-ip
        ry=ry-jp
        call bsp3(rx,1.,0,bx)
        call bsp3(ry,1.,0,by)
        if(cix>0) ip=modulo(ip+1,mx)-1  
        s=scaling(ip,jp)
        do j1=-1,2
        do i1=-1,2
          ii=ip+i1
          if(cix>0) ii=modulo(ii+1,mx)-1  
          jj=jp+j1
          c=bx(3-i1)*by(3-j1)*wd(id)*s
          bsp(ii,jj,n,k)=bsp(ii,jj,n,k)+zd(id)*c
          do j2=-1,2
          do i2=-1,2
            ki=i2-i1
            lj=j2-j1
#ifndef MATRIX_FREE
              Asp(ii,jj,ki,lj,n,n,k)=Asp(ii,jj,ki,lj,n,n,k)+
     &          bx(3-i2)*by(3-j2)*c
#endif
          enddo
          enddo
        enddo
        enddo
200   continue
      end subroutine

!!!!!!!!!!
      subroutine spmDataScaleP(n,k,xd,yd,zd,wd,nd,scaling)
      integer n,nd
      real xd(nd),yd(nd),zd(nd),wd(nd)
      real scaling(-1:mx+1-cix,-1:my+1)

      real bx(4),by(4)
      real*8, pointer :: bsp(:,:,:,:)
#ifndef MATRIX_FREE
      real(imk), pointer :: Asp(:,:,:,:,:,:,:)
#endif
      bsp=>infoVector
#ifndef MATRIX_FREE
      Asp=>infoMatrix
#endif

      jblk=max(nd/nProcessors,1)
!$OMP  PARALLEL DO PRIVATE(id,rx,ry,ip,jp,bx,by,s,c,ii,jj,i1,j1,i2,j2,ki,lj)
!$OMP& SCHEDULE(DYNAMIC,jblk)

      do 200 id=1,nd
        if(wd(id).le.weightmin) goto 200
        if((xd(id).lt.xmin).or.(xd(id).gt.xmax)) goto 200
        if((yd(id).lt.ymin).or.(yd(id).gt.ymax)) goto 200
        rx=(xd(id)-xmin)/hx
        ry=(yd(id)-ymin)/hy
        ip=int(rx)
        jp=int(ry)
        if(xd(id).eq.xmax) ip=mx-1
        if(yd(id).eq.ymax) jp=my-1
        rx=rx-ip
        ry=ry-jp
        call bsp3(rx,1.,0,bx)
        call bsp3(ry,1.,0,by)
        if(cix>0) ip=modulo(ip+1,mx)-1  
        s=scaling(ip,jp)
        do j1=-1,2
        do i1=-1,2
          ii=ip+i1
          if(cix>0) ii=modulo(ii+1,mx)-1  
          jj=jp+j1
          c=bx(3-i1)*by(3-j1)*wd(id)*s
!$OMP  ATOMIC
          bsp(ii,jj,n,k)=bsp(ii,jj,n,k)+zd(id)*c
          do j2=-1,2
          do i2=-1,2
            ki=i2-i1
            lj=j2-j1
#ifndef MATRIX_FREE
!$OMP  ATOMIC
              Asp(ii,jj,ki,lj,n,n,k)=Asp(ii,jj,ki,lj,n,n,k)+
     &          bx(3-i2)*by(3-j2)*c
#endif
          enddo
          enddo
        enddo
        enddo
200   continue
!$OMP  END PARALLEL DO
      end subroutine


!!!!!!!!!!
      subroutine spmDataScaleQ(n,k,xd,yd,zd,wd,nd,scaling)
      integer n,nd
      real xd(nd),yd(nd),zd(nd),wd(nd)
      real scaling(-1:mx+1-cix,-1:my+1)

      real bx(4),by(4)
      real*8, pointer :: bsp(:,:,:,:)
#ifndef MATRIX_FREE
      real(imk), pointer :: Asp(:,:,:,:,:,:,:)
#endif
      bsp=>infoVector
#ifndef MATRIX_FREE
      Asp=>infoMatrix
#endif

      jblk=max(my3/nProcessors,1)
      jblk=1
      jblk=max(my3/nProcessors/100,1)
!$OMP  PARALLEL DO PRIVATE(id,rx,ry,ip,jp,bx,by,s,c,ii,jj,i1,j1,i2,j2,ki,lj)
!$OMP& SCHEDULE(DYNAMIC,jblk)
      do jj=-1,my+1

      do 200 id=1,nd
        if(wd(id).le.weightmin) goto 200
        if((xd(id).lt.xmin).or.(xd(id).gt.xmax)) goto 200
        if((yd(id).lt.ymin).or.(yd(id).gt.ymax)) goto 200
        ry=(yd(id)-ymin)/hy
        jp=int(ry)
        if(yd(id).eq.ymax) jp=my-1
        j1=jj-jp; if(j1<-1.or.j1>2) goto 200
        ry=ry-jp
        call bsp3(ry,1.,0,by)
        rx=(xd(id)-xmin)/hx
        ip=int(rx)
        if(xd(id).eq.xmax) ip=mx-1
        rx=rx-ip
        call bsp3(rx,1.,0,bx)
        if(cix>0) ip=modulo(ip+1,mx)-1  
        s=scaling(ip,jp)
        do i1=-1,2
          ii=ip+i1
          if(cix>0) ii=modulo(ii+1,mx)-1  
          c=bx(3-i1)*by(3-j1)*wd(id)*s
          bsp(ii,jj,n,k)=bsp(ii,jj,n,k)+zd(id)*c
          do j2=-1,2
          do i2=-1,2
            ki=i2-i1
            lj=j2-j1
#ifndef MATRIX_FREE
              Asp(ii,jj,ki,lj,n,n,k)=Asp(ii,jj,ki,lj,n,n,k)+
     &          bx(3-i2)*by(3-j2)*c
#endif
          enddo
          enddo
        enddo
200   continue

      end do  
!$OMP  END PARALLEL DO
      end subroutine


!!!!!!!!!!
      subroutine spmDataWithBiasScale(n1,n2,k,xd,yd,zd,wd,nd,scaling)
      integer n1,n2,nd
      real xd(nd),yd(nd),zd(nd),wd(nd)
      real scaling(-1:mx+1-cix,-1:my+1)

      real bx(4),by(4)
      real*8, pointer :: bsp(:,:,:,:)
#ifndef MATRIX_FREE
      real(imk), pointer :: Asp(:,:,:,:,:,:,:)
#endif
      bsp=>infoVector
#ifndef MATRIX_FREE
      Asp=>infoMatrix
#endif
      do 200 id=1,nd
        if(wd(id).le.weightmin) goto 200
        if((xd(id).lt.xmin).or.(xd(id).gt.xmax)) goto 200
        if((yd(id).lt.ymin).or.(yd(id).gt.ymax)) goto 200
        rx=(xd(id)-xmin)/hx
        ry=(yd(id)-ymin)/hy
        ip=int(rx)
        jp=int(ry)
        if(xd(id).eq.xmax) ip=mx-1
        if(yd(id).eq.ymax) jp=my-1
        rx=rx-ip
        ry=ry-jp
        call bsp3(rx,1.,0,bx)
        call bsp3(ry,1.,0,by)
        if(cix>0) ip=modulo(ip+1,mx)-1  
        s=scaling(ip,jp)
        do j1=-1,2 
        do i1=-1,2
          ii=ip+i1
          if(cix>0) ii=modulo(ii+1,mx)-1  
          jj=jp+j1
          c=bx(3-i1)*by(3-j1)*wd(id)*s
          bsp(ii,jj,n1,k)=bsp(ii,jj,n1,k)+zd(id)*c
          bsp(ii,jj,n2,k)=bsp(ii,jj,n2,k)+zd(id)*c
          do j2=-1,2 
          do i2=-1,2
            ki=i2-i1
            lj=j2-j1
#ifndef MATRIX_FREE
              Asp(ii,jj,ki,lj,n1,n1,k)=Asp(ii,jj,ki,lj,n1,n1,k)+
     &          bx(3-i2)*by(3-j2)*c
              Asp(ii,jj,ki,lj,n2,n2,k)=Asp(ii,jj,ki,lj,n2,n2,k)+
     &          bx(3-i2)*by(3-j2)*c
              Asp(ii,jj,ki,lj,n1,n2,k)=Asp(ii,jj,ki,lj,n1,n2,k)+
     &          bx(3-i2)*by(3-j2)*c
              Asp(ii,jj,ki,lj,n2,n1,k)=Asp(ii,jj,ki,lj,n2,n1,k)+
     &          bx(3-i2)*by(3-j2)*c
#endif
          enddo
          enddo
        enddo
        enddo
200   continue
      end subroutine


!!!!!!!!!!
      subroutine spmDataWithBiasScaleQ(n1,n2,k,xd,yd,zd,wd,nd,scaling)
      integer n1,n2,nd
      real xd(nd),yd(nd),zd(nd),wd(nd)
      real scaling(-1:mx+1-cix,-1:my+1)

      real bx(4),by(4)
      real*8, pointer :: bsp(:,:,:,:)
#ifndef MATRIX_FREE
      real(imk), pointer :: Asp(:,:,:,:,:,:,:)
#endif
      bsp=>infoVector
#ifndef MATRIX_FREE
      Asp=>infoMatrix
#endif

      jblk=max(my3/nProcessors,1)
      jblk=1
      jblk=max(my3/nProcessors/100,1)
!$OMP  PARALLEL DO PRIVATE(id,rx,ry,ip,jp,bx,by,s,c,ii,jj,i1,j1,i2,j2,ki,lj)
!$OMP& SCHEDULE(DYNAMIC,jblk)
      do jj=-1,my+1

      do 200 id=1,nd
        if(wd(id).le.weightmin) goto 200
        if((xd(id).lt.xmin).or.(xd(id).gt.xmax)) goto 200
        if((yd(id).lt.ymin).or.(yd(id).gt.ymax)) goto 200
        ry=(yd(id)-ymin)/hy
        jp=int(ry)
        if(yd(id).eq.ymax) jp=my-1
        j1=jj-jp; if(j1<-1.or.j1>2) goto 200
        ry=ry-jp
        call bsp3(ry,1.,0,by)
        rx=(xd(id)-xmin)/hx
        ip=int(rx)
        if(xd(id).eq.xmax) ip=mx-1
        rx=rx-ip
        call bsp3(rx,1.,0,bx)
        if(cix>0) ip=modulo(ip+1,mx)-1  
        s=scaling(ip,jp)
        do i1=-1,2
          ii=ip+i1
          if(cix>0) ii=modulo(ii+1,mx)-1  
          c=bx(3-i1)*by(3-j1)*wd(id)*s
          bsp(ii,jj,n1,k)=bsp(ii,jj,n1,k)+zd(id)*c
          bsp(ii,jj,n2,k)=bsp(ii,jj,n2,k)+zd(id)*c
          do j2=-1,2 
          do i2=-1,2
            ki=i2-i1
            lj=j2-j1
#ifndef MATRIX_FREE
              Asp(ii,jj,ki,lj,n1,n1,k)=Asp(ii,jj,ki,lj,n1,n1,k)+
     &          bx(3-i2)*by(3-j2)*c
              Asp(ii,jj,ki,lj,n2,n2,k)=Asp(ii,jj,ki,lj,n2,n2,k)+
     &          bx(3-i2)*by(3-j2)*c
              Asp(ii,jj,ki,lj,n1,n2,k)=Asp(ii,jj,ki,lj,n1,n2,k)+
     &          bx(3-i2)*by(3-j2)*c
              Asp(ii,jj,ki,lj,n2,n1,k)=Asp(ii,jj,ki,lj,n2,n1,k)+
     &          bx(3-i2)*by(3-j2)*c
#endif
          enddo
          enddo
        enddo
200   continue

      end do  ! jj.
!$OMP  END PARALLEL DO
      end subroutine



!!!!!!!!!!
      subroutine spmRhoWeightScale(scaling,rho,xd,yd,nd)
      real scaling(-1:mx+1-cix,-1:my+1)
      integer nd
      real xd(nd),yd(nd),rho
      integer,allocatable :: kount(:,:)

      allocate(kount(-1:mx+1-cix,-1:my+1))
      kount(:,:)=0
      do 200 id=1,nd
        if((xd(id).lt.xmin).or.(xd(id).gt.xmax)) goto 200
        if((yd(id).lt.ymin).or.(yd(id).gt.ymax)) goto 200
        ip=int((xd(id)-xmin)/hx)
        jp=int((yd(id)-ymin)/hy)
        if(xd(id).eq.xmax) ip=mx-1
        if(yd(id).eq.ymax) jp=my-1
        if(cix>0) ip=modulo(ip+1,mx)-1  
        kount(ip,jp)=kount(ip,jp)+1
200   continue

!$OMP   PARALLEL DO
!$OMP&    PRIVATE(i,j)
!$OMP&    SCHEDULE(STATIC)
      do j=-1,my+1
      do i=-1,mx+1-cix
        if( kount(i,j).gt.0 ) then
            scaling(i,j)=1.0/(rho*(kount(i,j)-1)+1)
        else
            scaling(i,j)=1.0
        end if
      end do
      end do
!$OMP   END PARALLEL DO

      deallocate(kount)
      end subroutine


!!!!!!!!!!
      subroutine spmPoint(n,k,csp,x,y,defx,defy,dx,dy,z)
      integer n,defx,defy
      real x,y,dx,dy,z
      real csp(-1:mx+1-cix,-1:my+1,nv,mz3)

      real rx,ry,bx(4),by(4)
      integer ip,jp

      z=0.
      if((x.lt.xmin).or.(x.gt.xmax)) return
      if((y.lt.ymin).or.(y.gt.ymax)) return
      ip=int((x-xmin)/hx)
      jp=int((y-ymin)/hy)
      if(x.eq.xmax) ip=mx-1
      if(y.eq.ymax) jp=my-1
      rx=(x-xmin)/hx-ip
      ry=(y-ymin)/hy-jp
      call bsp3(rx,dx,defx,bx)
      call bsp3(ry,dy,defy,by)
      if(cix>0) ip=modulo(ip+1,mx)-1  
      do j=-1,2
      do i=-1,2
        ipi=ip+i
        if(cix>0) ipi=modulo(ipi+1,mx)-1  
        z=z+csp(ipi,jp+j,n,k)*bx(3-i)*by(3-j)
      enddo
      enddo
      end subroutine

!!!!!!!!!!
      subroutine bsp3(r,h,idef,bn)
      real bn(4)
      real a,r2,r3
      if(idef.eq.3) then
        a=1./(h*h*h)
        bn(1)=1.*a
        bn(2)=-3.*a
        bn(3)=3.*a
        bn(4)=-1.*a
        return
      endif
      if(idef.eq.2) then
        a=1./(h*h)
        bn(1)=r*a
        bn(2)=(-3*r+1)*a
        bn(3)=(3*r-2)*a
        bn(4)=(-r+1)*a
        return
      endif
      r2=r*r
      if(idef.eq.1) then
        a=.5/h
        bn(1)=r2*a
        bn(2)=(-3*r2+2*r+1)*a
        bn(3)=(3*r2-4*r)*a
        bn(4)=(-r2+2*r-1)*a
        return
      endif
      r3=r2*r
      if(idef.eq.0) then
        a=1./6.
        bn(1)=r3*a
        bn(2)=(3*(-r3+r2+r)+1)*a
        bn(3)=(3*r3-6*r2+4)*a
        bn(4)=(-r3+3*(r2-r)+1)*a
        return
      endif
      end subroutine

!!!!!!!!!!
      subroutine spmSOR(cij,iterOut,iterIn)

      integer iterOut,iterIn
      real cij(-1:mx+1,-1:my+1,nv,mz3)

#ifndef MATRIX_FREE
      real step,ratio,threshold
      real resSum,oldSum
      real(imk), pointer :: K4(:,:,:,:,:,:,:)
      real*8, pointer :: bij(:,:,:,:)
      K4=>infoMatrix
      bij=>infoVector

      do k=1,mz3
      step=1.2
      ratio=0.95
      threshold=0.01

      oldSum=0.
      do n=1,nv
      do j=-1,my+1
      do i=-1,mx+1
        cij(i,j,n,k)=0.
        if(oldSum.lt.abs(bij(i,j,n,k))) oldSum=abs(bij(i,j,n,k))
      enddo
      enddo
      enddo
      oldSum=oldSum*real(mx*my*nv*1024)

      do iter0=1,iterOut
       !!
       do iter1=1,iterIn

        resSum=0. 
        do m=1,nv
        do j=-1,my+1
        do i=-1,mx+1
          res=bij(i,j,m,k) 
          
          do n=1,nv
          do lj=max0(-3,-1-j),min0(3,my+1-j)
          do ki=max0(-3,-1-i),min0(3,mx+1-i)
            res=res-K4(i,j,ki,lj,m,n,k)*cij(ki+i,lj+j,n,k)
          enddo
          enddo
          enddo
          
          cij(i,j,m,k)=cij(i,j,m,k)+step*res/K4(i,j,0,0,m,m,k)
          resSum=resSum+abs(res)
          
        enddo
        enddo
        enddo

        if((oldSum-resSum).lt.resSum*threshold) step=step*ratio
        oldSum=resSum

       enddo
       !!
       resSum=resSum/(mx3*my3*nv)
       write(6,60) k,(iter0*iterIn),step,resSum
      enddo
      !!!

      end do 

60    format(i4': SOR #',i4,'. Stepsize',f9.3,'. Residue norm =',g12.3)
#endif
      end subroutine

!!!!!!!!!!!
      subroutine spmPCG(x,maxIteration,epsilon,betaMin)

      real x(-1:mx+1-cix,-1:my+1,nv,mz3)
      integer maxIteration

      logical diagPCG,outUVH
      parameter(diagPCG=.true.)
      parameter(outUVH=.false.)

      real epsilon,rhoMin,betaMin
      integer minIteration
      parameter(minIteration=5)

      real*8, pointer :: b(:,:,:,:)
#ifndef MATRIX_FREE
      real(imk), pointer :: A(:,:,:,:,:,:,:)
#endif
      real, pointer :: r(:,:,:,:),p(:,:,:,:),z(:,:,:,:),w(:,:,:,:)

      real,target :: u(-1:mx+1-cix,-1:my+1,nv,mz3),
     .               v(-1:mx+1-cix,-1:my+1,nv,mz3),
     .               h(-1:mx+1-cix,-1:my+1,nv,mz3)

      r=>u
      p=>v
      z=>h
      w=>z
#ifndef MATRIX_FREE
      A=>infoMatrix
#endif
      b=>infoVector

      jblk=max(my3/nProcessors,1)
      print*,jblk

      do k=1,mz3
       do n=1,nv
!$OMP  PARALLEL DO PRIVATE(j,i) SCHEDULE(STATIC,jblk)
        do j=-1,my+1
         do i=-1,mx+1-cix
            x(i,j,n,k)=0.
            r(i,j,n,k)=b(i,j,n,k)
         enddo
        enddo
!$OMP  END PARALLEL DO
       enddo
      enddo

      betaPCG=0.
      p=0.0

      do iteration=1,maxIteration

        rhoNew=0.

        do k=1,mz3
        do n=1,nv
#ifdef MATRIX_FREE
!$OMP  PARALLEL DO PRIVATE(j,i,diag_val) SCHEDULE(STATIC,jblk)
!$OMP&           reduction(+:rhoNew)
        do j=-1,my+1
        do i=-1,mx+1-cix
          diag_val = get_diagonal_mf(i,j,n,k)
          if(abs(diag_val).gt.1.) then
            z(i,j,n,k)=r(i,j,n,k)/diag_val
          else
            z(i,j,n,k)=r(i,j,n,k)
          endif
          rhoNew=rhoNew+r(i,j,n,k)*z(i,j,n,k)
        enddo
        enddo
!$OMP  END PARALLEL DO
#else
!$OMP  PARALLEL DO PRIVATE(j,i) SCHEDULE(STATIC,jblk)
!$OMP&           reduction(+:rhoNew)
        do j=-1,my+1
        do i=-1,mx+1-cix
          if(abs(A(i,j,0,0,n,n,k)).gt.1.) then
            z(i,j,n,k)=r(i,j,n,k)/A(i,j,0,0,n,n,k)
          else
            z(i,j,n,k)=r(i,j,n,k)
          endif
          rhoNew=rhoNew+r(i,j,n,k)*z(i,j,n,k)
        enddo
        enddo
!$OMP  END PARALLEL DO
#endif
        enddo
        enddo

        if(iteration.eq.1) rhoMin=rhoNew*epsilon
        if(rhoNew.le.rhoMin) goto 100  

        if(iteration.gt.1) betaPCG=rhoNew/rhoOld
        
        if(betaPCG.gt.betaMin.and.iteration.gt.minIteration) goto 100  

        do k=1,mz3
        do n=1,nv
!$OMP  PARALLEL DO PRIVATE(j,i) SCHEDULE(STATIC,jblk)
        do j=-1,my+1
        do i=-1,mx+1-cix
            p(i,j,n,k)=z(i,j,n,k)+betaPCG*p(i,j,n,k)
          w(i,j,n,k)=0.
        enddo
        enddo
!$OMP  END PARALLEL DO
        enddo
        enddo

#ifdef MATRIX_FREE
        ! Matrix-free: compute w = A*p on-the-fly
        do k=1,mz3
        do n=1,nv
          call matvec_matrix_free(p,w,n,k)
        enddo
        enddo
#else
        ! Standard: use stored matrix
        do k=1,mz3
        do n=1,nv
!$OMP  PARALLEL DO PRIVATE(j,i,no,jd,id,jo,io) SCHEDULE(STATIC,jblk)
        do j=-1,my+1
        do i=-1,mx+1-cix


            do no=1,nv
              do jd=-3,3
                jo=j+jd
                if((jo.ge.-1).and.(jo.le.my+1)) then
                  do id=-3,3
                    io=i+id
                    if(cix>0) io=modulo(io+1,mx)-1
                    if((io.ge.-1).and.(io.le.mx+1)) then


        w(i,j,n,k)=w(i,j,n,k)+A(i,j,id,jd,n,no,k)*p(io,jo,no,k)

                    endif
                  enddo
                endif
              enddo
            enddo

        enddo
        enddo
!$OMP  END PARALLEL DO
        enddo
        enddo
#endif

        pw=0.

        do k=1,mz3
        do n=1,nv
!$OMP   PARALLEL DO PRIVATE(j,i) SCHEDULE(STATIC,jblk)
!$OMP&           reduction(+:pw)
        do j=-1,my+1
        do i=-1,mx+1-cix
          pw=pw+p(i,j,n,k)*w(i,j,n,k)
        enddo
        enddo
!$OMP  END PARALLEL DO
        enddo
        enddo

        alphaPCG=rhoNew/pw

        ! Check for NaN in critical PCG variables
        if (isnan(rhoNew) .or. isnan(alphaPCG) .or. isnan(betaPCG)) then
          write(6,*) ''
          write(6,*) '**************************************'
          write(6,*) 'ERROR: NaN detected in PCG solver!'
          write(6,*) '**************************************'
          write(6,*) 'Iteration:', iteration
          write(6,*) 'rhoNew   =', rhoNew
          write(6,*) 'alphaPCG =', alphaPCG
          write(6,*) 'betaPCG  =', betaPCG
          write(6,*) 'pw       =', pw
          write(6,*) ''
          write(6,*) 'This indicates numerical instability.'
          write(6,*) 'Check input data quality and covariance'
          write(6,*) 'matrix conditioning.'
          write(6,*) '**************************************'
          call flush(6)
          stop 99
        endif

        do k=1,mz3
        do n=1,nv
!$OMP   PARALLEL DO PRIVATE(j,i) SCHEDULE(STATIC,jblk)
        do j=-1,my+1
        do i=-1,mx+1-cix
          x(i,j,n,k)=x(i,j,n,k)+alphaPCG*p(i,j,n,k)
          r(i,j,n,k)=r(i,j,n,k)-alphaPCG*w(i,j,n,k)
        enddo
        enddo
!$OMP  END PARALLEL DO
        enddo
        enddo

        rhoOld=rhoNew

        if(diagPCG) then
          write(6,90) iteration,rhoOld,alphaPCG,betaPCG
          call flush(6)
        endif
90      format('  PCG ',I6,': ',3G12.3)

      enddo 

100   continue

      if(outUVH) then 
        do k=1,mz3
        do j=-1,my+1
        do i=-1,mx+1-cix
          u(i,j,1,k)=x(i,j,1,k)
          v(i,j,1,k)=x(i,j,2,k)
          h(i,j,1,k)=x(i,j,3,k)
        enddo
        enddo
        enddo
        write(31) u(:,:,1,:),v(:,:,1,:),h(:,:,1,:) 
      endif

      end subroutine

!!!!!!!!!!
      end module
